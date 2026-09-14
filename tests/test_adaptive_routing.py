from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))

from evaluate_dispatch import (  # noqa: E402
    EvaluationError,
    evaluate_checkpoints,
    evaluate_route,
    load_checkpoint_corpus,
    load_route_corpus,
    main as evaluate_main,
)


class AdaptiveRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.route_corpus = load_route_corpus(
            ROOT / "docs" / "specs" / "adaptive-intent-routing" / "route-corpus.json"
        )
        self.checkpoint_corpus = load_checkpoint_corpus(
            ROOT / "docs" / "specs" / "adaptive-intent-routing" / "checkpoint-corpus.json"
        )

    @staticmethod
    def _decision_card() -> dict:
        return {
            "current_interpretation": "The request needs a bounded direction choice before implementation.",
            "proposed_default": "Start with the smallest reversible slice.",
            "included_scope": ["Repository reconnaissance", "One decision checkpoint"],
            "excluded_scope": ["Bulk implementation", "Irreversible external actions"],
            "material_risk": ["The wrong choice could expand the scope."],
            "questions": [
                {
                    "id": "scope",
                    "question": "Which bounded direction should be used first?",
                    "options": ["Recommended reversible slice", "Broader implementation"],
                    "recommended": "Recommended reversible slice",
                }
            ],
            "next_reversible_slice": "Inspect the named boundary and report evidence.",
        }

    def _perfect_route_decisions(self) -> list[dict]:
        decisions = []
        for case in self.route_corpus["cases"]:
            expected = case["expected"]
            decisions.append(
                {
                    "id": case["id"],
                    "task_mode": expected["task_mode"],
                    "intent_confidence": expected["intent_confidence"],
                    "change_impact": expected["change_impact"],
                    "discovery_budget": expected["discovery_budget"],
                    "reversible": expected["reversible"],
                    "blocking_decisions": ["Choose the first slice"]
                    if expected["decision_card"]
                    else [],
                    "next_gate": expected["next_gate"],
                    "abstain": expected["abstain"],
                    "approval_required": expected["approval_required"],
                    "role": expected["role"],
                    "budget_exhausted": expected["budget_exhausted"],
                    "evidence_sufficient": expected["evidence_sufficient"],
                    "rationale": "The route matches the request context and risk.",
                    "decision_card": self._decision_card()
                    if expected["decision_card"]
                    else None,
                    "execution_scope": expected["execution_scope"],
                    "continuation_mode": expected["continuation_mode"],
                    "stop_condition": expected["stop_condition"],
                }
            )
        return decisions

    def _perfect_checkpoint_decisions(self) -> list[dict]:
        return [
            {
                "id": case["id"],
                "disposition": case["expected"]["disposition"],
                "replan_required": case["expected"]["replan_required"],
                "rollback_target_available": case["expected"]["rollback_target_available"],
                "approval_required": case["expected"]["approval_required"],
                "rationale": "The evidence supports the checkpoint disposition.",
            }
            for case in self.checkpoint_corpus["cases"]
        ]

    def test_route_corpus_covers_initial_modes_and_five_impact_bands(self) -> None:
        self.assertEqual(
            {case["expected"]["task_mode"] for case in self.route_corpus["cases"]},
            {"execute", "explore_then_plan", "co_discover"},
        )
        self.assertEqual(
            {case["expected"]["change_impact"] for case in self.route_corpus["cases"]},
            {"trivial", "low", "material", "high", "critical"},
        )
        self.assertEqual(
            {case["expected"]["abstain"] for case in self.route_corpus["cases"]},
            {True, False},
        )
        self.assertEqual(
            {case["expected"]["execution_scope"] for case in self.route_corpus["cases"]},
            {"step", "slice", "outcome"},
        )
        self.assertEqual(
            {
                case["expected"]["continuation_mode"]
                for case in self.route_corpus["cases"]
            },
            {"attended_until_acceptance", "explicit_unattended"},
        )
        self.assertEqual(
            {case["expected"]["stop_condition"] for case in self.route_corpus["cases"]},
            {"named_boundary", "acceptance", "material_gate", "decision"},
        )

    def test_perfect_route_decisions_pass_all_behavioral_gates(self) -> None:
        report = evaluate_route(self.route_corpus, self._perfect_route_decisions())

        self.assertTrue(report["passed"])
        self.assertEqual(report["coverage"]["expected"], 12)
        self.assertEqual(report["route_selection"]["accuracy"], 1.0)
        self.assertEqual(report["signal_bundle"]["accuracy"], 1.0)
        self.assertEqual(report["execution_contract"]["accuracy"], 1.0)
        self.assertEqual(report["abstention"]["accuracy"], 1.0)
        self.assertEqual(report["decision_card"]["accuracy"], 1.0)
        self.assertEqual(report["false_direct_execution"], 0)
        self.assertEqual(report["false_overexploration"], 0)
        self.assertEqual(
            report["measurements"],
            {
                "latency_ms": None,
                "token_cost_proxy": None,
                "status": "not measured by offline semantic route evaluation",
            },
        )

    def test_review_intent_fields_are_scored_without_changing_task_mode(self) -> None:
        corpus = json.loads(json.dumps(self.route_corpus))
        intents = ("default", "fast", "strict")
        decisions = self._perfect_route_decisions()
        for index, (case, decision) in enumerate(zip(corpus["cases"], decisions)):
            intent = intents[index % len(intents)]
            optional_review = {
                "fast": "skip",
                "default": "existing_policy",
                "strict": "expanded",
            }[intent]
            fields = {
                "review_intent": intent,
                "review_intent_source": "explicit",
                "review_intent_scope": "turn",
                "optional_review": optional_review,
            }
            case["expected"].update(fields)
            decision.update(fields)

        report = evaluate_route(corpus, decisions)

        self.assertTrue(report["passed"])
        self.assertEqual(report["review_intent"]["accuracy"], 1.0)

    def test_review_intent_rejects_session_scope_and_unknown_mode(self) -> None:
        corpus = json.loads(json.dumps(self.route_corpus))
        for case in corpus["cases"]:
            case["expected"].update(
                {
                    "review_intent": "default",
                    "review_intent_source": "explicit",
                    "review_intent_scope": "turn",
                    "optional_review": "existing_policy",
                }
            )
        decisions = self._perfect_route_decisions()
        for decision in decisions:
            decision.update(
                {
                    "review_intent": "default",
                    "review_intent_source": "explicit",
                    "review_intent_scope": "session",
                    "optional_review": "existing_policy",
                }
            )

        report = evaluate_route(corpus, decisions)

        self.assertFalse(report["passed"])
        self.assertEqual(report["invalid_decisions"]["malformed"], len(decisions))

    def test_route_rejects_overconfident_and_missing_card_decisions(self) -> None:
        decisions = self._perfect_route_decisions()
        decisions[5]["abstain"] = False
        decisions[5]["intent_confidence"] = "clear"
        decisions[5]["blocking_decisions"] = []
        decisions[5]["decision_card"] = None

        report = evaluate_route(self.route_corpus, decisions)

        self.assertFalse(report["passed"])
        self.assertEqual(report["invalid_decisions"]["overconfident"], 1)
        self.assertEqual(report["invalid_decisions"]["decision_card_missing"], 0)

    def test_route_rejects_per_command_continuation_and_gate_downgrade(self) -> None:
        decisions = self._perfect_route_decisions()
        decisions[0]["continuation_mode"] = "per_command"
        decisions[3]["approval_required"] = False

        report = evaluate_route(self.route_corpus, decisions)

        self.assertFalse(report["passed"])
        self.assertEqual(report["invalid_decisions"]["malformed"], 1)
        self.assertEqual(report["invalid_decisions"]["overconfident"], 1)

    def test_route_card_requires_ask_user_question_style_options(self) -> None:
        decisions = self._perfect_route_decisions()
        decisions[3]["decision_card"]["questions"][0]["recommended"] = "Not an option"

        report = evaluate_route(self.route_corpus, decisions)

        self.assertFalse(report["passed"])
        self.assertEqual(report["invalid_decisions"]["decision_card_malformed"], 1)

    def test_exhausted_budget_requires_abstention_and_a_gate(self) -> None:
        decisions = self._perfect_route_decisions()
        exhausted = next(
            decision
            for decision in decisions
            if decision["id"] == "budget-exhausted-insufficient-evidence"
        )
        exhausted["abstain"] = False

        report = evaluate_route(self.route_corpus, decisions)

        self.assertFalse(report["passed"])
        self.assertEqual(report["invalid_decisions"]["overconfident"], 1)

    def test_route_cli_uses_adaptive_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            decisions_path = Path(directory) / "route-decisions.json"
            decisions_path.write_text(
                json.dumps(self._perfect_route_decisions()), encoding="utf-8"
            )
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = evaluate_main(["--route", "--decisions", str(decisions_path)])

        self.assertEqual(result, 0)
        self.assertTrue(json.loads(stdout.getvalue())["passed"])

    def test_checkpoint_cli_uses_checkpoint_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            decisions_path = Path(directory) / "checkpoint-decisions.json"
            decisions_path.write_text(
                json.dumps(self._perfect_checkpoint_decisions()), encoding="utf-8"
            )
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = evaluate_main(
                    ["--checkpoint", "--decisions", str(decisions_path)]
                )

        self.assertEqual(result, 0)
        self.assertTrue(json.loads(stdout.getvalue())["passed"])

    def test_perfect_checkpoint_decisions_pass_recovery_gates(self) -> None:
        report = evaluate_checkpoints(
            self.checkpoint_corpus, self._perfect_checkpoint_decisions()
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["disposition"], {"correct": 6, "total": 6})
        self.assertEqual(report["replan"], {"correct": 6, "total": 6})
        self.assertEqual(report["rollback_target"], {"correct": 6, "total": 6})

    def test_checkpoint_rejects_unsafe_rollback_without_target_or_approval(self) -> None:
        decisions = self._perfect_checkpoint_decisions()
        decisions[-1]["approval_required"] = False

        report = evaluate_checkpoints(self.checkpoint_corpus, decisions)

        self.assertFalse(report["passed"])
        self.assertEqual(report["invalid_decisions"]["unsafe_disposition"], 1)

    def test_invalid_route_corpus_is_rejected(self) -> None:
        with self.assertRaises(EvaluationError):
            load_route_corpus(ROOT / "docs" / "specs" / "dispatch-verification" / "task-class-corpus.json")


if __name__ == "__main__":
    unittest.main()
