from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))

from execution_contract import (  # noqa: E402
    ExecutionContractError,
    project_execution_contract,
    validate_execution_contract,
)


class ExecutionContractTests(unittest.TestCase):
    @staticmethod
    def _project(**overrides: object) -> dict[str, str]:
        context: dict[str, object] = {
            "task_mode": "execute",
            "intent_confidence": "clear",
            "change_impact": "low",
            "reversible": "yes",
            "approval_required": False,
        }
        context.update(overrides)
        return project_execution_contract(**context)

    def test_clear_task_runs_to_acceptance_by_default(self) -> None:
        self.assertEqual(
            self._project(),
            {
                "execution_scope": "outcome",
                "continuation_mode": "attended_until_acceptance",
                "stop_condition": "acceptance",
            },
        )

    def test_explicit_step_stops_at_named_boundary(self) -> None:
        self.assertEqual(
            self._project(explicit_scope="step"),
            {
                "execution_scope": "step",
                "continuation_mode": "attended_until_acceptance",
                "stop_condition": "named_boundary",
            },
        )

    def test_explicit_slice_stops_at_named_boundary(self) -> None:
        self.assertEqual(
            self._project(explicit_scope="slice"),
            {
                "execution_scope": "slice",
                "continuation_mode": "attended_until_acceptance",
                "stop_condition": "named_boundary",
            },
        )

    def test_unattended_mode_requires_explicit_request(self) -> None:
        self.assertEqual(
            self._project(unattended_requested=True),
            {
                "execution_scope": "outcome",
                "continuation_mode": "explicit_unattended",
                "stop_condition": "acceptance",
            },
        )

    def test_material_gate_precedes_acceptance(self) -> None:
        self.assertEqual(
            self._project(
                change_impact="high",
                reversible="partial",
                approval_required=True,
            ),
            {
                "execution_scope": "outcome",
                "continuation_mode": "attended_until_acceptance",
                "stop_condition": "material_gate",
            },
        )

    def test_unclear_direction_stops_for_decision_at_smallest_slice(self) -> None:
        self.assertEqual(
            self._project(
                task_mode="co_discover",
                intent_confidence="partial",
                change_impact="material",
            ),
            {
                "execution_scope": "slice",
                "continuation_mode": "attended_until_acceptance",
                "stop_condition": "decision",
            },
        )

    def test_invalid_input_fails_closed(self) -> None:
        with self.assertRaises(ExecutionContractError):
            self._project(explicit_scope="command")
        with self.assertRaises(ExecutionContractError):
            self._project(unattended_requested="yes")
        with self.assertRaises(ExecutionContractError):
            self._project(change_impact="high")

    def test_contract_validation_rejects_inconsistent_stop_condition(self) -> None:
        with self.assertRaises(ExecutionContractError):
            validate_execution_contract(
                {
                    "execution_scope": "step",
                    "continuation_mode": "attended_until_acceptance",
                    "stop_condition": "acceptance",
                }
            )


if __name__ == "__main__":
    unittest.main()
