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
        default=repository_root / "docs" / "specs" / "dispatch-verification" / "task-class-corpus.json",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--decisions", type=Path)
    source.add_argument("--live", action="store_true")
    parser.add_argument("--min-role-accuracy", type=float, default=1.0)
    parser.add_argument("--min-abstention-accuracy", type=float, default=1.0)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--task-eval-yes", action="store_true")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--codex-bin", default="codex")
    args = parser.parse_args(argv)

    try:
        corpus = load_corpus(args.corpus)
        if args.decisions is not None:
            if args.yes or args.case_id:
                raise EvaluationError("--yes and --case-id are only valid with --live")
            report = evaluate(
                corpus,
                load_decisions(args.decisions),
                min_role_accuracy=args.min_role_accuracy,
                min_abstention_accuracy=args.min_abstention_accuracy,
            )
        else:
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
