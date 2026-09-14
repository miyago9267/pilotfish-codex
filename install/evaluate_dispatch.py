#!/usr/bin/env python3
"""Evaluate behavioral task-class role selection without enforcing dispatch.

The offline evaluator compares submitted JSON decisions with the versioned
corpus. It is deliberately separate from ``verify_dispatch.py``: a passing
result describes policy behavior, not a runtime dispatch guarantee.

Decision file format:
    [{"id": "case-id", "decision": "delegate", "role": "scout",
      "rationale": "non-empty explanation"}]

For ``decision: "local"``, ``role`` must be JSON ``null``. The optional live
path is manually gated, capped, forbidden in CI, and accepts only an exact
no-tool JSON response from each independent Codex invocation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from execution_contract import (
    ExecutionContractError,
    validate_execution_contract,
)


ALLOWED_ROLES = frozenset(
    {
        "scout",
        "plan-verifier",
        "security-reviewer",
        "mech-executor",
        "executor",
        "verifier",
        "security-executor",
    }
)
ALLOWED_DECISIONS = frozenset({"delegate", "local"})
LIVE_CASE_CAP = 3

ALLOWED_TASK_MODES = frozenset({"execute", "explore_then_plan", "co_discover"})
ALLOWED_INTENT_CONFIDENCE = frozenset({"clear", "partial", "unclear"})
ALLOWED_REVIEW_INTENTS = frozenset({"fast", "default", "strict"})
ALLOWED_REVIEW_INTENT_SOURCES = frozenset({"explicit", "risk_default"})
ALLOWED_OPTIONAL_REVIEWS = frozenset({"skip", "existing_policy", "expanded"})
ALLOWED_CHANGE_IMPACT = frozenset({"trivial", "low", "material", "high", "critical"})
ALLOWED_DISCOVERY_BUDGETS = frozenset({"none", "minimum", "bounded", "deep"})
ALLOWED_REVERSIBILITY = frozenset({"yes", "partial", "no"})
ALLOWED_NEXT_GATES = frozenset({"discovery", "approval", "execution", "direction_check"})
ALLOWED_CHECKPOINT_DISPOSITIONS = frozenset({"CONTINUE", "PIVOT", "ROLLBACK"})
ROUTE_FIELDS = frozenset(
    {
        "id",
        "task_mode",
        "intent_confidence",
        "change_impact",
        "discovery_budget",
        "reversible",
        "blocking_decisions",
        "next_gate",
        "abstain",
        "approval_required",
        "role",
        "budget_exhausted",
        "evidence_sufficient",
        "rationale",
        "decision_card",
        "execution_scope",
        "continuation_mode",
        "stop_condition",
    }
)
ROUTE_EXPECTED_FIELDS = frozenset(
    {
        "task_mode",
        "intent_confidence",
        "change_impact",
        "discovery_budget",
        "reversible",
        "next_gate",
        "budget_exhausted",
        "evidence_sufficient",
        "abstain",
        "approval_required",
        "role",
        "decision_card",
        "execution_scope",
        "continuation_mode",
        "stop_condition",
    }
)
ROUTE_INTENT_FIELDS = frozenset(
    {"review_intent", "review_intent_source", "review_intent_scope", "optional_review"}
)
CARD_FIELDS = frozenset(
    {
        "current_interpretation",
        "proposed_default",
        "included_scope",
        "excluded_scope",
        "material_risk",
        "questions",
        "next_reversible_slice",
    }
)
CARD_REQUIRED_FIELDS = frozenset(
    {
        "current_interpretation",
        "proposed_default",
        "included_scope",
        "excluded_scope",
        "questions",
        "next_reversible_slice",
    }
)
CHECKPOINT_FIELDS = frozenset(
    {
        "id",
        "disposition",
        "replan_required",
        "rollback_target_available",
        "approval_required",
        "rationale",
    }
)
CHECKPOINT_EXPECTED_FIELDS = frozenset(
    {
        "disposition",
        "replan_required",
        "rollback_target_available",
        "approval_required",
    }
)


class EvaluationError(ValueError):
    """Raised when evaluator input or live evidence violates its contract."""


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_expected(expected: Any, case_id: str) -> None:
    if not isinstance(expected, dict) or set(expected) != {"decision", "role"}:
        raise EvaluationError(f"case {case_id}: expected must contain decision and role")
    decision = expected["decision"]
    role = expected["role"]
    if decision == "delegate" and role in ALLOWED_ROLES:
        return
    if decision == "local" and role is None:
        return
    raise EvaluationError(f"case {case_id}: invalid expected decision/role")


def validate_corpus(corpus: Any) -> dict[str, Any]:
    """Validate the versioned behavioral corpus before it can be evaluated."""
    if not isinstance(corpus, dict):
        raise EvaluationError("corpus must be an object")
    if type(corpus.get("version")) is not int or corpus["version"] < 1:
        raise EvaluationError("corpus version must be a positive integer")
    cases = corpus.get("cases")
    if not isinstance(cases, list):
        raise EvaluationError("corpus cases must be a list")

    ids: set[str] = set()
    delegate_roles: set[str] = set()
    local_count = 0
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "id",
            "prompt",
            "policy_basis",
            "expected",
        }:
            raise EvaluationError("each corpus case must have id, prompt, policy_basis, expected")
        case_id = case["id"]
        if not _is_nonempty_string(case_id):
            raise EvaluationError("corpus case id must be a non-empty string")
        if case_id in ids:
            raise EvaluationError(f"duplicate corpus case id: {case_id}")
        ids.add(case_id)
        if not _is_nonempty_string(case["prompt"]):
            raise EvaluationError(f"case {case_id}: prompt must be a non-empty string")
        policy_basis = case["policy_basis"]
        if not isinstance(policy_basis, list) or not policy_basis or not all(
            _is_nonempty_string(item) for item in policy_basis
        ):
            raise EvaluationError(f"case {case_id}: policy_basis must be non-empty strings")
        _validate_expected(case["expected"], case_id)
        if case["expected"]["decision"] == "delegate":
            delegate_roles.add(case["expected"]["role"])
        else:
            local_count += 1

    if delegate_roles != ALLOWED_ROLES:
        raise EvaluationError("corpus must cover every allowed delegate role exactly once")
    if local_count < 2:
        raise EvaluationError("corpus must contain at least two local cases")
    return corpus


def _load_json(path: Path, label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvaluationError(f"cannot read {label} {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"{label} is not valid JSON: {path}") from exc


def load_corpus(path: Path) -> dict[str, Any]:
    """Load and validate one versioned task-class corpus."""
    return validate_corpus(_load_json(path, "corpus"))


def load_decisions(path: Path) -> list[Any]:
    """Load a submitted decision array without accepting alternate envelopes."""
    decisions = _load_json(path, "decisions")
    if not isinstance(decisions, list):
        raise EvaluationError("decisions must be a JSON array")
    return decisions


def _decision_error(decision: Any) -> str | None:
    if not isinstance(decision, dict) or set(decision) != {
        "id",
        "decision",
        "role",
        "rationale",
    }:
        return "malformed"
    if not _is_nonempty_string(decision["id"]):
        return "malformed"
    if not isinstance(decision["decision"], str):
        return "malformed"
    if decision["decision"] not in ALLOWED_DECISIONS:
        return "malformed"
    if decision["decision"] == "delegate" and (
        not isinstance(decision["role"], str)
        or decision["role"] not in ALLOWED_ROLES
    ):
        return "malformed"
    if decision["decision"] == "local" and decision["role"] is not None:
        return "malformed"
    if not _is_nonempty_string(decision["rationale"]):
        return "empty_rationale"
    return None


def _threshold(value: float, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise EvaluationError(f"{name} must be between 0 and 1")


def evaluate(
    corpus: dict[str, Any],
    decisions: list[Any],
    *,
    min_role_accuracy: float = 1.0,
    min_abstention_accuracy: float = 1.0,
) -> dict[str, Any]:
    """Score exact coverage, delegate-role selection, and local abstention."""
    _threshold(min_role_accuracy, "min_role_accuracy")
    _threshold(min_abstention_accuracy, "min_abstention_accuracy")
    if not isinstance(decisions, list):
        raise EvaluationError("decisions must be a list")

    cases = corpus["cases"]
    expected_by_id = {case["id"]: case["expected"] for case in cases}
    invalid = {"malformed": 0, "empty_rationale": 0, "duplicate_ids": 0, "unknown_ids": 0}
    accepted: dict[str, dict[str, Any]] = {}
    submitted_ids: set[str] = set()

    for submitted in decisions:
        case_id = submitted.get("id") if isinstance(submitted, dict) else None
        duplicate = _is_nonempty_string(case_id) and case_id in submitted_ids
        if _is_nonempty_string(case_id):
            submitted_ids.add(case_id)

        error = _decision_error(submitted)
        if error is not None:
            invalid[error] += 1
        if duplicate:
            invalid["duplicate_ids"] += 1
        if error is not None or duplicate:
            continue
        assert isinstance(case_id, str)
        if case_id not in expected_by_id:
            invalid["unknown_ids"] += 1
            continue
        accepted[case_id] = submitted

    expected_ids = set(expected_by_id)
    coverage_complete = (
        submitted_ids == expected_ids
        and invalid["duplicate_ids"] == 0
        and invalid["unknown_ids"] == 0
    )
    delegate_cases = [
        (case_id, expected)
        for case_id, expected in expected_by_id.items()
        if expected["decision"] == "delegate"
    ]
    local_cases = [
        (case_id, expected)
        for case_id, expected in expected_by_id.items()
        if expected["decision"] == "local"
    ]
    role_correct = sum(
        accepted.get(case_id, {}).get("decision") == "delegate"
        and accepted.get(case_id, {}).get("role") == expected["role"]
        for case_id, expected in delegate_cases
    )
    abstention_correct = sum(
        accepted.get(case_id, {}).get("decision") == "local"
        and accepted.get(case_id, {}).get("role") is None
        for case_id, _ in local_cases
    )
    role_accuracy = role_correct / len(delegate_cases) if delegate_cases else 1.0
    abstention_accuracy = (
        abstention_correct / len(local_cases) if local_cases else 1.0
    )
    invalid["total"] = sum(invalid.values())
    passed = (
        coverage_complete
        and invalid["total"] == 0
        and role_accuracy >= min_role_accuracy
        and abstention_accuracy >= min_abstention_accuracy
    )
    return {
        "evaluator": "behavioral-not-runtime-enforcement",
        "corpus_version": corpus["version"],
        "coverage": {
            "expected": len(expected_ids),
            "submitted": len(decisions),
            "complete": coverage_complete,
        },
        "role_selection": {
            "correct": role_correct,
            "total": len(delegate_cases),
            "accuracy": role_accuracy,
        },
        "abstention": {
            "correct": abstention_correct,
            "total": len(local_cases),
            "accuracy": abstention_accuracy,
        },
        "invalid_decisions": invalid,
        "thresholds": {
            "min_role_accuracy": min_role_accuracy,
            "min_abstention_accuracy": min_abstention_accuracy,
        },
        "passed": passed,
    }


def _validate_string_list(value: Any, *, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_is_nonempty_string(item) for item in value)
    )


def _validate_route_expected(expected: Any, case_id: str) -> None:
    if not isinstance(expected, dict) or set(expected) not in {
        ROUTE_EXPECTED_FIELDS,
        ROUTE_EXPECTED_FIELDS | ROUTE_INTENT_FIELDS,
    }:
        raise EvaluationError(
            f"case {case_id}: route expected must contain "
            "task signals, role, approval, abstention, and card expectation"
        )
    for field, allowed in (
        ("task_mode", ALLOWED_TASK_MODES),
        ("intent_confidence", ALLOWED_INTENT_CONFIDENCE),
        ("change_impact", ALLOWED_CHANGE_IMPACT),
        ("discovery_budget", ALLOWED_DISCOVERY_BUDGETS),
        ("reversible", ALLOWED_REVERSIBILITY),
        ("next_gate", ALLOWED_NEXT_GATES),
    ):
        if expected[field] not in allowed:
            raise EvaluationError(f"case {case_id}: invalid expected {field}")
    if type(expected["abstain"]) is not bool:
        raise EvaluationError(f"case {case_id}: expected abstain must be boolean")
    if type(expected["approval_required"]) is not bool:
        raise EvaluationError(f"case {case_id}: expected approval_required must be boolean")
    for field in ("budget_exhausted", "evidence_sufficient"):
        if type(expected[field]) is not bool:
            raise EvaluationError(f"case {case_id}: expected {field} must be boolean")
    if expected["discovery_budget"] == "none" and expected["budget_exhausted"]:
        raise EvaluationError(f"case {case_id}: none budget cannot be exhausted")
    if expected["budget_exhausted"] and not expected["evidence_sufficient"]:
        if not expected["abstain"] or expected["next_gate"] not in {"discovery", "approval"}:
            raise EvaluationError(
                f"case {case_id}: exhausted insufficient evidence must abstain at a gate"
            )
    if expected["role"] is not None and expected["role"] not in ALLOWED_ROLES:
        raise EvaluationError(f"case {case_id}: invalid expected role")
    if type(expected["decision_card"]) is not bool:
        raise EvaluationError(f"case {case_id}: expected decision_card must be boolean")
    try:
        validate_execution_contract(
            {
                "execution_scope": expected["execution_scope"],
                "continuation_mode": expected["continuation_mode"],
                "stop_condition": expected["stop_condition"],
            }
        )
    except ExecutionContractError as exc:
        raise EvaluationError(f"case {case_id}: {exc}") from exc
    if expected["stop_condition"] == "material_gate" and not (
        expected["approval_required"] and expected["next_gate"] == "approval"
    ):
        raise EvaluationError(
            f"case {case_id}: material_gate must preserve the approval gate"
        )
    if ROUTE_INTENT_FIELDS.issubset(expected):
        if expected["review_intent"] not in ALLOWED_REVIEW_INTENTS:
            raise EvaluationError(f"case {case_id}: invalid expected review_intent")
        if expected["review_intent_source"] not in ALLOWED_REVIEW_INTENT_SOURCES:
            raise EvaluationError(f"case {case_id}: invalid expected review_intent_source")
        if expected["review_intent_scope"] != "turn":
            raise EvaluationError(f"case {case_id}: review_intent_scope must be turn")
        if expected["optional_review"] not in ALLOWED_OPTIONAL_REVIEWS:
            raise EvaluationError(f"case {case_id}: invalid expected optional_review")


def validate_route_corpus(corpus: Any) -> dict[str, Any]:
    """Validate the versioned adaptive route corpus."""
    if not isinstance(corpus, dict):
        raise EvaluationError("route corpus must be an object")
    if type(corpus.get("version")) is not int or corpus["version"] < 1:
        raise EvaluationError("route corpus version must be a positive integer")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationError("route corpus cases must be a non-empty list")

    ids: set[str] = set()
    modes: set[str] = set()
    impacts: set[str] = set()
    abstention_values: set[bool] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "id",
            "prompt",
            "policy_basis",
            "expected",
        }:
            raise EvaluationError(
                "each route corpus case must have id, prompt, policy_basis, expected"
            )
        case_id = case["id"]
        if not _is_nonempty_string(case_id):
            raise EvaluationError("route corpus case id must be a non-empty string")
        if case_id in ids:
            raise EvaluationError(f"duplicate route corpus case id: {case_id}")
        ids.add(case_id)
        if not _is_nonempty_string(case["prompt"]):
            raise EvaluationError(f"case {case_id}: prompt must be a non-empty string")
        if not isinstance(case["policy_basis"], list) or not case["policy_basis"]:
            raise EvaluationError(f"case {case_id}: policy_basis must be a non-empty list")
        if not all(_is_nonempty_string(item) for item in case["policy_basis"]):
            raise EvaluationError(f"case {case_id}: policy_basis must be non-empty strings")
        _validate_route_expected(case["expected"], case_id)
        modes.add(case["expected"]["task_mode"])
        impacts.add(case["expected"]["change_impact"])
        abstention_values.add(case["expected"]["abstain"])

    if modes != ALLOWED_TASK_MODES:
        raise EvaluationError("route corpus must cover all three task modes")
    if not {True, False}.issubset(abstention_values):
        raise EvaluationError("route corpus must contain abstaining and non-abstaining cases")
    if not {"trivial", "low", "material", "high", "critical"}.issubset(impacts):
        raise EvaluationError("route corpus must cover the five impact bands")
    return corpus


def load_route_corpus(path: Path) -> dict[str, Any]:
    """Load and validate one adaptive route corpus."""
    return validate_route_corpus(_load_json(path, "route corpus"))


def _validate_question(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "question",
        "options",
        "recommended",
    }:
        return False
    options = value["options"]
    return (
        _is_nonempty_string(value["id"])
        and _is_nonempty_string(value["question"])
        and isinstance(options, list)
        and len(options) >= 2
        and all(_is_nonempty_string(option) for option in options)
        and _is_nonempty_string(value["recommended"])
        and value["recommended"] in options
    )


def _route_card_error(card: Any) -> str | None:
    if not isinstance(card, dict) or not CARD_REQUIRED_FIELDS.issubset(card):
        return "decision_card_malformed"
    if set(card) - CARD_FIELDS:
        return "decision_card_malformed"
    for field in ("current_interpretation", "proposed_default", "next_reversible_slice"):
        if not _is_nonempty_string(card[field]):
            return "decision_card_malformed"
    for field in ("included_scope", "excluded_scope"):
        if not _validate_string_list(card[field]):
            return "decision_card_malformed"
    if "material_risk" in card and not _validate_string_list(card["material_risk"]):
        return "decision_card_malformed"
    if not isinstance(card["questions"], list) or not card["questions"]:
        return "decision_card_malformed"
    if not all(_validate_question(question) for question in card["questions"]):
        return "decision_card_malformed"
    return None


def _route_decision_error(decision: Any) -> str | None:
    if not isinstance(decision, dict) or set(decision) not in {
        ROUTE_FIELDS,
        ROUTE_FIELDS | ROUTE_INTENT_FIELDS,
    }:
        return "malformed"
    if not _is_nonempty_string(decision["id"]):
        return "malformed"
    for field, allowed in (
        ("task_mode", ALLOWED_TASK_MODES),
        ("intent_confidence", ALLOWED_INTENT_CONFIDENCE),
        ("change_impact", ALLOWED_CHANGE_IMPACT),
        ("discovery_budget", ALLOWED_DISCOVERY_BUDGETS),
        ("reversible", ALLOWED_REVERSIBILITY),
        ("next_gate", ALLOWED_NEXT_GATES),
    ):
        if decision[field] not in allowed:
            return "malformed"
    if not _validate_string_list(decision["blocking_decisions"]):
        return "malformed"
    for field in (
        "abstain",
        "approval_required",
        "budget_exhausted",
        "evidence_sufficient",
    ):
        if type(decision[field]) is not bool:
            return "malformed"
    if decision["role"] is not None and decision["role"] not in ALLOWED_ROLES:
        return "malformed"
    if not _is_nonempty_string(decision["rationale"]):
        return "empty_rationale"
    try:
        validate_execution_contract(
            {
                "execution_scope": decision["execution_scope"],
                "continuation_mode": decision["continuation_mode"],
                "stop_condition": decision["stop_condition"],
            }
        )
    except (ExecutionContractError, KeyError):
        return "malformed"
    if decision["stop_condition"] == "material_gate" and not (
        decision["approval_required"] and decision["next_gate"] == "approval"
    ):
        return "overconfident"
    if decision["approval_required"] and decision["next_gate"] != "approval":
        return "malformed"
    if decision["discovery_budget"] == "none" and decision["budget_exhausted"]:
        return "malformed"
    if decision["budget_exhausted"] and not decision["evidence_sufficient"]:
        if not decision["abstain"]:
            return "overconfident"
        if decision["next_gate"] not in {"discovery", "approval"}:
            return "malformed"
        if decision["decision_card"] is None:
            return "decision_card_missing"
    if decision["abstain"] != (decision["intent_confidence"] != "clear"):
        return "overconfident"
    if decision["abstain"] and not decision["blocking_decisions"]:
        return "malformed"
    if decision["task_mode"] == "co_discover" and decision["intent_confidence"] == "clear":
        return "overconfident"
    if decision["task_mode"] == "execute" and (
        decision["change_impact"] in {"high", "critical"}
        or decision["reversible"] == "no"
    ) and not (decision["approval_required"] and decision["next_gate"] == "approval"):
        return "overconfident"
    if decision["blocking_decisions"] and decision["decision_card"] is None:
        return "decision_card_missing"
    if decision["decision_card"] is not None:
        card_error = _route_card_error(decision["decision_card"])
        if card_error is not None:
            return card_error
    if ROUTE_INTENT_FIELDS.issubset(decision):
        if decision["review_intent"] not in ALLOWED_REVIEW_INTENTS:
            return "malformed"
        if decision["review_intent_source"] not in ALLOWED_REVIEW_INTENT_SOURCES:
            return "malformed"
        if decision["review_intent_scope"] != "turn":
            return "malformed"
        if decision["optional_review"] not in ALLOWED_OPTIONAL_REVIEWS:
            return "malformed"
    return None


def evaluate_route(
    corpus: dict[str, Any],
    decisions: list[Any],
    *,
    min_route_accuracy: float = 1.0,
    min_abstention_accuracy: float = 1.0,
    min_card_accuracy: float = 1.0,
) -> dict[str, Any]:
    """Score adaptive route signals, abstention, cards, roles, and approvals."""
    for value, name in (
        (min_route_accuracy, "min_route_accuracy"),
        (min_abstention_accuracy, "min_abstention_accuracy"),
        (min_card_accuracy, "min_card_accuracy"),
    ):
        _threshold(value, name)
    if not isinstance(decisions, list):
        raise EvaluationError("route decisions must be a list")

    expected_by_id = {case["id"]: case["expected"] for case in corpus["cases"]}
    invalid = {
        "malformed": 0,
        "empty_rationale": 0,
        "overconfident": 0,
        "decision_card_missing": 0,
        "decision_card_malformed": 0,
        "duplicate_ids": 0,
        "unknown_ids": 0,
    }
    accepted: dict[str, dict[str, Any]] = {}
    submitted_ids: set[str] = set()
    for submitted in decisions:
        case_id = submitted.get("id") if isinstance(submitted, dict) else None
        duplicate = _is_nonempty_string(case_id) and case_id in submitted_ids
        if _is_nonempty_string(case_id):
            submitted_ids.add(case_id)
        error = _route_decision_error(submitted)
        if error is not None:
            invalid[error] += 1
        if duplicate:
            invalid["duplicate_ids"] += 1
        if error is not None or duplicate:
            continue
        assert isinstance(case_id, str)
        if case_id not in expected_by_id:
            invalid["unknown_ids"] += 1
            continue
        accepted[case_id] = submitted

    expected_ids = set(expected_by_id)
    coverage_complete = (
        submitted_ids == expected_ids
        and invalid["duplicate_ids"] == 0
        and invalid["unknown_ids"] == 0
    )
    signal_fields = (
        "task_mode",
        "intent_confidence",
        "change_impact",
        "discovery_budget",
        "reversible",
        "next_gate",
        "budget_exhausted",
        "evidence_sufficient",
        "execution_scope",
        "continuation_mode",
        "stop_condition",
    )
    has_review_intent = any(
        ROUTE_INTENT_FIELDS.issubset(expected)
        for expected in expected_by_id.values()
    )
    if has_review_intent:
        signal_fields += tuple(ROUTE_INTENT_FIELDS)
    route_correct = sum(
        accepted.get(case_id, {}).get("task_mode") == expected["task_mode"]
        for case_id, expected in expected_by_id.items()
    )
    signal_correct = sum(
        all(accepted.get(case_id, {}).get(field) == expected[field] for field in signal_fields)
        for case_id, expected in expected_by_id.items()
    )
    abstention_correct = sum(
        accepted.get(case_id, {}).get("abstain") == expected["abstain"]
        for case_id, expected in expected_by_id.items()
    )
    card_correct = sum(
        (accepted.get(case_id, {}).get("decision_card") is not None) == expected["decision_card"]
        for case_id, expected in expected_by_id.items()
    )
    role_correct = sum(
        accepted.get(case_id, {}).get("role") == expected["role"]
        for case_id, expected in expected_by_id.items()
    )
    approval_correct = sum(
        accepted.get(case_id, {}).get("approval_required") == expected["approval_required"]
        for case_id, expected in expected_by_id.items()
    )
    execution_contract_correct = sum(
        all(
            accepted.get(case_id, {}).get(field) == expected[field]
            for field in ("execution_scope", "continuation_mode", "stop_condition")
        )
        for case_id, expected in expected_by_id.items()
    )
    review_intent_correct = (
        sum(
            all(
                accepted.get(case_id, {}).get(field) == expected[field]
                for field in ROUTE_INTENT_FIELDS
            )
            for case_id, expected in expected_by_id.items()
            if ROUTE_INTENT_FIELDS.issubset(expected)
        )
        if has_review_intent
        else None
    )
    total = len(expected_ids)
    false_direct = sum(
        accepted.get(case_id, {}).get("task_mode") == "execute"
        and expected["task_mode"] != "execute"
        for case_id, expected in expected_by_id.items()
    )
    false_overexploration = sum(
        accepted.get(case_id, {}).get("task_mode") in {"explore_then_plan", "co_discover"}
        and expected["task_mode"] == "execute"
        for case_id, expected in expected_by_id.items()
    )
    invalid["total"] = sum(invalid.values())
    route_accuracy = route_correct / total if total else 1.0
    abstention_accuracy = abstention_correct / total if total else 1.0
    card_accuracy = card_correct / total if total else 1.0
    passed = (
        coverage_complete
        and invalid["total"] == 0
        and route_accuracy >= min_route_accuracy
        and abstention_accuracy >= min_abstention_accuracy
        and card_accuracy >= min_card_accuracy
        and role_correct == total
        and approval_correct == total
        and execution_contract_correct == total
    )
    return {
        "evaluator": "adaptive-route-behavioral-not-runtime-enforcement",
        "corpus_version": corpus["version"],
        "coverage": {
            "expected": total,
            "submitted": len(decisions),
            "complete": coverage_complete,
        },
        "route_selection": {
            "correct": route_correct,
            "total": total,
            "accuracy": route_accuracy,
        },
        "signal_bundle": {
            "correct": signal_correct,
            "total": total,
            "accuracy": signal_correct / total if total else 1.0,
        },
        "abstention": {
            "correct": abstention_correct,
            "total": total,
            "accuracy": abstention_accuracy,
        },
        "decision_card": {
            "correct": card_correct,
            "total": total,
            "accuracy": card_accuracy,
        },
        "role_expectation": {"correct": role_correct, "total": total},
        "approval_expectation": {"correct": approval_correct, "total": total},
        "execution_contract": {
            "correct": execution_contract_correct,
            "total": total,
            "accuracy": execution_contract_correct / total if total else 1.0,
        },
        "review_intent": (
            {
                "correct": review_intent_correct,
                "total": total,
                "accuracy": review_intent_correct / total if total else 1.0,
            }
            if has_review_intent
            else {"status": "not measured by legacy route corpus"}
        ),
        "false_direct_execution": false_direct,
        "false_overexploration": false_overexploration,
        "measurements": {
            "latency_ms": None,
            "token_cost_proxy": None,
            "status": "not measured by offline semantic route evaluation",
        },
        "invalid_decisions": invalid,
        "thresholds": {
            "min_route_accuracy": min_route_accuracy,
            "min_abstention_accuracy": min_abstention_accuracy,
            "min_card_accuracy": min_card_accuracy,
        },
        "passed": passed,
    }


def _validate_checkpoint_expected(expected: Any, case_id: str) -> None:
    if not isinstance(expected, dict) or set(expected) != CHECKPOINT_EXPECTED_FIELDS:
        raise EvaluationError(f"case {case_id}: invalid checkpoint expected shape")
    if expected["disposition"] not in ALLOWED_CHECKPOINT_DISPOSITIONS:
        raise EvaluationError(f"case {case_id}: invalid checkpoint disposition")
    for field in ("replan_required", "rollback_target_available", "approval_required"):
        if type(expected[field]) is not bool:
            raise EvaluationError(f"case {case_id}: checkpoint {field} must be boolean")


def validate_checkpoint_corpus(corpus: Any) -> dict[str, Any]:
    """Validate direction-checkpoint fixtures."""
    if not isinstance(corpus, dict):
        raise EvaluationError("checkpoint corpus must be an object")
    if type(corpus.get("version")) is not int or corpus["version"] < 1:
        raise EvaluationError("checkpoint corpus version must be a positive integer")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationError("checkpoint corpus cases must be a non-empty list")
    ids: set[str] = set()
    dispositions: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "id",
            "prompt",
            "policy_basis",
            "expected",
        }:
            raise EvaluationError("each checkpoint case has an invalid shape")
        case_id = case["id"]
        if not _is_nonempty_string(case_id) or case_id in ids:
            raise EvaluationError(f"invalid or duplicate checkpoint case id: {case_id}")
        ids.add(case_id)
        if not _is_nonempty_string(case["prompt"]):
            raise EvaluationError(f"case {case_id}: prompt must be non-empty")
        if not isinstance(case["policy_basis"], list) or not case["policy_basis"]:
            raise EvaluationError(f"case {case_id}: policy_basis must be non-empty")
        _validate_checkpoint_expected(case["expected"], case_id)
        dispositions.add(case["expected"]["disposition"])
    if dispositions != ALLOWED_CHECKPOINT_DISPOSITIONS:
        raise EvaluationError("checkpoint corpus must cover CONTINUE, PIVOT, and ROLLBACK")
    return corpus


def load_checkpoint_corpus(path: Path) -> dict[str, Any]:
    """Load and validate direction-checkpoint fixtures."""
    return validate_checkpoint_corpus(_load_json(path, "checkpoint corpus"))


def _checkpoint_decision_error(decision: Any) -> str | None:
    if not isinstance(decision, dict) or set(decision) != CHECKPOINT_FIELDS:
        return "malformed"
    if not _is_nonempty_string(decision["id"]):
        return "malformed"
    if decision["disposition"] not in (*ALLOWED_CHECKPOINT_DISPOSITIONS, "INCONCLUSIVE"):
        return "malformed"
    for field in ("replan_required", "rollback_target_available", "approval_required"):
        if type(decision[field]) is not bool:
            return "malformed"
    if not _is_nonempty_string(decision["rationale"]):
        return "empty_rationale"
    if decision["disposition"] == "PIVOT" and not decision["replan_required"]:
        return "unsafe_disposition"
    if decision["disposition"] == "ROLLBACK" and (
        not decision["rollback_target_available"] and not decision["approval_required"]
    ):
        return "unsafe_disposition"
    if decision["disposition"] == "INCONCLUSIVE" and not decision["approval_required"]:
        return "unsafe_disposition"
    return None


def evaluate_checkpoints(corpus: dict[str, Any], decisions: list[Any]) -> dict[str, Any]:
    """Score direction dispositions independently from completed outcomes."""
    if not isinstance(decisions, list):
        raise EvaluationError("checkpoint decisions must be a list")
    expected_by_id = {case["id"]: case["expected"] for case in corpus["cases"]}
    invalid = {"malformed": 0, "empty_rationale": 0, "unsafe_disposition": 0, "duplicate_ids": 0, "unknown_ids": 0}
    accepted: dict[str, dict[str, Any]] = {}
    submitted_ids: set[str] = set()
    for submitted in decisions:
        case_id = submitted.get("id") if isinstance(submitted, dict) else None
        duplicate = _is_nonempty_string(case_id) and case_id in submitted_ids
        if _is_nonempty_string(case_id):
            submitted_ids.add(case_id)
        error = _checkpoint_decision_error(submitted)
        if error is not None:
            invalid[error] += 1
        if duplicate:
            invalid["duplicate_ids"] += 1
        if error is not None or duplicate:
            continue
        assert isinstance(case_id, str)
        if case_id not in expected_by_id:
            invalid["unknown_ids"] += 1
            continue
        accepted[case_id] = submitted

    expected_ids = set(expected_by_id)
    coverage_complete = submitted_ids == expected_ids and not any(
        invalid[field] for field in ("duplicate_ids", "unknown_ids")
    )
    total = len(expected_ids)
    disposition_correct = sum(
        accepted.get(case_id, {}).get("disposition") == expected["disposition"]
        for case_id, expected in expected_by_id.items()
    )
    replan_correct = sum(
        accepted.get(case_id, {}).get("replan_required") == expected["replan_required"]
        for case_id, expected in expected_by_id.items()
    )
    rollback_correct = sum(
        accepted.get(case_id, {}).get("rollback_target_available")
        == expected["rollback_target_available"]
        for case_id, expected in expected_by_id.items()
    )
    approval_correct = sum(
        accepted.get(case_id, {}).get("approval_required") == expected["approval_required"]
        for case_id, expected in expected_by_id.items()
    )
    invalid["total"] = sum(invalid.values())
    passed = (
        coverage_complete
        and invalid["total"] == 0
        and disposition_correct == total
        and replan_correct == total
        and rollback_correct == total
        and approval_correct == total
    )
    return {
        "evaluator": "direction-checkpoint-behavioral-not-runtime-enforcement",
        "corpus_version": corpus["version"],
        "coverage": {"expected": total, "submitted": len(decisions), "complete": coverage_complete},
        "disposition": {"correct": disposition_correct, "total": total},
        "replan": {"correct": replan_correct, "total": total},
        "rollback_target": {"correct": rollback_correct, "total": total},
        "approval": {"correct": approval_correct, "total": total},
        "invalid_decisions": invalid,
        "passed": passed,
    }


def _contains_forbidden_live_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key.startswith(("tool", "function")):
                return True
            if normalized_key == "name" and isinstance(child, str) and "spawn" in child:
                return True
            if normalized_key in {"type", "event_type", "kind", "name"} and isinstance(child, str):
                if any(
                    marker in child.lower()
                    for marker in (
                        "tool",
                        "function",
                        "spawn",
                        "sub_agent",
                        "command",
                        "search",
                        "file_change",
                        "computer",
                    )
                ):
                    return True
            if _contains_forbidden_live_evidence(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_live_evidence(item) for item in value)
    return False


def parse_live_output(output: str, *, expected_case_id: str) -> dict[str, Any]:
    """Parse one strict no-tool decision from supported Codex JSONL shapes."""
    messages: list[str] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationError(f"live output line {line_number} is not JSON") from exc
        if not isinstance(event, dict) or _contains_forbidden_live_evidence(event):
            raise EvaluationError("live output contains malformed or tool/spawn evidence")

        if event.get("type") == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") != "agent_message":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                raise EvaluationError("live agent message is missing text")
            messages.append(text)
            continue

        if event.get("type") != "response_item":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        content = payload.get("content")
        if not isinstance(content, list):
            raise EvaluationError("live response message is missing content")
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "output_text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                raise EvaluationError("live output text is missing text")
            messages.append(text)

    if len(messages) != 1:
        raise EvaluationError("live output must contain exactly one decision message")
    try:
        decision = json.loads(messages[0])
    except json.JSONDecodeError as exc:
        raise EvaluationError("live agent response must be one exact JSON object") from exc
    if _decision_error(decision) is not None or decision["id"] != expected_case_id:
        raise EvaluationError("live agent response violates the strict decision contract")
    return decision


def build_live_command(*, codex_bin: str, repository_root: Path, case: dict[str, Any]) -> list[str]:
    """Build one read-only, no-tool live decision command for a single case."""
    prompt = (
        "Classify this task using the Pilotfish behavioral routing policy. Do not "
        "call tools, do not spawn agents, and do not delegate. Return exactly one "
        "JSON object with keys id, decision, role, rationale; no markdown or prose. "
        f"Case ID: {case['id']}\nTask: {case['prompt']}\n"
        f"Policy basis: {', '.join(case['policy_basis'])}"
    )
    return [
        codex_bin,
        "exec",
        "--json",
        "--strict-config",
        "-C",
        str(repository_root),
        "-s",
        "read-only",
        prompt,
    ]


def run_live_case(*, codex_bin: str, repository_root: Path, case: dict[str, Any]) -> dict[str, Any]:
    """Run and fail closed on one manually authorized live decision request."""
    try:
        completed = subprocess.run(
            build_live_command(
                codex_bin=codex_bin, repository_root=repository_root, case=case
            ),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvaluationError(f"live decision command failed: {exc}") from exc
    if completed.returncode != 0:
        raise EvaluationError("live decision command returned non-zero")
    if completed.stderr.strip():
        raise EvaluationError("live decision command emitted unexpected stderr")
    return parse_live_output(completed.stdout, expected_case_id=case["id"])


def _print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
    )
    parser.add_argument("--route", action="store_true")
    parser.add_argument("--checkpoint", action="store_true")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--decisions", type=Path)
    source.add_argument("--live", action="store_true")
    parser.add_argument("--min-role-accuracy", type=float, default=1.0)
    parser.add_argument("--min-abstention-accuracy", type=float, default=1.0)
    parser.add_argument("--min-route-accuracy", type=float, default=1.0)
    parser.add_argument("--min-card-accuracy", type=float, default=1.0)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--task-eval-yes", action="store_true")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--codex-bin", default="codex")
    args = parser.parse_args(argv)

    try:
        if args.route and args.checkpoint:
            raise EvaluationError("--route and --checkpoint are mutually exclusive")
        if args.corpus is None:
            if args.route:
                args.corpus = (
                    repository_root
                    / "docs"
                    / "specs"
                    / "adaptive-intent-routing"
                    / "route-corpus.json"
                )
            elif args.checkpoint:
                args.corpus = (
                    repository_root
                    / "docs"
                    / "specs"
                    / "adaptive-intent-routing"
                    / "checkpoint-corpus.json"
                )
            else:
                args.corpus = (
                    repository_root
                    / "docs"
                    / "specs"
                    / "dispatch-verification"
                    / "task-class-corpus.json"
                )
        if args.route:
            corpus = load_route_corpus(args.corpus)
        elif args.checkpoint:
            corpus = load_checkpoint_corpus(args.corpus)
        else:
            corpus = load_corpus(args.corpus)
        if args.decisions is not None:
            if args.yes or args.case_id:
                raise EvaluationError("--yes and --case-id are only valid with --live")
            decisions = load_decisions(args.decisions)
            if args.route:
                report = evaluate_route(
                    corpus,
                    decisions,
                    min_route_accuracy=args.min_route_accuracy,
                    min_abstention_accuracy=args.min_abstention_accuracy,
                    min_card_accuracy=args.min_card_accuracy,
                )
            elif args.checkpoint:
                report = evaluate_checkpoints(corpus, decisions)
            else:
                report = evaluate(
                    corpus,
                    decisions,
                    min_role_accuracy=args.min_role_accuracy,
                    min_abstention_accuracy=args.min_abstention_accuracy,
                )
        else:
            if args.route or args.checkpoint:
                raise EvaluationError("live evaluation is only available for dispatch corpus")
            if not args.yes or not args.task_eval_yes:
                raise EvaluationError(
                    "live evaluation requires --yes and --task-eval-yes"
                )
            if os.environ.get("CI"):
                raise EvaluationError("live evaluation is prohibited in CI")
            if not args.case_id:
                raise EvaluationError("live evaluation requires at least one --case-id")
            if len(args.case_id) > LIVE_CASE_CAP or len(set(args.case_id)) != len(args.case_id):
                raise EvaluationError(f"live evaluation accepts 1 to {LIVE_CASE_CAP} unique cases")
            cases_by_id = {case["id"]: case for case in corpus["cases"]}
            if any(case_id not in cases_by_id for case_id in args.case_id):
                raise EvaluationError("live evaluation requested an unknown case id")
            selected_cases = [cases_by_id[case_id] for case_id in args.case_id]
            decisions = [
                run_live_case(
                    codex_bin=args.codex_bin,
                    repository_root=repository_root,
                    case=case,
                )
                for case in selected_cases
            ]
            report = evaluate(
                {"version": corpus["version"], "cases": selected_cases},
                decisions,
                min_role_accuracy=args.min_role_accuracy,
                min_abstention_accuracy=args.min_abstention_accuracy,
            )
            report["live"] = {"case_cap": LIVE_CASE_CAP, "cases_run": len(selected_cases)}
    except EvaluationError as exc:
        _print_report(
            {
                "evaluator": "behavioral-not-runtime-enforcement",
                "passed": False,
                "error": str(exc),
            }
        )
        return 2

    _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
