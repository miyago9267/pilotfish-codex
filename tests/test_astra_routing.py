from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))

import benchmark_routing as benchmark  # noqa: E402
import benchmark_role_fitness as fitness  # noqa: E402
import verify_dispatch  # noqa: E402
from routing_contract import (  # noqa: E402
    build_routing_context,
    validate_routing_context,
)


class AstraPricingTests(unittest.TestCase):
    def test_current_model_prices_include_astra(self) -> None:
        self.assertEqual(benchmark.MODEL_PRICES["gpt-5.6-luna"], (0.20, 1.20))
        self.assertEqual(benchmark.MODEL_PRICES["gpt-5.6-terra"], (2.00, 12.00))
        self.assertEqual(benchmark.MODEL_PRICES["gpt-5.6-sol"], (4.00, 20.00))
        self.assertEqual(benchmark.MODEL_PRICES["gpt-6-astra"], (10.00, 50.00))

    def test_long_context_surcharge_applies_to_input_and_output(self) -> None:
        base = benchmark.price_usage(
            "gpt-6-astra",
            input_tokens=100_000,
            output_tokens=10_000,
        )
        long = benchmark.price_usage(
            "gpt-6-astra",
            input_tokens=272_001,
            output_tokens=10_000,
        )
        self.assertAlmostEqual(base, 1.5)
        self.assertAlmostEqual(long, 6.19002)

    def test_long_context_surcharge_starts_after_exact_threshold(self) -> None:
        at_threshold = benchmark.price_usage(
            "gpt-6-astra",
            input_tokens=272_000,
            output_tokens=10_000,
        )
        above_threshold = benchmark.price_usage(
            "gpt-6-astra",
            input_tokens=272_001,
            output_tokens=10_000,
        )
        self.assertAlmostEqual(at_threshold, 3.22)
        self.assertAlmostEqual(above_threshold, 6.19002)
        self.assertGreater(above_threshold, at_threshold)

    def test_token_efficiency_is_an_estimate_not_recorded_usage(self) -> None:
        raw = benchmark.price_usage("gpt-6-astra", input_tokens=300_000, output_tokens=30_000)
        estimate = benchmark.estimate_task_cost(
            "gpt-6-astra",
            input_tokens=300_000,
            output_tokens=30_000,
            workload="agentic",
        )
        self.assertAlmostEqual(estimate, raw / 3)

    def test_reasoning_efficiency_matches_declared_175_percent_cost_ratio(self) -> None:
        sol = benchmark.price_usage(
            "gpt-5.6-sol",
            input_tokens=100_000,
            output_tokens=10_000,
        )
        astra = benchmark.estimate_task_cost(
            "gpt-6-astra",
            input_tokens=100_000,
            output_tokens=10_000,
            workload="reasoning",
        )
        self.assertAlmostEqual(astra / sol, 1.75)

    def test_reasoning_efficiency_keeps_long_context_surcharge_in_ratio(self) -> None:
        sol = benchmark.price_usage(
            "gpt-5.6-sol",
            input_tokens=272_001,
            output_tokens=10_000,
        )
        astra = benchmark.estimate_task_cost(
            "gpt-6-astra",
            input_tokens=272_001,
            output_tokens=10_000,
            workload="reasoning",
        )
        self.assertAlmostEqual(astra / sol, 1.75)


