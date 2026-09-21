from __future__ import annotations

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))
from validate_agents import ROLES, validate_agents_config, validate_config, validate_dir  # noqa: E402


class NativeTemplateTests(unittest.TestCase):
    def test_exact_agents_table_has_no_legacy_transport(self) -> None:
        with (ROOT / "templates" / "config.snippet.toml").open("rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(config["model"], "gpt-5.6-luna")
        self.assertEqual(config["model_reasoning_effort"], "medium")
        self.assertEqual(config["plan_mode_reasoning_effort"], "xhigh")
        self.assertTrue(config["features"]["default_mode_request_user_input"])
        self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 3)
        self.assertNotIn("max_concurrent_threads_per_session", config)
        self.assertNotIn("multi_agent_v2", config.get("features", {}))
        errors, warnings = validate_agents_config(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_role_manifest_is_exact_and_recursively_validated(self) -> None:
        agents = ROOT / "templates" / "agents"
        self.assertEqual({path.stem for path in agents.glob("*.toml")}, ROLES)
        self.assertEqual(validate_dir(agents, expected_names=ROLES), [])

    def test_model_routing_matches_cost_policy(self) -> None:
        agents = ROOT / "templates" / "agents"
        with (agents / "plan-verifier.toml").open("rb") as handle:
            plan_verifier = tomllib.load(handle)
        with (agents / "verifier.toml").open("rb") as handle:
            verifier = tomllib.load(handle)
        with (agents / "security-executor.toml").open("rb") as handle:
            security_executor = tomllib.load(handle)
        with (agents / "sol-executor.toml").open("rb") as handle:
            sol_executor = tomllib.load(handle)
        with (agents / "executor.toml").open("rb") as handle:
            executor = tomllib.load(handle)
        self.assertEqual(
            (plan_verifier["model"], plan_verifier["model_reasoning_effort"]),
            ("gpt-5.6-sol", "high"),
        )
        self.assertEqual(
            (verifier["model"], verifier["model_reasoning_effort"]),
            ("gpt-5.6-sol", "high"),
        )
        self.assertEqual(
            (security_executor["model"], security_executor["model_reasoning_effort"]),
            ("gpt-5.6-sol", "high"),
        )
        self.assertEqual(
            (executor["model"], executor["model_reasoning_effort"]),
            ("gpt-6-astra", "high"),
        )
        self.assertEqual(
            (sol_executor["model"], sol_executor["model_reasoning_effort"]),
            ("gpt-5.6-sol", "high"),
        )
        for path in agents.glob("*.toml"):
            with path.open("rb") as handle:
                self.assertNotEqual(tomllib.load(handle).get("model"), "gpt-5.6-terra")

    def test_rejects_forced_adapter_keys_and_duplicate_names(self) -> None:
        config = {"features": {"multi_agent_v2": {"enabled": True, "max_concurrent_threads_per_session": 4, "tool_namespace": "agents"}}, "agents": {"max_concurrent_threads_per_session": 3}}
        errors, _ = validate_agents_config(config)
        self.assertTrue(any("legacy features.multi_agent_v2" in item for item in errors))
        with tempfile.TemporaryDirectory() as directory:
            agents = Path(directory); source = (ROOT / "templates" / "agents" / "scout.toml").read_text(encoding="utf-8")
            (agents / "scout.toml").write_text(source, encoding="utf-8")
            (agents / "copy.toml").write_text(source, encoding="utf-8")
            problems = validate_dir(agents, expected_names=ROLES)
            self.assertTrue(any("duplicate role" in item for item in problems))
            self.assertTrue(any("manifest missing" in item for item in problems))

    def test_validator_rejects_nonpackaged_agents_keys(self) -> None:
        config = {"agents": {"max_concurrent_threads_per_session": 3, "max_depth": 1}}
        errors, _ = validate_agents_config(config)
        self.assertTrue(any("unsupported inline role" in item for item in errors))

    def test_policy_is_native_typed_and_post_hoc(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8")
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
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8")
        policy = " ".join(policy.split())
        self.assertIn("Decision cues", policy)
        self.assertIn("classify each bounded workstream", policy)
        self.assertIn("delegate it to the least expensive", policy)
        self.assertIn("two or more reconnaissance surfaces are independent", policy)
        self.assertIn("bounded implementation requiring judgment to `sol-executor`", policy)
        self.assertIn("approved security-sensitive implementation to `security-executor`", policy)
        self.assertIn("After a risk-triggered implementation", policy)
        self.assertIn("dispatch exactly one `mech-executor`", policy)
        self.assertIn("choose delegation by net benefit", policy)
        self.assertIn("stable, complete one-shot brief, not a numeric trigger", policy)
        self.assertIn("smallest coherent integration boundary", policy)
        self.assertIn("`spawn_agent` calls back-to-back", policy)

    def test_policy_exposes_adaptive_route_and_discovery_contract(self) -> None:
        policy = " ".join(
            (ROOT / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8").split()
        )
        for phrase in (
            "Adaptive intent routing",
            "`execute`",
            "`explore_then_plan`",
            "`co_discover`",
            "`change_impact`: `trivial`, `low`, `material`, `high`, or `critical`",
            "`discovery_budget`",
            "`budget_exhausted`",
            "`evidence_sufficient`",
            "`none`",
            "`minimum`",
            "`bounded`",
            "`deep`",
            "AskUserQuestion",
            "`direction_checkpoint`",
            "`CONTINUE`",
            "`PIVOT`",
            "`ROLLBACK`",
            "Outcome-level continuation",
            "`execution_scope`",
            "`continuation_mode`",
            "`stop_condition`",
            "phase boundary is progress reporting",
            "presence gates for likely long unattended work",
        ):
            self.assertIn(phrase, policy)

    def test_policy_preserves_risk_triggered_plan_review(self) -> None:
        policy = " ".join(
            (ROOT / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8").split()
        )
        self.assertIn("Independent review is risk-triggered, not a synonym for non-trivial", policy)
        self.assertIn("a data, schema, serialization, migration, or release boundary", policy)
        self.assertIn("After two automatic `REVISE` verdicts for the same unit", policy)
        self.assertIn("not merely to authorize another review round", policy)
        self.assertNotIn("Sol escalation is narrower than the risk trigger", policy)

    def test_policy_preserves_parent_ownership_and_no_untyped_fallback(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8")
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

    def test_verifier_uses_calibrated_outcomes(self) -> None:
        with (ROOT / "templates" / "agents" / "verifier.toml").open("rb") as handle:
            verifier = tomllib.load(handle)
        description = verifier["description"]
        instructions = " ".join(verifier["developer_instructions"].split())
        self.assertCountEqual(
            [verdict for verdict in ("CONFIRMED", "REFUTED", "INCONCLUSIVE") if verdict in description],
            ("CONFIRMED", "REFUTED", "INCONCLUSIVE"),
        )
        self.assertRegex(
            instructions,
            r"REFUTED — at least one reproducible P0-P2 finding blocks the exact claim",
        )
        self.assertRegex(
            instructions,
            r"regressions caused by the reviewed implementation are claim-relevant",
        )
        self.assertRegex(
            instructions,
            r"For every finding or advisory under any verdict",
        )
        self.assertRegex(
            instructions,
            r"any reproducible high-impact user or system failure that does not meet P0",
        )
        self.assertRegex(
            instructions,
            r"sufficient for every required acceptance condition.*"
            r"List each condition.*evidence and result",
        )
        self.assertRegex(
            instructions,
            r"REFUTED takes precedence when a reproducible P0-P2 blocker coexists.*"
            r"unevaluated required acceptance condition makes the verdict INCONCLUSIVE",
        )
        self.assertRegex(
            instructions,
            r"Priority measures .* user or system impact, not .* central to the exact claim.*"
            r"failed acceptance .* bounded or recoverable .* P2 unless .* P0 or high-impact P1.*"
            r"P1 = any reproducible\s+high-impact user or system failure that does not meet P0",
        )
        self.assertRegex(
            instructions,
            r"P3/P4 are non-blocking advisories and cannot by themselves produce REFUTED",
        )
        self.assertIn("Drive the primary acceptance flow first", instructions)
        self.assertIn("do not reopen adjacent hardening", instructions)
        self.assertRegex(
            instructions,
            r"Priority P0-P4, Confidence high/medium/low, Evidence, Expected, Actual, and Recheck",
        )
        self.assertRegex(
            instructions,
            r"INCONCLUSIVE .* State the reason, missing evidence, and retry condition",
        )
        self.assertNotRegex(
            instructions.lower(),
            r"assume (?:it|the change) is broken|do not trust|finding[- ]volume pressure",
        )

    def test_verifier_supports_direction_checkpoint_contract(self) -> None:
        with (ROOT / "templates" / "agents" / "verifier.toml").open("rb") as handle:
            verifier = tomllib.load(handle)
        description = verifier["description"]
        instructions = " ".join(verifier["developer_instructions"].split())
        for phrase in (
            "direction-checkpoint",
            "`direction_checkpoint`",
            "`CONTINUE`",
            "`PIVOT`",
            "`ROLLBACK`",
            "`INCONCLUSIVE`",
            "latest verified good checkpoint",
        ):
            self.assertIn(phrase, f"{description} {instructions}")

    def test_runbook_is_native_only(self) -> None:
        runbook = (ROOT / "install" / "AGENT-INSTALL.md").read_text(encoding="utf-8")
        self.assertIn("single parseable semantic version", runbook)
        self.assertIn("stage_smoke_home.py", runbook)
        self.assertIn("NATIVE_OK", runbook)
        self.assertIn("no `--mode` or `--all-roles`", runbook)
        self.assertNotIn("ADAPTER_OK", runbook)


if __name__ == "__main__":
    unittest.main()
