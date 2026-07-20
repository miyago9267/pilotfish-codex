#!/usr/bin/env python3
"""Prove that a named Codex child used its installed role model.

The live command is added below the evidence parser. Normal tests import only
the offline functions and never call Codex or scan the user's session store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from validate_agents import validate_config


TASK_NAME = "model_probe"
TASK_NAME_RE = re.compile(r"^[a-z0-9_]+$")
ROLE_NAMES = (
    "scout",
    "plan-verifier",
    "executor",
    "mech-executor",
    "security-reviewer",
    "security-executor",
    "verifier",
)
ROUTE_OBSERVATIONS = frozenset(
    {
        "not_attempted",
        "not_observed",
        "requested_role_not_executed",
        "typed_child_observed",
        "typed_child_verified",
    }
)
RECEIPT_VERSION = 1
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
    route_observation: str = "not_observed"


@dataclass(frozen=True)
class ReceiptDestination:
    directory: Path
    receipt_path: Path


@dataclass(frozen=True)
class LiveEvidence:
    parent_rollout: Path | None = None
    child_rollout: Path | None = None
    started_at_utc: str | None = None
    ended_at_utc: str | None = None


def _verdict(
    status: str,
    reason: str,
    *,
    parent_thread_id: str | None = None,
    child_thread_id: str | None = None,
    parent_model: str | None = None,
    child_model: str | None = None,
    route_observation: str = "not_observed",
) -> Verdict:
    if route_observation not in ROUTE_OBSERVATIONS:
        raise ValueError(f"unsupported route observation: {route_observation}")
    if status in {"ADAPTER_OK", "NATIVE_OK"}:
        route_observation = "typed_child_verified"
    elif child_thread_id is not None and route_observation == "not_observed":
        route_observation = "typed_child_observed"
    return Verdict(
        status=status,
        reason=reason,
        parent_thread_id=parent_thread_id,
        child_thread_id=child_thread_id,
        parent_model=parent_model,
        child_model=child_model,
        route_observation=route_observation,
    )


def _with_route_observation(verdict: Verdict, route_observation: str) -> Verdict:
    return _verdict(
        verdict.status,
        verdict.reason,
        parent_thread_id=verdict.parent_thread_id,
        child_thread_id=verdict.child_thread_id,
        parent_model=verdict.parent_model,
        child_model=verdict.child_model,
        route_observation=route_observation,
    )


def task_name_for_role(role: str) -> str:
    """Return the stable, schema-safe probe task name for one configured role."""
    if role not in ROLE_NAMES:
        raise ValueError(f"unsupported role: {role}")
    return f"{TASK_NAME}_{role.replace('-', '_')}"


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


def extract_child_thread_id(
    parent_events: list[dict], *, expected_task_name: str | None = None
) -> str:
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
    if expected_task_name is not None and task_name != expected_task_name:
        raise EvidenceError("spawn task name does not match requested role")

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
    role: str = "scout",
    task_name: str = TASK_NAME,
) -> list[str]:
    """Build the isolated one-parent/one-child live probe command."""
    if mode not in {"adapter", "native"}:
        raise ValueError(f"unsupported verification mode: {mode}")
    if role not in ROLE_NAMES:
        raise ValueError(f"unsupported role: {role}")
    if not TASK_NAME_RE.fullmatch(task_name):
        raise ValueError(f"invalid task name: {task_name}")

    namespace = "agents" if mode == "adapter" else "collaboration"
    prompt = (
        f"Call {namespace}.spawn_agent exactly once with: "
        f"task_name='{task_name}', agent_type='{role}', fork_turns='none', "
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
    expected_role_name: str = "scout",
    expected_task_name: str = TASK_NAME,
    adapter_free: bool = False,
) -> Verdict:
    """Return a fail-closed verdict from one exact parent/child rollout pair."""
    if expected_role_name not in ROLE_NAMES:
        raise ValueError(f"unsupported role: {expected_role_name}")
    if not TASK_NAME_RE.fullmatch(expected_task_name):
        raise ValueError(f"invalid task name: {expected_task_name}")
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
        if "missing" in str(exc):
            return _verdict(
                "FAILED",
                "requested_role_not_executed",
                parent_thread_id=parent_id,
                parent_model=parent_model,
                route_observation="requested_role_not_executed",
            )
        return _verdict(
            "FAILED",
            "spawn_call_ambiguous",
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
    if arguments.get("agent_type") != expected_role_name:
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
    if task_name != expected_task_name or not TASK_NAME_RE.fullmatch(str(task_name)):
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


class ReceiptError(ValueError):
    """Raised when a local audit receipt cannot be safely created."""


def _receipt_root(codex_home: Path) -> Path:
    return (codex_home / "dispatch-receipts").resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def prepare_receipt_destination(
    *,
    codex_home: Path,
    role: str,
    receipt: Path | None = None,
    receipt_dir: Path | None = None,
    name: str | None = None,
) -> ReceiptDestination:
    """Validate and create a private receipt destination before live dispatch."""
    if role not in ROLE_NAMES and role != "matrix":
        raise ReceiptError(f"unsupported receipt role: {role}")
    root = _receipt_root(codex_home)
    directory = root if receipt_dir is None else receipt_dir
    if not directory.is_absolute():
        directory = root / directory
    if not _inside(directory, root):
        raise ReceiptError("receipt directory must be under dispatch-receipts")
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    except OSError as exc:
        raise ReceiptError(f"cannot create receipt directory: {exc}") from exc
    if not _inside(directory, root):
        raise ReceiptError("receipt directory resolves outside dispatch-receipts")

    if receipt is not None:
        if receipt.is_absolute():
            target = receipt
        else:
            target = directory / receipt
    else:
        target = directory / (name or f"{task_name_for_role(role)}-{uuid.uuid4().hex}.json")
    if not target.name or target.suffix != ".json":
        raise ReceiptError("receipt name must end in .json")
    if target.parent.resolve() != directory.resolve() or not _inside(target, root):
        raise ReceiptError("receipt must be a direct file under the receipt directory")
    if target.exists():
        raise ReceiptError("receipt already exists")
    return ReceiptDestination(directory=directory.resolve(), receipt_path=target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ReceiptError(f"cannot hash rollout evidence: {exc}") from exc
    return digest.hexdigest()


def _rollout_record(path: Path, sessions_root: Path) -> dict[str, str]:
    try:
        reference = path.resolve().relative_to(sessions_root.resolve()).as_posix()
    except ValueError as exc:
        raise ReceiptError("rollout evidence is outside the session store") from exc
    return {"ref": reference, "sha256": _sha256(path)}


def _optional_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    try:
        return _sha256(path)
    except ReceiptError:
        return None


def _repository_version(repository_root: Path | None) -> str | None:
    if repository_root is None:
        return None
    try:
        version = (repository_root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return version or None


def _codex_version(codex_bin: str | None) -> str | None:
    if not codex_bin:
        return None
    try:
        completed = subprocess.run(
            [codex_bin, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    version = completed.stdout.strip().splitlines()
    return version[0] if version else None


def _observed_child_effort(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        context = _turn_context(load_jsonl(path), required_fields=("model", "effort"))
    except EvidenceError:
        return None
    return context.get("effort") if context is not None else None


def receipt_payload(
    *,
    role: str,
    verdict: Verdict,
    sessions_root: Path,
    evidence: LiveEvidence,
    repository_root: Path | None = None,
    codex_home: Path | None = None,
    codex_bin: str | None = None,
    mode: str = "adapter",
    parent_model: str | None = None,
    expected_namespace: str | None = None,
    task_name: str | None = None,
) -> dict:
    """Build redacted, post-hoc-only receipt data without command transcripts."""
    rollouts: dict[str, dict[str, str]] = {}
    if evidence.parent_rollout is not None:
        rollouts["parent"] = _rollout_record(evidence.parent_rollout, sessions_root)
    if evidence.child_rollout is not None:
        rollouts["child"] = _rollout_record(evidence.child_rollout, sessions_root)

    template_role = (
        repository_root / "templates" / "agents" / f"{role}.toml"
        if repository_root is not None
        else None
    )
    installed_role = (
        codex_home / "agents" / f"{role}.toml"
        if codex_home is not None
        else None
    )
    config = codex_home / "config.toml" if codex_home is not None else None
    template_hash = _optional_sha256(template_role)
    installed_hash = _optional_sha256(installed_role)
    config_hash = _optional_sha256(config)
    started_at = evidence.started_at_utc or datetime.now(timezone.utc).isoformat()
    ended_at = evidence.ended_at_utc or started_at
    observed_codex_version = _codex_version(codex_bin)

    return {
        "schema_version": RECEIPT_VERSION,
        "version": RECEIPT_VERSION,
        "schema": "dispatch-receipt/v1",
        "kind": "dispatch-receipt",
        "timestamps": {
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
        },
        "tool": {
            "repository_version": _repository_version(repository_root),
            "codex_version": observed_codex_version,
        },
        "request": {
            "mode": mode,
            "role": role,
            "task_name": task_name or task_name_for_role(role),
            "parent_model": parent_model,
            "expected_namespace": expected_namespace,
            "fork_turns": "none",
        },
        "preflight": {
            "template_role_sha256": template_hash,
            "installed_role_sha256": installed_hash,
            "config_sha256": config_hash,
            "role_drift": (
                template_hash is not None
                and installed_hash is not None
                and template_hash != installed_hash
            ),
        },
        "observation": {
            "stage": (
                "verified"
                if verdict.status in {"ADAPTER_OK", "NATIVE_OK"}
                else "observed" if evidence.parent_rollout is not None else "preflight"
            ),
            "route_observation": verdict.route_observation,
            "parent_thread_id": verdict.parent_thread_id,
            "child_thread_id": verdict.child_thread_id,
            "parent_model": verdict.parent_model,
            "child_model": verdict.child_model,
            "child_effort": _observed_child_effort(evidence.child_rollout),
            "rollouts": rollouts,
        },
        "verdict": {
            "status": verdict.status,
            "reason": verdict.reason,
            "exit_code": _exit_code(verdict.status),
        },
        # Keep these aliases for consumers of the original receipt shape.
        "role": role,
        "status": verdict.status,
        "reason": verdict.reason,
        "route_observation": verdict.route_observation,
        "rollouts": rollouts,
    }


def write_receipt(destination: ReceiptDestination, payload: dict) -> Path:
    """Atomically publish one mode-0600 receipt without replacing any file."""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".dispatch-receipt-", suffix=".tmp", dir=destination.directory
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination.receipt_path)
        except FileExistsError as exc:
            raise ReceiptError("receipt already exists") from exc
        finally:
            temporary.unlink(missing_ok=True)
        destination.receipt_path.chmod(0o600)
    except ReceiptError:
        raise
    except OSError as exc:
        raise ReceiptError(f"cannot write receipt: {exc}") from exc
    return destination.receipt_path


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
    role: str = "scout",
) -> tuple[RoleBinding | None, Verdict | None]:
    if role not in ROLE_NAMES:
        return None, _verdict("FAILED", "role_preflight_failed", route_observation="not_attempted")
    template_role = repository_root / "templates" / "agents" / f"{role}.toml"
    installed_role = codex_home / "agents" / f"{role}.toml"
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


def _execute_live(
    args: argparse.Namespace, *, role: str, expected: RoleBinding
) -> tuple[Verdict, LiveEvidence]:
    """Run one quota-bearing probe after preflight and receipt validation."""
    print(
        "warning: this live dispatch probe spends real model quota",
        file=sys.stderr,
    )
    command = build_codex_command(
        codex_bin=args.codex_bin,
        cwd=args.repository_root,
        mode=args.mode,
        parent_model=args.parent_model,
        role=role,
        task_name=task_name_for_role(role),
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
    started_at_utc = started_local.astimezone(timezone.utc).isoformat()
    ended_at_utc = ended_local.astimezone(timezone.utc).isoformat()
    if completed.returncode != 0:
        verdict = _with_route_observation(
            classify_exec_failure(stdout=completed.stdout, stderr=completed.stderr),
            "not_observed",
        )
        if verdict.status == "FAILED":
            print(completed.stderr.strip(), file=sys.stderr)
        return verdict, LiveEvidence(
            started_at_utc=started_at_utc,
            ended_at_utc=ended_at_utc,
        )

    sessions_root = args.codex_home / "sessions"
    try:
        parent_id = parse_exec_thread_id(completed.stdout)
        directories = candidate_day_directories(sessions_root, started_local, ended_local)
        utc_directories = candidate_day_directories(
            sessions_root,
            started_local.astimezone(timezone.utc),
            ended_local.astimezone(timezone.utc),
        )
        bounded_directories = list(dict.fromkeys(directories + utc_directories))
        parent_path = locate_rollout(sessions_root, parent_id, bounded_directories)
        parent_events = load_jsonl(parent_path)
    except EvidenceError as exc:
        print(str(exc), file=sys.stderr)
        return _verdict("FAILED", "rollout_evidence_invalid"), LiveEvidence(
            started_at_utc=started_at_utc,
            ended_at_utc=ended_at_utc,
        )

    evidence = LiveEvidence(
        parent_rollout=parent_path,
        started_at_utc=started_at_utc,
        ended_at_utc=ended_at_utc,
    )
    namespace = "agents" if args.mode == "adapter" else "collaboration"
    try:
        child_id = extract_child_thread_id(
            parent_events, expected_task_name=task_name_for_role(role)
        )
    except EvidenceError as exc:
        candidate = inspect_dispatch(
            parent_events,
            [],
            expected_role=expected,
            expected_namespace=namespace,
            expected_role_name=role,
            expected_task_name=task_name_for_role(role),
        )
        if candidate.reason == "requested_role_not_executed":
            return candidate, evidence
        print(str(exc), file=sys.stderr)
        return _verdict("FAILED", "rollout_evidence_invalid"), evidence

    try:
        child_path = locate_rollout(
            sessions_root, child_id, [parent_path.parent, *bounded_directories]
        )
        child_events = load_jsonl(child_path)
    except EvidenceError as exc:
        print(str(exc), file=sys.stderr)
        return _verdict("FAILED", "rollout_evidence_invalid"), evidence

    return (
        inspect_dispatch(
            parent_events,
            child_events,
            expected_role=expected,
            expected_namespace=namespace,
            expected_role_name=role,
            expected_task_name=task_name_for_role(role),
        ),
        LiveEvidence(
            parent_rollout=parent_path,
            child_rollout=child_path,
            started_at_utc=started_at_utc,
            ended_at_utc=ended_at_utc,
        ),
    )


def _live_verify(args: argparse.Namespace) -> Verdict:
    """Compatibility wrapper for callers that need only a single verdict."""
    if args.mode == "native":
        return _verdict("SKIPPED", "native_schema_introspection_unavailable", route_observation="not_attempted")
    expected, preflight_verdict = _preflight(
        codex_bin=args.codex_bin,
        codex_home=args.codex_home,
        repository_root=args.repository_root,
        mode=args.mode,
        parent_model=args.parent_model,
        role=args.role,
    )
    if preflight_verdict is not None:
        return _with_route_observation(preflight_verdict, "not_attempted")
    assert expected is not None
    return _execute_live(args, role=args.role, expected=expected)[0]


def _execute_live_or_preflight(
    args: argparse.Namespace, role: str
) -> tuple[Verdict, LiveEvidence]:
    expected, preflight_verdict = _preflight(
        codex_bin=args.codex_bin,
        codex_home=args.codex_home,
        repository_root=args.repository_root,
        mode=args.mode,
        parent_model=args.parent_model,
        role=role,
    )
    if preflight_verdict is not None:
        return _with_route_observation(preflight_verdict, "not_attempted"), LiveEvidence()
    assert expected is not None
    return _execute_live(args, role=role, expected=expected)


def _write_role_receipt(
    *,
    args: argparse.Namespace,
    role: str,
    verdict: Verdict,
    evidence: LiveEvidence,
    destination: ReceiptDestination,
) -> Verdict:
    try:
        write_receipt(
            destination,
            receipt_payload(
                role=role,
                verdict=verdict,
                sessions_root=args.codex_home / "sessions",
                evidence=evidence,
                repository_root=getattr(args, "repository_root", None),
                codex_home=args.codex_home,
                codex_bin=getattr(args, "codex_bin", None),
                mode=getattr(args, "mode", "adapter"),
                parent_model=getattr(args, "parent_model", None),
                expected_namespace=(
                    "agents" if getattr(args, "mode", "adapter") == "adapter" else "collaboration"
                ),
                task_name=task_name_for_role(role),
            ),
        )
    except ReceiptError as exc:
        print(f"receipt write failed: {exc}", file=sys.stderr)
        if verdict.status == "ADAPTER_OK":
            return _verdict(
                "FAILED",
                "receipt_write_failed",
                route_observation=verdict.route_observation,
            )
    else:
        print(f"receipt: {destination.receipt_path}", file=sys.stderr)
    return verdict


def _matrix_manifest_payload(results: list[tuple[str, Verdict, Path]]) -> dict:
    all_verified = all(verdict.status == "ADAPTER_OK" for _, verdict, _ in results)
    return {
        "version": RECEIPT_VERSION,
        "schema": "dispatch-receipt-matrix/v1",
        "kind": "dispatch-receipt-matrix",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ADAPTER_OK" if all_verified else "FAILED",
        "reason": "matrix_verified_all_roles" if all_verified else "matrix_role_failed",
        "roles": [
            {
                "role": role,
                "status": verdict.status,
                "reason": verdict.reason,
                "route_observation": verdict.route_observation,
                "receipt": path.name,
            }
            for role, verdict, path in results
        ],
    }


def _receipt_destinations(args: argparse.Namespace, roles: tuple[str, ...]) -> dict[str, ReceiptDestination]:
    if args.all_roles and args.receipt is not None:
        raise ReceiptError("--receipt is only valid for a single-role probe")
    return {
        role: prepare_receipt_destination(
            codex_home=args.codex_home,
            role=role,
            receipt=args.receipt if role == args.role and not args.all_roles else None,
            receipt_dir=args.receipt_dir,
        )
        for role in roles
    }


def _run_matrix(
    args: argparse.Namespace,
    destinations: dict[str, ReceiptDestination],
    manifest_destination: ReceiptDestination | None = None,
) -> Verdict:
    """Preflight every role, then probe sequentially and retain a full audit trail."""
    preflight: dict[str, RoleBinding] = {}
    preflight_failures: dict[str, Verdict] = {}
    for role in ROLE_NAMES:
        expected, verdict = _preflight(
            codex_bin=args.codex_bin,
            codex_home=args.codex_home,
            repository_root=args.repository_root,
            mode=args.mode,
            parent_model=args.parent_model,
            role=role,
        )
        if verdict is not None:
            preflight_failures[role] = _with_route_observation(verdict, "not_attempted")
        else:
            assert expected is not None
            preflight[role] = expected

    results: list[tuple[str, Verdict, Path]] = []
    stopped = bool(preflight_failures)
    for role in ROLE_NAMES:
        if role in preflight_failures:
            verdict, evidence = preflight_failures[role], LiveEvidence()
        elif stopped:
            verdict = _verdict(
                "SKIPPED", "matrix_not_attempted", route_observation="not_attempted"
            )
            evidence = LiveEvidence()
        else:
            verdict, evidence = _execute_live(args, role=role, expected=preflight[role])
        verdict = _write_role_receipt(
            args=args,
            role=role,
            verdict=verdict,
            evidence=evidence,
            destination=destinations[role],
        )
        results.append((role, verdict, destinations[role].receipt_path))
        if verdict.status != "ADAPTER_OK":
            stopped = True

    if manifest_destination is None:
        manifest_destination = prepare_receipt_destination(
            codex_home=args.codex_home,
            role="matrix",
            receipt_dir=args.receipt_dir,
            name=f"dispatch-matrix-{uuid.uuid4().hex}.json",
        )
    try:
        write_receipt(manifest_destination, _matrix_manifest_payload(results))
    except ReceiptError as exc:
        print(f"receipt write failed: {exc}", file=sys.stderr)
        return _verdict("FAILED", "receipt_write_failed", route_observation="not_observed")
    print(f"receipt: {manifest_destination.receipt_path}", file=sys.stderr)
    if all(verdict.status == "ADAPTER_OK" for _, verdict, _ in results):
        return _verdict(
            "ADAPTER_OK", "matrix_verified_all_roles", route_observation="typed_child_verified"
        )
    failed = next(verdict for _, verdict, _ in results if verdict.status != "ADAPTER_OK")
    return _verdict(
        "FAILED", "matrix_role_failed", route_observation=failed.route_observation
    )


def main(argv: list[str] | None = None) -> int:
    repository_root = Path(__file__).resolve().parents[1]
    default_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--mode", choices=("adapter", "native"), default="adapter")
    parser.add_argument("--role", choices=ROLE_NAMES, default="scout")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--all-roles", action="store_true")
    parser.add_argument("--matrix-yes", action="store_true")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path, default=default_home)
    parser.add_argument("--repository-root", type=Path, default=repository_root)
    parser.add_argument("--parent-model", default="gpt-5.6-terra")
    args = parser.parse_args(argv)

    if not args.live:
        verdict = _verdict("SKIPPED", "live_flag_required", route_observation="not_attempted")
    elif not args.yes:
        verdict = _verdict("SKIPPED", "operator_opt_in_required", route_observation="not_attempted")
    elif args.mode == "native":
        verdict = _verdict("SKIPPED", "native_schema_introspection_unavailable", route_observation="not_attempted")
    elif args.all_roles and not args.matrix_yes:
        verdict = _verdict("SKIPPED", "matrix_operator_opt_in_required", route_observation="not_attempted")
    else:
        roles = ROLE_NAMES if args.all_roles else (args.role,)
        try:
            destinations = _receipt_destinations(args, roles)
        except ReceiptError as exc:
            print(f"receipt destination failed: {exc}", file=sys.stderr)
            verdict = _verdict("FAILED", "receipt_destination_invalid", route_observation="not_attempted")
        else:
            if args.all_roles:
                try:
                    manifest_destination = prepare_receipt_destination(
                        codex_home=args.codex_home,
                        role="matrix",
                        receipt_dir=args.receipt_dir,
                        name=f"dispatch-matrix-{uuid.uuid4().hex}.json",
                    )
                except ReceiptError as exc:
                    print(f"receipt destination failed: {exc}", file=sys.stderr)
                    verdict = _verdict(
                        "FAILED", "receipt_destination_invalid", route_observation="not_attempted"
                    )
                else:
                    verdict = _run_matrix(args, destinations, manifest_destination)
            else:
                verdict, evidence = _execute_live_or_preflight(args, args.role)
                verdict = _write_role_receipt(
                    args=args,
                    role=args.role,
                    verdict=verdict,
                    evidence=evidence,
                    destination=destinations[args.role],
                )

    _print_verdict(verdict)
    return _exit_code(verdict.status)


if __name__ == "__main__":
    raise SystemExit(main())
