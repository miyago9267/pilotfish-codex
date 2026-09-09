"""Offline native installer tests; all homes are temporary."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))
import install as installer  # noqa: E402
import hook_registration  # noqa: E402
import stage_smoke_home  # noqa: E402
from hook_registration import (  # noqa: E402
    CURRENT_PROJECTION_ID,
    HookRegistrationError,
    TRUSTED_PROJECTIONS,
    load_registration,
    merge_registration,
    projection_digest,
    strict_json_loads,
    windows_compatibility_warnings,
)
from install import (  # noqa: E402
    InstallAbort,
    codex_version_token,
    is_compatible_codex_output,
    install,
    is_parseable_codex_output,
    merge_config_text,
    parse_codex_version,
)


def _foreign_group(command: str = "/bin/foreign") -> dict[str, object]:
    return {"matcher": "foreign", "hooks": [{"type": "command", "command": command}]}


def _write_registration(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n")


class HookRegistrationTests(unittest.TestCase):
    def test_windows_warning_identifies_unix_only_foreign_hook(self) -> None:
        document = {"hooks": {"Stop": [_foreign_group("/bin/foreign")]}}
        warnings = windows_compatibility_warnings(document)
        self.assertEqual(len(warnings), 1)
        self.assertIn("hooks.Stop[0].hooks[0]", warnings[0])
        self.assertIn("commandWindows", warnings[0])
        self.assertIn("/bin/foreign", warnings[0])
        self.assertIn("preserved it", warnings[0])

    def test_windows_warning_ignores_windows_aware_and_non_command_handlers(self) -> None:
        document = {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "aware",
                        "hooks": [
                            {"type": "command", "command": "/x", "commandWindows": "x.exe"},
                            {"type": "prompt", "command": "/not-a-command"},
                        ],
                    }
                ]
            }
        }
        self.assertEqual(windows_compatibility_warnings(document), [])

    def test_strict_parser_rejects_duplicates_non_finite_and_malformed_shapes(self) -> None:
        invalid = (
            '{"hooks":{},"hooks":{}}',
            '{"hooks":{"Stop":[{"hooks":[{"timeout":NaN}]}]}}',
            '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"/x","timeout":1e309}]}]}}',
            '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"/x","timeout":-1e309}]}]}}',
            '[]',
            '{"hooks":[]}',
            '{"hooks":{"Stop":{}}}',
            '{"hooks":{"Stop":[[]]}}',
            '{"hooks":{"Stop":[{"hooks":{}}]}}',
            '{"hooks":{"Stop":[{"hooks":[[]]}]}}',
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(HookRegistrationError):
                load_registration(payload, source="test hooks.json")

        with self.assertRaises(HookRegistrationError):
            strict_json_loads('{"outer":{"x":1,"x":2}}', source="state")
        self.assertEqual(strict_json_loads('{"value":1.5}', source="state"), {"value": 1.5})
        for overflow in ("1e309", "-1e309"):
            with self.subTest(overflow=overflow), self.assertRaises(HookRegistrationError):
                strict_json_loads(f'{{"value":{overflow}}}', source="state")

    def test_comparison_is_type_strict(self) -> None:
        source = (ROOT / "templates" / "hooks.json").read_bytes()
        document = json.loads(source)
        document["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 10.0
        with self.assertRaises(HookRegistrationError):
            merge_registration(
                json.dumps(document).encode(),
                source,
                owned_projection_id=CURRENT_PROJECTION_ID,
            )

    def test_historical_projection_updates_in_place_and_rejects_desired_collision(self) -> None:
        source = (ROOT / "templates" / "hooks.json").read_bytes()
        old_id = "test-historical-v0"
        old_group = {"matcher": "old", "hooks": [{"type": "command", "command": "/old"}]}
        TRUSTED_PROJECTIONS[old_id] = {
            "UserPromptSubmit": old_group,
            "Stop": old_group,
        }
        try:
            document = {
                "hooks": {
                    "UserPromptSubmit": [_foreign_group("/before"), old_group],
                    "Stop": [old_group, _foreign_group("/after")],
                }
            }
            merged, projection_id = merge_registration(
                json.dumps(document).encode(), source, owned_projection_id=old_id
            )
            parsed = json.loads(merged)
            self.assertEqual(projection_id, CURRENT_PROJECTION_ID)
            self.assertEqual(parsed["hooks"]["UserPromptSubmit"][0], _foreign_group("/before"))
            self.assertEqual(parsed["hooks"]["Stop"][1], _foreign_group("/after"))

            desired_group = TRUSTED_PROJECTIONS[CURRENT_PROJECTION_ID]["Stop"]
            document["hooks"]["Other"] = [desired_group]
            with self.assertRaisesRegex(HookRegistrationError, "collides"):
                merge_registration(
                    json.dumps(document).encode(), source, owned_projection_id=old_id
                )
        finally:
            del TRUSTED_PROJECTIONS[old_id]


class NativeConfigMergeTests(unittest.TestCase):
    def test_empty_config_renders_exact_native_table(self) -> None:
        rendered, _ = merge_config_text("")
        data = tomllib.loads(rendered)
        self.assertEqual(data["model"], "gpt-5.6-luna")
        self.assertEqual(data["model_reasoning_effort"], "medium")
        self.assertEqual(data["plan_mode_reasoning_effort"], "xhigh")
        self.assertTrue(data["features"]["default_mode_request_user_input"])
        self.assertEqual(data["max_concurrent_threads_per_session"], 3)
        self.assertNotIn("multi_agent_v2", data.get("features", {}))

    def test_existing_root_model_and_effort_are_preserved(self) -> None:
        rendered, _ = merge_config_text(
            'model = "custom-model"\n'
            'model_reasoning_effort = "high"\n'
            'plan_mode_reasoning_effort = "max"\n'
        )
        data = tomllib.loads(rendered)
        self.assertEqual(data["model"], "custom-model")
        self.assertEqual(data["model_reasoning_effort"], "high")
        self.assertEqual(data["plan_mode_reasoning_effort"], "max")

    def test_legacy_v2_requires_provenance_and_disabled_aborts(self) -> None:
        old = "[features.multi_agent_v2]\nenabled = true\nmax_concurrent_threads_per_session = 4\n"
        with self.assertRaisesRegex(InstallAbort, "provenance"):
            merge_config_text(old)
        migrated, _ = merge_config_text(old, migration_proven=True)
        migrated_data = tomllib.loads(migrated)
        self.assertEqual(migrated_data["max_concurrent_threads_per_session"], 3)
        self.assertTrue(migrated_data["features"]["default_mode_request_user_input"])
        for text in ("[features]\nmulti_agent_v2 = false\n", "[features.multi_agent_v2]\nenabled = false\n", "[features]\nmulti_agent_v2 = true\n"):
            with self.subTest(text=text):
                with self.assertRaises(InstallAbort):
                    merge_config_text(text)

    def test_normalizes_child_domain_and_rejects_conflicts(self) -> None:
        for value in (0, 8, 9, '"4"'):
            with self.subTest(value=value):
                with self.assertRaises(InstallAbort):
                    merge_config_text(f"max_concurrent_threads_per_session = {value}\n")
        with self.assertRaises(InstallAbort):
            merge_config_text("max_concurrent_threads_per_session = 2\n")

    def test_existing_decision_card_setting_is_enabled(self) -> None:
        rendered, _ = merge_config_text(
            "[features]\n"
            "default_mode_request_user_input = false\n"
        )
        self.assertTrue(tomllib.loads(rendered)["features"]["default_mode_request_user_input"])

    def test_agents_table_is_exact_and_rejects_legacy_or_unknown_keys(self) -> None:
        for text in (
            "[agents]\nmax_concurrent_threads_per_session = 3\n",
            "[agents]\nmax_threads = 3\n",
        ):
            with self.subTest(text=text):
                with self.assertRaises(InstallAbort):
                    merge_config_text(text)

    def test_unowned_legacy_key_is_preserved(self) -> None:
        original = "custom = true\n"
        rendered, _ = merge_config_text(original)
        self.assertTrue(tomllib.loads(rendered)["custom"])

    def test_owned_legacy_key_is_removed(self) -> None:
        original = "[features]\nmulti_agent = true\n"
        rendered, _ = merge_config_text(original, owned_legacy=frozenset({"features.multi_agent"}))
        data = tomllib.loads(rendered)
        self.assertNotIn("multi_agent", data["features"])
        self.assertEqual(data["max_concurrent_threads_per_session"], 3)

    def test_version_parser_does_not_hard_pin_releases(self) -> None:
        self.assertEqual(parse_codex_version("codex 0.146.0"), (0, 146, 0))
        self.assertEqual(parse_codex_version("codex-cli 0.147.0-alpha.1.2"), (0, 147, 0))
        self.assertEqual(codex_version_token("codex-cli 0.147.0-alpha.1.2"), "0.147.0-alpha.1.2")
        self.assertTrue(is_parseable_codex_output("codex-cli 0.146.0"))
        self.assertTrue(is_parseable_codex_output("codex-cli 0.147.0-alpha.1.2"))
        self.assertFalse(is_compatible_codex_output("codex-cli 0.146.0"))
        self.assertTrue(is_compatible_codex_output("codex-cli 0.147.0-alpha.1.2"))
        for output in ("0.146.0-beta", "0.145.9", "0.146.0 0.146.1", "none"):
            with self.subTest(output=output):
                if output == "0.146.0-beta":
                    self.assertEqual(parse_codex_version(output), (0, 146, 0))
                    self.assertTrue(is_parseable_codex_output(output))
                elif output in {"none", "0.146.0 0.146.1"}:
                    self.assertFalse(is_parseable_codex_output(output))
                else:
                    self.assertTrue(is_parseable_codex_output(output))
        self.assertFalse(is_compatible_codex_output("codex-cli 0.145.9"))

    def test_plugin_version_precedence_respects_release_candidates(self) -> None:
        self.assertGreater(
            installer._plugin_version_key("1.8.0"),
            installer._plugin_version_key("1.8.0-rc.1"),
        )
        self.assertGreater(
            installer._plugin_version_key("1.8.0-rc.2"),
            installer._plugin_version_key("1.8.0-rc.1"),
        )


class NativeInstallTests(unittest.TestCase):
    def test_codex_cli_resolves_windows_command_variants(self) -> None:
        with mock.patch.object(
            installer.shutil, "which", side_effect=[None, None, r"C:\codex.cmd"]
        ):
            self.assertEqual(installer._codex_cli(), "codex.cmd")

    def run_install(self, home: Path, **kwargs: object) -> int:
        return install(source_root=ROOT, codex_home=home, dry_run=False, check_codex=False, **kwargs)

    def _legacy_home(self, home: Path) -> Path:
        self.assertEqual(self.run_install(home), 0)
        config = home / "config.toml"
        legacy = (
            'model = "gpt-5.6-luna"\nmodel_reasoning_effort = "medium"\n'
            'plan_mode_reasoning_effort = "xhigh"\n\n'
            '[features.multi_agent_v2]\nenabled = true\n'
            'max_concurrent_threads_per_session = 4\n'
        )
        config.write_text(legacy)
        state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
        state = json.loads(state_path.read_text())
        state["target_fingerprints"]["config.toml"] = hashlib.sha256(legacy.encode()).hexdigest()
        state["original_targets"]["config.toml"] = {
            "present": True,
            "sha256": hashlib.sha256(legacy.encode()).hexdigest(),
            "bytes_b64": installer.base64.b64encode(legacy.encode()).decode(),
        }
        state_path.write_text(json.dumps(state, sort_keys=True) + "\n")
        return state_path

    def test_exact_legacy_v2_migration_and_dry_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            state_path = self._legacy_home(home)
            before = (home / "config.toml").read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(install(source_root=ROOT, codex_home=home, dry_run=True, check_codex=False), 0)
            self.assertIn("would change primary: config.toml", output.getvalue())
            self.assertIn(f"allowed transaction artifact: {state_path.name}.pending", output.getvalue())
            self.assertEqual((home / "config.toml").read_bytes(), before)
            self.assertEqual(self.run_install(home), 0)
            data = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(data["max_concurrent_threads_per_session"], 3)

    def test_legacy_v2_migration_allows_canonical_security_reviewer_upgrade(self) -> None:
        previous = ROOT / "install" / "previous" / "v1.3.0" / "agents" / "security-reviewer.toml"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            state_path = self._legacy_home(home)
            target = home / "agents" / "security-reviewer.toml"
            target.write_bytes(previous.read_bytes())
            state = json.loads(state_path.read_text())
            state["target_fingerprints"]["agents/security-reviewer.toml"] = hashlib.sha256(
                target.read_bytes()
            ).hexdigest()
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n")

            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(
                target.read_bytes(),
                (ROOT / "templates" / "agents" / "security-reviewer.toml").read_bytes(),
            )

    def test_legacy_v2_extra_state_entry_aborts_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            state_path = self._legacy_home(home)
            state = json.loads(state_path.read_text())
            state["target_fingerprints"]["extra.toml"] = "0" * 64
            state_path.write_text(json.dumps(state))
            before = (home / "config.toml").read_bytes()
            with self.assertRaisesRegex(InstallAbort, "manifest"):
                self.run_install(home)
            self.assertEqual((home / "config.toml").read_bytes(), before)

    def test_install_is_atomic_idempotent_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            config = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(config["max_concurrent_threads_per_session"], 3)
            self.assertEqual({p.stem for p in (home / "agents").glob("*.toml")}, {"executor", "mech-executor", "plan-verifier", "scout", "security-executor", "security-reviewer", "verifier"})
            state = home.with_name(f"{home.name}.pilotfish-install-state.json")
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["status"], "committed")
            self.assertIn("config.toml", recorded["target_fingerprints"])
            self.assertEqual(
                (home / "hooks.json").read_bytes(),
                (ROOT / "templates" / "hooks.json").read_bytes(),
            )
            self.assertEqual(
                (home / "hooks" / "pilotfish_autoroute_gate.py").read_bytes(),
                (ROOT / "hooks" / "pilotfish_autoroute_gate.py").read_bytes(),
            )
            self.assertEqual(recorded["state_version"], 3)
            self.assertEqual(recorded["plugin"]["name"], "pilotfish-codex")
            self.assertEqual(recorded["plugin"]["status"], "unavailable")
            self.assertTrue(recorded["plugin"]["source_sha256"])
            self.assertEqual(recorded["runtime_status"], "integrated-plugin-unavailable")
            self.assertNotIn("hooks.json", recorded["target_fingerprints"])
            self.assertEqual(
                recorded["hook_registration"]["projection_id"],
                CURRENT_PROJECTION_ID,
            )
            self.assertEqual(
                recorded["hook_registration"]["projection_sha256"],
                projection_digest(CURRENT_PROJECTION_ID),
            )
            self.assertIn(
                "hooks/pilotfish_autoroute_gate.py",
                recorded["target_fingerprints"],
            )
            self.assertIn("config.toml", recorded["original_targets"])
            first = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            self.assertEqual(self.run_install(home), 0)
            second = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            self.assertEqual(first, second)

    def test_state_accepts_verified_unowned_config_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            config = home / "config.toml"
            config.write_bytes(config.read_bytes() + b'\n[plugins."local-extra"]\nenabled = true\n')
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text())
            state["target_fingerprints"]["config.toml"] = hashlib.sha256(
                config.read_bytes()
            ).hexdigest()
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n")

            self.assertEqual(self.run_install(home), 0)

    @unittest.skipUnless(os.name == "nt", "Windows-specific installer path")
    def test_windows_install_uses_path_replacement_for_role_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            with mock.patch.object(installer, "IS_WINDOWS", True):
                with mock.patch.object(
                    installer.os,
                    "open",
                    side_effect=AssertionError("Windows path must not open agents directory"),
                ):
                    self.assertIsNone(installer._open_agents_directory(home / "agents"))
                self.assertEqual(self.run_install(home), 0)
            self.assertEqual(
                {p.stem for p in (home / "agents").glob("*.toml")},
                {"executor", "mech-executor", "plan-verifier", "scout", "security-executor", "security-reviewer", "verifier"},
            )

    def test_windows_crlf_policy_preserves_original_bytes_for_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            policy = home / "AGENTS.md"
            policy.write_bytes(b"# Existing policy\r\n")
            with mock.patch.object(installer, "IS_WINDOWS", True):
                self.assertEqual(self.run_install(home), 0)
            installed = policy.read_bytes()
            self.assertIn(b"# Existing policy\r\n", installed)
            self.assertNotIn(b"# Existing policy\n", installed.replace(b"\r\n", b""))

    def test_runtime_install_integrates_policy_and_records_ownership_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            policy = home / "AGENTS.md"
            original = (
                "# Miyago\n\n"
                "- Persona: Monika\n"
                "- Language: Traditional Chinese\n"
                "- Always include a concise recap.\n"
            ).encode()
            policy.write_bytes(original)

            self.assertEqual(self.run_install(home), 0)

            installed = policy.read_bytes()
            self.assertTrue(installed.startswith(original))
            self.assertIn(b"<!-- pilotfish-codex:begin -->", installed)
            self.assertFalse((home / "pilotfish" / "AGENTS.md").exists())
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                state["policy_ownership"],
                {
                    "user_policy": {
                        "path": "AGENTS.md",
                        "owner": "user",
                        "status": "integrated",
                        "sha256": hashlib.sha256(original).hexdigest(),
                    },
                    "pilotfish_policy": {
                        "path": "AGENTS.md",
                        "owner": "pilotfish",
                        "status": "integrated",
                        "sha256": hashlib.sha256(installed).hexdigest(),
                    },
                },
            )
            backup_name = state["rollback_backups"]["AGENTS.md"]
            self.assertTrue((home / backup_name).is_file())

    def test_policy_symlink_requires_explicit_opt_in_and_updates_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            target = root / "managed-AGENTS.md"
            original = b"# Dotfiles policy\n"
            target.write_bytes(original)
            os.symlink(target, home / "AGENTS.md")

            with self.assertRaisesRegex(InstallAbort, "explicit policy integration"):
                self.run_install(home)
            self.assertEqual(target.read_bytes(), original)

            self.assertEqual(
                self.run_install(
                    home,
                    follow_policy_symlink=True,
                    policy_root=target.parent,
                ),
                0,
            )
            installed = target.read_bytes()
            self.assertTrue(installed.startswith(original))
            self.assertIn(b"<!-- pilotfish-codex:begin -->", installed)
            self.assertTrue((home / "AGENTS.md").is_symlink())

    def test_existing_full_policy_marker_migrates_to_bootstrap_without_touching_user_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            prefix = b"# Persona\nkeep-before = true\n\n"
            suffix = b"\n## Local rule\nkeep-after = true\n"
            policy = home / "AGENTS.md"
            old = (ROOT / "templates" / "agents-md.orchestration.md").read_bytes()
            policy.write_bytes(prefix + old + suffix)

            self.assertEqual(self.run_install(home), 0)

            installed = policy.read_bytes()
            self.assertTrue(installed.startswith(prefix))
            self.assertTrue(installed.endswith(suffix))
            self.assertIn(b"### Pilotfish always-on bootstrap", installed)
            self.assertNotIn(b"#### Native typed spawn policy", installed)

    def test_plugin_adapter_uses_codex_marketplace_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            completed = [
                mock.Mock(returncode=0, stdout="{}", stderr=""),
                mock.Mock(
                    returncode=0,
                    stdout=json.dumps({
                        "marketplaces": [{
                            "name": "pilotfish-codex",
                            "root": str(ROOT / "plugin"),
                        }]
                    }),
                    stderr="",
                ),
                mock.Mock(
                    returncode=0,
                    stdout="{}",
                    stderr="",
                ),
                mock.Mock(
                    returncode=0,
                    stdout=json.dumps({
                        "installed": [{
                            "name": "pilotfish-codex",
                            "marketplaceName": "pilotfish-codex",
                            "version": installer.PILOTFISH_PLUGIN_VERSION,
                            "enabled": True,
                            "marketplaceSource": {"source": str(ROOT / "plugin")},
                        }]
                    }),
                    stderr="",
                ),
            ]
            with mock.patch.object(installer.subprocess, "run", side_effect=completed) as run:
                result = installer._install_plugin(
                    source_root=ROOT,
                    codex_home=home,
                    dry_run=False,
                    enabled=True,
                )
            self.assertEqual(result["status"], "installed")
            self.assertEqual(run.call_count, 4)
            self.assertEqual(run.call_args_list[0].args[0][0:4], [
                "codex", "plugin", "marketplace", "add",
            ])
            self.assertEqual(run.call_args_list[1].args[0], [
                "codex", "plugin", "marketplace", "list", "--json",
            ])
            self.assertEqual(run.call_args_list[2].args[0][0:4], [
                "codex", "plugin", "add", "pilotfish-codex@pilotfish-codex",
            ])
            self.assertEqual(run.call_args_list[3].args[0], [
                "codex", "plugin", "list", "--json",
            ])
            self.assertEqual(run.call_args_list[0].kwargs["env"]["CODEX_HOME"], str(home))

    def test_plugin_unavailable_commits_native_fallback_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            unavailable = {
                "name": "pilotfish-codex",
                            "version": installer.PILOTFISH_PLUGIN_VERSION,
                "status": "unavailable",
                "source_sha256": installer._plugin_source_digest(ROOT / "plugin"),
            }
            with mock.patch.object(
                installer.subprocess, "run",
                return_value=mock.Mock(returncode=0, stdout="codex 0.147.0", stderr=""),
            ), mock.patch.object(installer, "_probe_plugin", return_value=unavailable), mock.patch.object(
                installer, "_install_plugin", return_value=unavailable,
            ) as install_plugin:
                self.assertEqual(
                    installer.install(
                        source_root=ROOT,
                        codex_home=home,
                        dry_run=False,
                        check_codex=True,
                    ),
                    0,
                )
            state = json.loads(
                home.with_name(f"{home.name}.pilotfish-install-state.json").read_text()
            )
            self.assertEqual(state["runtime_status"], "integrated-plugin-unavailable")
            self.assertEqual(state["plugin"]["status"], "unavailable")
            install_plugin.assert_called_once()
            self.assertTrue((home / "AGENTS.md").is_file())

    def test_codex_hooks_state_append_is_accepted_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            config = home / "config.toml"
            config.write_bytes(
                config.read_bytes()
                + b'\n[hooks.state]\npilotfish_autoroute_gate = "trusted"\n'
            )
            expected = config.read_bytes()

            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(config.read_bytes(), expected)

    def test_user_main_model_drift_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            config = home / "config.toml"
            changed = config.read_text().replace(
                'model = "gpt-5.6-luna"', 'model = "gpt-5.6-sol"'
            )
            config.write_text(changed)
            self.assertEqual(self.run_install(home), 0)
            self.assertIn('model = "gpt-5.6-sol"', config.read_text())

    def test_reconcile_current_policy_preserves_bytes_and_publishes_v4_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            previous_state = state_path.read_bytes()
            policy = home / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# User-owned current rule\n")
            preimage = policy.read_bytes()

            self.assertEqual(
                self.run_install(home, reconcile_current=True),
                0,
            )

            installed = policy.read_bytes()
            self.assertIn(b"# User-owned current rule", installed)
            self.assertIn(b"<!-- pilotfish-codex:begin -->", installed)
            state = json.loads(state_path.read_text())
            self.assertEqual(state["state_version"], 4)
            reconciliation = state["reconciliation"]
            self.assertEqual(
                reconciliation["previous_state_sha256"],
                hashlib.sha256(previous_state).hexdigest(),
            )
            self.assertEqual(
                reconciliation["accepted_preimages"]["AGENTS.md"]["sha256"],
                hashlib.sha256(preimage).hexdigest(),
            )
            self.assertEqual(
                reconciliation["post_merge_target_fingerprints"]["AGENTS.md"],
                hashlib.sha256(installed).hexdigest(),
            )
            state_backup = home.parent / reconciliation["previous_state_backup"]["path"]
            self.assertTrue(state_backup.is_file())
            self.assertEqual(
                hashlib.sha256(state_backup.read_bytes()).hexdigest(),
                reconciliation["previous_state_backup"]["sha256"],
            )
            backup = state["rollback_backups"]["AGENTS.md"]
            backup_path = home / backup["path"]
            self.assertTrue(backup_path.is_file())
            self.assertEqual(
                hashlib.sha256(backup_path.read_bytes()).hexdigest(),
                backup["sha256"],
            )
            self.assertEqual(set(state["rollback_backups"]), {"AGENTS.md", "config.toml"})

    def test_reconcile_current_policy_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            policy = home / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# drift\n")
            before = policy.read_bytes()

            with self.assertRaisesRegex(InstallAbort, "committed install state is stale"):
                self.run_install(home)
            self.assertEqual(policy.read_bytes(), before)

    def test_reconcile_current_rerun_is_idempotent_after_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            policy = home / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# current\n")
            self.assertEqual(self.run_install(home, reconcile_current=True), 0)
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state_before = state_path.read_bytes()
            files_before = {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file()
            }
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    install(
                        source_root=ROOT,
                        codex_home=home,
                        dry_run=True,
                        check_codex=False,
                        reconcile_current=True,
                    ),
                    0,
                )
            self.assertIn("already up to date; nothing to change", output.getvalue())
            self.assertEqual(state_path.read_bytes(), state_before)
            self.assertEqual(
                {
                    path.relative_to(home): path.read_bytes()
                    for path in home.rglob("*")
                    if path.is_file()
                },
                files_before,
            )

    def test_symlink_policy_uses_contained_backup_and_records_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            canonical = root / "canonical"
            home.mkdir()
            canonical.mkdir()
            target = canonical / "AGENTS.md"
            target.write_bytes(b"# Current canonical policy\n")
            os.symlink(target, home / "AGENTS.md")

            self.assertEqual(
                self.run_install(
                    home,
                    follow_policy_symlink=True,
                    policy_root=canonical,
                ),
                0,
            )
            state = json.loads(
                home.with_name(f"{home.name}.pilotfish-install-state.json").read_text()
            )
            self.assertEqual(state["state_version"], 4)
            backup = state["rollback_backups"]["AGENTS.md"]
            backup_path = home / backup["path"]
            self.assertEqual(backup_path.parent, home)
            self.assertTrue(backup_path.is_file())
            self.assertTrue((home / "AGENTS.md").is_symlink())
            identity = state["reconciliation"]["accepted_preimages"]["AGENTS.md"]
            self.assertEqual(identity["target_path"], str(target.resolve()))
            self.assertTrue(identity["symlink"])

    def test_v4_hook_projection_upgrade_filters_hooks_backup_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            hooks_path = home / "hooks.json"
            hooks = json.loads(hooks_path.read_text())
            legacy = TRUSTED_PROJECTIONS["pilotfish-autoroute-v1"]
            for event in ("UserPromptSubmit", "Stop"):
                hooks["hooks"][event] = [legacy[event]]
            hooks_path.write_text(json.dumps(hooks, indent=2) + "\n")
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text())
            state["hook_registration"] = {
                "version": 1,
                "projection_id": "pilotfish-autoroute-v1",
                "projection_sha256": projection_digest("pilotfish-autoroute-v1"),
            }
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n")
            policy = home / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# current\n")

            self.assertEqual(self.run_install(home, reconcile_current=True), 0)
            committed = json.loads(state_path.read_text())
            self.assertEqual(committed["state_version"], 4)
            self.assertNotIn("hooks.json", committed["rollback_backups"])

    def test_symlink_policy_root_escape_aborts_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            allowed = root / "allowed"
            outside = root / "outside"
            home.mkdir()
            allowed.mkdir()
            outside.mkdir()
            target = outside / "AGENTS.md"
            target.write_bytes(b"# Outside policy\n")
            os.symlink(target, home / "AGENTS.md")

            with self.assertRaisesRegex(InstallAbort, "policy target escapes configured root"):
                self.run_install(
                    home,
                    follow_policy_symlink=True,
                    policy_root=allowed,
                )
            self.assertEqual(target.read_bytes(), b"# Outside policy\n")
            self.assertFalse((home / "agents").exists())

    def test_symlink_policy_race_aborts_without_layering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            canonical = root / "canonical"
            home.mkdir()
            canonical.mkdir()
            target = canonical / "AGENTS.md"
            target.write_bytes(b"# Current canonical policy\n")
            os.symlink(target, home / "AGENTS.md")
            self.assertEqual(
                self.run_install(home, follow_policy_symlink=True, policy_root=canonical),
                0,
            )
            target.write_bytes(target.read_bytes() + b"\n# current drift\n")
            before = target.read_bytes()
            original_assert = installer._assert_policy_identity
            calls = 0

            def mutate_after_check(identity: object, **_: object) -> None:
                nonlocal calls
                calls += 1
                original_assert(identity)
                if calls == 2:
                    target.write_bytes(target.read_bytes() + b"\n# concurrent edit\n")

            with mock.patch.object(
                installer, "_assert_policy_identity", side_effect=mutate_after_check
            ):
                with self.assertRaisesRegex(InstallAbort, "policy target changed"):
                    self.run_install(
                        home,
                        reconcile_current=True,
                        follow_policy_symlink=True,
                        policy_root=canonical,
                    )
            self.assertNotEqual(target.read_bytes(), before)
            self.assertIn(b"# concurrent edit", target.read_bytes())

    def test_backup_symlink_race_cannot_overwrite_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            (home / "AGENTS.md").write_bytes(b"# Current policy\n")
            sentinel = root / "sentinel"
            sentinel.write_bytes(b"keep me\n")
            captured: dict[str, Path] = {}
            original_planner = installer._planned_backup_path
            original_is_symlink = Path.is_symlink
            injected = False

            def capture_backup(*args: object, **kwargs: object) -> Path:
                backup = original_planner(*args, **kwargs)
                if backup.name.startswith("AGENTS.md.pilotfish-codex-"):
                    captured["path"] = backup
                return backup

            def race_is_symlink(path: Path) -> bool:
                nonlocal injected
                result = original_is_symlink(path)
                backup = captured.get("path")
                if backup is not None and path == backup and not injected:
                    os.symlink(sentinel, backup)
                    injected = True
                    return False
                return result

            with mock.patch.object(
                installer, "_planned_backup_path", side_effect=capture_backup
            ), mock.patch.object(Path, "is_symlink", new=race_is_symlink):
                with self.assertRaisesRegex(InstallAbort, "rollback backup"):
                    self.run_install(home)
            self.assertTrue(injected)
            self.assertEqual(sentinel.read_bytes(), b"keep me\n")
            self.assertTrue(captured["path"].is_symlink())

    def test_v4_state_requires_rollback_evidence_for_accepted_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            policy = home / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# current\n")
            self.assertEqual(self.run_install(home, reconcile_current=True), 0)
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text())
            self.assertEqual(state["state_version"], 4)
            state["rollback_backups"] = {}
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n")
            with self.assertRaisesRegex(InstallAbort, "rollback backup"):
                self.run_install(home)

    def test_v4_state_rejects_forged_preimage_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            policy = home / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# current\n")
            self.assertEqual(self.run_install(home, reconcile_current=True), 0)
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text())
            preimage = state["reconciliation"]["accepted_preimages"]["AGENTS.md"]
            preimage["target_path"] = str(home.parent / "outside-policy.md")
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n")
            with self.assertRaisesRegex(InstallAbort, "preimage"):
                self.run_install(home)

    def test_reconcile_does_not_approve_same_name_role_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            policy = home / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# current policy\n")
            role = home / "agents" / "mech-executor.toml"
            role.write_bytes(role.read_bytes() + b"\n# customized\n")
            before = role.read_bytes()

            with self.assertRaisesRegex(InstallAbort, "installed_role_drift"):
                self.run_install(home, reconcile_current=True)
            self.assertEqual(role.read_bytes(), before)

    def test_newer_installed_plugin_fails_closed_without_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            plugin_list = json.dumps(
                {
                    "installed": [
                        {
                            "name": "pilotfish-codex",
                            "marketplaceName": "pilotfish-codex",
                            "version": "1.8.1",
                            "enabled": True,
                        }
                    ]
                }
            )

            def fake_run(args: list[str], **_: object) -> mock.Mock:
                if args == ["codex", "--version"]:
                    return mock.Mock(returncode=0, stdout="codex 0.147.0", stderr="")
                if args == ["codex", "plugin", "list", "--json"]:
                    return mock.Mock(returncode=0, stdout=plugin_list, stderr="")
                raise AssertionError(args)

            with mock.patch.object(installer.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(InstallAbort, "newer than source"):
                    installer.install(
                        source_root=ROOT,
                        codex_home=home,
                        dry_run=True,
                        check_codex=True,
                    )
            self.assertFalse(home.exists())

    def test_plugin_foreign_config_mutation_aborts_after_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            unavailable = {
                "name": "pilotfish-codex",
                "version": installer.PILOTFISH_PLUGIN_VERSION,
                "status": "unavailable",
                "source_sha256": installer._plugin_source_digest(ROOT / "plugin"),
            }

            def mutate_config(**_: object) -> dict[str, str]:
                config = home / "config.toml"
                config.write_bytes(config.read_bytes() + b"\n[foreign]\nkeep = true\n")
                return unavailable

            with mock.patch.object(
                installer.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout="codex 0.147.0", stderr=""),
            ), mock.patch.object(
                installer, "_probe_plugin", return_value=unavailable
            ), mock.patch.object(
                installer, "_install_plugin", side_effect=mutate_config
            ):
                with self.assertRaisesRegex(InstallAbort, "foreign config mutation"):
                    installer.install(
                        source_root=ROOT,
                        codex_home=home,
                        dry_run=False,
                        check_codex=True,
                    )
            self.assertIn(b"[foreign]", (home / "config.toml").read_bytes())
            pending = home.with_name(f"{home.name}.pilotfish-install-state.json.pending")
            self.assertTrue(pending.is_file())
            self.assertEqual(json.loads(pending.read_text())["status"], "aborted")

    def test_owned_routing_drift_aborts_without_installer_writes(self) -> None:
        mutations = {
            "agents": lambda text: text.replace(
                "max_concurrent_threads_per_session = 3",
                "max_concurrent_threads_per_session = 2",
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / "home"
                self.assertEqual(self.run_install(home), 0)
                config = home / "config.toml"
                config.write_text(mutate(config.read_text()))
                before = {
                    path.relative_to(home): path.read_bytes()
                    for path in home.rglob("*")
                    if path.is_file()
                }

                expected_error = "conflicts"
                with self.assertRaisesRegex(InstallAbort, expected_error):
                    self.run_install(home)

                after = {
                    path.relative_to(home): path.read_bytes()
                    for path in home.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)
                self.assertFalse(
                    home.with_name(f"{home.name}.pilotfish-install-state.json.pending").exists()
                )

    def test_config_snapshot_change_during_state_validation_aborts_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            config = home / "config.toml"
            before = {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file() and path != config
            }
            original_load_state = installer._load_state

            def load_state_with_race(target_home: Path) -> dict | None:
                state = original_load_state(target_home)
                config.write_bytes(config.read_bytes() + b"\n[hooks.state]\nrace = true\n")
                return state

            with mock.patch.object(installer, "_load_state", side_effect=load_state_with_race):
                with self.assertRaisesRegex(InstallAbort, "changed during state validation"):
                    self.run_install(home)

            after = {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file() and path != config
            }
            self.assertEqual(after, before)
            self.assertFalse(
                home.with_name(f"{home.name}.pilotfish-install-state.json.pending").exists()
            )

    def test_legacy_v2_provenance_allows_hooks_state_but_rejects_legacy_deviation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self._legacy_home(home)
            config = home / "config.toml"
            config.write_bytes(config.read_bytes() + b"\n[hooks.state]\nlegacy = true\n")
            self.assertEqual(self.run_install(home), 0)
            migrated = tomllib.loads(config.read_text())
            self.assertEqual(migrated["hooks"]["state"], {"legacy": True})
            self.assertNotIn("multi_agent_v2", migrated.get("features", {}))

            config.write_bytes(
                config.read_bytes()
                + b"\n[features.multi_agent_v2]\nenabled = true\n"
                + b"max_concurrent_threads_per_session = 5\n"
            )
            before = config.read_bytes()
            with self.assertRaisesRegex(InstallAbort, "routing projection"):
                self.run_install(home)
            self.assertEqual(config.read_bytes(), before)

    def test_fresh_foreign_hooks_are_preserved_and_rerun_accepts_later_addition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            hooks = home / "hooks.json"
            first_foreign = _foreign_group("/first")
            _write_registration(hooks, {"description": "keep", "hooks": {"Stop": [first_foreign]}})

            self.assertEqual(self.run_install(home), 0)
            installed = json.loads(hooks.read_text())
            self.assertEqual(installed["description"], "keep")
            self.assertEqual(installed["hooks"]["Stop"][0], first_foreign)

            second_foreign = _foreign_group("/second")
            installed["hooks"]["Stop"].insert(1, second_foreign)
            _write_registration(hooks, installed)
            expected = hooks.read_bytes()
            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(hooks.read_bytes(), expected)

    def test_committed_state_binds_group_semantics_and_hook_script_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            hooks = home / "hooks.json"
            hooks.write_bytes(hooks.read_bytes() + b"\n")
            self.assertEqual(self.run_install(home), 0)

            document = json.loads(hooks.read_text())
            document["hooks"]["Stop"][0]["matcher"] = "tampered-wrapper"
            _write_registration(hooks, document)
            with self.assertRaisesRegex(InstallAbort, "committed hook registration"):
                self.run_install(home)

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            script = home / "hooks" / "pilotfish_autoroute_gate.py"
            script.write_bytes(script.read_bytes() + b"\n")
            before = {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file()
            }
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state_before = state_path.read_bytes()
            with self.assertRaisesRegex(InstallAbort, "committed install state is stale"):
                self.run_install(home)
            after = {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            self.assertEqual(state_path.read_bytes(), state_before)
            self.assertFalse(state_path.with_suffix(".json.pending").exists())

    def test_state_proven_legacy_hook_script_upgrades_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            script = home / "hooks" / "pilotfish_autoroute_gate.py"
            previous_payload = b"# previously installed trusted hook payload\n"
            script.write_bytes(previous_payload)

            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text())
            state.pop("state_version")
            state.pop("hook_registration")
            state["target_fingerprints"][
                "hooks/pilotfish_autoroute_gate.py"
            ] = hashlib.sha256(previous_payload).hexdigest()
            registration_payload = (ROOT / "templates" / "hooks.json").read_bytes()
            state["target_fingerprints"]["hooks.json"] = hashlib.sha256(
                registration_payload
            ).hexdigest()
            state["original_targets"]["hooks.json"] = {
                "present": False,
                "sha256": None,
                "bytes_b64": None,
            }
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n")

            self.assertEqual(self.run_install(home), 0)
            selected_payload = (
                ROOT / "hooks" / "pilotfish_autoroute_gate.py"
            ).read_bytes()
            self.assertEqual(script.read_bytes(), selected_payload)
            committed = json.loads(state_path.read_text())
            self.assertEqual(committed["state_version"], 3)
            self.assertEqual(
                committed["target_fingerprints"][
                    "hooks/pilotfish_autoroute_gate.py"
                ],
                hashlib.sha256(selected_payload).hexdigest(),
            )

            committed_before = state_path.read_bytes()
            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(script.read_bytes(), selected_payload)
            self.assertEqual(state_path.read_bytes(), committed_before)

    def test_hook_script_mutation_after_state_validation_aborts_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            script = home / "hooks" / "pilotfish_autoroute_gate.py"
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state_before = state_path.read_bytes()
            mutated_payload = b"# concurrent custom hook payload\n"
            original_validate = installer._validate_committed_state

            def validate_then_mutate(*args, **kwargs):
                result = original_validate(*args, **kwargs)
                script.write_bytes(mutated_payload)
                return result

            with mock.patch.object(
                installer,
                "_validate_committed_state",
                side_effect=validate_then_mutate,
            ):
                with self.assertRaisesRegex(InstallAbort, "installed_hook_drift"):
                    self.run_install(home)

            self.assertEqual(script.read_bytes(), mutated_payload)
            self.assertEqual(state_path.read_bytes(), state_before)
            self.assertFalse(state_path.with_suffix(".json.pending").exists())

    def test_owned_group_missing_duplicate_cross_event_and_handler_tamper_abort(self) -> None:
        mutations = {}

        def missing(document: dict) -> None:
            document["hooks"]["Stop"].pop()

        def duplicate(document: dict) -> None:
            document["hooks"]["Stop"].append(document["hooks"]["Stop"][0])

        def cross_event(document: dict) -> None:
            document["hooks"]["Other"] = [document["hooks"]["Stop"][0]]

        def handler_tamper(document: dict) -> None:
            document["hooks"]["Stop"][0]["hooks"][0]["timeout"] = True

        mutations.update(
            missing=missing,
            duplicate=duplicate,
            cross_event=cross_event,
            handler_tamper=handler_tamper,
        )
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / "home"
                self.assertEqual(self.run_install(home), 0)
                hooks = home / "hooks.json"
                document = json.loads(hooks.read_text())
                mutate(document)
                _write_registration(hooks, document)
                before = hooks.read_bytes()
                with self.assertRaisesRegex(InstallAbort, "committed hook registration"):
                    self.run_install(home)
                self.assertEqual(hooks.read_bytes(), before)

    def test_same_event_foreign_group_reordering_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            hooks = home / "hooks.json"
            document = json.loads(hooks.read_text())
            document["hooks"]["Stop"].insert(0, _foreign_group())
            _write_registration(hooks, document)
            expected = hooks.read_bytes()
            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(hooks.read_bytes(), expected)

    def test_no_state_canonical_collision_aborts_in_bound_or_wrong_event(self) -> None:
        source = json.loads((ROOT / "templates" / "hooks.json").read_text())
        group = source["hooks"]["Stop"][0]
        registrations = (
            source,
            {"hooks": {"Other": [group]}},
        )
        for document in registrations:
            with self.subTest(events=tuple(document["hooks"])), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / "home"
                home.mkdir()
                _write_registration(home / "hooks.json", document)
                with self.assertRaisesRegex(InstallAbort, "unowned hooks.json"):
                    self.run_install(home)
                self.assertFalse((home / "config.toml").exists())

    def test_state_rejects_duplicate_keys_and_projection_body_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            raw = state_path.read_text()
            state_path.write_text('{"status":"committed",' + raw.lstrip()[1:])
            with self.assertRaisesRegex(InstallAbort, "install state is invalid"):
                self.run_install(home)

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text())
            state["hook_registration"]["groups"] = json.loads(
                (ROOT / "templates" / "hooks.json").read_text()
            )["hooks"]
            state_path.write_text(json.dumps(state))
            with self.assertRaisesRegex(InstallAbort, "projection state"):
                self.run_install(home)

    def test_exact_legacy_raw_state_migrates_with_foreign_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            hooks = home / "hooks.json"
            document = json.loads(hooks.read_text())
            foreign = _foreign_group("/legacy-foreign")
            document["hooks"]["Stop"].insert(0, foreign)
            _write_registration(hooks, document)

            state_path = home.with_name(f"{home.name}.pilotfish-install-state.json")
            state = json.loads(state_path.read_text())
            state.pop("state_version")
            state.pop("hook_registration")
            source_payload = (ROOT / "templates" / "hooks.json").read_bytes()
            state["target_fingerprints"]["hooks.json"] = hashlib.sha256(
                source_payload
            ).hexdigest()
            state["original_targets"]["hooks.json"] = {
                "present": False,
                "sha256": None,
                "bytes_b64": None,
            }
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n")
            before = hooks.read_bytes()

            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(hooks.read_bytes(), before)
            migrated = json.loads(state_path.read_text())
            self.assertEqual(migrated["state_version"], 3)
            self.assertNotIn("hooks.json", migrated["target_fingerprints"])
            self.assertEqual(self.run_install(home), 0)

    def test_transaction_preserves_foreign_hook_race_before_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            hooks = home / "hooks.json"
            _write_registration(hooks, {"hooks": {"Stop": [_foreign_group("/original")]}})
            original_replace = installer._replace_staged
            injected = False

            def replace_with_race(temp, destination, expected_original, *, role_directory_fd):
                nonlocal injected
                if destination == hooks and not injected:
                    document = json.loads(hooks.read_text())
                    document["hooks"]["Stop"].append(_foreign_group("/concurrent"))
                    _write_registration(hooks, document)
                    injected = True
                return original_replace(
                    temp,
                    destination,
                    expected_original,
                    role_directory_fd=role_directory_fd,
                )

            with mock.patch.object(installer, "_replace_staged", side_effect=replace_with_race):
                with self.assertRaisesRegex(InstallAbort, "immediately before replacement"):
                    self.run_install(home)
            self.assertTrue(injected)
            self.assertIn("/concurrent", hooks.read_text())
            pending = home.with_name(f"{home.name}.pilotfish-install-state.json.pending")
            self.assertEqual(json.loads(pending.read_text())["status"], "aborted")

    def test_transaction_preserves_foreign_hook_race_after_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            hooks = home / "hooks.json"
            _write_registration(hooks, {"hooks": {"Stop": [_foreign_group("/original")]}})
            original_commit = installer._commit

            def commit_then_race(*args, **kwargs):
                receipts = original_commit(*args, **kwargs)
                document = json.loads(hooks.read_text())
                document["hooks"]["Stop"].append(_foreign_group("/concurrent"))
                _write_registration(hooks, document)
                return receipts

            with mock.patch.object(installer, "_commit", side_effect=commit_then_race):
                with self.assertRaisesRegex(InstallAbort, "post-write transaction"):
                    self.run_install(home)
            self.assertIn("/concurrent", hooks.read_text())
            self.assertFalse(home.with_name(f"{home.name}.pilotfish-install-state.json").exists())
            pending = home.with_name(f"{home.name}.pilotfish-install-state.json.pending")
            self.assertEqual(json.loads(pending.read_text())["status"], "aborted")

    def test_staged_layout_requires_exact_owned_hook_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            self.assertIsNone(
                stage_smoke_home.explicit_layout_error(
                    home,
                    allow_rollback_backups=True,
                    project_active_root=True,
                )
            )
            projection = stage_smoke_home._required_input_projection(home.resolve())
            self.assertEqual(len(projection), 6)

            extra = home / "hooks" / "unowned.py"
            extra.write_text("pass\n")
            self.assertIn(
                "unapproved entry",
                stage_smoke_home.explicit_layout_error(
                    home,
                    allow_rollback_backups=True,
                    project_active_root=True,
                ),
            )

    def test_pending_state_and_role_drift_abort_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            pending = home.with_name(f"{home.name}.pilotfish-install-state.json.pending")
            pending.write_text("{}")
            with self.assertRaises(InstallAbort):
                self.run_install(home)

            pending.unlink()
            agents = home / "agents"; agents.mkdir()
            (agents / "scout.toml").write_text('name = "scout"\n')
            with self.assertRaises(InstallAbort):
                self.run_install(home)

    def test_unowned_agents_key_aborts_before_any_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            config = home / "config.toml"
            original = '[custom]\nkeep = "yes"\n\n[agents]\nmax_depth = 1\n'
            config.write_text(original)
            with self.assertRaisesRegex(InstallAbort, "agents table"):
                self.run_install(home)
            self.assertEqual(config.read_text(), original)
            self.assertFalse((home / "agents").exists())
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse(home.with_name(f"{home.name}.pilotfish-install-state.json").exists())

    def test_release_pinned_v130_roles_upgrade_but_custom_bytes_abort(self) -> None:
        previous = ROOT / "install" / "previous" / "v1.3.0" / "agents"
        expected = installer.CANONICAL_ROLE_UPGRADE_DIGESTS
        for role in ("plan-verifier", "security-reviewer"):
            payload = (previous / f"{role}.toml").read_bytes()
            self.assertIn(hashlib.sha256(payload).hexdigest(), expected[role])

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            for role in installer.ROLES:
                source = ROOT / "templates" / "agents" / f"{role}.toml"
                prior = previous / f"{role}.toml"
                (agents / f"{role}.toml").write_bytes(
                    prior.read_bytes() if prior.exists() else source.read_bytes()
                )

            self.assertEqual(self.run_install(home), 0)
            for role in ("plan-verifier", "security-reviewer"):
                self.assertEqual(
                    (agents / f"{role}.toml").read_bytes(),
                    (ROOT / "templates" / "agents" / f"{role}.toml").read_bytes(),
                )

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            payload = (previous / "plan-verifier.toml").read_bytes() + b"# custom\n"
            (agents / "plan-verifier.toml").write_bytes(payload)
            with self.assertRaisesRegex(InstallAbort, "installed_role_drift"):
                self.run_install(home)

            self.assertEqual(
                self.run_install(home, replace_drifted_roles=True),
                0,
            )
            self.assertEqual(
                (agents / "plan-verifier.toml").read_bytes(),
                (ROOT / "templates/agents/plan-verifier.toml").read_bytes(),
            )

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            (agents / "plan-verifier.toml").write_bytes(
                (previous / "plan-verifier.toml").read_bytes() + b"# custom\n"
            )
            with self.assertRaisesRegex(InstallAbort, "installed_role_drift"):
                self.run_install(
                    home,
                    replace_drifted_role=("security-reviewer",),
                )
            self.assertEqual(
                self.run_install(
                    home,
                    replace_drifted_role=("plan-verifier",),
                ),
                0,
            )

    def test_dry_run_names_canonical_role_upgrades_without_writes(self) -> None:
        previous = ROOT / "install" / "previous" / "v1.3.0" / "agents"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            for role in installer.ROLES:
                source = ROOT / "templates" / "agents" / f"{role}.toml"
                prior = previous / f"{role}.toml"
                (agents / f"{role}.toml").write_bytes(
                    prior.read_bytes() if prior.exists() else source.read_bytes()
                )
            before = {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file()
            }
            state = home.with_name(f"{home.name}.pilotfish-install-state.json")
            pending = state.with_suffix(".json.pending")
            self.assertFalse(state.exists())
            self.assertFalse(pending.exists())

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = install(
                    source_root=ROOT, codex_home=home, dry_run=True, check_codex=False
                )
            stdout = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("note: upgraded canonical role plan-verifier", stdout)
            self.assertIn("note: upgraded canonical role security-reviewer", stdout)
            self.assertIn("would change", stdout)
            after = {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            self.assertFalse(state.exists())
            self.assertFalse(pending.exists())

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            (agents / "plan-verifier.toml").write_bytes(
                (previous / "plan-verifier.toml").read_bytes() + b"# custom\n"
            )
            with self.assertRaisesRegex(InstallAbort, "installed_role_drift"):
                install(source_root=ROOT, codex_home=home, dry_run=True, check_codex=False)

    def test_release_pinned_v131_roles_upgrade_but_custom_bytes_abort(self) -> None:
        previous = ROOT / "install" / "previous" / "v1.3.1" / "agents"
        for role in ("plan-verifier", "verifier"):
            digest = hashlib.sha256((previous / f"{role}.toml").read_bytes()).hexdigest()
            self.assertIn(digest, installer.CANONICAL_ROLE_UPGRADE_DIGESTS[role])

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            for role in installer.ROLES:
                source = ROOT / "templates" / "agents" / f"{role}.toml"
                (agents / f"{role}.toml").write_bytes(source.read_bytes())
            for role in ("plan-verifier", "verifier"):
                (agents / f"{role}.toml").write_bytes(
                    (previous / f"{role}.toml").read_bytes()
                )

            self.assertEqual(self.run_install(home), 0)
            for role in ("plan-verifier", "verifier"):
                self.assertEqual(
                    (agents / f"{role}.toml").read_bytes(),
                    (ROOT / "templates" / "agents" / f"{role}.toml").read_bytes(),
                )

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            (agents / "plan-verifier.toml").write_bytes(
                (previous / "plan-verifier.toml").read_bytes() + b"# custom\n"
            )
            with self.assertRaisesRegex(InstallAbort, "installed_role_drift"):
                self.run_install(home)

        runbook = (ROOT / "install" / "AGENT-INSTALL.md").read_text()
        self.assertIn(
            "released canonical\nv1.3.1 `plan-verifier` and `verifier`",
            runbook,
        )
        self.assertIn("released canonical v1.3.3 payloads", runbook)

    def test_release_pinned_v132_security_executor_upgrades(self) -> None:
        previous = (
            ROOT
            / "install"
            / "previous"
            / "v1.3.2"
            / "agents"
            / "security-executor.toml"
        )
        digest = hashlib.sha256(previous.read_bytes()).hexdigest()
        self.assertIn(
            digest,
            installer.CANONICAL_ROLE_UPGRADE_DIGESTS["security-executor"],
        )

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            for role in installer.ROLES:
                source = ROOT / "templates" / "agents" / f"{role}.toml"
                (agents / f"{role}.toml").write_bytes(source.read_bytes())
            (agents / "security-executor.toml").write_bytes(previous.read_bytes())

            self.assertEqual(self.run_install(home), 0)
            installed = agents / "security-executor.toml"
            self.assertEqual(
                installed.read_bytes(),
                (ROOT / "templates" / "agents" / "security-executor.toml").read_bytes(),
            )
            state = json.loads(
                home.with_name(f"{home.name}.pilotfish-install-state.json").read_text()
            )
            self.assertEqual(
                state["target_fingerprints"]["agents/security-executor.toml"],
                hashlib.sha256(installed.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                state["original_targets"]["agents/security-executor.toml"]["sha256"],
                digest,
            )
            self.assertEqual(self.run_install(home), 0)

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            (agents / "security-executor.toml").write_bytes(
                previous.read_bytes() + b"# custom\n"
            )
            with self.assertRaisesRegex(InstallAbort, "installed_role_drift"):
                self.run_install(home)

    def test_release_pinned_v133_routing_roles_upgrade(self) -> None:
        previous = ROOT / "install" / "previous" / "v1.3.3" / "agents"
        roles = ("plan-verifier", "verifier")
        for role in roles:
            digest = hashlib.sha256((previous / f"{role}.toml").read_bytes()).hexdigest()
            self.assertIn(digest, installer.CANONICAL_ROLE_UPGRADE_DIGESTS[role])

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            for role in installer.ROLES:
                source = ROOT / "templates" / "agents" / f"{role}.toml"
                (agents / f"{role}.toml").write_bytes(source.read_bytes())
            for role in roles:
                (agents / f"{role}.toml").write_bytes(
                    (previous / f"{role}.toml").read_bytes()
                )

            self.assertEqual(self.run_install(home), 0)
            for role in roles:
                self.assertEqual(
                    (agents / f"{role}.toml").read_bytes(),
                    (ROOT / "templates" / "agents" / f"{role}.toml").read_bytes(),
                )

    def test_two_nonempty_policy_files_abort_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            agents_policy = home / "AGENTS.md"
            override_policy = home / "AGENTS.override.md"
            agents_policy.write_bytes(b"primary policy\n")
            override_policy.write_bytes(b"override policy\n")
            before = {path.name: path.read_bytes() for path in home.iterdir()}

            with self.assertRaisesRegex(InstallAbort, "both policy files"):
                self.run_install(home)

            after = {path.name: path.read_bytes() for path in home.iterdir()}
            self.assertEqual(after, before)

    def test_policy_override_appearing_after_selection_aborts_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            agents_policy = home / "AGENTS.md"
            override_policy = home / "AGENTS.override.md"
            pending = home.with_name(f"{home.name}.pilotfish-install-state.json.pending")
            state = home.with_name(f"{home.name}.pilotfish-install-state.json")
            agents_policy.write_bytes(b"primary policy\n")
            original_atomic_write = installer._atomic_write
            injected = False

            def atomic_write_with_policy_race(path: Path, payload: bytes, mode: int) -> None:
                nonlocal injected
                original_atomic_write(path, payload, mode)
                if path == pending and not injected:
                    override_policy.write_bytes(b"late override policy\n")
                    injected = True

            with mock.patch.object(installer, "_atomic_write", side_effect=atomic_write_with_policy_race):
                with self.assertRaisesRegex(InstallAbort, "both policy files"):
                    self.run_install(home)

            self.assertTrue(injected)
            self.assertEqual(agents_policy.read_bytes(), b"primary policy\n")
            self.assertEqual(override_policy.read_bytes(), b"late override policy\n")
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse(any((home / "agents").glob("*.toml")))
            self.assertFalse(state.exists())
            aborted = json.loads(pending.read_text())
            self.assertEqual(aborted["status"], "aborted")
            self.assertEqual(aborted["error"], "InstallAbort")

    def test_extra_valid_role_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"; agents = home / "agents"; agents.mkdir(parents=True)
            extra = agents / "custom-reviewer.toml"
            extra.write_text(
                'name = "custom-reviewer"\n'
                'description = "User-owned role"\n'
                'model = "gpt-5.6-luna"\n'
                'model_reasoning_effort = "medium"\n'
                'developer_instructions = "Review the requested change."\n'
            )
            self.assertEqual(self.run_install(home), 0)
            self.assertEqual(
                extra.read_text(),
                'name = "custom-reviewer"\n'
                'description = "User-owned role"\n'
                'model = "gpt-5.6-luna"\n'
                'model_reasoning_effort = "medium"\n'
                'developer_instructions = "Review the requested change."\n',
            )

    def test_nested_malformed_or_duplicate_role_aborts_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"; nested = home / "agents" / "nested"; nested.mkdir(parents=True)
            (nested / "scout.toml").write_text('name = "scout"\n')
            with self.assertRaisesRegex(InstallAbort, "invalid role"):
                self.run_install(home)
            self.assertFalse((home / "config.toml").exists())

    def test_agents_root_symlink_is_rejected_before_role_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = root / "home"; home.mkdir(); outside = root / "outside"; outside.mkdir()
            os.symlink(outside, home / "agents")
            with self.assertRaisesRegex(InstallAbort, "agents root"):
                self.run_install(home)


if __name__ == "__main__":
    unittest.main()
