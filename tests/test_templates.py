from __future__ import annotations

import hashlib
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "templates" / "agents"
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

        for role in ROUTING:
            self.assertIn(f"`{role}`", readme)

    def test_design_explains_codex_adaptation_boundary(self) -> None:
        design = (ROOT / "docs" / "design.md").read_text(encoding="utf-8")
        self.assertIn("Remora supplies routing data", design)
        self.assertIn("Pilotfish's uppercase `Explore` role is deliberately absent", design)
        self.assertIn("policy names roles but never embeds", design)
        self.assertIn("delegation-planning layer", design)


if __name__ == "__main__":
    unittest.main()