class AstraRoleRoutingTests(unittest.TestCase):
    def test_tool_and_cross_system_work_selects_astra_candidate(self) -> None:
        candidate, reason = benchmark.select_role_candidate(
            "verifier",
            complexity="cross_system",
            tool_actions=2,
        )
        self.assertEqual(candidate.as_dict(), {"model": "gpt-6-astra", "reasoning_effort": "high"})
        self.assertEqual(reason, "tool-complexity")

    def test_cross_system_is_a_tool_complexity_trigger_even_without_counted_calls(self) -> None:
        candidate, reason = benchmark.select_role_candidate(
            "verifier",
            complexity="cross_system",
        )
        self.assertEqual(candidate.as_dict(), {"model": "gpt-6-astra", "reasoning_effort": "high"})
        self.assertEqual(reason, "tool-complexity")

    def test_routine_verifier_stays_luna(self) -> None:
        candidate, reason = benchmark.select_role_candidate("verifier", complexity="routine")
        self.assertEqual(candidate.as_dict(), {"model": "gpt-5.6-luna", "reasoning_effort": "xhigh"})
        self.assertEqual(reason, "baseline")

    def test_critical_without_an_allowed_capability_trigger_stays_baseline(self) -> None:
        candidate, reason = benchmark.select_role_candidate("verifier", complexity="critical")
        self.assertEqual(candidate.as_dict(), {"model": "gpt-5.6-luna", "reasoning_effort": "xhigh"})
        self.assertEqual(reason, "baseline")

    def test_long_horizon_and_disagreement_are_explicit_astra_triggers(self) -> None:
        candidate, reason = benchmark.select_role_candidate("executor", complexity="long_horizon")
        self.assertEqual(candidate.as_dict(), {"model": "gpt-6-astra", "reasoning_effort": "high"})
        self.assertEqual(reason, "long-horizon")
        candidate, reason = benchmark.select_role_candidate("semantic-adjudicator", disagreement=True)
        self.assertEqual(candidate.as_dict(), {"model": "gpt-6-astra", "reasoning_effort": "high"})
        self.assertEqual(reason, "disagreement")

    def test_semantic_adjudicator_does_not_escalate_without_disagreement(self) -> None:
        candidate, reason = benchmark.select_role_candidate(
            "semantic-adjudicator",
            complexity="cross_system",
            tool_actions=2,
            external_evidence=True,
        )
        self.assertEqual(candidate.as_dict(), {"model": "gpt-5.6-sol", "reasoning_effort": "high"})
        self.assertEqual(reason, "baseline")

    def test_candidate_projection_is_provider_explicit_and_bounded(self) -> None:
        projection = benchmark.candidate_projection()
        self.assertIn("security-reviewer", projection)
        self.assertIn(
            {"model": "gpt-6-astra", "reasoning_effort": "high"},
            projection["security-reviewer"],
        )
        self.assertNotIn("plan-verifier", projection)

    def test_mechanical_roles_are_luna_only_even_when_tool_triggers_fire(self) -> None:
        for role in ("mech-executor", "scout"):
            with self.subTest(role=role):
                candidate, reason = benchmark.select_role_candidate(
                    role,
                    complexity="long_horizon",
                    tool_actions=20,
                    external_evidence=True,
                    disagreement=True,
                )
                self.assertEqual(candidate.model, "gpt-5.6-luna")
                self.assertEqual(reason, "baseline-only")

    def test_mechanical_role_binding_drift_fails_closed(self) -> None:
        with mock.patch.object(
            benchmark,
            "_template_candidate",
            return_value=benchmark.Candidate("gpt-6-astra", "high"),
        ):
            with self.assertRaisesRegex(benchmark.BenchmarkError, "baseline-only role binding drift"):
                benchmark.select_role_candidate("mech-executor", complexity="routine")

    def test_default_policy_forbids_astra_override_for_mechanical_roles(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8")
        bootstrap = (ROOT / "templates" / "agents-md.bootstrap.md").read_text(encoding="utf-8")
        role = (ROOT / "templates" / "agents" / "mech-executor.toml").read_text(encoding="utf-8")
        skill = (ROOT / "plugin" / "plugins" / "pilotfish-codex" / "skills" / "pilotfish-orchestration" / "SKILL.md").read_text(encoding="utf-8")
        for source in (policy, bootstrap, role, skill):
            self.assertIn("mech-executor", source)
            self.assertIn("Astra", source)
        self.assertIn("baseline-only", policy)
        self.assertIn("baseline-only", bootstrap)
        self.assertIn("never request Astra", role)
        self.assertIn("baseline-only Luna roles", skill)

    def test_role_fitness_binding_is_loaded_from_template(self) -> None:
        expected = fitness.load_expected_bindings()
        self.assertEqual(expected["security-reviewer"], ("gpt-5.6-sol", "high"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in (ROOT / "templates" / "agents").glob("*.toml"):
                content = source.read_text(encoding="utf-8")
                if source.stem == "security-reviewer":
                    content = content.replace("gpt-5.6-sol", "gpt-6-astra")
                (root / source.name).write_text(content, encoding="utf-8")
            self.assertEqual(
                fitness.load_expected_bindings(root)["security-reviewer"],
                ("gpt-6-astra", "high"),
            )


class RoutingReceiptTests(unittest.TestCase):
    def test_routing_context_is_explicit_and_redacted(self) -> None:
        context = build_routing_context(
            model_candidate="gpt-6-astra",
            model_snapshot="gpt-6-astra@high",
            complexity="cross_system",
            escalation_reason="tool-complexity",
            permission_profile="read-only",
            claim={"case_id": "case-1", "outcome": "verified"},
        )
        validate_routing_context(context)
        self.assertEqual(context["model_candidate"], "gpt-6-astra")
        self.assertEqual(context["role"], "unknown")
        self.assertEqual(context["evidence_budget"]["context_scope"], "named-inputs-only")
        self.assertRegex(context["claim_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertNotIn("case-1", json.dumps(context))

    def test_routing_context_rejects_unknown_or_unredacted_fields(self) -> None:
        context = build_routing_context(
            model_candidate="gpt-6-astra",
            model_snapshot="gpt-6-astra@high",
            complexity="routine",
            escalation_reason="baseline",
            permission_profile="read-only",
            claim="claim",
        )
        context["prompt"] = "should not be retained"
        with self.assertRaises(ValueError):
            validate_routing_context(context)
        context = build_routing_context(
            model_candidate="gpt-6-astra",
            model_snapshot="gpt-6-astra@high",
            complexity="routine",
            escalation_reason="baseline",
            permission_profile="read-only",
            claim="claim",
        )
        context["evidence_budget"] = {"max_tool_calls": "20", "max_wall_seconds": 600, "context_scope": "named-inputs-only"}
        with self.assertRaises(ValueError):
            validate_routing_context(context)

    def test_platform_halt_maps_to_capability_gap(self) -> None:
        self.assertEqual(benchmark.failure_class_for_receipt("SKIPPED", "platform_halt"), "capability_gap")
        self.assertTrue(verify_dispatch.platform_halt_detected('{"type":"safety_check_failed"}'))
        self.assertTrue(
            verify_dispatch.platform_halt_detected(
                '{"type":"turn_aborted","reason":"platform_safety"}'
            )
        )
        self.assertFalse(verify_dispatch.platform_halt_detected('{"type":"turn_aborted","reason":"user"}'))

    def test_dispatch_receipt_carries_routing_context_and_halt_state(self) -> None:
        hashes = {"config": "a" * 64, "role_manifest": "b" * 64, "policy": "c" * 64}
        verdict = verify_dispatch._verdict("SKIPPED", "platform_halt", child_created="unknown", platform_halt="capability_gap")
        payload = verify_dispatch.receipt_payload(
            verdict,
            codex_version="unknown",
            active=hashes,
            target=hashes,
        )
        self.assertEqual(payload["platform_halt"], "capability_gap")
        validate_routing_context(payload["routing"])

    def test_platform_halt_preserves_requested_candidate_without_child_evidence(self) -> None:
        hashes = {"config": "a" * 64, "role_manifest": "b" * 64, "policy": "c" * 64}
        verdict = verify_dispatch._verdict(
            "SKIPPED",
            "platform_halt",
            phase="execution-pre-child",
            child_created="unknown",
            platform_halt="capability_gap",
        )
        payload = verify_dispatch.receipt_payload(
            verdict,
            codex_version="unknown",
            active=hashes,
            target=hashes,
            expected_role="verifier",
            expected_binding=verify_dispatch.RoleBinding("gpt-6-astra", "high"),
        )
        self.assertEqual(payload["routing"]["role"], "verifier")
        self.assertEqual(payload["routing"]["model_candidate"], "gpt-6-astra")
        self.assertEqual(payload["routing"]["model_snapshot"], "gpt-6-astra@high")
        self.assertNotIn("model", payload)

    def test_plan_verifier_platform_halt_keeps_read_only_explicit_risk(self) -> None:
        hashes = {"config": "a" * 64, "role_manifest": "b" * 64, "policy": "c" * 64}
        verdict = verify_dispatch._verdict(
            "SKIPPED",
            "platform_halt",
            phase="execution-pre-child",
            child_created="unknown",
            platform_halt="capability_gap",
        )
        payload = verify_dispatch.receipt_payload(
            verdict,
            codex_version="unknown",
            active=hashes,
            target=hashes,
            expected_role="plan-verifier",
            expected_binding=verify_dispatch.RoleBinding("gpt-5.6-sol", "high"),
        )
        routing = payload["routing"]
        self.assertEqual(routing["role"], "plan-verifier")
        self.assertEqual(routing["model_candidate"], "gpt-5.6-sol")
        self.assertEqual(routing["model_snapshot"], "gpt-5.6-sol@high")
        self.assertEqual(routing["permission_profile"], "read-only")
        self.assertEqual(routing["escalation_reason"], "explicit-risk")
        self.assertNotIn("model", payload)

    def test_receipt_rejects_routing_candidate_mismatch(self) -> None:
        hashes = {"config": "a" * 64, "role_manifest": "b" * 64, "policy": "c" * 64}
        verdict = verify_dispatch._verdict(
            "NATIVE_OK",
            "native_verified",
            phase="post-spawn",
            child_created="yes",
            role="verifier",
            task_name="model_probe_verifier",
            fork_turns="none",
            parent_ref="a" * 16,
            child_ref="b" * 16,
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
            correlation_mode="spawn_activity",
        )
        payload = verify_dispatch.receipt_payload(
            verdict,
            codex_version="0.153.4",
            active=hashes,
            target=hashes,
        )
        payload["routing"]["model_candidate"] = "gpt-6-astra"
        with self.assertRaises(verify_dispatch.ReceiptError):
            verify_dispatch.validate_receipt(payload)

    def test_default_prompt_and_policy_are_capability_first(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8")
        self.assertIn("Capability-first model routing", policy)
        self.assertIn("Do not replace `plan-verifier`", policy)
        self.assertIn("Do not create a new computer-use role", policy)
        bootstrap = (ROOT / "templates" / "agents-md.bootstrap.md").read_text(encoding="utf-8")
        self.assertIn("Route by capability", bootstrap)
        self.assertIn("tool or evidence trigger", benchmark.PARENT_PROMPT)
        self.assertIn("difficulty alone", benchmark.PARENT_PROMPT)
        self.assertIn("max_tool_calls=20", benchmark.PARENT_PROMPT)
        self.assertIn("smallest sufficient change", benchmark.PARENT_PROMPT)


if __name__ == "__main__":
    unittest.main()
