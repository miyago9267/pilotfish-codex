#!/usr/bin/env python3
"""Prove that a named Codex child used its installed role model.

The live command is added below the evidence parser. Normal tests import only
the offline functions and never call Codex or scan the user's session store.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from validate_agents import validate_config


TASK_NAME = "model_probe"
TASK_NAME_RE = re.compile(r"^[a-z0-9_]+$")
PARENT_EVIDENCE_TYPES = frozenset(
    {"session_meta", "turn_context", "response_item", "event_msg"}
)
CHILD_EVIDENCE_TYPES = frozenset({"session_meta", "turn_context"})
EXTRACTOR_EVIDENCE_TYPES = frozenset({"response_item", "event_msg"})


class EvidenceError(ValueError):
    """Raised when rollout evidence is missing, malformed, or ambiguous."""


@dataclass(frozen=True)
class RoleBinding:
    model: str
    effort: str


@dataclass(frozen=True)
class Verdict:
    status: str
    reason: str
    parent_thread_id: str | None = None
    child_thread_id: str | None = None
    parent_model: str | None = None
    child_model: str | None = None


def _verdict(
    status: str,
    reason: str,
    *,
    parent_thread_id: str | None = None,
    child_thread_id: str | None = None,
    parent_model: str | None = None,
    child_model: str | None = None,
) -> Verdict:
    return Verdict(
        status=status,
        reason=reason,
        parent_thread_id=parent_thread_id,
        child_thread_id=child_thread_id,
        parent_model=parent_model,
        child_model=child_model,
    )


def _payloads(events: Iterable[dict], item_type: str) -> list[dict]:
    return [
        event["payload"]
        for event in events
        if event.get("type") == item_type and isinstance(event.get("payload"), dict)
    ]


def _validate_evidence_events(
    events: Iterable[dict], relevant_types: frozenset[str]
) -> None:
    """Reject malformed evidence while ignoring unrelated event payloads."""
    for event in events:
        if not isinstance(event, dict):
            raise EvidenceError("rollout event is not an object")
        event_type = event.get("type")
        if event_type not in relevant_types:
            continue
        if not isinstance(event.get("payload"), dict):
            raise EvidenceError(f"{event_type} payload is not an object")


def load_jsonl(path: Path) -> list[dict]:
    """Load a rollout JSONL file and reject malformed or non-object events."""
    events: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvidenceError(f"cannot read rollout {path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(event, dict):
            raise EvidenceError(f"{path}:{line_number}: event is not an object")
        try:
            _validate_evidence_events([event], PARENT_EVIDENCE_TYPES)
        except EvidenceError as exc:
            raise EvidenceError(f"{path}:{line_number}: {exc}") from exc
        events.append(event)

    if not events:
        raise EvidenceError(f"{path}: rollout is empty")
    return events


def parse_exec_thread_id(output: str) -> str:
    """Extract one exact parent thread ID from `codex exec --json` output."""
    thread_ids: set[str] = set()
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"exec output line {line_number} is not JSON") from exc
        if not isinstance(event, dict):
            raise EvidenceError(f"exec output line {line_number} is not an object")
        if event.get("type") != "thread.started":
            continue
        thread_id = event.get("thread_id")
        if thread_id is None and isinstance(event.get("thread"), dict):
            thread_id = event["thread"].get("id")
        if isinstance(thread_id, str) and thread_id:
            thread_ids.add(thread_id)

    if len(thread_ids) != 1:
        raise EvidenceError(
            f"expected one exec parent thread ID, found {len(thread_ids)}"
        )
    return thread_ids.pop()


def locate_rollout(
    sessions_root: Path,
    thread_id: str,
    candidate_directories: Iterable[Path],
) -> Path:
    """Find one rollout by exact thread-ID suffix in bounded day directories.

    The suffix comparison is literal on purpose: a thread ID is evidence
    parsed from exec output, so glob metacharacters in it must never change
    which file matches."""
    trust_root = sessions_root.resolve()
    suffix = f"-{thread_id}.jsonl"
    matches: set[Path] = set()
    for directory in candidate_directories:
        resolved_directory = directory.resolve()
        if not resolved_directory.is_relative_to(trust_root):
            raise EvidenceError(
                f"candidate rollout directory is outside {trust_root}: "
                f"{resolved_directory}"
            )
        if resolved_directory.is_dir():
            for path in resolved_directory.iterdir():
                if not path.name.endswith(suffix) or not path.is_file():
                    continue
                resolved_path = path.resolve()
                if not resolved_path.is_relative_to(trust_root):
                    raise EvidenceError(
                        f"rollout resolves outside {trust_root}: {resolved_path}"
                    )
                matches.add(resolved_path)

    if len(matches) != 1:
        raise EvidenceError(
            f"expected one rollout for thread {thread_id}, found {len(matches)}"
        )
    return matches.pop()


def candidate_day_directories(
    sessions_root: Path,
    started_at: datetime,
    ended_at: datetime,
) -> list[Path]:
    """Return unique day directories explicitly crossed by one live probe."""
    first_date, last_date = sorted((started_at.date(), ended_at.date()))
    dates = (
        first_date + timedelta(days=offset)
        for offset in range((last_date - first_date).days + 1)
    )
    return [
        sessions_root / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
        for date in dates
    ]


def read_role_config(path: Path) -> dict:
    """Read one complete role TOML for install-drift comparison."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise EvidenceError(f"role file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise EvidenceError(f"invalid role TOML: {path}") from exc
    return data


