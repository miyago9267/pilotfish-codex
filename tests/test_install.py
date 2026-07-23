"""Offline native installer tests; all homes are temporary."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))
import install as installer  # noqa: E402
from install import InstallAbort, install, merge_config_text, parse_codex_version  # noqa: E402


class NativeConfigMergeTests(unittest.TestCase):
    def test_empty_config_renders_exact_native_table(self) -> None:
        rendered, _ = merge_config_text("")
        data = tomllib.loads(rendered)
        self.assertEqual(data["features"]["multi_agent_v2"], {"enabled": True, "max_concurrent_threads_per_session": 4})
        self.assertNotIn("agents", data)
        self.assertNotIn("multi_agent", data["features"])

    def test_scalar_true_is_converted_and_false_aborts(self) -> None:
        rendered, _ = merge_config_text("[features]\nmulti_agent_v2 = true\n")
        self.assertTrue(tomllib.loads(rendered)["features"]["multi_agent_v2"]["enabled"])
        for text in ("[features]\nmulti_agent_v2 = false\n", "[features.multi_agent_v2]\nenabled = false\n"):
            with self.subTest(text=text):
                with self.assertRaises(InstallAbort):
                    merge_config_text(text)

    def test_normalizes_managed_domain_and_rejects_conflicts(self) -> None:
        rendered, _ = merge_config_text("[features.multi_agent_v2]\nenabled = true\nmax_concurrent_threads_per_session = 8\n")
        self.assertEqual(tomllib.loads(rendered)["features"]["multi_agent_v2"]["max_concurrent_threads_per_session"], 4)
        for value in (0, 9, '"4"'):
            with self.subTest(value=value):
                with self.assertRaises(InstallAbort):
                    merge_config_text(f"[features.multi_agent_v2]\nenabled = true\nmax_concurrent_threads_per_session = {value}\n")
        with self.assertRaises(InstallAbort):
            merge_config_text("[agents]\nmax_concurrent_threads_per_session = 2\n")

    def test_unowned_legacy_key_is_preserved(self) -> None:
        original = "[features]\nmulti_agent = true\n\n[features.multi_agent_v2]\nenabled = true\n"
        rendered, notes = merge_config_text(original)
        self.assertTrue(tomllib.loads(rendered)["features"]["multi_agent"])
        self.assertIn("legacy_key_unowned: preserved features.multi_agent", notes)

    def test_owned_legacy_key_is_removed(self) -> None:
        original = "[features]\nmulti_agent = true\n\n[features.multi_agent_v2]\nenabled = true\ntool_namespace = \"agents\"\n"
        rendered, _ = merge_config_text(original, owned_legacy=frozenset({"features.multi_agent", "features.multi_agent_v2.tool_namespace"}))
        data = tomllib.loads(rendered)
        self.assertNotIn("multi_agent", data["features"])
        self.assertNotIn("tool_namespace", data["features"]["multi_agent_v2"])

    def test_exact_version_parser(self) -> None:
        self.assertEqual(parse_codex_version("codex 0.145.0"), (0, 145, 0))
        for output in ("0.145.0-beta", "0.145.0 0.145.1", "none"):
            with self.subTest(output=output):
                self.assertIsNone(parse_codex_version(output))


class NativeInstallTests(unittest.TestCase):
    def run_install(self, home: Path, **kwargs: object) -> int:
        return install(source_root=ROOT, codex_home=home, dry_run=False, check_codex=False, **kwargs)

    def test_install_is_atomic_idempotent_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            self.assertEqual(self.run_install(home), 0)
            config = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(config["features"]["multi_agent_v2"]["max_concurrent_threads_per_session"], 4)
            self.assertEqual({p.stem for p in (home / "agents").glob("*.toml")}, {"executor", "mech-executor", "plan-verifier", "scout", "security-executor", "security-reviewer", "verifier"})
            state = home.with_name(f"{home.name}.pilotfish-install-state.json")
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["status"], "committed")
            self.assertIn("config.toml", recorded["target_fingerprints"])
            self.assertIn("config.toml", recorded["original_targets"])
            first = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            self.assertEqual(self.run_install(home), 0)
            second = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            self.assertEqual(first, second)

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

    def test_extra_role_aborts_without_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"; agents = home / "agents"; agents.mkdir(parents=True)
            (agents / "Explore.toml").write_text('name = "Explore"\n')
            with self.assertRaisesRegex(InstallAbort, "invalid role"):
                self.run_install(home)
            self.assertTrue((agents / "Explore.toml").exists())

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
