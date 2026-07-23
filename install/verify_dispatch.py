#!/usr/bin/env python3
"""Offline-safe verifier for the native Codex 0.145.0 dispatch contract.

``--live --yes`` is deliberately the only path that invokes Codex.  All normal
helpers validate staged inputs, receipts, and rollout evidence without reading a
real Codex home or spending quota.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install import PINNED_CODEX_VERSION, parse_codex_version
from validate_agents import ROLES, validate_agent
from stage_smoke_home import StageError, explicit_layout_error, project_config_bytes

TASK_NAME = "model_probe"
TASK_NAME_RE = re.compile(r"^[a-z0-9_]+$")
ROLE_NAMES = tuple(sorted(ROLES))
RECEIPT_KEYS = frozenset({
    "status", "reason_code", "phase", "child_created", "codex_version",
    "active_config_sha256", "active_role_manifest_sha256", "active_policy_sha256",
    "target_config_sha256", "target_role_manifest_sha256", "target_policy_sha256",
    "role", "task_name", "fork_turns", "parent_ref", "child_ref", "model",
    "reasoning_effort", "sandbox",
})
MATRIX = {
    ("preflight", "live_flag_required", "SKIPPED"), ("preflight", "operator_opt_in_required", "SKIPPED"),
    ("preflight", "native_schema_introspection_unavailable", "SKIPPED"),
    ("preflight", "version_parse_failed", "SKIPPED"), ("preflight", "version_not_pinned", "FAILED"),
    ("preflight", "auth_unavailable", "SKIPPED"), ("preflight", "smoke_cwd_untrusted", "FAILED"),
    ("preflight", "stage_layout_untrusted", "FAILED"), ("preflight", "external_input_unowned", "FAILED"),
    ("preflight", "role_layer_unapproved", "FAILED"), ("preflight", "role_manifest_extra", "FAILED"),
    ("preflight", "legacy_key_unowned", "FAILED"), ("preflight", "target_hash_mismatch", "FAILED"),
    ("preflight", "snapshot_mutated", "FAILED"), ("preflight", "role_preflight_failed", "FAILED"),
    ("preflight", "installed_role_drift", "FAILED"), ("preflight", "parent_model_not_distinct", "FAILED"),
    ("preflight", "environment_propagation_failed", "FAILED"), ("preflight", "environment_binding_unobservable", "SKIPPED"),
    ("preflight", "environment_binding_mismatch", "FAILED"),
    ("execution-pre-child", "snapshot_mutated", "FAILED"), ("execution-pre-child", "parent_model_unavailable", "SKIPPED"),
    ("execution-pre-child", "codex_exec_failed", "FAILED"),
    ("post-spawn", "parent_model_unavailable_after_spawn", "SKIPPED"), ("post-spawn", "snapshot_mutated", "FAILED"),
    ("post-spawn", "codex_exec_failed_after_spawn", "FAILED"), ("post-spawn", "native_v2_selection_unobservable", "SKIPPED"),
    ("post-spawn", "native_v2_selection_mismatch", "FAILED"), ("post-spawn", "native_spawn_evidence_missing", "SKIPPED"),
    ("post-spawn", "untyped_fallback_detected", "FAILED"), ("dispatch", "policy_violation", "FAILED"),
    ("dispatch", "service_tier_override_forbidden", "FAILED"), ("post-spawn", "parent_child_mismatch", "FAILED"),
    ("post-spawn", "child_evidence_missing", "SKIPPED"), ("post-spawn", "child_binding_unobservable", "SKIPPED"),
    ("post-spawn", "child_binding_mismatch", "FAILED"), ("post-spawn", "child_model_mismatch", "FAILED"),
    ("post-spawn", "child_effort_mismatch", "FAILED"), ("post-spawn", "inherited_parent_model", "FAILED"),
    ("post-spawn", "native_verified", "NATIVE_OK"),
}


class EvidenceError(ValueError):
    pass


class ReceiptError(ValueError):
    pass


@dataclass(frozen=True)
class RoleBinding:
    model: str
    effort: str


@dataclass(frozen=True)
class Verdict:
    status: str
    reason_code: str
    phase: str = "post-spawn"
    child_created: str = "unknown"
    role: str | None = None
    task_name: str | None = None
    fork_turns: str | None = None
    parent_ref: str | None = None
    child_ref: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


def _verdict(status: str, reason_code: str, *, phase: str = "post-spawn", child_created: str = "unknown", **values: str | None) -> Verdict:
    return Verdict(status, reason_code, phase, child_created, **values)


def _short_ref(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:16] if isinstance(value, str) and value else None


def _stat_fingerprint(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable_file_snapshot(
    path: Path,
    home: Path,
) -> tuple[bytes, tuple[int, ...]]:
    try:
        root = home.resolve(strict=True)
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or not resolved.is_relative_to(root)
    ):
        raise ReceiptError("mandatory input escapes its home")
    fd: int | None = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        if _stat_fingerprint(opened) != _stat_fingerprint(before):
            raise ReceiptError("mandatory hash input mutated")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            content = handle.read()
        after_fd = os.fstat(fd)
        after_path = path.lstat()
        if (
            _stat_fingerprint(after_fd) != _stat_fingerprint(before)
            or _stat_fingerprint(after_path) != _stat_fingerprint(before)
        ):
            raise ReceiptError("mandatory hash input mutated")
        return content, _stat_fingerprint(before)
    except OSError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _revalidate_hash_sources(
    snapshots: list[tuple[Path, tuple[int, ...]]],
) -> None:
    for source, expected in snapshots:
        try:
            current = source.lstat()
        except OSError as exc:
            raise ReceiptError("mandatory hash input mutated") from exc
        if _stat_fingerprint(current) != expected:
            raise ReceiptError("mandatory hash input mutated")


def _optional_fingerprint(path: Path) -> tuple[int, ...] | None:
    try:
        return _stat_fingerprint(path.lstat())
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc


def _role_manifest(home: Path) -> tuple[str, list[tuple[Path, bytes]]]:
    try:
        root = home.resolve(strict=True)
        agents = home / "agents"
        agents_before = agents.lstat()
        agents_resolved = agents.resolve(strict=True)
    except OSError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    if (
        stat.S_ISLNK(agents_before.st_mode)
        or not stat.S_ISDIR(agents_before.st_mode)
        or not agents_resolved.is_relative_to(root)
    ):
        raise ReceiptError("mandatory input escapes its home")
    try:
        paths = sorted(agents.rglob("*.toml"))
    except OSError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    if not paths:
        raise ReceiptError("mandatory hash input unavailable")
    directories = {agents}
    for path in paths:
        parent = path.parent
        while True:
            directories.add(parent)
            if parent == agents:
                break
            parent = parent.parent
    directory_snapshots: list[tuple[Path, tuple[int, ...]]] = []
    for directory in sorted(directories):
        try:
            directory_stat = (
                agents_before if directory == agents else directory.lstat()
            )
            directory_resolved = directory.resolve(strict=True)
        except OSError as exc:
            raise ReceiptError("mandatory hash input unavailable") from exc
        if (
            stat.S_ISLNK(directory_stat.st_mode)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or not directory_resolved.is_relative_to(agents_resolved)
        ):
            raise ReceiptError("mandatory input escapes its home")
        directory_snapshots.append(
            (directory, _stat_fingerprint(directory_stat))
        )
    entries: list[tuple[Path, bytes]] = []
    file_snapshots: list[tuple[Path, tuple[int, ...]]] = []
    for path in paths:
        content, fingerprint = _read_stable_file_snapshot(path, home)
        entries.append(
            (
                path.relative_to(agents),
                content,
            )
        )
        file_snapshots.append((path, fingerprint))
    _revalidate_hash_sources(file_snapshots + directory_snapshots)
    try:
        paths_after = sorted(agents.rglob("*.toml"))
    except OSError as exc:
        raise ReceiptError("mandatory hash input mutated") from exc
    if paths_after != paths:
        raise ReceiptError("mandatory hash input mutated")
    digest = hashlib.sha256()
    for relative, content in entries:
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    return digest.hexdigest(), entries


def role_manifest_hash(home: Path) -> str:
    return _role_manifest(home)[0]


def effective_policy(home: Path) -> Path:
    candidates: list[Path] = []
    for name in ("AGENTS.override.md", "AGENTS.md"):
        candidate = home / name
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ReceiptError("effective global policy is unavailable") from exc
        if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISREG(candidate_stat.st_mode):
            raise ReceiptError("effective global policy is unsafe")
        candidates.append(candidate)
    if len(candidates) != 1:
        raise ReceiptError("exactly one effective global policy file is required")
    return candidates[0]


def _validate_role_entries(
    entries: list[tuple[Path, bytes]],
) -> tuple[list[str], list[dict]]:
    problems: list[str] = []
    parsed: list[dict] = []
    seen: set[str] = set()
    for relative, content in entries:
        data = tomllib.loads(content.decode("utf-8"))
        parsed.append(data)
        name = data.get("name")
        if name != relative.stem:
            problems.append(
                f"{relative.name}: name '{name}' does not match filename"
            )
        if isinstance(name, str):
            if name in seen:
                problems.append(
                    f"{relative.name}: duplicate role name '{name}'"
                )
            else:
                seen.add(name)
        problems.extend(
            f"{relative.name}: {message}"
            for message in validate_agent(data)
        )
    missing = ROLES - seen
    extra = seen - ROLES
    if missing:
        problems.append(f"role manifest missing: {', '.join(sorted(missing))}")
    if extra:
        problems.append(f"role manifest extra: {', '.join(sorted(extra))}")
    return problems, parsed


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def validate_home_pair(active: Path, staged: Path) -> tuple[Path, Path]:
    if not active.is_absolute() or not staged.is_absolute():
        raise ReceiptError("homes must be absolute")
    try:
        left, right = active.resolve(strict=True), staged.resolve(strict=True)
    except OSError as exc:
        raise ReceiptError("homes must exist and be readable") from exc
    if not left.is_dir() or not right.is_dir() or not os.access(left, os.R_OK | os.X_OK) or not os.access(right, os.R_OK | os.X_OK):
        raise ReceiptError("homes must be readable directories")
    try:
        left.relative_to(right)
    except ValueError:
        pass
    else:
        raise ReceiptError("homes must be distinct and non-nested")
    try:
        right.relative_to(left)
    except ValueError:
        pass
    else:
        raise ReceiptError("homes must be distinct and non-nested")
    return left, right


def _path_value(value: object) -> bool:
    return isinstance(value, str) and bool(re.match(r"(?:/|~/|\./|\.\./|\$\{(?:HOME|CODEX_HOME)\}|[A-Za-z]:\\\\|\\\\\\\\|[A-Za-z][A-Za-z0-9+.-]*://)", value))


def _external_inputs(value: object, keys: tuple[str, ...] = ()) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            segment = str(key).lower()
            path_key = segment in {"path", "file", "dir", "directory", "command", "executable", "cwd"} or segment.endswith("_path")
            if path_key and ((segment in {"command", "executable"} and bool(child)) or _path_value(child)):
                return True
            if _external_inputs(child, keys + (segment,)):
                return True
    elif isinstance(value, list):
        return any(_external_inputs(item, keys) for item in value)
    return _path_value(value) and any(key in {"path", "file", "dir", "directory", "command", "executable", "cwd"} or key.endswith("_path") for key in keys)


def validate_stage_layout(home: Path, *, active_home: bool = False) -> str | None:
    """Validate staged layout or the explicit active-home input projection."""
    try:
        root = home.resolve(strict=True)
        if explicit_layout_error(
            root,
            allow_rollback_backups=active_home,
            project_active_root=active_home,
        ):
            return "stage_layout_untrusted"
        policy_candidates = [
            home / "AGENTS.override.md",
            home / "AGENTS.md",
        ]
        policy_projection = [
            (candidate, _optional_fingerprint(candidate))
            for candidate in policy_candidates
        ]
        policy = effective_policy(home)
        config_path = home / "config.toml"
        config_content, config_fingerprint = _read_stable_file_snapshot(
            config_path,
            root,
        )
        _, policy_fingerprint = _read_stable_file_snapshot(policy, root)
        config = tomllib.loads(config_content.decode("utf-8"))
        features = config.get("features", {})
        agents_config = config.get("agents", {})
        v2 = features.get("multi_agent_v2", {}) if isinstance(features, dict) else {}
        if (isinstance(features, dict) and features.get("multi_agent") is not None) or (isinstance(v2, dict) and any(key in v2 for key in ("tool_namespace", "hide_spawn_agent_metadata"))) or (isinstance(agents_config, dict) and any(key in agents_config for key in ("max_threads", "max_concurrent_threads_per_session"))):
            return "legacy_key_unowned"
        if isinstance(agents_config, dict) and set(agents_config) - {"max_depth"}:
            return "role_layer_unapproved"
        if active_home:
            project_config_bytes(config_content)
        else:
            for forbidden in ("notify", "mcp_servers", "plugins", "skills", "marketplace", "marketplaces", "model_providers", "projects", "project_root_markers", "experimental_compact_prompt_file", "log_dir", "sqlite_home"):
                if forbidden in config and _external_inputs({forbidden: config[forbidden]}):
                    return "external_input_unowned"
            if _external_inputs(config):
                return "external_input_unowned"
            project_config_bytes(config_content)
        _, manifest_entries = _role_manifest(root)
        problems, role_configs = _validate_role_entries(manifest_entries)
        if any(_external_inputs(role_config) for role_config in role_configs):
            return "external_input_unowned"
        if any("extra" in problem for problem in problems):
            return "role_manifest_extra"
        if problems:
            return "role_preflight_failed"
        _revalidate_hash_sources(
            [
                (config_path, config_fingerprint),
                (policy, policy_fingerprint),
            ]
        )
        if any(
            _optional_fingerprint(candidate) != expected
            for candidate, expected in policy_projection
        ):
            return "stage_layout_untrusted"
    except (
        OSError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        ReceiptError,
        StageError,
    ):
        return "stage_layout_untrusted"
    return None


def hash_inputs(home: Path) -> dict[str, str]:
    config = home / "config.toml"
    policy_candidates = [
        home / "AGENTS.override.md",
        home / "AGENTS.md",
    ]
    policy_projection = [
        (candidate, _optional_fingerprint(candidate))
        for candidate in policy_candidates
    ]
    policy = effective_policy(home)
    config_content, config_fingerprint = _read_stable_file_snapshot(config, home)
    policy_content, policy_fingerprint = _read_stable_file_snapshot(policy, home)
    try:
        config_projection = project_config_bytes(config_content)
    except StageError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    manifest_hash, manifest_entries = _role_manifest(home)
    _revalidate_hash_sources(
        [
            (config, config_fingerprint),
            (policy, policy_fingerprint),
        ]
    )
    if any(
        _optional_fingerprint(candidate) != expected
        for candidate, expected in policy_projection
    ):
        raise ReceiptError("mandatory hash input mutated")
    names: list[object] = []
    try:
        for relative, content in manifest_entries:
            name = tomllib.loads(content.decode("utf-8")).get("name")
            if name != relative.stem:
                raise ReceiptError("mandatory hash input unavailable")
            names.append(name)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    if len(names) != len(ROLES) or set(names) != ROLES:
        raise ReceiptError("mandatory hash input unavailable")
    return {
        "config": hashlib.sha256(config_projection).hexdigest(),
        "role_manifest": manifest_hash,
        "policy": hashlib.sha256(policy_content).hexdigest(),
    }


def snapshot_inputs(home: Path) -> dict[str, str]:
    return hash_inputs(home)


def snapshot_changed(home: Path, snapshot: dict[str, str]) -> bool:
    return hash_inputs(home) != snapshot


def read_role_binding(path: Path) -> RoleBinding:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvidenceError(f"invalid role TOML: {path}") from exc
    model, effort = data.get("model"), data.get("model_reasoning_effort")
    if not isinstance(model, str) or not model or not isinstance(effort, str) or not effort:
        raise EvidenceError(f"role binding is incomplete: {path}")
    return RoleBinding(model, effort)


def task_name_for_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"unsupported role: {role}")
    return f"{TASK_NAME}_{role.replace('-', '_')}"


def build_codex_command(*, codex_bin: str, cwd: Path, parent_model: str, role: str = "scout", task_name: str | None = None) -> list[str]:
    task = task_name or task_name_for_role(role)
    if role not in ROLES or not TASK_NAME_RE.fullmatch(task):
        raise ValueError("invalid role or task name")
    prompt = (
        "Call spawn_agent exactly once with message='Do not run commands. Reply only READY.', "
        f"agent_type='{role}', task_name='{task}', fork_turns='none'. "
        "Then call wait_agent exactly once with timeout_ms=30000 so the child "
        "can complete. Do not use an untyped fallback, a second spawn, or any "
        "child override."
    )
    return [
        codex_bin,
        "exec",
        "--json",
        "--strict-config",
        "--skip-git-repo-check",
        "-C",
        str(cwd),
        "-m",
        parent_model,
        "-c",
        'model_reasoning_effort="low"',
        "-s",
        "read-only",
        prompt,
    ]


def _payloads(events: Iterable[dict], kind: str) -> list[dict]:
    return [event["payload"] for event in events if isinstance(event, dict) and event.get("type") == kind and isinstance(event.get("payload"), dict)]


def _events_valid(events: Iterable[object], kinds: set[str]) -> bool:
    return all(isinstance(event, dict) and (event.get("type") not in kinds or isinstance(event.get("payload"), dict)) for event in events)


def inspect_dispatch(parent_events: list[dict], child_events: list[dict], *, expected_role: RoleBinding, expected_role_name: str = "scout", expected_task_name: str | None = None) -> Verdict:
    """Classify native evidence without using an adapter namespace predicate."""
    task = expected_task_name or task_name_for_role(expected_role_name)
    if not _events_valid(parent_events, {"session_meta", "turn_context", "response_item", "event_msg"}):
        return _verdict("FAILED", "policy_violation", phase="dispatch")
    parent_contexts = _payloads(parent_events, "turn_context")
    raw_versions = [ctx.get("multi_agent_version") for ctx in parent_contexts if "multi_agent_version" in ctx]
    if any(not isinstance(version, str) for version in raw_versions):
        return _verdict("FAILED", "native_v2_selection_mismatch", child_created="unknown")
    versions = set(raw_versions)
    function_calls = [
        (index, event["payload"])
        for index, event in enumerate(parent_events)
        if isinstance(event, dict)
        and event.get("type") == "response_item"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("type") == "function_call"
    ]
    calls = [
        (index, payload)
        for index, payload in function_calls
        if payload.get("name") == "spawn_agent"
    ]
    waits = [
        (index, payload)
        for index, payload in function_calls
        if payload.get("name") == "wait_agent"
    ]
    untyped = [p for p in _payloads(parent_events, "response_item") if p.get("type") == "function_call" and p.get("name") != "spawn_agent" and "spawn" in str(p.get("name", ""))]
    activities = [p for p in _payloads(parent_events, "event_msg") if p.get("type") == "sub_agent_activity" and p.get("kind") == "started"]
    created = "yes" if activities else "unknown"
    if untyped:
        return _verdict("FAILED", "untyped_fallback_detected", child_created=created)
    if len(calls) > 1:
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    if not calls:
        return _verdict("SKIPPED", "native_spawn_evidence_missing", child_created=created)
    call_index, call = calls[0]
    try:
        args = json.loads(call.get("arguments", ""))
    except (TypeError, json.JSONDecodeError):
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    if not isinstance(args, dict):
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    if "service_tier" in args:
        return _verdict("FAILED", "service_tier_override_forbidden", phase="dispatch", child_created=created)
    allowed = {"message", "agent_type", "task_name", "fork_turns"}
    if set(args) != allowed or not isinstance(args.get("message"), str) or not args["message"].strip() or args.get("agent_type") != expected_role_name or args.get("task_name") != task or not TASK_NAME_RE.fullmatch(str(args.get("task_name"))) or args.get("fork_turns") not in {"none", "1", "2", "3"}:
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    if len(waits) != 1:
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    wait_index, wait_call = waits[0]
    try:
        wait_args = json.loads(wait_call.get("arguments", ""))
    except (TypeError, json.JSONDecodeError):
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    if wait_index <= call_index or wait_args != {"timeout_ms": 30000}:
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    call_id = call.get("call_id")
    matched = [a for a in activities if a.get("event_id") == call_id]
    if not isinstance(call_id, str) or not call_id or len(matched) != 1:
        return _verdict("SKIPPED", "native_spawn_evidence_missing", child_created=created)
    if not versions:
        return _verdict("SKIPPED", "native_v2_selection_unobservable", child_created="yes")
    if versions != {"v2"}:
        return _verdict("FAILED", "native_v2_selection_mismatch", child_created="yes")
    child_id = matched[0].get("agent_thread_id")
    parent_id = next((p.get("id") for p in _payloads(parent_events, "session_meta") if isinstance(p.get("id"), str)), None)
    contexts = _payloads(child_events, "turn_context")
    sessions = _payloads(child_events, "session_meta")
    if not contexts or not sessions:
        return _verdict("SKIPPED", "child_evidence_missing", child_created="yes")
    context = contexts[0]
    model, effort = context.get("model"), context.get("effort")
    if not isinstance(model, str) or not model or not isinstance(effort, str) or not effort:
        return _verdict("SKIPPED", "child_binding_unobservable", child_created="yes")
    session = sessions[0]
    if session.get("id") != child_id or session.get("parent_thread_id") != parent_id:
        return _verdict("FAILED", "parent_child_mismatch", child_created="yes")
    if model != expected_role.model:
        return _verdict("FAILED", "child_model_mismatch", child_created="yes")
    if effort != expected_role.effort:
        return _verdict("FAILED", "child_effort_mismatch", child_created="yes")
    parent_model = parent_contexts[0].get("model") if parent_contexts else None
    if model == parent_model:
        return _verdict("FAILED", "inherited_parent_model", child_created="yes")
    return _verdict("NATIVE_OK", "native_verified", child_created="yes", role=expected_role_name, task_name=task, fork_turns=args["fork_turns"], parent_ref=_short_ref(parent_id), child_ref=_short_ref(child_id), model=model, reasoning_effort=effort)


def load_jsonl(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: event = json.loads(line)
        except json.JSONDecodeError as exc: raise EvidenceError("invalid JSON rollout") from exc
        if not isinstance(event, dict): raise EvidenceError("rollout event is not an object")
        events.append(event)
    if not events: raise EvidenceError("rollout is empty")
    return events


def parse_exec_thread_id(output: str) -> str:
    values = set()
    for line in output.splitlines():
        if not line.strip(): continue
        try: event = json.loads(line)
        except json.JSONDecodeError as exc: raise EvidenceError("exec output is not JSON") from exc
        if not isinstance(event, dict): raise EvidenceError("exec event is not an object")
        if event.get("type") == "thread.started":
            value = event.get("thread_id") or (event.get("thread") or {}).get("id")
            if isinstance(value, str) and value: values.add(value)
    if len(values) != 1: raise EvidenceError("expected one parent thread ID")
    return values.pop()


def locate_rollout(sessions_root: Path, thread_id: str) -> Path:
    """Find one exact thread-suffixed rollout during the explicit live smoke."""
    try:
        root = sessions_root.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError("session store is unavailable") from exc
    suffix = f"-{thread_id}.jsonl"
    matches = [
        path.resolve() for path in root.rglob("*.jsonl")
        if path.name.endswith(suffix) and path.is_file() and _inside(path, root)
    ]
    if len(matches) != 1:
        raise EvidenceError("expected one exact rollout")
    return matches[0]


def child_thread_from_parent(events: list[dict]) -> str:
    calls = [p for p in _payloads(events, "response_item") if p.get("type") == "function_call" and p.get("name") == "spawn_agent"]
    if len(calls) != 1 or not isinstance(calls[0].get("call_id"), str):
        raise EvidenceError("typed spawn is unobservable")
    activities = [p for p in _payloads(events, "event_msg") if p.get("type") == "sub_agent_activity" and p.get("kind") == "started" and p.get("event_id") == calls[0]["call_id"]]
    if len(activities) != 1 or not isinstance(activities[0].get("agent_thread_id"), str):
        raise EvidenceError("child activity is unobservable")
    return activities[0]["agent_thread_id"]


def inspect_available_evidence(home: Path, stdout: str, binding: RoleBinding, role: str) -> tuple[Verdict | None, bool]:
    """Inspect bounded rollout evidence and retain the spawn-attempt boundary."""
    try:
        parent_id = parse_exec_thread_id(stdout)
        parent_events = load_jsonl(locate_rollout(home / "sessions", parent_id))
        boundary = any(p.get("type") == "function_call" and p.get("name") == "spawn_agent" for p in _payloads(parent_events, "response_item"))
        try:
            child_id = child_thread_from_parent(parent_events)
            child_events = load_jsonl(locate_rollout(home / "sessions", child_id))
        except EvidenceError:
            child_events = []
        return inspect_dispatch(parent_events, child_events, expected_role=binding, expected_role_name=role), boundary
    except EvidenceError:
        return None, False


def receipt_payload(verdict: Verdict, *, codex_version: str, active: dict[str, str], target: dict[str, str]) -> dict:
    payload = {
        "status": verdict.status, "reason_code": verdict.reason_code, "phase": verdict.phase,
        "child_created": verdict.child_created, "codex_version": codex_version,
        "active_config_sha256": active["config"], "active_role_manifest_sha256": active["role_manifest"], "active_policy_sha256": active["policy"],
        "target_config_sha256": target["config"], "target_role_manifest_sha256": target["role_manifest"], "target_policy_sha256": target["policy"],
    }
    for key in ("role", "task_name", "fork_turns", "parent_ref", "child_ref", "model", "reasoning_effort"):
        value = getattr(verdict, key)
        if value is not None: payload[key] = value
    validate_receipt(payload)
    return payload


def validate_receipt(payload: dict) -> None:
    required = {"status", "reason_code", "phase", "child_created", "codex_version",
                "active_config_sha256", "active_role_manifest_sha256", "active_policy_sha256",
                "target_config_sha256", "target_role_manifest_sha256", "target_policy_sha256"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - RECEIPT_KEYS:
        raise ReceiptError("receipt keys are invalid")
    if (payload["phase"], payload["reason_code"], payload["status"]) not in MATRIX:
        raise ReceiptError("receipt reason matrix row is invalid")
    if payload["child_created"] not in {"no", "yes", "unknown"}:
        raise ReceiptError("receipt child_created is invalid")
    version = payload["codex_version"]
    if version != "unknown" and not re.fullmatch(r"\d+\.\d+\.\d+", str(version)):
        raise ReceiptError("receipt version is invalid")
    hashes = [key for key in required if key.endswith("sha256")]
    if any(not isinstance(payload[key], str) or not re.fullmatch(r"[0-9a-f]{64}", payload[key]) for key in hashes):
        raise ReceiptError("receipt hashes are invalid")
    evidence = {"role", "task_name", "fork_turns", "parent_ref", "child_ref", "model", "reasoning_effort", "sandbox"}
    if payload["phase"] in {"preflight", "execution-pre-child"} and evidence & set(payload):
        raise ReceiptError("pre-child receipt contains observed child evidence")
    if payload["phase"] == "preflight" and payload["child_created"] != "no":
        raise ReceiptError("preflight receipt child state is invalid")
    allowed_children = {
        "preflight": {"no"}, "execution-pre-child": {"no", "unknown"},
        "post-spawn": {"yes", "unknown"}, "dispatch": {"yes", "unknown"},
    }
    if payload["child_created"] not in allowed_children[payload["phase"]]:
        raise ReceiptError("receipt phase/child state is impossible")
    if payload["reason_code"] == "child_evidence_missing" and payload["child_created"] == "no":
        raise ReceiptError("child evidence row has impossible child state")
    if payload["phase"] == "dispatch" and payload["child_created"] == "no":
        raise ReceiptError("dispatch receipt child state is invalid")
    if payload["phase"] == "execution-pre-child" and payload["reason_code"] == "codex_exec_failed" and payload["child_created"] == "yes":
        raise ReceiptError("pre-child execution failure cannot claim a child")
    child_bound_reasons = {"parent_child_mismatch", "child_binding_unobservable", "child_binding_mismatch", "child_model_mismatch", "child_effort_mismatch", "inherited_parent_model", "native_verified"}
    if payload["reason_code"] in child_bound_reasons and payload["child_created"] != "yes":
        raise ReceiptError("child-bound receipt lacks observed child")
    if payload["status"] == "NATIVE_OK" and (payload["codex_version"] != "0.145.0" or payload["active_config_sha256"] != payload["target_config_sha256"] or payload["active_role_manifest_sha256"] != payload["target_role_manifest_sha256"] or payload["active_policy_sha256"] != payload["target_policy_sha256"]):
        raise ReceiptError("NATIVE_OK receipt has invalid version or hash equality")
    if "role" in payload and (not isinstance(payload["role"], str) or payload["role"] not in ROLES):
        raise ReceiptError("role evidence is invalid")
    if "task_name" in payload and (not isinstance(payload["task_name"], str) or not TASK_NAME_RE.fullmatch(payload["task_name"])):
        raise ReceiptError("task evidence is invalid")
    if "fork_turns" in payload and (not isinstance(payload["fork_turns"], str) or payload["fork_turns"] not in {"none", "1", "2", "3"}):
        raise ReceiptError("fork evidence is invalid")
    for field in ("model", "reasoning_effort"):
        if field in payload and (not isinstance(payload[field], str) or not payload[field].strip()):
            raise ReceiptError("model evidence is invalid")
    if "sandbox" in payload and not isinstance(payload["sandbox"], (str, dict)):
        raise ReceiptError("sandbox evidence is invalid")
    if "sandbox" in payload and not payload["sandbox"]:
        raise ReceiptError("sandbox must be observed")
    for ref in ("parent_ref", "child_ref"):
        if ref in payload and (not isinstance(payload[ref], str) or not payload[ref] or not re.fullmatch(r"[0-9a-f]{16}", payload[ref])):
            raise ReceiptError("receipt reference leaks runtime data")
    for key, value in payload.items():
        if key in {"parent_ref", "child_ref"}:
            continue
        if isinstance(value, str) and ("/" in value or "\\" in value or "secret" in value.lower()):
            raise ReceiptError("receipt contains path or secret data")
    if payload["status"] == "NATIVE_OK":
        needed = {"role", "task_name", "fork_turns", "parent_ref", "child_ref", "model", "reasoning_effort"}
        if payload["phase"] != "post-spawn" or payload["child_created"] != "yes" or not needed <= set(payload) or payload["role"] not in ROLES or not TASK_NAME_RE.fullmatch(str(payload["task_name"])) or payload["fork_turns"] not in {"none", "1", "2", "3"} or not isinstance(payload["model"], str) or not payload["model"].strip() or not isinstance(payload["reasoning_effort"], str) or not payload["reasoning_effort"].strip():
            raise ReceiptError("NATIVE_OK receipt lacks core evidence")


def receipt_destination(home: Path, requested: Path | None, role: str) -> Path:
    root = home / "dispatch-receipts"
    path = root / f"{task_name_for_role(role)}.json" if requested is None else requested
    if not path.is_absolute():
        path = root / path
    try:
        path.parent.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ReceiptError("receipt_destination_invalid") from exc
    if path.suffix != ".json" or path.name == ".json" or path.exists():
        raise ReceiptError("receipt_destination_invalid")
    return path


def write_receipt(path: Path, payload: dict) -> None:
    validate_receipt(payload)
    if path.exists() or path.suffix != ".json": raise ReceiptError("receipt destination already exists or is invalid")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    temp = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":")); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.link(temp, path)
    except OSError as exc:
        raise ReceiptError("receipt_write_failed") from exc
    finally:
        temp.unlink(missing_ok=True)


def _clean_cwd(cwd: Path, repository_root: Path, markers: list[str]) -> bool:
    try:
        cwd_real, repo_real = cwd.resolve(strict=True), repository_root.resolve(strict=True)
    except OSError: return False
    try: cwd_real.relative_to(repo_real); return False
    except ValueError: pass
    current = cwd_real
    while True:
        if any((current / name).exists() for name in ("AGENTS.md", "AGENTS.override.md", ".codex", *markers)): return False
        if current == current.parent: return True
        current = current.parent


def _preflight(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, str], RoleBinding] | Verdict:
    try:
        active_home, staged_home = validate_home_pair(args.active_codex_home, args.codex_home)
        reason = validate_stage_layout(active_home, active_home=True)
        if reason: return _verdict("FAILED", reason, phase="preflight", child_created="no")
        active_hash = hash_inputs(active_home)
        reason = validate_stage_layout(staged_home)
        if reason: return _verdict("FAILED", reason, phase="preflight", child_created="no")
        target_hash = hash_inputs(staged_home)
    except ReceiptError:
        raise
    if active_hash != target_hash:
        return _verdict("FAILED", "target_hash_mismatch", phase="preflight", child_created="no")
    for role in ROLES:
        installed = staged_home / "agents" / f"{role}.toml"
        packaged = args.repository_root / "templates" / "agents" / f"{role}.toml"
        if not installed.is_file() or not packaged.is_file() or installed.read_bytes() != packaged.read_bytes():
            return _verdict("FAILED", "installed_role_drift", phase="preflight", child_created="no")
    try:
        with (staged_home / "config.toml").open("rb") as handle:
            marker_config = tomllib.load(handle).get("project_root_markers", [".git"])
    except (OSError, tomllib.TOMLDecodeError):
        return _verdict("FAILED", "stage_layout_untrusted", phase="preflight", child_created="no")
    if not isinstance(marker_config, list) or not all(isinstance(marker, str) for marker in marker_config):
        return _verdict("FAILED", "stage_layout_untrusted", phase="preflight", child_created="no")
    if not _clean_cwd(args.codex_cwd, args.repository_root, marker_config):
        return _verdict("FAILED", "smoke_cwd_untrusted", phase="preflight", child_created="no")
    role_path = staged_home / "agents" / f"{args.role}.toml"
    binding = read_role_binding(role_path)
    if binding.model == args.parent_model:
        return _verdict("FAILED", "parent_model_not_distinct", phase="preflight", child_created="no")
    return active_hash, target_hash, binding


def _print(verdict: Verdict) -> None:
    print(f"{verdict.status} reason_code={verdict.reason_code} phase={verdict.phase} child_created={verdict.child_created}")


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--all-roles" or arg == "--mode" or arg.startswith("--mode=") for arg in raw):
        print("cli_input_invalid", file=sys.stderr); return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true"); parser.add_argument("--yes", action="store_true")
    parser.add_argument("--role", choices=ROLE_NAMES, default="scout")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--active-codex-home", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-cwd", type=Path, required=True)
    parser.add_argument("--parent-model", default="gpt-5.6-terra")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--launch-capture", type=Path)
    args = parser.parse_args(raw)
    if not args.live:
        _print(_verdict("SKIPPED", "live_flag_required", phase="preflight", child_created="no")); return 2
    if not args.yes:
        _print(_verdict("SKIPPED", "operator_opt_in_required", phase="preflight", child_created="no")); return 2
    try:
        destination = receipt_destination(args.codex_home, args.receipt, args.role)
    except ReceiptError:
        print("receipt_destination_invalid", file=sys.stderr); return 1
    try:
        preflight = _preflight(args)
    except ReceiptError as exc:
        print("home_input_invalid" if "home" in str(exc) else "hash_input_unavailable", file=sys.stderr); return 1
    if isinstance(preflight, Verdict):
        _print(preflight); return 1 if preflight.status == "FAILED" else 2
    active_hash, target_hash, binding = preflight
    if args.launch_capture is None:
        verdict = _verdict("SKIPPED", "environment_binding_unobservable", phase="preflight", child_created="no")
        try:
            write_receipt(destination, receipt_payload(verdict, codex_version="unknown", active=active_hash, target=target_hash))
        except ReceiptError:
            print("receipt_write_failed", file=sys.stderr); return 1
        _print(verdict); return 2
    try:
        capture = json.loads(args.launch_capture.read_text(encoding="utf-8"))
        expected = {"CODEX_HOME": str(args.codex_home), "CODEX_SQLITE_HOME": str(args.codex_home), "codex_cwd": str(args.codex_cwd)}
        if not isinstance(capture, dict) or any(capture.get(key) != value for key, value in expected.items()):
            verdict = _verdict("FAILED", "environment_binding_mismatch", phase="preflight", child_created="no")
            write_receipt(destination, receipt_payload(verdict, codex_version="unknown", active=active_hash, target=target_hash))
            _print(verdict); return 1
    except (OSError, json.JSONDecodeError, ReceiptError):
        print("environment_binding_unobservable", file=sys.stderr); return 2
    try:
        version_run = subprocess.run([args.codex_bin, "--version"], capture_output=True, text=True, check=False)
        token = parse_codex_version(version_run.stdout + version_run.stderr) if version_run.returncode == 0 else None
    except OSError:
        token = None
    if token is None:
        verdict = _verdict("SKIPPED", "version_parse_failed", phase="preflight", child_created="no")
    elif token != PINNED_CODEX_VERSION:
        verdict = _verdict("FAILED", "version_not_pinned", phase="preflight", child_created="no")
    else:
        try:
            login = subprocess.run([args.codex_bin, "login", "status"], capture_output=True, text=True, check=False)
        except OSError:
            login = None
        if login is None or login.returncode != 0:
            verdict = _verdict("SKIPPED", "auth_unavailable", phase="preflight", child_created="no")
        else:
            env = {"CODEX_HOME": str(args.codex_home), "CODEX_SQLITE_HOME": str(args.codex_home), **{k: v for k, v in os.environ.items() if k not in {"CODEX_HOME", "CODEX_SQLITE_HOME"}}}
            if env.get("CODEX_HOME") != str(args.codex_home) or env.get("CODEX_SQLITE_HOME") != str(args.codex_home):
                verdict = _verdict("FAILED", "environment_propagation_failed", phase="preflight", child_created="no")
                payload = receipt_payload(verdict, codex_version="0.145.0", active=active_hash, target=target_hash)
                write_receipt(destination, payload)
                _print(verdict)
                return 1
            command = build_codex_command(codex_bin=args.codex_bin, cwd=args.codex_cwd, parent_model=args.parent_model, role=args.role)
            before = snapshot_inputs(args.codex_home)
            completed = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, check=False)
            changed = snapshot_changed(args.codex_home, before)
            observed, spawn_boundary = inspect_available_evidence(args.codex_home, completed.stdout, binding, args.role)
            if completed.returncode:
                if spawn_boundary:
                    child_state = observed.child_created if observed is not None else "unknown"
                    verdict = _verdict("FAILED", "codex_exec_failed_after_spawn", phase="post-spawn", child_created=child_state)
                else:
                    child_state = observed.child_created if observed is not None else "unknown"
                    verdict = _verdict("FAILED", "codex_exec_failed", phase="execution-pre-child", child_created=child_state)
            else:
                verdict = observed or _verdict("SKIPPED", "native_spawn_evidence_missing", child_created="unknown")
            if changed:
                phase = "post-spawn" if spawn_boundary else "execution-pre-child"
                verdict = _verdict("FAILED", "snapshot_mutated", phase=phase, child_created=verdict.child_created)
    version_text = ".".join(map(str, token)) if token else "unknown"
    try:
        payload = receipt_payload(verdict, codex_version=version_text, active=active_hash, target=target_hash)
        write_receipt(destination, payload)
    except ReceiptError:
        print("receipt_write_failed", file=sys.stderr); return 1
    _print(verdict)
    return 0 if verdict.status == "NATIVE_OK" else 2 if verdict.status == "SKIPPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
