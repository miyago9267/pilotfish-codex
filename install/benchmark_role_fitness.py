#!/usr/bin/env python3
"""Contract runner and evidence adapter for the role-fitness benchmark.

The runner remains offline-first: it never starts Codex implicitly.  Its live
evidence adapter consumes already-issued dispatch receipts, validates their
stage boundary, and emits a sanitized repeat summary for the scorecard.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Sequence

from role_fitness_scorecard import append_repeat_record, score_architecture
from validate_agents import ROLES, validate_agent
from verify_dispatch import validate_receipt


class BenchmarkContractError(ValueError):
    """A dry-run input violates the fail-closed benchmark contract."""


VERSION = "role-fitness-v1"
SCORECARD_VERSION = "operational-v1"
ROLE_TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "agents"


def load_expected_bindings(agent_root: Path = ROLE_TEMPLATE_ROOT) -> dict[str, tuple[str, str]]:
    """Read benchmark bindings from the canonical role TOMLs.

    Keeping the benchmark projection derived from the manifest prevents a
    template-only model change from silently measuring an old binding.
    """
    if not agent_root.is_dir() or agent_root.is_symlink():
        raise BenchmarkContractError("role template root is invalid")
    bindings: dict[str, tuple[str, str]] = {}
    for path in sorted(agent_root.glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise BenchmarkContractError(f"role template cannot be read: {path.name}") from exc
        errors = validate_agent(data)
        name = data.get("name")
        model = data.get("model")
        effort = data.get("model_reasoning_effort")
        if errors or name != path.stem or not isinstance(model, str) or not isinstance(effort, str):
            raise BenchmarkContractError(f"role template binding is invalid: {path.name}")
        if name in bindings:
            raise BenchmarkContractError(f"duplicate role template: {name}")
        bindings[name] = (model, effort)
    if set(bindings) != set(ROLES):
        raise BenchmarkContractError("role template manifest is incomplete")
    return bindings


EXPECTED_BINDINGS = load_expected_bindings()
COHORTS = {
    "plan_review": {"cases": 12, "arms": 24, "stages": 1},
    "mechanical_execution": {"cases": 12, "arms": 24, "stages": 2},
    "split_workflow": {"cases": 6, "arms": 12, "stages": 3},
}
MAX_ARMS = 60
MAX_PAID_PROCESSES = 108
MAX_WALL_SECONDS = 6 * 60 * 60
HANDOFF_KEYS = frozenset(
    {
        "scenario_id",
        "fixture_hash",
        "original_plan_hash",
        "approved_plan_hash",
        "ledger_commitment",
        "revision_ids",
        "review_score_hash",
    }
)
PUBLIC_KEYS = frozenset(
    {
        "version",
        "cohort",
        "aggregates",
        "metrics",
        "limits",
        "commitment_hashes",
        "metric_versions",
    }
)
SECRET_OR_PATH_RE = re.compile(
    r"(?:[/\\])|(?:auth|token|password|secret|credential|api[_-]?key)",
    re.IGNORECASE,
)
ADMITTED_PHASES = frozenset({"execution-pre-child", "post-spawn", "dispatch"})
FAILURE_CLASSES = frozenset({
    "none",
    "auth",
    "timeout",
    "receipt",
    "cleanup",
    "metric_correlation",
    "native_spawn",
    "execution",
    "preflight",
    "capability_gap",
})
STAGE_KEYS = frozenset(
    {"stage_id", "status", "phase", "reason_code", "admitted", "passed", "failure_class"}
)


def fixture_commitment(
    salt: bytes, fixture_hash: str, ledger_bytes: bytes, rubric_bytes: bytes
) -> str:
    """Create the salted pre-run commitment required by the SPEC."""
    if not salt or not fixture_hash:
        raise BenchmarkContractError("commitment inputs are incomplete")
    return hmac.new(
        salt, fixture_hash.encode("utf-8") + ledger_bytes + rubric_bytes, hashlib.sha256
    ).hexdigest()


def validate_handoff(value: dict[str, Any]) -> bool:
    """Validate the identity-free execution handoff schema."""
    if set(value) != HANDOFF_KEYS:
        raise BenchmarkContractError("handoff contains unknown or missing fields")
    for key in HANDOFF_KEYS - {"revision_ids"}:
        if not isinstance(value[key], str) or not value[key]:
            raise BenchmarkContractError(f"handoff field is invalid: {key}")
    revisions = value["revision_ids"]
    if not isinstance(revisions, list) or not revisions or any(
        not isinstance(item, str) or not item for item in revisions
    ):
        raise BenchmarkContractError("handoff revision_ids is invalid")
    return True


def validate_mechanical_result(case_id: str, result: dict[str, Any]) -> bool:
    """Validate the only artifact admitted by a mechanical acceptance script."""
    if not isinstance(result, dict) or set(result) != {"case_id", "accepted"}:
        raise BenchmarkContractError("mechanical result schema is invalid")
    if result != {"case_id": case_id, "accepted": True}:
        raise BenchmarkContractError("mechanical result did not pass acceptance")
    return True


def build_split_handoff(
    *,
    private_root: Path,
    case_id: str,
    review_output: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply only ledger-supported fragments and create an identity-free handoff."""
    from role_fitness_fixtures import score_plan_review, validate_split_revisions

    manifest = json.loads((private_root / "manifest.json").read_text(encoding="utf-8"))
    case = next((item for item in manifest["cases"] if item.get("case_id") == case_id), None)
    if not isinstance(case, dict) or case.get("cohort") != "split_workflow":
        raise BenchmarkContractError("split case is not in the fixture manifest")
    ledgers = json.loads((private_root / "ledgers.json").read_text(encoding="utf-8"))
    ledger = ledgers.get(case_id)
    if not isinstance(ledger, list):
        raise BenchmarkContractError("split ledger is missing")
    score = score_plan_review(ledger, review_output)
    if not score["passed"] or score["claimed_findings"] != score["matched_findings"]:
        return None
    claimed_revision_ids = {
        finding.get("revision_id") for finding in review_output["findings"]
    }
    revision_ids = [entry["revision_id"] for entry in ledger if entry.get("revision_id") in claimed_revision_ids]
    if not revision_ids:
        return None
    revisions_path = private_root / "revisions" / f"{case_id}.json"
    revisions = json.loads(revisions_path.read_text(encoding="utf-8"))
    validate_split_revisions(case_id, revisions)
    fragments = {item["revision_id"]: item["text"] for item in revisions["revision_fragments"]}
    if any(revision_id not in fragments for revision_id in revision_ids):
        return None
    original = (private_root / "fixtures" / f"{case_id}.md").read_bytes()
    approved = original + b"\n\n" + b"\n".join(fragments[revision_id].encode("utf-8") for revision_id in sorted(revision_ids))
    handoff = {
        "scenario_id": case_id,
        "fixture_hash": case["fixture_hash"],
        "original_plan_hash": hashlib.sha256(original).hexdigest(),
        "approved_plan_hash": hashlib.sha256(approved).hexdigest(),
        "ledger_commitment": case["ledger_commitment"],
        "revision_ids": sorted(revision_ids),
        "review_score_hash": hashlib.sha256(json.dumps(score, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    }
    validate_handoff(handoff)
    if handoff["approved_plan_hash"] == handoff["original_plan_hash"]:
        raise BenchmarkContractError("split handoff did not derive a new plan")
    return handoff


def validate_public_projection(value: dict[str, Any]) -> dict[str, Any]:
    """Reject non-allowlisted public report fields and secret/path-like data."""
    if not isinstance(value, dict) or not set(value).issubset(PUBLIC_KEYS):
        raise BenchmarkContractError("public projection contains unknown fields")

    def walk(item: Any) -> None:
        if isinstance(item, str) and SECRET_OR_PATH_RE.search(item):
            raise BenchmarkContractError("public projection contains secret-like data")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or SECRET_OR_PATH_RE.search(key):
                    raise BenchmarkContractError("public projection contains unsafe key")
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return value


def validate_resource_admission(*, arms: int, paid_processes: int, wall_seconds: int) -> None:
    """Enforce the hard cohort resource ceilings before execution."""
    if (
        arms < 0
        or paid_processes < 0
        or wall_seconds < 0
        or arms > MAX_ARMS
        or paid_processes > MAX_PAID_PROCESSES
        or wall_seconds > MAX_WALL_SECONDS
    ):
        raise BenchmarkContractError("benchmark resource admission exceeds hard cap")


def _failure_class(status: str, reason_code: str, phase: str) -> str:
    if status == "NATIVE_OK":
        return "none"
    if reason_code == "platform_halt":
        return "capability_gap"
    if phase == "preflight":
        return "auth" if reason_code == "auth_unavailable" else "preflight"
    if reason_code in {"codex_exec_failed", "codex_exec_failed_after_spawn"}:
        return "execution"
    if reason_code in {"native_spawn_evidence_missing", "child_evidence_missing", "child_binding_unobservable"}:
        return "native_spawn"
    if "timeout" in reason_code:
        return "timeout"
    if "receipt" in reason_code:
        return "receipt"
    return "metric_correlation" if "correlation" in reason_code else "execution"


def build_live_run_summary(
    *,
    run_id: str,
    manifest_hash: str,
    scorecard_hash: str,
    receipt_paths: Sequence[Path],
    stability_passed: bool = False,
) -> dict[str, Any]:
    """Build a sanitized repeat summary from validated dispatch receipts.

    A receipt is admitted only after it crossed the execution boundary.  A
    preflight skip therefore cannot inflate availability, while an admitted
    timeout or missing child evidence remains in the denominator.
    """
    if not run_id or not manifest_hash or not scorecard_hash or not receipt_paths:
        raise BenchmarkContractError("live run identity or receipts are incomplete")
    stages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in receipt_paths:
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise BenchmarkContractError("receipt path is invalid")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise BenchmarkContractError("receipt is not an object")
            validate_receipt(payload)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise BenchmarkContractError("receipt is invalid") from exc
        stage_id = path.stem
        if stage_id in seen:
            raise BenchmarkContractError("duplicate receipt stage")
        seen.add(stage_id)
        status = payload["status"]
        phase = payload["phase"]
        admitted = phase in ADMITTED_PHASES
        stages.append({
            "stage_id": stage_id,
            "status": status,
            "phase": phase,
            "reason_code": payload["reason_code"],
            "admitted": admitted,
            "passed": admitted and status == "NATIVE_OK",
            "failure_class": _failure_class(status, payload["reason_code"], phase),
        })
    if any(stage["failure_class"] not in FAILURE_CLASSES for stage in stages):
        raise BenchmarkContractError("receipt failure taxonomy is invalid")
    admitted = [stage for stage in stages if stage["admitted"]]
    failures: dict[str, int] = {}
    for stage in admitted:
        if not stage["passed"]:
            key = stage["failure_class"]
            failures[key] = failures.get(key, 0) + 1
    return {
        "run_id": run_id,
        "manifest_hash": manifest_hash,
        "scorecard_hash": scorecard_hash,
        "mode": "live-evidence",
        "availability": {"passed": sum(stage["passed"] for stage in admitted), "total": len(admitted)},
        "stability": {"passed": int(stability_passed), "total": 1},
        "failure_taxonomy": failures,
        "stages": stages,
        "evidence": {"receipts_validated": len(stages), "raw_sessions_published": 0},
    }


def validate_live_run_summary(summary: Mapping[str, Any]) -> None:
    """Validate stage accounting before a summary enters the repeat ledger."""
    if summary.get("mode") != "live-evidence":
        raise BenchmarkContractError("run summary must declare live evidence")
    stages = summary.get("stages")
    if not isinstance(stages, list) or not stages:
        raise BenchmarkContractError("run summary stages are missing")
    admitted = 0
    passed = 0
    failure_counts: dict[str, int] = {}
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != STAGE_KEYS:
            raise BenchmarkContractError("stage accounting schema is invalid")
        if (
            not isinstance(stage["stage_id"], str)
            or not stage["stage_id"]
            or not isinstance(stage["status"], str)
            or not isinstance(stage["phase"], str)
            or not isinstance(stage["reason_code"], str)
            or not isinstance(stage["admitted"], bool)
            or not isinstance(stage["passed"], bool)
            or stage["failure_class"] not in FAILURE_CLASSES
        ):
            raise BenchmarkContractError("stage accounting value is invalid")
        if stage["passed"] and (not stage["admitted"] or stage["status"] != "NATIVE_OK"):
            raise BenchmarkContractError("stage pass is not admitted native evidence")
        if stage["admitted"]:
            admitted += 1
            passed += int(stage["passed"])
            if not stage["passed"]:
                failure_counts[stage["failure_class"]] = failure_counts.get(stage["failure_class"], 0) + 1
    availability = summary.get("availability")
    if availability != {"passed": passed, "total": admitted}:
        raise BenchmarkContractError("availability does not reconcile with stages")
    if summary.get("failure_taxonomy") != failure_counts:
        raise BenchmarkContractError("failure taxonomy does not reconcile with stages")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_role_bindings(role_root: Path) -> dict[str, dict[str, Any]]:
    """Validate exactly the installed roles and their expected bindings."""
    if not role_root.is_dir() or role_root.is_symlink():
        raise BenchmarkContractError("role root must be a real directory")
    expected_bindings = load_expected_bindings()
    expected_names = set(expected_bindings)
    actual_names = {path.stem for path in role_root.glob("*.toml")}
    if actual_names != expected_names or actual_names != set(ROLES):
        raise BenchmarkContractError("role manifest is incomplete or has extras")

    result: dict[str, dict[str, Any]] = {}
    for role, (expected_model, expected_effort) in expected_bindings.items():
        path = role_root / f"{role}.toml"
        if path.is_symlink() or not path.is_file():
            raise BenchmarkContractError(f"role file is invalid: {role}")
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise BenchmarkContractError(f"role TOML cannot be read: {role}") from exc
        errors = validate_agent(data)
        actual = (data.get("model"), data.get("model_reasoning_effort"))
        if errors or actual != (expected_model, expected_effort):
            raise BenchmarkContractError(f"role binding mismatch: {role}")
        result[role] = {
            "model": expected_model,
            "reasoning_effort": expected_effort,
            "valid": True,
            "sha256": _sha256(path.read_bytes()),
        }
    return result


def build_dry_run_report(role_root: Path) -> dict[str, Any]:
    """Validate the offline seam without starting Codex or reading auth."""
    bindings = validate_role_bindings(role_root)
    manifest_input = json.dumps(
        {"version": VERSION, "bindings": bindings, "cohorts": COHORTS},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    validate_resource_admission(arms=60, paid_processes=108, wall_seconds=MAX_WALL_SECONDS)
    validate_handoff(
        {
            "scenario_id": "dry-run",
            "fixture_hash": "fixture-hash",
            "original_plan_hash": "original-plan-hash",
            "approved_plan_hash": "approved-plan-hash",
            "ledger_commitment": fixture_commitment(
                b"dry-run-salt", "fixture-hash", b"ledger", b"rubric"
            ),
            "revision_ids": ["dry-run-revision"],
            "review_score_hash": "review-score-hash",
        }
    )
    validate_public_projection({"version": "role-fitness-public-v1", "cohort": COHORTS})
    validate_live_run_summary(
        {
            "mode": "live-evidence",
            "stages": [{
                "stage_id": "synthetic-correlation",
                "status": "NATIVE_OK",
                "phase": "post-spawn",
                "reason_code": "native_verified",
                "admitted": True,
                "passed": True,
                "failure_class": "none",
            }],
            "availability": {"passed": 1, "total": 1},
            "failure_taxonomy": {},
        }
    )
    architecture = score_architecture(
        {
            "role_binding": True,
            "stage_ownership": True,
            "handoff_validation": True,
            "receipt_correlation": True,
            "public_projection": True,
        }
    )
    return {
        "version": VERSION,
        "mode": "dry-run",
        "live_calls": 0,
        "manifest_hash": _sha256(manifest_input),
        "scorecard_path": {"version": SCORECARD_VERSION, "valid": True},
        "architecture": architecture,
        "offline_contracts": {
            "commitment": "valid",
            "handoff": "valid",
            "public_projection": "valid",
            "resource_admission": "valid",
        },
        "role_bindings": bindings,
        "cohorts": COHORTS,
        "security_gates": {
            "auth_isolation": "not_run",
            "private_retention": "not_run",
            "public_projection": "not_run",
            "handoff_validation": "not_run",
        },
        "live_execution": "receipt-adapter-only",
    }


def append_run_summary(ledger_path: Path, summary_path: Path) -> dict[str, Any]:
    """Append one explicit run summary; reject malformed or missing records."""
    if not summary_path.is_file() or summary_path.is_symlink():
        raise BenchmarkContractError("run summary path is invalid")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkContractError("run summary is not valid JSON") from exc
    if not isinstance(summary, dict):
        raise BenchmarkContractError("run summary must be an object")
    for key in ("run_id", "manifest_hash", "scorecard_hash", "availability", "stability", "stages", "failure_taxonomy"):
        if key not in summary:
            raise BenchmarkContractError(f"run summary field is missing: {key}")
    validate_live_run_summary(summary)
    try:
        return append_repeat_record(ledger_path, summary)
    except ValueError as exc:
        raise BenchmarkContractError(str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--build-summary", action="store_true")
    parser.add_argument("--receipt", action="append", type=Path, default=[])
    parser.add_argument("--run-id")
    parser.add_argument("--manifest-hash")
    parser.add_argument("--scorecard-hash")
    parser.add_argument("--role-root", type=Path, default=Path(__file__).resolve().parents[1] / "templates" / "agents")
    parser.add_argument("--append-run", type=Path)
    parser.add_argument("--run-summary", type=Path)
    args = parser.parse_args(argv)
    if args.build_summary:
        if args.dry_run or args.append_run or args.run_summary:
            parser.error("--build-summary cannot be combined with another run mode")
        if not all((args.run_id, args.manifest_hash, args.scorecard_hash)) or not args.receipt:
            parser.error("--build-summary requires run identity and at least one --receipt")
        return build_live_run_summary(
            run_id=args.run_id,
            manifest_hash=args.manifest_hash,
            scorecard_hash=args.scorecard_hash,
            receipt_paths=args.receipt,
        )
    if not args.dry_run and not (args.append_run and args.run_summary):
        parser.error("only --dry-run, --build-summary, or --append-run with --run-summary is supported")
    if args.dry_run:
        return build_dry_run_report(args.role_root)
    if args.append_run is None or args.run_summary is None:
        parser.error("--append-run requires --run-summary")
    return append_run_summary(args.append_run, args.run_summary)


if __name__ == "__main__":
    json.dump(main(), sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