def read_role_binding(path: Path) -> RoleBinding:
    """Read the model and effort that a named role must resolve to."""
    data = read_role_config(path)

    model = data.get("model")
    effort = data.get("model_reasoning_effort")
    if not isinstance(model, str) or not model:
        raise EvidenceError(f"role model is missing: {path}")
    if not isinstance(effort, str) or not effort:
        raise EvidenceError(f"role effort is missing: {path}")
    return RoleBinding(model=model, effort=effort)


def _spawn_call(parent_events: list[dict]) -> dict:
    spawn_calls = [
        payload
        for payload in _payloads(parent_events, "response_item")
        if payload.get("type") == "function_call"
        and payload.get("name") == "spawn_agent"
    ]
    if len(spawn_calls) != 1:
        reason = "missing" if not spawn_calls else "ambiguous"
        raise EvidenceError(f"spawn call is {reason}")
    return spawn_calls[0]


def extract_child_thread_id(parent_events: list[dict]) -> str:
    """Resolve one child from the exact spawn call/activity correlation."""
    _validate_evidence_events(parent_events, EXTRACTOR_EVIDENCE_TYPES)
    spawn = _spawn_call(parent_events)
    call_id = spawn.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise EvidenceError("spawn call has no call ID")
    try:
        arguments = json.loads(spawn.get("arguments", ""))
    except (json.JSONDecodeError, TypeError) as exc:
        raise EvidenceError("spawn arguments are invalid") from exc
    if not isinstance(arguments, dict):
        raise EvidenceError("spawn arguments are not an object")
    task_name = arguments.get("task_name")

    activities = [
        payload
        for payload in _payloads(parent_events, "event_msg")
        if payload.get("type") == "sub_agent_activity"
        and isinstance(payload.get("event_id"), str)
        and bool(payload.get("event_id"))
        and payload["event_id"] == call_id
        and payload.get("kind") == "started"
        and payload.get("agent_path") == f"/root/{task_name}"
    ]
    if len(activities) != 1:
        raise EvidenceError(
            f"expected one correlated child activity, found {len(activities)}"
        )
    child_id = activities[0].get("agent_thread_id")
    if not isinstance(child_id, str) or not child_id:
        raise EvidenceError("correlated child activity has no thread ID")
    return child_id


def build_codex_command(
    *,
    codex_bin: str,
    cwd: Path,
    mode: str,
    parent_model: str,
) -> list[str]:
    """Build the isolated one-parent/one-child live probe command."""
    if mode not in {"adapter", "native"}:
        raise ValueError(f"unsupported verification mode: {mode}")

    namespace = "agents" if mode == "adapter" else "collaboration"
    prompt = (
        f"Call {namespace}.spawn_agent exactly once with: "
        "task_name='model_probe', agent_type='scout', fork_turns='none', "
        "message='Do not run commands. Reply only with READY.'. Then use only "
        "agent lifecycle tools to wait for the child to finish and close it; "
        "relay its answer without calling non-lifecycle tools."
    )
    command = [
        codex_bin,
        "exec",
        "--json",
        "--strict-config",
        "-C",
        str(cwd),
        "-m",
        parent_model,
        "-c",
        'model_reasoning_effort="low"',
        "-s",
        "read-only",
    ]
    if mode == "native":
        command.append("--ignore-user-config")
    command.append(prompt)
    return command


