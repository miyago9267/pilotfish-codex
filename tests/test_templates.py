from __future__ import annotations

import hashlib
import io
import re
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "templates" / "agents"
sys.path.insert(0, str(ROOT / "install"))

from validate_agents import (  # noqa: E402
    validate_agent,
    validate_config,
    validate_dir,
    validate_multi_agent_v2_config,
    main as validate_main,
)
ROUTING = {
    "scout": ("gpt-5.6-luna", "low", "read-only"),
    "plan-verifier": ("gpt-5.6-sol", "medium", "read-only"),
    "security-reviewer": ("gpt-5.6-sol", "high", "read-only"),
    "mech-executor": ("gpt-5.6-luna", "medium", None),
    "executor": ("gpt-5.6-luna", "max", None),
    "verifier": ("gpt-5.6-sol", "high", "workspace-write"),
    "security-executor": ("gpt-5.6-sol", "max", None),
}


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


class TemplateContractTests(unittest.TestCase):
    def test_complete_codex_role_routing_map(self) -> None:
        files = {path.stem: path for path in AGENTS_DIR.glob("*.toml")}
        self.assertEqual(len(ROUTING), 7)
        self.assertEqual(set(files), set(ROUTING))

        for role, (model, effort, sandbox) in ROUTING.items():
            agent = load_toml(files[role])
            self.assertEqual(agent["name"], role)
            self.assertEqual(agent["model"], model)
            self.assertEqual(agent["model_reasoning_effort"], effort)
            self.assertEqual(agent.get("sandbox_mode"), sandbox)
            self.assertIn("cannot delegate", agent["developer_instructions"])

        scout = load_toml(files["scout"])
        self.assertIn("broad codebase sweeps", scout["description"])
        self.assertIn("focused lookup", scout["description"])

    def test_review_and_execution_boundaries_stay_separate(self) -> None:
        plan = load_toml(AGENTS_DIR / "plan-verifier.toml")
        outcome = load_toml(AGENTS_DIR / "verifier.toml")
        security_review = load_toml(AGENTS_DIR / "security-reviewer.toml")
        security_execute = load_toml(AGENTS_DIR / "security-executor.toml")

        self.assertIn("READY", plan["developer_instructions"])
        self.assertIn("REVISE", plan["developer_instructions"])
        self.assertNotIn("CONFIRMED", plan["developer_instructions"])
        self.assertNotIn("REFUTED", plan["developer_instructions"])

        self.assertIn("CONFIRMED", outcome["developer_instructions"])
        self.assertIn("REFUTED", outcome["developer_instructions"])
        self.assertNotIn("READY", outcome["developer_instructions"])
        self.assertNotIn("REVISE", outcome["developer_instructions"])

        self.assertEqual(security_review["web_search"], "live")
        self.assertIn("approved implementation", security_review["developer_instructions"])
        self.assertIn("pre-approval evidence", security_execute["developer_instructions"])

    def test_config_keeps_main_effort_user_controlled(self) -> None:
        config = load_toml(ROOT / "templates" / "config.snippet.toml")
        self.assertEqual(config["model"], "gpt-5.6-sol")
        self.assertNotIn("model_reasoning_effort", config)
        self.assertTrue(config["features"]["multi_agent"])
        adapter = config["features"]["multi_agent_v2"]
        self.assertFalse(adapter["hide_spawn_agent_metadata"])
        self.assertEqual(adapter["tool_namespace"], "agents")
        self.assertEqual(adapter["max_concurrent_threads_per_session"], 4)
        self.assertNotIn("enabled", adapter)
        self.assertEqual(config["agents"]["max_threads"], 3)
        self.assertEqual(config["agents"]["max_depth"], 1)

    def test_policy_version_and_roster(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"<!-- pilotfish-codex v{version} -->", policy)
        self.assertEqual(policy.count("pilotfish-codex:begin"), 1)
        self.assertEqual(policy.count("pilotfish-codex:end"), 1)

        for role in ROUTING:
            row = rf"\| `{re.escape(role)}` \|"
            self.assertRegex(policy, row)

        self.assertNotIn("`Explore`", policy)
        self.assertNotIn("gpt-5.6-", policy)
        self.assertNotIn("| Model |", policy)
        self.assertNotIn("| Effort |", policy)
        self.assertIn("Discovery", policy)
        self.assertIn("Plan", policy)
        self.assertIn("Approval", policy)
        self.assertIn("Execution", policy)
        self.assertIn("Verification", policy)
        self.assertIn("delegation-planning layer", policy)
        self.assertIn("agent TOMLs remain authoritative", policy)
        self.assertIn("Never swap `plan-verifier` and `verifier`", policy)

    def test_installer_covers_strict_global_install(self) -> None:
        installer = (ROOT / "install" / "AGENT-INSTALL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Codex CLI 0.144.1 or newer", installer)
        self.assertIn("codex --strict-config doctor --summary", installer)
        self.assertIn("~/.codex/AGENTS.override.md", installer)
        self.assertIn("model_reasoning_effort", installer)
        self.assertIn("confirmed legacy-owned", installer)
        self.assertIn("config.toml.pilotfish-[0-9]*", installer)
        self.assertIn("config.toml.pilotfish-codex-*", installer)
        self.assertIn("current project root", installer)
        self.assertIn("inactive instruction", installer)
        self.assertIn("Retired v1.0.x `explore.toml`", installer)
        self.assertIn("Retired pre-release `Explore.toml`", installer)
        self.assertRegex(installer, r"Stop only when the\s+version")
        self.assertRegex(
            installer,
            r"do not claim an exact\s+seven-role installation",
        )
        self.assertIn("[features.multi_agent_v2]", installer)
        self.assertIn("hide_spawn_agent_metadata", installer)
        self.assertIn("tool_namespace", installer)
        self.assertIn("max_concurrent_threads_per_session", installer)
        self.assertIn("Do not set `features.multi_agent_v2.enabled`", installer)
        self.assertIn("start a fresh Codex session", installer)
        self.assertIn("install/verify_dispatch.py --live --yes", installer)
        self.assertIn(
            "--config ~/.codex/config.toml ~/.codex/agents",
            installer,
        )

        for role in ROUTING:
            self.assertRegex(installer, rf"`{re.escape(role)}`")

    def test_installer_migrates_v10_state_without_guessing(self) -> None:
        installer = (ROOT / "install" / "AGENT-INSTALL.md").read_text(
            encoding="utf-8"
        )

        self.assertRegex(
            installer,
            r"Prefer the earliest legacy backup, then the\s+earliest current backup",
        )
        self.assertIn("never copy", installer)
        self.assertIn("either pristine prefix", installer)
        self.assertRegex(
            installer,
            r'v1\.0\.x upgrade whose current root\s+'
            r'`model_reasoning_effort = "medium"`',
        )
        self.assertRegex(installer, r"If the root\s+key was absent there")
        self.assertIn("explicit remove-or-keep choice", installer)
        self.assertRegex(installer, r"If the backup contained the\s+key")
        self.assertIn("If no pristine backup exists", installer)

        self.assertIn("deduplicate candidates by resolved path", installer)
        self.assertIn("current project root", installer)
        self.assertIn("remove each stale marked block", installer)
        self.assertIn("Re-run the same preflight", installer)

    def test_retired_explore_template_is_verifiable_but_inactive(self) -> None:
        retired = {
            "v1.0.0": "9bfdcbc3c032c084dcc0ee77e4fa74de3b30f0e1dfd1e87e180545052a85b59b",
            "v1.0.1": "d90b4735917afe9d5525c2f0429406c6bffa8d539d664b27760ed4680449a9a4",
        }

        for version, expected_hash in retired.items():
            path = ROOT / "install" / "retired" / version / "explore.toml"
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash
            )
            self.assertEqual(load_toml(path)["name"], "explore")

        self.assertFalse((AGENTS_DIR / "explore.toml").exists())

    def test_readme_matches_seven_role_contract(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("The seven Codex roles", readme)
        self.assertIn("Claude-only `Explore` override", readme)
        self.assertIn("main-session effort remains user-controlled", readme)
        self.assertIn("parent-session permission override", readme)
        self.assertIn("obsolete marked Pilotfish block", readme)
        self.assertIn("MultiAgentV2 compatibility", readme)
        self.assertIn("install/verify_dispatch.py --live --yes", readme)
        self.assertIn("ADAPTER_OK", readme)
        self.assertIn("NATIVE_OK", readme)

        for role in ROUTING:
            self.assertIn(f"`{role}`", readme)

    def test_design_explains_codex_adaptation_boundary(self) -> None:
        design = (ROOT / "docs" / "design.md").read_text(encoding="utf-8")
        self.assertIn("Remora supplies routing data", design)
        self.assertIn("Pilotfish's uppercase `Explore` role is deliberately absent", design)
        self.assertIn("policy names roles but never embeds", design)
        self.assertIn("delegation-planning layer", design)
        self.assertIn("Compatibility adapter", design)
        self.assertIn("adapter-required", design)
        self.assertIn("native-ready", design)
        self.assertIn("fail closed", design)
        self.assertIn("static packaging proof", design)
        self.assertIn("live routing proof", design)


class AgentStaticValidationTests(unittest.TestCase):
    """Close the gap `codex --strict-config doctor` leaves: it validates
    config.toml only, never agents/*.toml. Unknown keys and out-of-enum values
    must fail before a role reaches a live session."""

    VALID = {
        "name": "scout",
        "description": "read-only reconnaissance",
        "model": "gpt-5.6-luna",
        "model_reasoning_effort": "low",
        "sandbox_mode": "read-only",
        "developer_instructions": "You are a scout.",
    }

    def test_all_templates_pass_the_validator(self) -> None:
        self.assertEqual(validate_dir(AGENTS_DIR), [])

    def test_unknown_key_fails(self) -> None:
        agent = dict(self.VALID, sandbox_moed="read-only")
        errors = validate_agent(agent)
        self.assertTrue(any("unknown key" in e for e in errors))

    def test_missing_required_key_fails(self) -> None:
        agent = dict(self.VALID)
        del agent["model"]
        errors = validate_agent(agent)
        self.assertTrue(any("missing required" in e for e in errors))

    def test_bad_sandbox_enum_fails(self) -> None:
        agent = dict(self.VALID, sandbox_mode="read_only")
        errors = validate_agent(agent)
        self.assertTrue(any("sandbox_mode" in e for e in errors))

    def test_bad_web_search_enum_fails(self) -> None:
        agent = dict(self.VALID, web_search="on")
        errors = validate_agent(agent)
        self.assertTrue(any("web_search" in e for e in errors))

    def test_bad_reasoning_effort_fails(self) -> None:
        agent = dict(self.VALID, model_reasoning_effort="maxx")
        errors = validate_agent(agent)
        self.assertTrue(any("model_reasoning_effort" in e for e in errors))

    def test_blank_developer_instructions_fails(self) -> None:
        agent = dict(self.VALID, developer_instructions="   ")
        errors = validate_agent(agent)
        self.assertTrue(any("cannot be blank" in e for e in errors))


class MultiAgentV2ConfigValidationTests(unittest.TestCase):
    def valid_config(self, concurrency: object = 4) -> dict:
        return {
            "features": {
                "multi_agent": True,
                "multi_agent_v2": {
                    "hide_spawn_agent_metadata": False,
                    "tool_namespace": "agents",
                    "max_concurrent_threads_per_session": concurrency,
                },
            },
            "agents": {"max_threads": 3, "max_depth": 1},
        }

    def test_packaged_adapter_is_valid_and_defaults_to_four(self) -> None:
        config = load_toml(ROOT / "templates" / "config.snippet.toml")

        errors, warnings = validate_multi_agent_v2_config(config)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertNotIn("enabled", config["features"]["multi_agent_v2"])

    def test_partial_or_forced_adapter_fails_closed(self) -> None:
        missing_namespace = self.valid_config()
        del missing_namespace["features"]["multi_agent_v2"]["tool_namespace"]
        forced_v2 = self.valid_config()
        forced_v2["features"]["multi_agent_v2"]["enabled"] = True

        missing_errors, _ = validate_multi_agent_v2_config(missing_namespace)
        forced_errors, _ = validate_multi_agent_v2_config(forced_v2)

        self.assertTrue(any("tool_namespace" in error for error in missing_errors))
        self.assertTrue(any("enabled" in error for error in forced_errors))

        missing_concurrency = self.valid_config()
        del missing_concurrency["features"]["multi_agent_v2"][
            "max_concurrent_threads_per_session"
        ]
        missing_errors, _ = validate_multi_agent_v2_config(missing_concurrency)
        self.assertTrue(any("concurrency" in error for error in missing_errors))

        missing_table, _ = validate_multi_agent_v2_config({"features": {}})
        self.assertTrue(any("table is missing" in error for error in missing_table))

    def test_concurrency_boundaries_and_warnings(self) -> None:
        invalid_values = (0, 9, "4", True)
        for value in invalid_values:
            with self.subTest(value=value):
                errors, _ = validate_multi_agent_v2_config(self.valid_config(value))
                self.assertTrue(any("concurrency" in error for error in errors))

        errors, warnings = validate_multi_agent_v2_config(self.valid_config(1))
        self.assertEqual(errors, [])
        self.assertTrue(any("disables child delegation" in item for item in warnings))

        errors, warnings = validate_multi_agent_v2_config(self.valid_config(3))
        self.assertEqual(errors, [])
        self.assertTrue(any("recommended value is 4" in item for item in warnings))

        errors, warnings = validate_multi_agent_v2_config(self.valid_config(5))
        self.assertEqual(errors, [])
        self.assertTrue(any("higher cost" in item for item in warnings))

        errors, warnings = validate_multi_agent_v2_config(self.valid_config(8))
        self.assertEqual(errors, [])
        self.assertTrue(any("higher cost" in item for item in warnings))

    def test_config_file_reports_malformed_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[features.multi_agent_v2\n", encoding="utf-8")

            errors, warnings = validate_config(path)

        self.assertEqual(warnings, [])
        self.assertTrue(any("invalid TOML" in error for error in errors))

    def test_cli_validates_an_explicit_config_and_agent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_bytes(
                (ROOT / "templates" / "config.snippet.toml").read_bytes()
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = validate_main(
                    ["--config", str(config_path), str(AGENTS_DIR)]
                )

        self.assertEqual(result, 0)
        self.assertIn("all Pilotfish config and agent TOMLs valid", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_reports_config_errors_and_non_default_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                """
[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
max_concurrent_threads_per_session = 9
""".lstrip(),
                encoding="utf-8",
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = validate_main(["--config", str(config_path), str(AGENTS_DIR)])

        self.assertEqual(result, 1)
        self.assertIn("concurrency must be an integer from 1 to 8", stderr.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                """
[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
max_concurrent_threads_per_session = 3
""".lstrip(),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = validate_main(["--config", str(config_path), str(AGENTS_DIR)])

        self.assertEqual(result, 0)
        self.assertIn("warning:", stderr.getvalue())
        self.assertIn("concurrency 3", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
