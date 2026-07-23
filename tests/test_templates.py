from __future__ import annotations

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))
from validate_agents import ROLES, validate_config, validate_dir, validate_multi_agent_v2_config  # noqa: E402


class NativeTemplateTests(unittest.TestCase):
    def test_exact_v2_table_has_no_adapter_transport(self) -> None:
        with (ROOT / "templates" / "config.snippet.toml").open("rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(config["features"]["multi_agent_v2"], {"enabled": True, "max_concurrent_threads_per_session": 4})
        self.assertNotIn("multi_agent", config["features"])
        self.assertNotIn("agents", config)
        errors, warnings = validate_multi_agent_v2_config(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_role_manifest_is_exact_and_recursively_validated(self) -> None:
        agents = ROOT / "templates" / "agents"
        self.assertEqual({path.stem for path in agents.glob("*.toml")}, ROLES)
        self.assertEqual(validate_dir(agents, expected_names=ROLES), [])

    def test_rejects_forced_adapter_keys_and_duplicate_names(self) -> None:
        config = {"features": {"multi_agent": True, "multi_agent_v2": {"enabled": True, "max_concurrent_threads_per_session": 4, "tool_namespace": "agents"}}}
        errors, _ = validate_multi_agent_v2_config(config)
        self.assertTrue(any("tool_namespace" in item for item in errors))
        with tempfile.TemporaryDirectory() as directory:
            agents = Path(directory); source = (ROOT / "templates" / "agents" / "scout.toml").read_text()
            (agents / "scout.toml").write_text(source)
            (agents / "copy.toml").write_text(source)
            problems = validate_dir(agents, expected_names=ROLES)
            self.assertTrue(any("duplicate role" in item for item in problems))
            self.assertTrue(any("manifest missing" in item for item in problems))

    def test_policy_is_native_typed_and_post_hoc(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        self.assertIn("native typed `spawn_agent`", policy)
        self.assertIn("non-empty `message`", policy)
        self.assertIn("`agent_type`", policy)
        self.assertIn("`[a-z0-9_]+`", policy)
        self.assertIn('`"1"` through `"3"`', policy)
        self.assertIn("never retry with an untyped child", policy)
        self.assertIn("post-hoc", policy)
        self.assertNotIn("agents.spawn_agent", policy)
        self.assertNotIn("fork_turns = \"all\"", policy)

    def test_policy_exposes_proactive_role_decision_cues(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        self.assertIn("Decision cues", policy)
        self.assertIn("classify each bounded workstream", policy)
        self.assertIn("delegate it to the least expensive", policy)
        self.assertIn("two or more reconnaissance surfaces are independent", policy)
        self.assertIn("bounded implementation requiring judgment to `executor`", policy)
        self.assertIn("approved security-sensitive implementation to `security-executor`", policy)
        self.assertIn("After a non-trivial implementation", policy)
        self.assertIn("dispatch exactly one `mech-executor`", policy)
        self.assertIn("choose delegation by net benefit", policy)
        self.assertIn("stable, complete one-shot brief, not a numeric trigger", policy)
        self.assertIn("smallest coherent integration boundary", policy)
        self.assertIn("`spawn_agent` calls back-to-back", policy)

    def test_policy_preserves_parent_ownership_and_no_untyped_fallback(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        self.assertIn("The parent session remains responsible and accountable throughout", policy)
        self.assertIn("integrates writes", policy)
        self.assertIn("makes final judgment", policy)
        self.assertIn("small, local, already-stable edit", policy)
        self.assertIn("tightly coupled unknown bug", policy)
        self.assertIn("Typed dispatch is an all-or-nothing child-creation boundary", policy)
        self.assertIn("No untyped fallback is permitted", policy)
        self.assertIn("must not silently substitute an untyped child", policy)
        self.assertNotIn("retry as an untyped child", policy)

    def test_runbook_is_native_only(self) -> None:
        runbook = (ROOT / "install" / "AGENT-INSTALL.md").read_text()
        self.assertIn("exactly Codex `0.145.0`", runbook)
        self.assertIn("stage_smoke_home.py", runbook)
        self.assertIn("NATIVE_OK", runbook)
        self.assertIn("no `--mode` or `--all-roles`", runbook)
        self.assertNotIn("ADAPTER_OK", runbook)


if __name__ == "__main__":
    unittest.main()