def _session_id(events: list[dict]) -> tuple[str | None, str | None]:
    payloads = _payloads(events, "session_meta")
    if len(payloads) != 1:
        return None, None
    session_id = payloads[0].get("id")
    parent_id = payloads[0].get("parent_thread_id")
    return (
        session_id if isinstance(session_id, str) else None,
        parent_id if isinstance(parent_id, str) else None,
    )


def _turn_context(
    events: list[dict], *, required_fields: tuple[str, ...]
) -> dict | None:
    payloads: list[dict] = []
    for event in events:
        if event.get("type") != "turn_context":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise EvidenceError("turn context payload is not an object")
        payloads.append(payload)
    if not payloads:
        return None

    evidence: list[tuple[str, ...]] = []
    for payload in payloads:
        values = tuple(payload.get(field) for field in required_fields)
        if any(not isinstance(value, str) or not value for value in values):
            raise EvidenceError("turn context has invalid required fields")
        evidence.append(values)
    if any(values != evidence[0] for values in evidence[1:]):
        raise EvidenceError("turn context evidence conflicts")
    return payloads[0]


def inspect_dispatch(
    parent_events: list[dict],
    child_events: list[dict],
    *,
    expected_role: RoleBinding,
    expected_namespace: str,
    adapter_free: bool = False,
) -> Verdict:
    """Return a fail-closed verdict from one exact parent/child rollout pair."""
    try:
        _validate_evidence_events(parent_events, PARENT_EVIDENCE_TYPES)
    except EvidenceError as exc:
        reason = (
            "parent_context_invalid"
            if str(exc).startswith("turn_context ")
            else "parent_evidence_invalid"
        )
        return _verdict("FAILED", reason)

    parent_id, _ = _session_id(parent_events)
    try:
        parent_context = _turn_context(
            parent_events,
            required_fields=("model", "effort", "multi_agent_version"),
        )
    except EvidenceError as exc:
        reason = (
            "parent_context_conflict"
            if "conflicts" in str(exc)
            else "parent_context_invalid"
        )
        return _verdict("FAILED", reason, parent_thread_id=parent_id)
    if parent_id is None or parent_context is None:
        return _verdict("FAILED", "parent_evidence_missing")

    parent_model = parent_context.get("model")
    multi_agent_version = parent_context.get("multi_agent_version")
    if multi_agent_version == "v1":
        return _verdict(
            "SKIPPED",
            "adapter_not_exercised",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )
    if multi_agent_version != "v2":
        return _verdict(
            "FAILED",
            "multi_agent_version_mismatch",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )

    try:
        spawn = _spawn_call(parent_events)
    except EvidenceError as exc:
        reason = "spawn_call_ambiguous" if "ambiguous" in str(exc) else "spawn_call_missing"
        return _verdict(
            "FAILED",
            reason,
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )
    if spawn.get("namespace") != expected_namespace:
        return _verdict(
            "FAILED",
            "namespace_mismatch",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )

    try:
        arguments = json.loads(spawn.get("arguments", ""))
    except (json.JSONDecodeError, TypeError):
        return _verdict(
            "FAILED",
            "spawn_arguments_invalid",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )
    if not isinstance(arguments, dict):
        return _verdict(
            "FAILED",
            "spawn_arguments_invalid",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )
    if "service_tier" in arguments:
        return _verdict(
            "FAILED",
            "service_tier_override_forbidden",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )
    if arguments.get("agent_type") != "scout":
        return _verdict(
            "FAILED",
            "agent_type_mismatch",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )
    if arguments.get("fork_turns") != "none":
        return _verdict(
            "FAILED",
            "fork_turns_mismatch",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )

    task_name = arguments.get("task_name")
    if task_name != TASK_NAME or not TASK_NAME_RE.fullmatch(str(task_name)):
        return _verdict(
            "FAILED",
            "task_name_mismatch",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )

    call_id = spawn.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return _verdict(
            "FAILED",
            "spawn_call_id_missing",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )
    activities = [
        payload
        for payload in _payloads(parent_events, "event_msg")
        if payload.get("type") == "sub_agent_activity"
        and isinstance(payload.get("event_id"), str)
        and bool(payload.get("event_id"))
        and payload["event_id"] == call_id
        and payload.get("kind") == "started"
        and payload.get("agent_path") == f"/root/{task_name}"
    ]
    if len(activities) != 1:
        return _verdict(
            "FAILED",
            "child_activity_missing" if not activities else "child_activity_ambiguous",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )

    child_id = activities[0].get("agent_thread_id")
    if not isinstance(child_id, str) or not child_id:
        return _verdict(
            "FAILED",
            "child_thread_id_missing",
            parent_thread_id=parent_id,
            parent_model=parent_model,
        )

    try:
        _validate_evidence_events(child_events, CHILD_EVIDENCE_TYPES)
    except EvidenceError as exc:
        reason = (
            "child_context_invalid"
            if str(exc).startswith("turn_context ")
            else "child_evidence_invalid"
        )
        return _verdict(
            "FAILED",
            reason,
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
        )

    child_session_id, child_parent_id = _session_id(child_events)
    try:
        child_context = _turn_context(
            child_events,
            required_fields=("model", "effort"),
        )
    except EvidenceError as exc:
        reason = (
            "child_context_conflict"
            if "conflicts" in str(exc)
            else "child_context_invalid"
        )
        return _verdict(
            "FAILED",
            reason,
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
        )
    if child_session_id != child_id or child_parent_id != parent_id:
        return _verdict(
            "FAILED",
            "parent_child_mismatch",
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
        )
    if child_context is None:
        return _verdict(
            "FAILED",
            "child_evidence_missing",
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
        )

    child_model = child_context.get("model")
    child_effort = child_context.get("effort")
    if child_model != expected_role.model:
        return _verdict(
            "FAILED",
            "child_model_mismatch",
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
            child_model=child_model,
        )
    if child_effort != expected_role.effort:
        return _verdict(
            "FAILED",
            "child_effort_mismatch",
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
            child_model=child_model,
        )
    if child_model == parent_model:
        return _verdict(
            "FAILED",
            "inherited_parent_model",
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
            child_model=child_model,
        )

    if expected_namespace == "collaboration" and not adapter_free:
        return _verdict(
            "FAILED",
            "native_adapter_state_unproven",
            parent_thread_id=parent_id,
            child_thread_id=child_id,
            parent_model=parent_model,
            child_model=child_model,
        )

    status = "NATIVE_OK" if expected_namespace == "collaboration" else "ADAPTER_OK"
    return _verdict(
        status,
        "verified_distinct_model",
        parent_thread_id=parent_id,
        child_thread_id=child_id,
        parent_model=parent_model,
        child_model=child_model,
    )


