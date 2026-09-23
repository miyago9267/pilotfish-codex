#!/usr/bin/env python3
"""Run explicitly authorized, bounded native dispatch repeats.

This is the live evidence adapter for the first operational slice.  It creates
one fresh staged Codex home per stage, invokes the existing fail-closed
``verify_dispatch.py --live --yes`` contract, retains only sanitized receipts,
and emits repeat summaries.  It does not claim the content-bearing
role-fitness cohort by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from benchmark_role_fitness import (
    BenchmarkContractError,
    build_live_run_summary,
    build_dry_run_report,
    validate_live_run_summary,
    validate_resource_admission,
)
from role_fitness_scorecard import aggregate_repeats, append_repeat_record, score_rate
from stage_smoke_home import StageError, materialize


DEFAULT_ROLES = ("scout",)
DEFAULT_PARENT_MODEL = "gpt-6-luna"
MAX_REPEAT_COUNT = 3
DEFAULT_STAGE_TIMEOUT = 360


def scorecard_hash(repository_root: Path) -> str:
    source = Path(__file__).with_name("role_fitness_scorecard.py")
    payload = b"operational-v1\0" + source.read_bytes()
    return hashlib.sha256(payload).hexdigest()


def _launch_capture(home: Path, cwd: Path) -> Path:
    path = home.parent / "launch-capture.json"
    path.write_text(
        json.dumps(
            {"CODEX_HOME": str(home), "CODEX_SQLITE_HOME": str(home), "codex_cwd": str(cwd)},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _remove_private_root(path: Path) -> None:
    """Remove staged auth/session material and fail closed if it remains."""
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise BenchmarkContractError("private stage cleanup failed") from exc
    if path.exists() or path.is_symlink():
        raise BenchmarkContractError("private stage cleanup was incomplete")


def run_stage(
    *,
    active_home: Path,
    codex_bin: str,
    repository_root: Path,
    role: str,
    stage_id: str,
    parent_model: str,
    timeout: int,
) -> dict[str, Any]:
    """Run one isolated dispatch stage and return its sanitized receipt."""
    directory = Path(tempfile.mkdtemp(prefix=f"pilotfish-{stage_id}-"))
    try:
        root = directory
        home = root / "codex-home"
        cwd = root / "clean-cwd"
        cwd.mkdir()
        try:
            materialize(active_home, home)
        except StageError as exc:
            raise BenchmarkContractError(f"stage materialization failed: {exc}") from exc
        capture = _launch_capture(home, cwd)
        command = [
            sys.executable,
            str(repository_root / "install" / "verify_dispatch.py"),
            "--live",
            "--yes",
            "--role",
            role,
            "--codex-bin",
            codex_bin,
            "--codex-home",
            str(home),
            "--active-codex-home",
            str(active_home),
            "--repository-root",
            str(repository_root),
            "--codex-cwd",
            str(cwd),
            "--parent-model",
            parent_model,
            "--receipt",
            f"{stage_id}.json",
            "--launch-capture",
            str(capture),
        ]
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"CODEX_HOME", "CODEX_SQLITE_HOME"}
        }
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env={**env, "PYTHONUNBUFFERED": "1"},
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise BenchmarkContractError(f"stage timed out: {stage_id}") from exc
        receipt = home / "dispatch-receipts" / f"{stage_id}.json"
        if not receipt.is_file() or receipt.is_symlink():
            detail = (completed.stdout or completed.stderr).strip()[:240]
            raise BenchmarkContractError(
                f"stage did not produce a receipt: {stage_id}: {detail}"
            )
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BenchmarkContractError(f"stage receipt is unreadable: {stage_id}") from exc
        if not isinstance(payload, dict):
            raise BenchmarkContractError(f"stage receipt is not an object: {stage_id}")
        # The receipt validator is called by build_live_run_summary; the
        # subprocess status is intentionally not used to turn a failed stage
        # into a pass.
        return payload
    finally:
        _remove_private_root(directory)


def run_repeats(
    *,
    active_home: Path,
    codex_bin: str,
    repository_root: Path,
    roles: Sequence[str],
    repeats: int,
    stages_per_role: int,
    parent_model: str,
    timeout: int,
    checkpoint_path: Path | None = None,
) -> list[dict[str, Any]]:
    if repeats < 1 or repeats > MAX_REPEAT_COUNT:
        raise BenchmarkContractError("repeat count must be between 1 and 3")
    if stages_per_role < 1:
        raise BenchmarkContractError("stages_per_role must be positive")
    if not roles or any(not role for role in roles):
        raise BenchmarkContractError("at least one role is required")
    total_stages = repeats * len(roles) * stages_per_role
    validate_resource_admission(
        arms=total_stages,
        paid_processes=total_stages,
        wall_seconds=total_stages * timeout,
    )
    manifest_hash = build_dry_run_report(repository_root / "templates" / "agents")["manifest_hash"]
    stable_scorecard_hash = scorecard_hash(repository_root)
    summaries: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        run_id = f"R{repeat}"
        receipts: list[Path] = []
        with tempfile.TemporaryDirectory(prefix=f"pilotfish-{run_id}-") as receipt_root:
            for role in roles:
                for stage_number in range(1, stages_per_role + 1):
                    stage_id = f"{run_id}-{role}-{stage_number}"
                    payload = run_stage(
                        active_home=active_home,
                        codex_bin=codex_bin,
                        repository_root=repository_root,
                        role=role,
                        stage_id=stage_id,
                        parent_model=parent_model,
                        timeout=timeout,
                    )
                    destination = Path(receipt_root) / f"{stage_id}.json"
                    destination.write_text(
                        json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    receipts.append(destination)
            summary = build_live_run_summary(
                run_id=run_id,
                manifest_hash=manifest_hash,
                scorecard_hash=stable_scorecard_hash,
                receipt_paths=receipts,
                stability_passed=True,
            )
        validate_live_run_summary(summary)
        summaries.append(summary)
        if checkpoint_path is not None:
            checkpoint_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "version": "role-fitness-live-dispatch-v1",
                        "status": "running",
                        "summaries": summaries,
                        "aggregate": aggregate_repeats(summaries),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
    return summaries


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--active-codex-home", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--role", action="append", dest="roles", default=[])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--stages-per-role", type=int, default=1)
    parser.add_argument("--parent-model", default=DEFAULT_PARENT_MODEL)
    parser.add_argument("--stage-timeout", type=int, default=DEFAULT_STAGE_TIMEOUT)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args(argv)
    if not args.live or not args.yes:
        parser.error("live repeat requires both --live and --yes")
    roles = tuple(args.roles) if args.roles else DEFAULT_ROLES
    summaries = run_repeats(
        active_home=args.active_codex_home,
        codex_bin=args.codex_bin,
        repository_root=args.repository_root,
        roles=roles,
        repeats=args.repeats,
        stages_per_role=args.stages_per_role,
        parent_model=args.parent_model,
        timeout=args.stage_timeout,
        checkpoint_path=args.checkpoint,
    )
    aggregate = aggregate_repeats(summaries)
    availability = aggregate["availability"]
    confidence = score_rate(
        availability["passed"],
        availability["total"],
        minimum_samples=30,
        required_lower_bound=0.80,
    )
    aggregate["availability_gate"] = {
        **confidence,
        "target_lower_bound": 0.90,
        "target_proven": confidence["lower_bound"] >= 0.90,
        "scope": "dispatch-only",
    }
    if args.checkpoint:
        args.checkpoint.write_text(
            json.dumps(
                {
                    "version": "role-fitness-live-dispatch-v1",
                    "status": "completed",
                    "summaries": summaries,
                    "aggregate": aggregate,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    if args.ledger:
        for summary in summaries:
            append_repeat_record(args.ledger, summary)
    return {"version": "role-fitness-live-dispatch-v1", "summaries": summaries, "aggregate": aggregate}


if __name__ == "__main__":
    try:
        json.dump(main(), sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    except BenchmarkContractError as exc:
        print(f"benchmark_live_failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
