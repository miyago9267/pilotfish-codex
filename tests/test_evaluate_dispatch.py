from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))

from evaluate_dispatch import (  # noqa: E402
    EvaluationError,
    evaluate,
    load_corpus,
    main as evaluate_main,
    parse_live_output,
    run_live_case,
)


class DispatchEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = load_corpus(
            ROOT / "docs" / "specs" / "dispatch-verification" / "task-class-corpus.json"
        )

    def _perfect_decisions(self) -> list[dict]:
        return [
            {
                "id": case["id"],
                "decision": case["expected"]["decision"],
                "role": case["expected"]["role"],
                "rationale": "Matches the declared policy boundary.",
            }
            for case in self.corpus["cases"]
        ]

    def test_corpus_contains_versioned_full_role_and_local_coverage(self) -> None:
        roles = {
            case["expected"]["role"]
            for case in self.corpus["cases"]
            if case["expected"]["decision"] == "delegate"
        }
        local_cases = [
            case for case in self.corpus["cases"] if case["expected"]["decision"] == "local"
        ]

        self.assertEqual(self.corpus["version"], 1)
        self.assertEqual(
            roles,
            {
                "scout",
                "plan-verifier",
                "security-reviewer",
                "mech-executor",
                "executor",
                "verifier",
                "security-executor",
            },
        )
        self.assertGreaterEqual(len(local_cases), 2)
        self.assertTrue(all(case["policy_basis"] for case in self.corpus["cases"]))

    def test_duplicate_corpus_ids_are_rejected(self) -> None:
        payload = dict(self.corpus)
        payload["cases"] = list(self.corpus["cases"])
        payload["cases"][1] = dict(payload["cases"][0])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(EvaluationError):
                load_corpus(path)

    def test_perfect_decisions_meet_all_thresholds(self) -> None:
        report = evaluate(self.corpus, self._perfect_decisions())

        self.assertTrue(report["passed"])
        self.assertEqual(report["coverage"], {"expected": 9, "submitted": 9, "complete": True})
        self.assertEqual(report["role_selection"], {"correct": 7, "total": 7, "accuracy": 1.0})
        self.assertEqual(report["abstention"], {"correct": 2, "total": 2, "accuracy": 1.0})
        self.assertEqual(report["invalid_decisions"]["total"], 0)

    def test_single_delegate_or_local_subset_scores_without_division_error(self) -> None:
        delegate_case = next(
            case for case in self.corpus["cases"] if case["expected"]["decision"] == "delegate"
        )
        local_case = next(
            case for case in self.corpus["cases"] if case["expected"]["decision"] == "local"
        )

        delegate_report = evaluate(
            {"version": 1, "cases": [delegate_case]},
            [
                {
                    "id": delegate_case["id"],
                    "decision": "delegate",
                    "role": delegate_case["expected"]["role"],
                    "rationale": "Independent work matches the role boundary.",
                }
            ],
        )
        local_report = evaluate(
            {"version": 1, "cases": [local_case]},
            [
                {
                    "id": local_case["id"],
                    "decision": "local",
                    "role": None,
                    "rationale": "The task remains coupled to the parent context.",
                }
            ],
        )

        self.assertTrue(delegate_report["passed"])
        self.assertTrue(local_report["passed"])
        self.assertEqual(delegate_report["abstention"]["accuracy"], 1.0)
        self.assertEqual(local_report["role_selection"]["accuracy"], 1.0)

    def test_wrong_delegate_role_fails_role_threshold(self) -> None:
        decisions = self._perfect_decisions()
        decisions[0]["role"] = "executor"

        report = evaluate(self.corpus, decisions, min_role_accuracy=1.0)

        self.assertFalse(report["passed"])
        self.assertEqual(report["role_selection"]["correct"], 6)
        self.assertEqual(report["abstention"]["accuracy"], 1.0)

    def test_wrong_abstention_fails_abstention_threshold(self) -> None:
        decisions = self._perfect_decisions()
        decisions[-1].update({"decision": "delegate", "role": "executor"})

        report = evaluate(self.corpus, decisions, min_abstention_accuracy=1.0)

        self.assertFalse(report["passed"])
        self.assertEqual(report["abstention"]["correct"], 1)
        self.assertEqual(report["role_selection"]["accuracy"], 1.0)

    def test_cli_returns_nonzero_when_threshold_is_not_met(self) -> None:
        decisions = self._perfect_decisions()
        decisions[0]["role"] = "executor"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            path.write_text(json.dumps(decisions), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = evaluate_main(
                    ["--decisions", str(path), "--min-role-accuracy", "1.0"]
                )

        self.assertEqual(result, 1)
        self.assertFalse(json.loads(stdout.getvalue())["passed"])

    def test_malformed_missing_and_duplicate_decisions_fail_closed(self) -> None:
        decisions = self._perfect_decisions()
        decisions[0]["rationale"] = " "
        decisions.pop()
        decisions.append(dict(decisions[1]))
        decisions.append(
            {
                "id": "unexpected",
                "decision": "delegate",
                "role": "scout",
                "rationale": "Shape is valid but ID is unknown.",
            }
        )
        decisions.append({"id": "malformed"})

        report = evaluate(self.corpus, decisions)

        self.assertFalse(report["passed"])
        self.assertFalse(report["coverage"]["complete"])
        self.assertEqual(report["invalid_decisions"]["empty_rationale"], 1)
        self.assertEqual(report["invalid_decisions"]["duplicate_ids"], 1)
        self.assertEqual(report["invalid_decisions"]["unknown_ids"], 1)
        self.assertGreaterEqual(report["invalid_decisions"]["malformed"], 1)

    def test_invalid_shape_and_threshold_configuration_are_rejected(self) -> None:
        with self.assertRaises(EvaluationError):
            evaluate(self.corpus, {"decisions": []})
        with self.assertRaises(EvaluationError):
            evaluate(self.corpus, self._perfect_decisions(), min_role_accuracy=1.1)

    def test_unhashable_decision_and_role_values_fail_closed(self) -> None:
        for field, value in (("decision", []), ("role", [])):
            decisions = self._perfect_decisions()
            decisions[0][field] = value
            with self.subTest(field=field):
                report = evaluate(self.corpus, decisions)
                self.assertFalse(report["passed"])
                self.assertEqual(report["invalid_decisions"]["malformed"], 1)

    def test_live_parser_accepts_exact_no_tool_response(self) -> None:
        decision = self._perfect_decisions()[0]
        transcript = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(decision),
                },
            }
        )

        self.assertEqual(
            parse_live_output(transcript, expected_case_id=decision["id"]), decision
        )

    def test_live_cli_requires_dedicated_task_evaluation_opt_in(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = evaluate_main(
                [
                    "--live",
                    "--yes",
                    "--case-id",
                    self.corpus["cases"][0]["id"],
                ]
            )
        self.assertEqual(result, 2)
        self.assertIn("task-eval-yes", stdout.getvalue())

    def test_live_parser_accepts_current_codex_response_item_shape(self) -> None:
        decision = self._perfect_decisions()[0]
        transcript = json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": json.dumps(decision)},
                    ],
                },
            }
        )

        self.assertEqual(
            parse_live_output(transcript, expected_case_id=decision["id"]), decision
        )

    def test_mocked_live_runner_accepts_only_the_no_tool_parser_contract(self) -> None:
        case = self.corpus["cases"][0]
        decision = self._perfect_decisions()[0]
        transcript = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(decision)},
            }
        )
        completed = CompletedProcess([], 0, stdout=transcript, stderr="")

        with patch("evaluate_dispatch.subprocess.run", return_value=completed) as run:
            result = run_live_case(
                codex_bin="codex",
                repository_root=ROOT,
                case=case,
            )

        self.assertEqual(result, decision)
        command = run.call_args.args[0]
        self.assertIn("--json", command)
        self.assertIn("read-only", command)
        self.assertIn("Do not call tools", command[-1])
        self.assertIn("do not spawn agents", command[-1])

    def test_live_parser_rejects_tool_or_spawn_evidence_and_non_strict_output(self) -> None:
        decision = self._perfect_decisions()[0]
        tool_evidence = "\n".join(
            (
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "function_call", "name": "spawn_agent"},
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(decision),
                        },
                    }
                ),
            )
        )
        prose = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": f"Decision: {json.dumps(decision)}",
                },
            }
        )

        with self.assertRaises(EvaluationError):
            parse_live_output(tool_evidence, expected_case_id=decision["id"])
        with self.assertRaises(EvaluationError):
            parse_live_output(prose, expected_case_id=decision["id"])

        for forbidden_type in ("command_execution", "web_search", "file_change"):
            transcript = "\n".join(
                (
                    json.dumps({"type": forbidden_type}),
                    json.dumps(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": json.dumps(decision)}
                                ],
                            },
                        }
                    ),
                )
            )
            with self.subTest(forbidden_type=forbidden_type):
                with self.assertRaises(EvaluationError):
                    parse_live_output(transcript, expected_case_id=decision["id"])


if __name__ == "__main__":
    unittest.main()