def _print_verdict(verdict: Verdict) -> None:
    if verdict.status == "FAILED":
        print(
            "warning: routing verification failed; stop named-role dispatch "
            "to avoid unintended parent-model cost",
            file=sys.stderr,
        )
    fields = [verdict.status, f"reason={verdict.reason}"]
    for name in (
        "parent_thread_id",
        "child_thread_id",
        "parent_model",
        "child_model",
    ):
        value = getattr(verdict, name)
        if value is not None:
            fields.append(f"{name}={value}")
    print(" ".join(fields))


def _exit_code(status: str) -> int:
    if status in {"ADAPTER_OK", "NATIVE_OK"}:
        return 0
    if status == "SKIPPED":
        return 2
    return 1


def classify_exec_failure(*, stdout: str, stderr: str) -> Verdict:
    """Map an unsuccessful Codex process to a stable fail-closed verdict."""
    diagnostic = f"{stdout}\n{stderr}".lower()
    if "not logged in" in diagnostic or "authentication" in diagnostic:
        return _verdict("SKIPPED", "auth_unavailable")
    if "model" in diagnostic and "unavailable" in diagnostic:
        return _verdict("SKIPPED", "parent_model_unavailable")
    return _verdict("FAILED", "codex_exec_failed")


def _preflight(
    *,
    codex_bin: str,
    codex_home: Path,
    repository_root: Path,
    mode: str,
    parent_model: str,
) -> tuple[RoleBinding | None, Verdict | None]:
    template_role = repository_root / "templates" / "agents" / "scout.toml"
    installed_role = codex_home / "agents" / "scout.toml"
    try:
        template_config = read_role_config(template_role)
        installed_config = read_role_config(installed_role)
        expected = read_role_binding(template_role)
    except EvidenceError as exc:
        print(f"role preflight failed: {exc}", file=sys.stderr)
        return None, _verdict("FAILED", "role_preflight_failed")

    if installed_config != template_config:
        return None, _verdict("FAILED", "installed_role_drift")
    if parent_model == expected.model:
        return None, _verdict("FAILED", "parent_model_not_distinct")

    if mode == "adapter":
        config_errors, config_warnings = validate_config(codex_home / "config.toml")
        for warning in config_warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if config_errors:
            print("\n".join(config_errors), file=sys.stderr)
            return None, _verdict("FAILED", "adapter_config_invalid")

        try:
            with (codex_home / "config.toml").open("rb") as handle:
                config = tomllib.load(handle)
            concurrency = config["features"]["multi_agent_v2"][
                "max_concurrent_threads_per_session"
            ]
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            return None, _verdict("FAILED", "adapter_config_invalid")
        if concurrency == 1:
            return None, _verdict("SKIPPED", "child_delegation_disabled")

    try:
        version = subprocess.run(
            [codex_bin, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None, _verdict("SKIPPED", "codex_unavailable")
    if version.returncode != 0:
        return None, _verdict("SKIPPED", "codex_unavailable")

    login = subprocess.run(
        [codex_bin, "login", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if login.returncode != 0:
        return None, _verdict("SKIPPED", "auth_unavailable")
    return expected, None


def _live_verify(args: argparse.Namespace) -> Verdict:
    if args.mode == "native":
        return _verdict("SKIPPED", "native_schema_introspection_unavailable")

    codex_home = args.codex_home
    expected, preflight_verdict = _preflight(
        codex_bin=args.codex_bin,
        codex_home=codex_home,
        repository_root=args.repository_root,
        mode=args.mode,
        parent_model=args.parent_model,
    )
    if preflight_verdict is not None:
        return preflight_verdict
    assert expected is not None

    print(
        "warning: this live dispatch probe spends real model quota",
        file=sys.stderr,
    )
    command = build_codex_command(
        codex_bin=args.codex_bin,
        cwd=args.repository_root,
        mode=args.mode,
        parent_model=args.parent_model,
    )
    started_local = datetime.now().astimezone()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    ended_local = datetime.now().astimezone()
    if completed.returncode != 0:
        verdict = classify_exec_failure(
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if verdict.status == "FAILED":
            print(completed.stderr.strip(), file=sys.stderr)
        return verdict

    try:
        parent_id = parse_exec_thread_id(completed.stdout)
        sessions_root = codex_home / "sessions"
        directories = candidate_day_directories(
            sessions_root, started_local, ended_local
        )
        utc_directories = candidate_day_directories(
            sessions_root,
            started_local.astimezone(timezone.utc),
            ended_local.astimezone(timezone.utc),
        )
        bounded_directories = list(dict.fromkeys(directories + utc_directories))
        parent_path = locate_rollout(
            sessions_root,
            parent_id,
            bounded_directories,
        )
        parent_events = load_jsonl(parent_path)
        child_id = extract_child_thread_id(parent_events)
        child_path = locate_rollout(
            sessions_root,
            child_id,
            [parent_path.parent, *bounded_directories],
        )
        child_events = load_jsonl(child_path)
    except EvidenceError as exc:
        print(str(exc), file=sys.stderr)
        return _verdict("FAILED", "rollout_evidence_invalid")

    namespace = "agents" if args.mode == "adapter" else "collaboration"
    return inspect_dispatch(
        parent_events,
        child_events,
        expected_role=expected,
        expected_namespace=namespace,
    )


def main(argv: list[str] | None = None) -> int:
    repository_root = Path(__file__).resolve().parents[1]
    default_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--mode", choices=("adapter", "native"), default="adapter")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path, default=default_home)
    parser.add_argument("--repository-root", type=Path, default=repository_root)
    parser.add_argument("--parent-model", default="gpt-5.6-terra")
    args = parser.parse_args(argv)

    if not args.live:
        verdict = _verdict("SKIPPED", "live_flag_required")
    elif not args.yes:
        verdict = _verdict("SKIPPED", "operator_opt_in_required")
    else:
        verdict = _live_verify(args)

    _print_verdict(verdict)
    return _exit_code(verdict.status)


if __name__ == "__main__":
    raise SystemExit(main())
