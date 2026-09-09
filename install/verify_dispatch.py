#!/usr/bin/env python3
"""Offline-safe verifier for the native Codex dispatch contract.

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
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install import codex_version_token, parse_codex_version
from validate_agents import ROLES, validate_agent
from stage_smoke_home import (
    StageError,
    _active_hook_state,
    _read_proven_policy_symlink,
    _state_policy_digest,
    explicit_layout_error,
    project_config_bytes,
)
from routing_contract import (
    UNKNOWN_MODEL,
    UNKNOWN_SNAPSHOT,
    build_routing_context,
    validate_routing_context,
)

TASK_NAME = "model_probe"
TASK_NAME_RE = re.compile(r"^[a-z0-9_]+$")
ROLE_NAMES = tuple(sorted(ROLES))
AUTO_ROUTE_PROMPT = (
    "Read the material, cross-service production database schema migration Plan in "
    "PLAN.md and determine whether it is ready for user approval. Do not "
    "implement, modify files, or contact external systems. Return a concise "
    "approval recommendation and every P0-P2 blocker you find."
)
AUTO_ROUTE_DIRECTIVE_TOKENS = ("spawn", "delegate", "subagent")
AUTO_ROUTE_PARENT_MODEL = "gpt-5.6-luna"
AUTO_ROUTE_PARENT_EFFORT = "medium"
NATIVE_MULTI_AGENT_FEATURE = "multi_agent_v2"
CORRELATION_MODES = frozenset({"spawn_activity", "session_metadata"})
RECEIPT_KEYS = frozenset({
    "status", "reason_code", "phase", "child_created", "codex_version",
    "active_config_sha256", "active_role_manifest_sha256", "active_policy_sha256",
    "target_config_sha256", "target_role_manifest_sha256", "target_policy_sha256",
    "role", "task_name", "fork_turns", "parent_ref", "child_ref", "model",
    "reasoning_effort", "sandbox", "correlation_mode", "routing", "platform_halt",
})
MATRIX = {
    ("preflight", "live_flag_required", "SKIPPED"), ("preflight", "operator_opt_in_required", "SKIPPED"),
    ("preflight", "native_schema_introspection_unavailable", "SKIPPED"),
    ("preflight", "version_parse_failed", "SKIPPED"),
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
    ("execution-pre-child", "platform_halt", "SKIPPED"),
    ("post-spawn", "parent_model_unavailable_after_spawn", "SKIPPED"), ("post-spawn", "snapshot_mutated", "FAILED"),
    ("post-spawn", "codex_exec_failed_after_spawn", "FAILED"), ("post-spawn", "native_v2_selection_unobservable", "SKIPPED"),
    ("post-spawn", "native_v2_selection_mismatch", "FAILED"), ("post-spawn", "native_spawn_evidence_missing", "SKIPPED"),
    ("post-spawn", "autoroute_prompt_missing", "FAILED"), ("post-spawn", "autoroute_prompt_directive_detected", "FAILED"),
    ("post-spawn", "autoroute_plan_verifier_missing", "FAILED"),
    ("post-spawn", "platform_halt", "SKIPPED"),
    ("post-spawn", "policy_violation", "FAILED"),
    ("post-spawn", "untyped_fallback_detected", "FAILED"), ("dispatch", "policy_violation", "FAILED"),
    ("dispatch", "platform_halt", "SKIPPED"),
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


PLATFORM_HALT_EVENT_TYPES = frozenset({"safety_check_failed", "platform_halt"})


def platform_halt_detected(*outputs: str) -> bool:
    """Recognize only structured platform-stop events from Codex output."""
    for output in outputs:
        if not isinstance(output, str):
            continue
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
            event_type = payload.get("type")
            if event_type in PLATFORM_HALT_EVENT_TYPES:
                return True
            if (
                event_type in {"task_stopped", "turn_aborted"}
                and payload.get("reason") in {"safety_check", "platform_safety"}
            ):
                return True
            if payload.get("status") == "platform_halt" and payload.get("reason") == "safety_check":
                return True
    return False


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
    correlation_mode: str | None = None
    platform_halt: str = "none"


def _verdict(status: str, reason_code: str, *, phase: str = "post-spawn", child_created: str = "unknown", **values: str | None) -> Verdict:
    return Verdict(status, reason_code, phase, child_created, **values)


def _platform_halt_verdict(*, phase: str, observed: Verdict | None) -> Verdict:
    """Preserve observed binding metadata while classifying a platform stop."""
    values: dict[str, str | None] = {}
    if observed is not None:
        for field in (
            "role",
            "task_name",
            "fork_turns",
            "parent_ref",
            "child_ref",
            "model",
            "reasoning_effort",
            "correlation_mode",
        ):
            value = getattr(observed, field, None)
            if value is not None:
                values[field] = value
    return _verdict(
        "SKIPPED",
        "platform_halt",
        phase=phase,
        child_created=observed.child_created if observed is not None else "unknown",
        platform_halt="capability_gap",
        **values,
    )


def _short_ref(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:16] if isinstance(value, str) and value else None


def _stat_fingerprint(value: os.stat_result) -> tuple[int, ...]:
    if os.name == "nt":
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
        )
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


def effective_policy(home: Path, *, active_home: bool = False) -> Path:
    candidates: list[Path] = []
    for name in ("AGENTS.override.md", "AGENTS.md"):
        candidate = home / name
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ReceiptError("effective global policy is unavailable") from exc
        if stat.S_ISLNK(candidate_stat.st_mode):
            if not active_home:
                raise ReceiptError("effective global policy is unsafe")
        elif not stat.S_ISREG(candidate_stat.st_mode):
            raise ReceiptError("effective global policy is unsafe")
        candidates.append(candidate)
    if len(candidates) != 1:
        raise ReceiptError("exactly one effective global policy file is required")
    return candidates[0]


def _read_effective_policy_snapshot(
    home: Path,
    policy: Path,
    *,
    active_home: bool,
) -> tuple[bytes, list[tuple[Path, tuple[int, ...]]]]:
    try:
        policy_stat = policy.lstat()
    except OSError as exc:
        raise ReceiptError("effective global policy is unavailable") from exc
    if not stat.S_ISLNK(policy_stat.st_mode):
        content, fingerprint = _read_stable_file_snapshot(policy, home)
        return content, [(policy, fingerprint)]
    if not active_home:
        raise ReceiptError("effective global policy is unsafe")

    hooks_path = home / "hooks.json"
    hooks_content, hooks_fingerprint = _read_stable_file_snapshot(
        hooks_path,
        home,
    )
    try:
        _, state_snapshot, state = _active_hook_state(home, hooks_content)
        expected_digest = _state_policy_digest(state, policy.name)
        content, policy_snapshots = _read_proven_policy_symlink(
            policy,
            home,
            expected_digest,
        )
    except StageError as exc:
        raise ReceiptError("effective global policy is unsafe") from exc
    if state_snapshot is None:
        raise ReceiptError("effective global policy is unsafe")
    snapshots = [
        (hooks_path, hooks_fingerprint),
        state_snapshot,
        *policy_snapshots,
    ]
    _revalidate_hash_sources(snapshots)
    return content, snapshots


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
        home = root
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
        policy = effective_policy(home, active_home=active_home)
        config_path = home / "config.toml"
        config_content, config_fingerprint = _read_stable_file_snapshot(
            config_path,
            root,
        )
        _, policy_snapshots = _read_effective_policy_snapshot(
            root,
            policy,
            active_home=active_home,
        )
        config = tomllib.loads(config_content.decode("utf-8"))
        features = config.get("features", {})
        agents_config = config.get("agents", {})
        if isinstance(features, dict) and (
            features.get("multi_agent") is not None
            or "multi_agent_v2" in features
            or features.get("default_mode_request_user_input") is not True
        ):
            return "legacy_key_unowned"
        if not isinstance(agents_config, dict) or agents_config or config.get("max_concurrent_threads_per_session") != 3:
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
                *policy_snapshots,
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


def hash_inputs(home: Path, *, active_home: bool = False) -> dict[str, str]:
    try:
        home = home.resolve(strict=True)
    except OSError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    config = home / "config.toml"
    policy_candidates = [
        home / "AGENTS.override.md",
        home / "AGENTS.md",
    ]
    policy_projection = [
        (candidate, _optional_fingerprint(candidate))
        for candidate in policy_candidates
    ]
    policy = effective_policy(home, active_home=active_home)
    config_content, config_fingerprint = _read_stable_file_snapshot(config, home)
    policy_content, policy_snapshots = _read_effective_policy_snapshot(
        home,
        policy,
        active_home=active_home,
    )
    try:
        config_projection = project_config_bytes(config_content)
    except StageError as exc:
        raise ReceiptError("mandatory hash input unavailable") from exc
    manifest_hash, manifest_entries = _role_manifest(home)
    _revalidate_hash_sources(
        [
            (config, config_fingerprint),
            *policy_snapshots,
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


def snapshot_inputs(home: Path, *, active_home: bool = False) -> dict[str, str]:
    return hash_inputs(home, active_home=active_home)


def snapshot_changed(
    home: Path,
    snapshot: dict[str, str],
    *,
    active_home: bool = False,
) -> bool:
    return hash_inputs(home, active_home=active_home) != snapshot


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
        "--enable",
        NATIVE_MULTI_AGENT_FEATURE,
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


def build_autoroute_command(*, codex_bin: str, cwd: Path) -> list[str]:
    """Run the no-directive Plan-review probe on the configured root model."""
    return [
        codex_bin,
        "exec",
        "--json",
        "--strict-config",
        "--skip-git-repo-check",
        "-C",
        str(cwd),
        "-s",
        "read-only",
        AUTO_ROUTE_PROMPT,
    ]


def _payloads(events: Iterable[dict], kind: str) -> list[dict]:
    return [event["payload"] for event in events if isinstance(event, dict) and event.get("type") == kind and isinstance(event.get("payload"), dict)]


def _events_valid(events: Iterable[object], kinds: set[str]) -> bool:
    return all(isinstance(event, dict) and (event.get("type") not in kinds or isinstance(event.get("payload"), dict)) for event in events)


def _js_string_fields(source: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(\"(?:\\\\.|[^\"\\\\])*\")", source):
        try:
            fields[match.group(1)] = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
    return fields


def _custom_native_calls(events: Iterable[dict]) -> list[tuple[int, dict]]:
    """Normalize current custom-tool transport into the legacy call shape."""
    calls: list[tuple[int, dict]] = []
    for index, event in enumerate(events):
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict) or payload.get("type") != "custom_tool_call":
            continue
        source = payload.get("input")
        if not isinstance(source, str):
            continue
        if re.search(r"tools\.[A-Za-z0-9_]+__spawn_agent\s*\(", source):
            fields = _js_string_fields(source)
            arguments = {key: fields[key] for key in ("message", "agent_type", "task_name", "fork_turns") if key in fields}
            calls.append((index, {"type": "function_call", "name": "spawn_agent", "call_id": payload.get("call_id"), "arguments": json.dumps(arguments)}))
        elif re.search(r"tools\.[A-Za-z0-9_]+__wait_agent\s*\(", source):
            timeout = re.search(r"\btimeout_ms\s*:\s*(\d+)", source)
            targets_match = re.search(r"\btargets\s*:\s*\[(.*?)\]", source, re.DOTALL)
            arguments: dict[str, object] = {}
            if timeout:
                arguments["timeout_ms"] = int(timeout.group(1))
            if targets_match:
                arguments["targets"] = re.findall(r'"((?:\\.|[^"\\])*)"', targets_match.group(1))
            calls.append((index, {"type": "function_call", "name": "wait_agent", "call_id": payload.get("call_id"), "arguments": json.dumps(arguments)}))
    return calls


def _native_calls(events: Iterable[dict]) -> list[tuple[int, dict]]:
    calls = [
        (index, event["payload"])
        for index, event in enumerate(events)
        if isinstance(event, dict)
        and event.get("type") == "response_item"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("type") == "function_call"
    ]
    return calls + _custom_native_calls(events)


def _notification_activities(events: Iterable[dict], call_id: str | None) -> list[dict]:
    activities: list[dict] = []
    for payload in _payloads(events, "response_item"):
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            continue
        content = payload.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            text = item.get("text") if isinstance(item, dict) else None
            if not isinstance(text, str) or "<subagent_notification>" not in text:
                continue
            match = re.search(r"<subagent_notification>\s*(\{[^\r\n]+\})", text)
            if not match:
                continue
            try:
                notification = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            child_id = notification.get("agent_path")
            if isinstance(child_id, str) and child_id:
                activities.append({"kind": "started", "event_id": call_id, "agent_thread_id": child_id})
    return activities


def _native_activities(events: Iterable[dict], calls: list[tuple[int, dict]]) -> list[dict]:
    activities = [
        payload
        for payload in _payloads(events, "event_msg")
        if payload.get("type") == "sub_agent_activity" and payload.get("kind") == "started"
    ]
    spawn = next((payload for _, payload in calls if payload.get("name") == "spawn_agent"), None)
    call_id = spawn.get("call_id") if spawn else None
    if not activities:
        activities.extend(_notification_activities(events, call_id))
    return activities


def inspect_dispatch(
    parent_events: list[dict],
    child_events: list[dict],
    *,
    expected_role: RoleBinding,
    expected_role_name: str = "scout",
    expected_task_name: str | None = None,
    metadata_child_id: str | None = None,
    expected_wait_timeout_ms: int = 30000,
) -> Verdict:
    """Classify native evidence without using an adapter namespace predicate."""
    if type(expected_wait_timeout_ms) is not int or expected_wait_timeout_ms <= 0:
        return _verdict("FAILED", "policy_violation", phase="dispatch")
    task = expected_task_name or task_name_for_role(expected_role_name)
    if not _events_valid(parent_events, {"session_meta", "turn_context", "response_item", "event_msg"}):
        return _verdict("FAILED", "policy_violation", phase="dispatch")
    if platform_halt_detected(
        *(json.dumps(event, sort_keys=True) for event in (*parent_events, *child_events))
    ):
        phase = "post-spawn" if child_events else "dispatch"
        contexts = _payloads(child_events, "turn_context")
        context = contexts[0] if contexts else {}
        values: dict[str, str | None] = {}
        if child_events:
            values = {
                "role": expected_role_name,
                "model": context.get("model") if isinstance(context.get("model"), str) else expected_role.model,
                "reasoning_effort": context.get("effort") if isinstance(context.get("effort"), str) else expected_role.effort,
            }
        return _verdict(
            "SKIPPED",
            "platform_halt",
            phase=phase,
            child_created="yes" if child_events else "unknown",
            platform_halt="capability_gap",
            **values,
        )
    function_calls = _native_calls(parent_events)
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
    activities = _native_activities(parent_events, function_calls)
    created = "yes" if activities or metadata_child_id else "unknown"
    # The rollout marker is undocumented and optional.  If a runtime emits it,
    # an explicitly non-native value is still contradictory evidence.
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
    if wait_index <= call_index or wait_args.get("timeout_ms") != expected_wait_timeout_ms or set(wait_args) - {"timeout_ms", "targets"}:
        return _verdict("FAILED", "policy_violation", phase="dispatch", child_created=created)
    call_id = call.get("call_id")
    if metadata_child_id is not None:
        if activities or not isinstance(metadata_child_id, str) or not metadata_child_id:
            return _verdict("FAILED", "policy_violation", child_created=created)
        child_id = metadata_child_id
        correlation_mode = "session_metadata"
    else:
        matched = [a for a in activities if a.get("event_id") == call_id]
        if not isinstance(call_id, str) or not call_id or len(matched) != 1:
            return _verdict("SKIPPED", "native_spawn_evidence_missing", child_created=created)
        child_id = matched[0].get("agent_thread_id")
        correlation_mode = "spawn_activity"
    targets = wait_args.get("targets")
    if targets is not None and targets != [child_id]:
        return _verdict("FAILED", "parent_child_mismatch", child_created="yes")
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
    # The observed child binding is authoritative. A role may intentionally use
    # the same model and effort as its parent, which cannot be distinguished
    # from inheritance but is behaviorally equivalent to the installed role.
    return _verdict("NATIVE_OK", "native_verified", child_created="yes", role=expected_role_name, task_name=task, fork_turns=args["fork_turns"], parent_ref=_short_ref(parent_id), child_ref=_short_ref(child_id), model=model, reasoning_effort=effort, correlation_mode=correlation_mode)


def _user_message_texts(events: Iterable[dict]) -> list[str]:
    texts: list[str] = []
    for payload in _payloads(events, "response_item"):
        if payload.get("type") != "message" or payload.get("role") != "user":
            continue
        content = payload.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "input_text" and isinstance(item.get("text"), str):
                texts.append(item["text"])
    return texts


def inspect_autoroute(
    parent_events: list[dict],
    child_rollouts: dict[str, list[dict]],
    *,
    expected_role: RoleBinding,
    parent_rollout_id: str,
) -> Verdict:
    """Verify that the fresh no-directive parent selected Plan review itself."""
    prompts = _user_message_texts(parent_events)
    submitted_probe = next(
        (prompt for prompt in prompts if prompt == AUTO_ROUTE_PROMPT),
        None,
    )
    if submitted_probe is None:
        return _verdict("FAILED", "autoroute_prompt_missing")
    if any(
        token in submitted_probe.casefold()
        for token in AUTO_ROUTE_DIRECTIVE_TOKENS
    ):
        return _verdict("FAILED", "autoroute_prompt_directive_detected")
    if not _events_valid(
        parent_events,
        {"session_meta", "turn_context", "response_item", "event_msg"},
    ):
        return _verdict("FAILED", "policy_violation")

    function_calls = [
        payload
        for payload in _payloads(parent_events, "response_item")
        if payload.get("type") == "function_call"
    ]
    spawn_calls = [payload for payload in function_calls if payload.get("name") == "spawn_agent"]
    untyped_spawns = [
        payload
        for payload in function_calls
        if payload.get("name") != "spawn_agent"
        and "spawn" in str(payload.get("name", ""))
    ]
    activities = [
        payload
        for payload in _payloads(parent_events, "event_msg")
        if payload.get("type") == "sub_agent_activity"
    ]
    transport_present = bool(spawn_calls or untyped_spawns or activities)
    task_name: str | None = None
    fork_turns: str | None = None
    correlation_mode: str

    if transport_present:
        if untyped_spawns or len(spawn_calls) != 1 or len(activities) != 1:
            return _verdict("FAILED", "policy_violation")
        call = spawn_calls[0]
        try:
            args = json.loads(call.get("arguments", ""))
        except (TypeError, json.JSONDecodeError):
            return _verdict("FAILED", "policy_violation")
        if (
            not isinstance(args, dict)
            or set(args) != {"message", "agent_type", "task_name", "fork_turns"}
            or not isinstance(args.get("message"), str)
            or not args["message"].strip()
            or args.get("agent_type") != "plan-verifier"
            or not TASK_NAME_RE.fullmatch(str(args.get("task_name")))
            or args.get("fork_turns") not in {"none", "1", "2", "3"}
        ):
            return _verdict("FAILED", "policy_violation")
        call_id = call.get("call_id")
        activity = activities[0]
        child_id = activity.get("agent_thread_id")
        if (
            not isinstance(call_id, str)
            or not call_id
            or activity.get("kind") != "started"
            or activity.get("event_id") != call_id
            or not isinstance(child_id, str)
            or not child_id
        ):
            return _verdict("FAILED", "policy_violation")
        parent_id = next(
            (
                payload.get("id")
                for payload in _payloads(parent_events, "session_meta")
                if isinstance(payload.get("id"), str)
            ),
            None,
        )
        task_name, fork_turns = args["task_name"], args["fork_turns"]
        correlation_mode = "spawn_activity"
    else:
        parent_sessions = _payloads(parent_events, "session_meta")
        parent_contexts = _payloads(parent_events, "turn_context")
        child_state = "yes" if child_rollouts else "no"
        if (
            not isinstance(parent_rollout_id, str)
            or not parent_rollout_id
            or len(parent_sessions) != 1
            or parent_sessions[0].get("id") != parent_rollout_id
            or len(parent_contexts) != 1
            or parent_contexts[0].get("model") != AUTO_ROUTE_PARENT_MODEL
            or parent_contexts[0].get("effort") != AUTO_ROUTE_PARENT_EFFORT
        ):
            return _verdict("FAILED", "policy_violation", child_created=child_state)
        parent_id = parent_rollout_id
        if not child_rollouts:
            return _verdict(
                "FAILED",
                "autoroute_plan_verifier_missing",
                child_created="no",
            )
        if len(child_rollouts) != 1:
            return _verdict("FAILED", "policy_violation", child_created="yes")
        child_id = next(iter(child_rollouts))
        if not isinstance(child_id, str) or not child_id:
            return _verdict("FAILED", "policy_violation", child_created="yes")
        correlation_mode = "session_metadata"

    child_events = child_rollouts.get(child_id)
    if not child_events:
        if correlation_mode == "session_metadata":
            return _verdict("FAILED", "policy_violation", child_created="yes")
        return _verdict("SKIPPED", "child_evidence_missing", child_created="yes")
    if not _events_valid(child_events, {"session_meta", "turn_context"}):
        return _verdict("FAILED", "policy_violation", child_created="yes")
    child_sessions = _payloads(child_events, "session_meta")
    child_contexts = _payloads(child_events, "turn_context")
    if len(child_sessions) != 1 or len(child_contexts) != 1:
        if correlation_mode == "session_metadata":
            return _verdict("FAILED", "policy_violation", child_created="yes")
        return _verdict("SKIPPED", "child_binding_unobservable", child_created="yes")
    child_session, child_context = child_sessions[0], child_contexts[0]
    if child_session.get("id") != child_id or child_session.get("parent_thread_id") != parent_id or child_session.get("agent_role") != "plan-verifier":
        return _verdict("FAILED", "parent_child_mismatch", child_created="yes")
    model, effort = child_context.get("model"), child_context.get("effort")
    if not isinstance(model, str) or not isinstance(effort, str):
        if correlation_mode == "session_metadata":
            return _verdict("FAILED", "policy_violation", child_created="yes")
        return _verdict("SKIPPED", "child_binding_unobservable", child_created="yes")
    if model != expected_role.model:
        return _verdict("FAILED", "child_model_mismatch", child_created="yes")
    if effort != expected_role.effort:
        return _verdict("FAILED", "child_effort_mismatch", child_created="yes")
    return _verdict(
        "NATIVE_OK",
        "native_verified",
        child_created="yes",
        role="plan-verifier",
        task_name=task_name,
        fork_turns=fork_turns,
        parent_ref=_short_ref(parent_id),
        child_ref=_short_ref(child_id),
        model=model,
        reasoning_effort=effort,
        correlation_mode=correlation_mode,
    )


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
    calls = [p for _, p in _native_calls(events) if p.get("name") == "spawn_agent"]
    if len(calls) != 1 or not isinstance(calls[0].get("call_id"), str):
        raise EvidenceError("typed spawn is unobservable")
    activities = [p for p in _native_activities(events, [(0, calls[0])]) if p.get("event_id") == calls[0]["call_id"]]
    if len(activities) != 1 or not isinstance(activities[0].get("agent_thread_id"), str):
        raise EvidenceError("child activity is unobservable")
    return activities[0]["agent_thread_id"]


def inspect_autoroute_available_evidence(
    home: Path,
    stdout: str,
    binding: RoleBinding,
) -> tuple[Verdict | None, bool]:
    """Inspect only children linked from the fresh no-directive parent trace."""
    try:
        parent_id = parse_exec_thread_id(stdout)
        parent_events = load_jsonl(locate_rollout(home / "sessions", parent_id))
        transport_calls = [
            payload
            for payload in _payloads(parent_events, "response_item")
            if payload.get("type") == "function_call"
            and "spawn" in str(payload.get("name", ""))
        ]
        activities = [
            payload
            for payload in _payloads(parent_events, "event_msg")
            if payload.get("type") == "sub_agent_activity"
        ]
        transport_present = bool(transport_calls or activities)
        children: dict[str, list[dict]] = {}
        if transport_present:
            for activity in activities:
                child_id = activity.get("agent_thread_id")
                if not isinstance(child_id, str) or not child_id or child_id in children:
                    continue
                try:
                    children[child_id] = load_jsonl(
                        locate_rollout(home / "sessions", child_id)
                    )
                except EvidenceError:
                    continue
        else:
            children = child_rollouts_for_parent(home / "sessions", parent_id)
        verdict = inspect_autoroute(
            parent_events,
            children,
            expected_role=binding,
            parent_rollout_id=parent_id,
        )
        return verdict, transport_present or bool(children)
    except EvidenceError:
        return None, False


def child_rollouts_for_parent(sessions_root: Path, parent_id: str) -> dict[str, list[dict]]:
    """Return bounded, metadata-linked children when v1 omits parent tool events."""
    try:
        root = sessions_root.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError("session store is unavailable") from exc
    matches: dict[str, list[dict]] = {}
    candidates = 0
    for path in root.rglob("*.jsonl"):
        candidates += 1
        if candidates > 64 or not path.is_file() or not _inside(path, root):
            raise EvidenceError("child evidence is unavailable")
        events = load_jsonl(path.resolve())
        sessions = _payloads(events, "session_meta")
        if len(sessions) != 1 or sessions[0].get("parent_thread_id") != parent_id:
            continue
        child_id = sessions[0].get("id")
        if not isinstance(child_id, str) or not child_id or child_id in matches:
            raise EvidenceError("child evidence is ambiguous")
        matches[child_id] = events
    return matches


def inspect_available_evidence(
    home: Path,
    stdout: str,
    binding: RoleBinding,
    role: str,
    *,
    expected_wait_timeout_ms: int = 30000,
) -> tuple[Verdict | None, bool]:
    """Inspect bounded rollout evidence and retain the spawn-attempt boundary."""
    try:
        parent_id = parse_exec_thread_id(stdout)
        parent_events = load_jsonl(locate_rollout(home / "sessions", parent_id))
        function_calls = _native_calls(parent_events)
        boundary = any(p.get("name") == "spawn_agent" for _, p in function_calls)
        activities = _native_activities(parent_events, function_calls)
        metadata_child_id: str | None = None
        try:
            child_id = child_thread_from_parent(parent_events)
            child_events = load_jsonl(locate_rollout(home / "sessions", child_id))
        except EvidenceError:
            child_events = []
            if not activities:
                try:
                    linked_children = child_rollouts_for_parent(home / "sessions", parent_id)
                except EvidenceError:
                    linked_children = {}
                if len(linked_children) == 1:
                    metadata_child_id, child_events = next(iter(linked_children.items()))
        return inspect_dispatch(
            parent_events,
            child_events,
            expected_role=binding,
            expected_role_name=role,
            metadata_child_id=metadata_child_id,
            expected_wait_timeout_ms=expected_wait_timeout_ms,
        ), boundary
    except EvidenceError:
        return None, False


def run_autoroute_probe(
    *,
    codex_bin: str,
    codex_home: Path,
    binding: RoleBinding,
    cwd: Path,
) -> tuple[Verdict, bool]:
    """Run one read-only, no-directive Plan-review selection probe."""
    fixture = (
        "# Production schema migration plan (synthetic smoke fixture)\n\n"
        "## Outcome\n\n"
        "Move three production services to the next database schema version with no\n"
        "planned downtime.\n\n"
        "## Scope\n\n"
        "- Add the new schema, backfill rows, and switch all three services.\n"
        "- Remove the old schema only after production validation.\n"
        "- Update deployment manifests and service configuration in three repositories.\n\n"
        "## Proposed sequence\n\n"
        "1. Add the compatible schema and deploy configuration updates.\n"
        "2. Backfill rows and switch all services to the new schema.\n"
        "3. Confirm production behavior, then remove the obsolete schema.\n\n"
        "## Approval boundary\n\n"
        "No implementation is authorized. Assess only whether this material,\n"
        "cross-service, production data-migration Plan is ready for approval.\n"
    )
    before = snapshot_inputs(codex_home)
    env = {
        "CODEX_HOME": str(codex_home),
        "CODEX_SQLITE_HOME": str(codex_home),
        **{key: value for key, value in os.environ.items() if key not in {"CODEX_HOME", "CODEX_SQLITE_HOME"}},
    }
    plan_path = cwd / "PLAN.md"
    if plan_path.exists():
        return _verdict("FAILED", "smoke_cwd_untrusted", phase="preflight", child_created="no"), False
    try:
        plan_path.write_text(fixture, encoding="utf-8")
        completed = subprocess.run(
            build_autoroute_command(codex_bin=codex_bin, cwd=cwd),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=env,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _verdict("FAILED", "codex_exec_failed", phase="execution-pre-child", child_created="no"), False
    finally:
        plan_path.unlink(missing_ok=True)
    observed, spawn_boundary = inspect_autoroute_available_evidence(codex_home, completed.stdout, binding)
    if snapshot_changed(codex_home, before):
        return _verdict("FAILED", "snapshot_mutated", phase="post-spawn" if spawn_boundary else "execution-pre-child", child_created=observed.child_created if observed else "unknown"), spawn_boundary
    if platform_halt_detected(completed.stdout, getattr(completed, "stderr", "")):
        return _platform_halt_verdict(
            phase="post-spawn" if spawn_boundary else "execution-pre-child",
            observed=observed,
        ), spawn_boundary
    if completed.returncode:
        return _verdict("FAILED", "codex_exec_failed_after_spawn" if spawn_boundary else "codex_exec_failed", phase="post-spawn" if spawn_boundary else "execution-pre-child", child_created=observed.child_created if observed else "unknown"), spawn_boundary
    return observed or _verdict("SKIPPED", "native_spawn_evidence_missing"), spawn_boundary


def receipt_payload(
    verdict: Verdict,
    *,
    codex_version: str,
    active: dict[str, str],
    target: dict[str, str],
    routing: Mapping[str, Any] | None = None,
    complexity: str = "routine",
    escalation_reason: str | None = None,
    permission_profile: str | None = None,
    expected_role: str | None = None,
    expected_binding: RoleBinding | None = None,
) -> dict:
    if routing is None:
        preserve_requested = verdict.reason_code == "platform_halt"
        effective_role = verdict.role or (
            expected_role if preserve_requested and expected_role else "unknown"
        )
        model = verdict.model or (
            expected_binding.model if preserve_requested and expected_binding is not None else UNKNOWN_MODEL
        )
        effort = verdict.reasoning_effort or (
            expected_binding.effort if preserve_requested and expected_binding is not None else None
        )
        snapshot = f"{model}@{effort}" if effort else UNKNOWN_SNAPSHOT
        if escalation_reason is None:
            escalation_reason = "explicit-risk" if effective_role == "plan-verifier" else "baseline"
        if permission_profile is None:
            permission_profile = (
                "read-only"
                if verdict.phase == "preflight"
                or effective_role in {"scout", "plan-verifier", "security-reviewer"}
                else "workspace-write"
            )
        try:
            routing = build_routing_context(
                runtime="codex",
                role=effective_role,
                model_candidate=model,
                model_snapshot=snapshot,
                complexity=complexity,
                escalation_reason=escalation_reason,
                permission_profile=permission_profile,
                claim={
                    "phase": verdict.phase,
                    "reason_code": verdict.reason_code,
                    "role": verdict.role,
                    "task_name": verdict.task_name,
                },
            )
        except ValueError as exc:
            raise ReceiptError("routing context is invalid") from exc
    else:
        try:
            validate_routing_context(routing)
        except ValueError as exc:
            raise ReceiptError("routing context is invalid") from exc
    payload = {
        "status": verdict.status, "reason_code": verdict.reason_code, "phase": verdict.phase,
        "child_created": verdict.child_created, "codex_version": codex_version,
        "active_config_sha256": active["config"], "active_role_manifest_sha256": active["role_manifest"], "active_policy_sha256": active["policy"],
        "target_config_sha256": target["config"], "target_role_manifest_sha256": target["role_manifest"], "target_policy_sha256": target["policy"],
        "routing": dict(routing),
        "platform_halt": verdict.platform_halt,
    }
    for key in ("role", "task_name", "fork_turns", "parent_ref", "child_ref", "model", "reasoning_effort", "correlation_mode"):
        value = getattr(verdict, key)
        if value is not None: payload[key] = value
    validate_receipt(payload)
    return payload


def validate_receipt(payload: dict) -> None:
    required = {"status", "reason_code", "phase", "child_created", "codex_version",
                "active_config_sha256", "active_role_manifest_sha256", "active_policy_sha256",
                "target_config_sha256", "target_role_manifest_sha256", "target_policy_sha256",
                "routing", "platform_halt"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - RECEIPT_KEYS:
        raise ReceiptError("receipt keys are invalid")
    if (payload["phase"], payload["reason_code"], payload["status"]) not in MATRIX:
        raise ReceiptError("receipt reason matrix row is invalid")
    if payload["child_created"] not in {"no", "yes", "unknown"}:
        raise ReceiptError("receipt child_created is invalid")
    if payload["platform_halt"] not in {"none", "capability_gap"}:
        raise ReceiptError("receipt platform halt state is invalid")
    try:
        validate_routing_context(payload["routing"])
    except (TypeError, ValueError) as exc:
        raise ReceiptError("receipt routing context is invalid") from exc
    if payload["reason_code"] == "platform_halt" and payload["platform_halt"] != "capability_gap":
        raise ReceiptError("platform halt reason lacks capability gap state")
    if payload["platform_halt"] == "capability_gap" and payload["reason_code"] != "platform_halt":
        raise ReceiptError("capability gap state lacks platform halt reason")
    if payload["platform_halt"] == "capability_gap" and payload["status"] == "NATIVE_OK":
        raise ReceiptError("platform halt cannot be a native success")
    routing = payload["routing"]
    if "role" in payload and routing["role"] != payload["role"]:
        raise ReceiptError("receipt routing role mismatch")
    if "model" in payload and routing["model_candidate"] != payload["model"]:
        raise ReceiptError("receipt routing model mismatch")
    if "model" in payload and "reasoning_effort" in payload:
        expected_snapshot = f"{payload['model']}@{payload['reasoning_effort']}"
        if routing["model_snapshot"] != expected_snapshot:
            raise ReceiptError("receipt routing snapshot mismatch")
    version = payload["codex_version"]
    if version != "unknown" and not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?", str(version)):
        raise ReceiptError("receipt version is invalid")
    hashes = [key for key in required if key.endswith("sha256")]
    if any(not isinstance(payload[key], str) or not re.fullmatch(r"[0-9a-f]{64}", payload[key]) for key in hashes):
        raise ReceiptError("receipt hashes are invalid")
    evidence = {"role", "task_name", "fork_turns", "parent_ref", "child_ref", "model", "reasoning_effort", "sandbox", "correlation_mode"}
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
    if payload["status"] == "NATIVE_OK" and (payload["codex_version"] == "unknown" or payload["active_config_sha256"] != payload["target_config_sha256"] or payload["active_role_manifest_sha256"] != payload["target_role_manifest_sha256"] or payload["active_policy_sha256"] != payload["target_policy_sha256"]):
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
    if "correlation_mode" in payload and (
        not isinstance(payload["correlation_mode"], str)
        or payload["correlation_mode"] not in CORRELATION_MODES
    ):
        raise ReceiptError("receipt correlation mode is invalid")
    for ref in ("parent_ref", "child_ref"):
        if ref in payload and (not isinstance(payload[ref], str) or not payload[ref] or not re.fullmatch(r"[0-9a-f]{16}", payload[ref])):
            raise ReceiptError("receipt reference leaks runtime data")
    for key, value in payload.items():
        if key in {"parent_ref", "child_ref"}:
            continue
        if isinstance(value, str) and ("/" in value or "\\" in value or "secret" in value.lower()):
            raise ReceiptError("receipt contains path or secret data")
    if payload["status"] == "NATIVE_OK":
        needed = {"role", "parent_ref", "child_ref", "model", "reasoning_effort", "correlation_mode"}
        if payload["phase"] != "post-spawn" or payload["child_created"] != "yes" or not needed <= set(payload) or payload["role"] not in ROLES or not isinstance(payload["model"], str) or not payload["model"].strip() or not isinstance(payload["reasoning_effort"], str) or not payload["reasoning_effort"].strip():
            raise ReceiptError("NATIVE_OK receipt lacks core evidence")
        if payload["correlation_mode"] == "session_metadata" and payload["role"] != "plan-verifier":
            raise ReceiptError("session metadata receipt is not autoroute evidence")


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
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":")); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temp, 0o600)
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
        active_hash = hash_inputs(active_home, active_home=True)
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
    parser.add_argument("--autoroute", action="store_true")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--active-codex-home", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-cwd", type=Path, required=True)
    parser.add_argument("--parent-model", default="gpt-5.6-luna")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--launch-capture", type=Path)
    args = parser.parse_args(raw)
    if args.autoroute:
        args.role = "plan-verifier"
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
            write_receipt(
                destination,
                receipt_payload(
                    verdict,
                    codex_version="unknown",
                    active=active_hash,
                    target=target_hash,
                    expected_role=args.role,
                    expected_binding=binding,
                ),
            )
        except ReceiptError:
            print("receipt_write_failed", file=sys.stderr); return 1
        _print(verdict); return 2
    try:
        capture = json.loads(args.launch_capture.read_text(encoding="utf-8"))
        expected = {"CODEX_HOME": str(args.codex_home), "CODEX_SQLITE_HOME": str(args.codex_home), "codex_cwd": str(args.codex_cwd)}
        if not isinstance(capture, dict) or any(capture.get(key) != value for key, value in expected.items()):
            verdict = _verdict("FAILED", "environment_binding_mismatch", phase="preflight", child_created="no")
            write_receipt(
                destination,
                receipt_payload(
                    verdict,
                    codex_version="unknown",
                    active=active_hash,
                    target=target_hash,
                    expected_role=args.role,
                    expected_binding=binding,
                ),
            )
            _print(verdict); return 1
    except (OSError, json.JSONDecodeError, ReceiptError):
        print("environment_binding_unobservable", file=sys.stderr); return 2
    version_text: str | None = None
    try:
        version_run = subprocess.run([args.codex_bin, "--version"], capture_output=True, text=True, check=False)
        raw_version = version_run.stdout + version_run.stderr
        version_text = codex_version_token(raw_version) if version_run.returncode == 0 else None
        token = parse_codex_version(raw_version) if version_text is not None else None
    except OSError:
        token = None
    if token is None:
        verdict = _verdict("SKIPPED", "version_parse_failed", phase="preflight", child_created="no")
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
                payload = receipt_payload(
                    verdict,
                    codex_version=version_text or "unknown",
                    active=active_hash,
                    target=target_hash,
                    expected_role=args.role,
                    expected_binding=binding,
                )
                write_receipt(destination, payload)
                _print(verdict)
                return 1
            if args.autoroute:
                verdict, spawn_boundary = run_autoroute_probe(
                    codex_bin=args.codex_bin,
                    codex_home=args.codex_home,
                    binding=binding,
                    cwd=args.codex_cwd,
                )
            else:
                command = build_codex_command(codex_bin=args.codex_bin, cwd=args.codex_cwd, parent_model=args.parent_model, role=args.role)
                before = snapshot_inputs(args.codex_home)
                completed = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, check=False)
                changed = snapshot_changed(args.codex_home, before)
                observed, spawn_boundary = inspect_available_evidence(args.codex_home, completed.stdout, binding, args.role)
                if platform_halt_detected(completed.stdout, completed.stderr):
                    verdict = _platform_halt_verdict(
                        phase="post-spawn" if spawn_boundary else "execution-pre-child",
                        observed=observed,
                    )
                elif completed.returncode:
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
    version_text = version_text or "unknown"
    try:
        payload = receipt_payload(
            verdict,
            codex_version=version_text,
            active=active_hash,
            target=target_hash,
            expected_role=args.role,
            expected_binding=binding,
        )
        write_receipt(destination, payload)
    except ReceiptError:
        print("receipt_write_failed", file=sys.stderr); return 1
    _print(verdict)
    return 0 if verdict.status == "NATIVE_OK" else 2 if verdict.status == "SKIPPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
