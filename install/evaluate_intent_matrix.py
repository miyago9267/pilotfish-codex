#!/usr/bin/env python3
"""Evaluate the 1.6.0 intent Matrix against the real local hook runtime."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "install"))

import pilotfish_autoroute_gate as gate  # noqa: E402
from intent_review_matrix import validate_matrix  # noqa: E402
from review_intent_contract import validate_signal  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    return validate_matrix(json.loads(path.read_text(encoding="utf-8")))


def _invoke_hook(case: dict[str, Any]) -> dict[str, Any] | None:
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "matrix-session",
        "turn_id": case["id"],
        "prompt": case["prompt"],
    }
    environment = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="intent-hook-matrix-") as home:
        environment["CODEX_HOME"] = home
        completed = subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "pilotfish_autoroute_gate.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
    if completed.returncode != 0:
        raise ValueError(f"case {case['id']} hook process failed")
    if not completed.stdout.strip():
        return None
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"case {case['id']} hook output is not JSON") from exc
    if not isinstance(output, dict):
        raise ValueError(f"case {case['id']} hook output is not an object")
    return output


def _signal_from_output(case: dict[str, Any], output: dict[str, Any] | None) -> dict[str, Any] | None:
    if output is None:
        return None
    try:
        context = output["hookSpecificOutput"]["additionalContext"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"case {case['id']} hook signal shape is invalid") from exc
    if not isinstance(context, str):
        raise ValueError(f"case {case['id']} hook signal context is invalid")
    if "Pilotfish review intent signal: " not in context:
        route_prefix = "Pilotfish automatic model route: "
        if route_prefix not in context:
            raise ValueError(f"case {case['id']} hook signal context is invalid")
        encoded_route = context.split(route_prefix, 1)[1].split("\n", 1)[0]
        route = json.loads(encoded_route)
        if not isinstance(route, dict) or route.get("turn_id") != case["id"]:
            raise ValueError(f"case {case['id']} automatic route context is invalid")
        return None
    encoded = context.split("Pilotfish review intent signal: ", 1)[1].split("\n", 1)[0]
    return validate_signal(json.loads(encoded))


def evaluate(matrix: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    counters = Counter()
    hard_gate_by_scenario: dict[str, set[tuple[tuple[str, ...], bool, bool]]] = {}
    for case in matrix["cases"]:
        expected = case["expected"]
        output = _invoke_hook(case)
        signal = _signal_from_output(case, output)
        actual_intent = None if signal is None else signal["review_intent"]
        categories = gate.classify_prompt(case["prompt"])
        expected_intent = expected["review_intent"]
        intent_ok = actual_intent == (None if expected_intent == "default" and case["intent_variant"] == "none" else expected_intent)
        if case["intent_variant"] == "conflicting_or_quoted":
            intent_ok = actual_intent is None
        expected_categories = tuple(expected["risk_categories"])
        category_ok = categories == expected_categories
        context = output.get("hookSpecificOutput", {}).get("additionalContext", "") if output else ""
        route_signal_present = isinstance(context, str) and "Pilotfish automatic model route: " in context
        signal_ok = (signal is None and actual_intent is None and route_signal_present) or (
            signal is not None
            and signal["turn_id"] == case["id"]
            and "prompt" not in signal
        )
        sol_expected = bool(expected_categories) and (
            "security" in expected_categories or len(expected_categories) >= 2
        )
        sol_actual = gate.requires_sol_review(categories)
        row = {
            "id": case["id"],
            "intent_variant": case["intent_variant"],
            "intent_expected": expected_intent,
            "intent_observed": actual_intent,
            "intent_correct": intent_ok,
            "categories_expected": list(expected_categories),
            "categories_observed": list(categories),
            "categories_correct": category_ok,
            "sol_trigger_expected": sol_expected,
            "sol_trigger_observed": sol_actual,
            "signal_contract_valid": signal_ok,
            "hook_process_valid": output is None or signal is not None or route_signal_present,
            "hard_gate_preserved": expected["hard_gate_preserved"],
        }
        rows.append(row)
        counters["intent_total"] += 1
        counters["intent_correct"] += int(intent_ok)
        counters["category_total"] += 1
        counters["category_correct"] += int(category_ok)
        counters["signal_total"] += int(actual_intent is not None)
        counters["signal_correct"] += int(signal_ok and actual_intent is not None)
        counters["hook_process_total"] += 1
        counters["hook_process_correct"] += int(
            output is None or signal is not None or route_signal_present
        )
        counters["sol_total"] += 1
        counters["sol_correct"] += int(sol_actual == sol_expected)
        hard_gate_by_scenario.setdefault(case["scenario"], set()).add(
            (categories, sol_actual, bool(expected["approval_required"]))
        )

    hard_gate_parity = all(len(values) == 1 for values in hard_gate_by_scenario.values())
    mandatory_review_trigger_preserved = all(
        (not expected["hard_gate_preserved"]) or row["sol_trigger_observed"]
        for row, case in zip(rows, matrix["cases"])
        for expected in [case["expected"]]
    )
    return {
        "version": "intent-review-runtime-matrix-v1",
        "cases": len(rows),
        "metrics": {
            "intent_accuracy": counters["intent_correct"] / counters["intent_total"],
            "risk_category_accuracy": counters["category_correct"] / counters["category_total"],
            "signal_contract_accuracy": counters["signal_correct"] / counters["signal_total"],
            "hook_process_accuracy": counters["hook_process_correct"] / counters["hook_process_total"],
            "sol_trigger_accuracy": counters["sol_correct"] / counters["sol_total"],
            "hard_gate_parity": hard_gate_parity,
            "mandatory_review_trigger_preserved": mandatory_review_trigger_preserved,
        },
        "counts": dict(counters),
        "hard_gate_by_scenario": {
            key: [
                {"categories": list(categories), "sol_trigger": sol_trigger, "approval_required": approval_required}
                for categories, sol_trigger, approval_required in sorted(values)
            ]
            for key, values in hard_gate_by_scenario.items()
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(_load(args.matrix))
    args.output.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": report["cases"], "metrics": report["metrics"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
