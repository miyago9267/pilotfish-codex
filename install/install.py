#!/usr/bin/env python3
"""Install the one native Codex rust-v0.146.0 Pilotfish target.

This route refuses unsupported versions and ambiguous ownership.  It never
selects the retired adapter route.  Existing user bytes are preserved unless a
committed Pilotfish sidecar proves that a legacy path is installer-owned.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_registration import (
    CURRENT_PROJECTION_ID,
    HookRegistrationError,
    legacy_projection_id,
    load_registration,
    merge_registration,
    projection_state,
    strict_json_loads,
    validate_owned_projection,
    validate_projection_state,
    validate_source_registration,
)
from validate_agents import ROLES, validate_agent, validate_agents_config

PINNED_CODEX_VERSION = (0, 146, 0)
MARKER_BEGIN = "<!-- pilotfish-codex:begin -->"
MARKER_END = "<!-- pilotfish-codex:end -->"
NATIVE_TABLE = ("[agents]", "enabled = true", "max_concurrent_threads_per_session = 3")
OLD_V2_KEYS = frozenset({"enabled", "max_concurrent_threads_per_session"})
LEGACY_PATHS = frozenset({
    "features.multi_agent", "features.multi_agent_v2.tool_namespace",
    "features.multi_agent_v2.hide_spawn_agent_metadata", "agents.max_threads",
    "agents.max_concurrent_threads_per_session",
})
CANONICAL_ROLE_UPGRADE_DIGESTS = {
    "plan-verifier": frozenset({
        "c552938705065c826da9a3cbaf09c2fbbaa9fde4adb1f691a59b694d8468f541",
        "e29dff16ee22d8dcf60f214c7226eba52e9c1d5fca475d47ca750c8850a32852",
        "5cfd8630f9807a45eb18bfd587ab12dc41e8c06de82872ec6aa87f2c3e4c8fe0",
    }),
    "security-reviewer": frozenset({
        "94d7de12d1cb197c98e83c2f78d402cf3fb393e860feee1e146f5b6294075d27",
    }),
    "security-executor": frozenset({
        "90568cf473e0e8025bfbd2a22a9c46d4db6d6b4ed0d344c975f4116365da9ce0",
    }),
    "verifier": frozenset({
        "9478638b7456b6e4120ecd5a59408431d886c87ae1a7391aade61bc84d722e2e",
        "07e9864edc5734644557bff9c26a41476a30620779980658954e07ff865c9cb8",
    }),
}


class InstallAbort(Exception):
    """The caller must resolve this state before any target write."""


def parse_codex_version(output: str) -> tuple[int, int, int] | None:
    """Accept exactly one bare generic semantic version with no suffix."""
    tokens = re.findall(r"(?<![0-9A-Za-z_.-])(\d+)\.(\d+)\.(\d+)(?![0-9A-Za-z_.-])", output)
    if len(tokens) != 1:
        return None
    return tuple(int(part) for part in tokens[0])  # type: ignore[return-value]


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _table_span(lines: list[str], header: str) -> tuple[int, int] | None:
    start = None
    for i, line in enumerate(lines):
        if line.split("#", 1)[0].strip() == f"[{header}]":
            start = i
            break
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].split("#", 1)[0].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return start, i
    return start, len(lines)


def _set_table_key(lines: list[str], table: str, key: str, value: str, nl: str) -> list[str]:
    span = _table_span(lines, table)
    if span is None:
        if lines and lines[-1].strip():
            lines = lines + [nl]
        return lines + [f"[{table}]{nl}", f"{key} = {value}{nl}"]
    start, end = span
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    result = list(lines)
    for i in range(start + 1, end):
        if pattern.match(result[i]):
            ending = "\r\n" if result[i].endswith("\r\n") else "\n"
            result[i] = f"{key} = {value}{ending}"
            return result
    return result[: start + 1] + [f"{key} = {value}{nl}"] + result[start + 1 :]


def _remove_table_key(lines: list[str], table: str, key: str) -> list[str]:
    span = _table_span(lines, table)
    if span is None:
        return lines
    start, end = span
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    return [line for i, line in enumerate(lines) if not (start < i < end and pattern.match(line))]


def _remove_table(lines: list[str], table: str) -> list[str]:
    span = _table_span(lines, table)
    if span is None:
        return lines
    start, end = span
    result = lines[:start] + lines[end:]
    while start > 0 and start <= len(result) and not result[start - 1].strip():
        result.pop(start - 1)
        start -= 1
    return result


def _inline_or_dotted_v2(text: str) -> bool:
    """Reject only forms whose rewrite would collide with a table header."""
    return bool(re.search(r"^\s*features\.multi_agent_v2\s*=|^\s*multi_agent_v2\s*=\s*\{", text, re.M))


def merge_config_text(
    text: str,
    *,
    owned_legacy: frozenset[str] = frozenset(),
    migration_proven: bool = False,
) -> tuple[str, list[str]]:
    """Render the native ``[agents]`` table while preserving user config."""
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise InstallAbort(f"existing config.toml is invalid TOML: {exc}") from exc
    features = config.get("features", {})
    if not isinstance(features, dict):
        raise InstallAbort("features must be a TOML table")
    agents = config.get("agents", {})
    if not isinstance(agents, dict):
        raise InstallAbort("agents must be a TOML table")
    expected_agent_keys = {"enabled", "max_concurrent_threads_per_session"}
    unknown_agent_keys = set(agents) - expected_agent_keys
    if unknown_agent_keys:
        raise InstallAbort(
            "agents table has unsupported key(s): "
            + ", ".join(sorted(unknown_agent_keys))
        )
    v2 = features.get("multi_agent_v2")
    if v2 is not None and not isinstance(v2, dict):
        raise InstallAbort("legacy features.multi_agent_v2 must be an exact table")
    if _inline_or_dotted_v2(text):
        raise InstallAbort("features.multi_agent_v2 uses inline or dotted TOML syntax that cannot be safely rewritten")
    migrating_v2 = v2 is not None
    if isinstance(v2, dict):
        if set(v2) != OLD_V2_KEYS:
            raise InstallAbort("legacy V2 table has extra or unowned entries")
        if v2.get("enabled") is not True:
            raise InstallAbort("legacy features.multi_agent_v2 is explicitly disabled")
        if type(v2.get("max_concurrent_threads_per_session")) is not int or v2["max_concurrent_threads_per_session"] != 4:
            raise InstallAbort("legacy V2 concurrency must be exactly 4")
        if not migration_proven:
            raise InstallAbort("legacy V2 migration requires committed installer provenance")
    if agents.get("enabled") is not None and agents.get("enabled") is not True:
        raise InstallAbort("agents.enabled conflicts with native migration")
    fallback = agents.get("max_concurrent_threads_per_session")
    if fallback is not None and (type(fallback) is not int or fallback != 3):
        raise InstallAbort("agents.max_concurrent_threads_per_session conflicts with native child concurrency 3")
    if "max_threads" in agents:
        raise InstallAbort("legacy agents.max_threads is unowned")
    if features.get("multi_agent") is True and "features.multi_agent" not in owned_legacy:
        raise InstallAbort("legacy_key_unowned: features.multi_agent")

    lines = text.splitlines(keepends=True)
    nl = _newline(text)
    notes: list[str] = []
    missing_root_defaults = []
    if "model" not in config:
        missing_root_defaults.append(('model = "gpt-5.6-luna"', "set model = gpt-5.6-luna"))
    if "model_reasoning_effort" not in config:
        missing_root_defaults.append(("model_reasoning_effort = \"medium\"", "set model_reasoning_effort = medium"))
    if "plan_mode_reasoning_effort" not in config:
        missing_root_defaults.append(("plan_mode_reasoning_effort = \"xhigh\"", "set plan_mode_reasoning_effort = xhigh"))
    if missing_root_defaults:
        index = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
        lines[index:index] = [f"{line}{nl}" for line, _ in missing_root_defaults]
        notes.extend(note for _, note in missing_root_defaults)
    if migrating_v2:
        lines = _remove_table(lines, "features.multi_agent_v2")
        notes.append("migrated exact legacy V2 table to native agents table")
    if "features.multi_agent" in owned_legacy:
        lines = _remove_table_key(lines, "features", "multi_agent")
        notes.append("removed owned legacy key features.multi_agent")
    lines = _set_table_key(lines, "agents", "enabled", "true", nl)
    lines = _set_table_key(lines, "agents", "max_concurrent_threads_per_session", "3", nl)
    notes.append("normalized native agents child concurrency to 3")
    result = "".join(lines)
    try:
        tomllib.loads(result)
    except tomllib.TOMLDecodeError as exc:
        raise InstallAbort(f"merge produced invalid TOML: {exc}") from exc
    return result, list(dict.fromkeys(notes))


def merge_instruction_text(text: str, block: str) -> tuple[str, str]:
    begins, ends = text.count(MARKER_BEGIN), text.count(MARKER_END)
    if begins != ends or begins > 1:
        raise InstallAbort("instruction file has unmatched or multiple pilotfish-codex marker pairs")
    block = block.rstrip("\n")
    if begins:
        start, end = text.index(MARKER_BEGIN), text.index(MARKER_END) + len(MARKER_END)
        return text[:start] + block + text[end:], "replaced"
    return (text.rstrip("\n") + "\n\n" if text else "") + block + "\n", "appended"


def active_instruction_file(home: Path) -> Path:
    agents = home / "AGENTS.md"
    override = home / "AGENTS.override.md"
    agents_active = agents.is_file() and bool(agents.read_text(encoding="utf-8").strip())
    override_active = override.is_file() and bool(override.read_text(encoding="utf-8").strip())
    if agents_active and override_active:
        raise InstallAbort("both policy files are non-empty; operator resolution required")
    return override if override_active else agents


def _assert_active_instruction_file(home: Path, expected: Path) -> None:
    if active_instruction_file(home) != expected:
        raise InstallAbort("active policy file changed while install was planned")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _state_path(home: Path) -> Path:
    return home.with_name(f"{home.name}.pilotfish-install-state.json")


def _load_state(home: Path) -> dict | None:
    pending = _state_path(home).with_suffix(".json.pending")
    if pending.exists():
        raise InstallAbort("pending install state exists; resolve the aborted transaction before writing")
    path = _state_path(home)
    if not path.exists():
        return None
    try:
        state = strict_json_loads(path.read_bytes(), source="install state")
    except (OSError, HookRegistrationError) as exc:
        raise InstallAbort("install state is invalid; resolve it before writing") from exc
    if not isinstance(state, dict) or state.get("status") != "committed":
        raise InstallAbort("install state is not a committed transaction")
    return state


def _required_state_targets(
    policy_path: Path,
    home: Path,
    *,
    include_hooks: bool = True,
) -> frozenset[str]:
    policy_relative = policy_path.relative_to(home).as_posix()
    targets = {
        "config.toml",
        *(f"agents/{role}.toml" for role in ROLES),
        policy_relative,
    }
    if include_hooks:
        targets.update({"hooks.json", "hooks/pilotfish_autoroute_gate.py"})
    return frozenset(targets)


def _required_v2_state_targets(policy_path: Path, home: Path) -> frozenset[str]:
    return _required_state_targets(policy_path, home) - {"hooks.json"}


def _config_value(config: dict, dotted: str) -> tuple[bool, object | None]:
    current: object = config
    for segment in dotted.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False, None
        current = current[segment]
    return True, current


def _routing_projection(config: dict, owned_legacy: frozenset[str]) -> dict[str, object]:
    """Return only config state whose ownership belongs to Pilotfish."""
    return {
        "model": _config_value(config, "model"),
        "model_reasoning_effort": _config_value(config, "model_reasoning_effort"),
        "plan_mode_reasoning_effort": _config_value(config, "plan_mode_reasoning_effort"),
        "agents": _config_value(config, "agents"),
        "legacy_v2": _config_value(config, "features.multi_agent_v2"),
        "owned_legacy": tuple(
            (path, _config_value(config, path)) for path in sorted(owned_legacy)
        ),
    }


def _decode_config(payload: bytes, *, source: str) -> tuple[str, dict]:
    try:
        text = payload.decode("utf-8")
        parsed = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InstallAbort(f"{source} config.toml is invalid: {exc}") from exc
    return text, parsed


def _validate_committed_state(
    state: dict,
    *,
    home: Path,
    policy_path: Path,
    config_snapshot: bytes | None,
) -> tuple[frozenset[str], bool, str, bool, str | None]:
    """Validate sidecar provenance, including event-bound hook ownership."""
    if not isinstance(state, dict) or state.get("status") != "committed":
        raise InstallAbort("install state is not a committed transaction")
    legacy_allowed = {"status", "target_fingerprints", "original_targets", "owned_legacy"}
    v2_allowed = legacy_allowed | {"state_version", "hook_registration"}
    is_v2 = "state_version" in state
    allowed_top = v2_allowed if is_v2 else legacy_allowed
    if set(state) != allowed_top:
        raise InstallAbort("install state has missing or unknown fields")
    if is_v2 and (
        type(state["state_version"]) is not int or state["state_version"] != 2
    ):
        raise InstallAbort("install state version is malformed")
    targets = state.get("target_fingerprints")
    originals = state.get("original_targets")
    if not isinstance(targets, dict) or not isinstance(originals, dict):
        raise InstallAbort("install state target evidence is malformed")
    recorded = frozenset(targets)
    required = (
        _required_v2_state_targets(policy_path, home)
        if is_v2
        else _required_state_targets(policy_path, home)
    )
    if recorded != required or set(originals) != recorded:
        raise InstallAbort("install state target manifest is stale or incomplete")
    try:
        if is_v2:
            hook_projection_id = validate_projection_state(state["hook_registration"])
        else:
            raw_fingerprint = targets.get("hooks.json")
            if not isinstance(raw_fingerprint, str):
                raise HookRegistrationError("legacy hooks.json fingerprint is malformed")
            hook_projection_id = legacy_projection_id(raw_fingerprint)
        hooks_path = home / "hooks.json"
        if not hooks_path.is_file():
            raise HookRegistrationError("owned hooks.json is missing")
        registration = load_registration(
            hooks_path.read_bytes(), source="existing hooks.json"
        )
        validate_owned_projection(registration, hook_projection_id)
    except (OSError, HookRegistrationError) as exc:
        raise InstallAbort(f"committed hook registration is invalid: {exc}") from exc
    config_path = home / "config.toml"
    config_on_disk = config_path.read_bytes() if config_path.is_file() else None
    if config_on_disk != config_snapshot:
        raise InstallAbort("config.toml changed during state validation")
    sha_re = re.compile(r"^[0-9a-f]{64}$")
    original_payloads: dict[str, bytes | None] = {}
    hook_script_fingerprint: str | None = None
    for relative in sorted(recorded):
        fingerprint = targets.get(relative)
        evidence = originals.get(relative)
        if not isinstance(fingerprint, str) or not sha_re.fullmatch(fingerprint):
            raise InstallAbort("install state target fingerprint is malformed")
        if not isinstance(evidence, dict) or set(evidence) != {"present", "sha256", "bytes_b64"}:
            raise InstallAbort("install state original evidence is malformed")
        present, digest, encoded = evidence["present"], evidence["sha256"], evidence["bytes_b64"]
        if not isinstance(present, bool):
            raise InstallAbort("install state original presence is malformed")
        if present:
            if not isinstance(digest, str) or not sha_re.fullmatch(digest) or not isinstance(encoded, str):
                raise InstallAbort("install state original bytes are malformed")
            try:
                original = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise InstallAbort("install state original bytes are malformed")
            if _sha256_bytes(original) != digest:
                raise InstallAbort("install state original bytes fingerprint mismatch")
            original_payloads[relative] = original
        elif digest is not None or encoded is not None:
            raise InstallAbort("install state absent-original evidence is malformed")
        else:
            original_payloads[relative] = None
        target = home / relative
        if relative in {"config.toml", "hooks.json"}:
            continue
        if not target.is_file() or _sha256_bytes(target.read_bytes()) != fingerprint:
            raise InstallAbort("committed install state is stale; operator resolution required")
        if relative == "hooks/pilotfish_autoroute_gate.py":
            hook_script_fingerprint = fingerprint
    ownership = state.get("owned_legacy", {})
    if not isinstance(ownership, dict):
        raise InstallAbort("install state ownership evidence is malformed")
    proven: set[str] = set()
    for path, evidence in ownership.items():
        if path not in LEGACY_PATHS or not isinstance(evidence, dict):
            raise InstallAbort("install state ownership evidence is malformed")
        if set(evidence) != {"original_present", "original_sha256", "original_bytes_b64"}:
            raise InstallAbort("install state ownership evidence is malformed")
        present = evidence["original_present"]
        digest = evidence["original_sha256"]
        encoded = evidence["original_bytes_b64"]
        if not isinstance(present, bool) or not present or not isinstance(digest, str) or not sha_re.fullmatch(digest) or not isinstance(encoded, str):
            raise InstallAbort("install state ownership evidence is malformed")
        try:
            original = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise InstallAbort("install state ownership evidence is malformed")
        if _sha256_bytes(original) != digest:
            raise InstallAbort("install state ownership fingerprint mismatch")
        proven.add(path)
    owned = frozenset(proven)
    if config_snapshot is None:
        raise InstallAbort("committed install state is stale; operator resolution required")

    recorded_config_digest = targets["config.toml"]
    original_config = original_payloads["config.toml"] or b""
    original_text, original_parsed = _decode_config(
        original_config, source="install state original"
    )
    original_features = original_parsed.get("features", {})
    migration_proven = (
        isinstance(original_features, dict)
        and "multi_agent_v2" in original_features
    )
    reconstructed, _ = merge_config_text(
        original_text,
        owned_legacy=owned,
        migration_proven=migration_proven,
    )
    if _sha256_bytes(original_config) == recorded_config_digest:
        expected_config = original_config
    elif _sha256_bytes(reconstructed.encode()) == recorded_config_digest:
        expected_config = reconstructed.encode()
    else:
        raise InstallAbort("committed config provenance cannot be reconstructed")

    if _sha256_bytes(config_snapshot) != recorded_config_digest:
        _, expected_parsed = _decode_config(
            expected_config, source="reconstructed committed"
        )
        _, current_parsed = _decode_config(config_snapshot, source="current")
        if _routing_projection(current_parsed, owned) != _routing_projection(
            expected_parsed, owned
        ):
            raise InstallAbort("committed config routing projection is stale")
    return (
        owned,
        migration_proven,
        hook_projection_id,
        not is_v2,
        hook_script_fingerprint,
    )


def _config_path_present(data: dict, dotted: str) -> bool:
    current: object = data
    for segment in dotted.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    return True


def _backup_owned_legacy(home: Path, config_text: str) -> frozenset[str]:
    """Use an earliest matching pristine backup as per-key ownership proof."""
    try:
        current = tomllib.loads(config_text)
    except tomllib.TOMLDecodeError:
        return frozenset()
    features = current.get("features", {})
    v2 = features.get("multi_agent_v2", {}) if isinstance(features, dict) else {}
    agents = current.get("agents", {})
    complete_adapter = (
        isinstance(features, dict) and features.get("multi_agent") is True and
        isinstance(v2, dict) and v2.get("tool_namespace") == "agents" and
        v2.get("hide_spawn_agent_metadata") is False and
        v2.get("max_concurrent_threads_per_session") == 4 and
        isinstance(agents, dict) and agents.get("max_threads") == 3
    )
    if not complete_adapter:
        return frozenset()
    # A filename is not provenance. Only release-pinned pristine bytes are
    # acceptable here; arbitrary user backups never authorize deletion.
    # Only the exact released complete adapter snapshot is backup evidence.
    # Empty or partial user backups are never ownership proof.
    known_pristine_digests = frozenset({
        "2c78ed5bf224914829127bf5c3c6537cf6277f7602577a68d8497df4922bc269",
    })
    candidates = sorted(home.glob("config.toml.pilotfish-codex-*"))
    for backup in candidates:
        try:
            backup_bytes = backup.read_bytes()
            digest_matches = _sha256_bytes(backup_bytes) in known_pristine_digests
            legacy_marker = backup.with_name(f"{backup.name}.pilotfish-v1.2-pristine")
            blank_legacy_matches = backup_bytes == b"" and legacy_marker.read_text(encoding="utf-8") == "pilotfish-codex-v1.2-adapter-pristine\n"
            if not digest_matches and not blank_legacy_matches:
                continue
        except OSError:
            continue
        try:
            pristine = tomllib.loads(backup_bytes.decode("utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if blank_legacy_matches or all(_config_path_present(pristine, path) for path in LEGACY_PATHS):
            return frozenset(LEGACY_PATHS)
    return frozenset()


def _assert_agents_root(agents: Path, home: Path) -> None:
    """Fail closed if the role root is swapped or escapes its home."""
    if agents.is_symlink():
        raise InstallAbort("agents root must not be a symlink")
    try:
        home_real = home.resolve(strict=False)
        agents_real = agents.resolve(strict=False)
        agents_real.relative_to(home_real)
    except (OSError, ValueError) as exc:
        raise InstallAbort("agents root escapes Codex home") from exc
    if not agents.exists():
        return
    if not agents.is_dir():
        raise InstallAbort("agents path is not a directory")
    seen: set[str] = set()
    for path in sorted(agents.rglob("*.toml")):
        if path.is_symlink():
            raise InstallAbort(f"unsafe role symlink: {path}")
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise InstallAbort(f"malformed role TOML: {path}") from exc
        name = data.get("name")
        if not isinstance(name, str) or name != path.stem:
            raise InstallAbort(f"role filename/name mismatch: {path}")
        if name in seen:
            raise InstallAbort(f"duplicate role name: {name}")
        seen.add(name)
        errors = validate_agent(data)
        if errors:
            raise InstallAbort(f"invalid role {path}: {'; '.join(errors)}")
        if name not in ROLES:
            raise InstallAbort(f"role_manifest_extra: {name}")


def _destination(path: Path) -> Path:
    if path.is_symlink():
        target = path.resolve(strict=True)
        if not target.is_file():
            raise InstallAbort(f"refusing non-file symlink target: {path}")
        return target
    return path


def _assert_hook_targets(codex_home: Path) -> None:
    """Reject symlinked or non-regular source-owned hook target paths."""
    hooks_root = codex_home / "hooks"
    try:
        home_real = codex_home.resolve(strict=False)
        hooks_real = hooks_root.resolve(strict=False)
        hooks_real.relative_to(home_real)
    except (OSError, ValueError) as exc:
        raise InstallAbort("hooks root escapes Codex home") from exc
    if hooks_root.exists() or hooks_root.is_symlink():
        if hooks_root.is_symlink() or not hooks_root.is_dir():
            raise InstallAbort("hooks root must be a non-symlink directory")
    for path in (
        codex_home / "hooks.json",
        hooks_root / "pilotfish_autoroute_gate.py",
    ):
        if not path.exists() and not path.is_symlink():
            continue
        try:
            info = path.lstat()
        except OSError as exc:
            raise InstallAbort("hook target is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise InstallAbort("hook target must be a regular non-symlink file")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _atomic_write(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.pilotfish-", dir=path.parent)
    temp = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _replace_staged(
    temp: Path,
    destination: Path,
    expected_original: bytes | None,
    *,
    role_directory_fd: int | None,
) -> None:
    """Last-moment compare-and-replace seam used by transaction race tests."""
    actual = destination.read_bytes() if destination.is_file() else None
    if actual != expected_original:
        raise InstallAbort(f"{destination} changed immediately before replacement")
    if role_directory_fd is None:
        os.replace(temp, destination)
    else:
        os.replace(temp, destination.name, dst_dir_fd=role_directory_fd)


def _atomic_write_if_unchanged(
    path: Path,
    payload: bytes,
    mode: int,
    expected_original: bytes | None,
) -> None:
    current = path.read_bytes() if path.is_file() else None
    if current != expected_original:
        raise InstallAbort(f"{path} changed immediately before state publication")
    _atomic_write(path, payload, mode)


def _commit(writes: list[tuple[Path, bytes, int, bytes | None]], stamp: str,
            *, agents_root: Path, hooks_root: Path, codex_home: Path,
            policy_path: Path) -> list[tuple[Path, bytes | None, bytes, int]]:
    _assert_active_instruction_file(codex_home, policy_path)
    _assert_hook_targets(codex_home)
    staged: list[tuple[Path, Path, bytes | None, bool, bool]] = []
    expected_post = {_destination(path): payload for path, payload, _, _ in writes}
    agents_root.mkdir(parents=True, exist_ok=True)
    _assert_agents_root(agents_root, codex_home)
    hooks_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_hook_targets(codex_home)
    agents_fd: int | None = None
    try:
        # Windows cannot open a directory with os.open for the dir_fd form of
        # os.replace. Use the ordinary path-based replacement there; the
        # surrounding containment and fingerprint checks still apply.
        if os.name != "nt":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            agents_fd = os.open(agents_root, flags)
        for path, payload, mode, original in writes:
            is_role = path.parent == agents_root
            is_hook = path == codex_home / "hooks.json" or path.parent == hooks_root
            if is_role:
                _assert_agents_root(agents_root, codex_home)
            if is_hook:
                _assert_hook_targets(codex_home)
            dest = _destination(path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp_dir = codex_home if is_role else dest.parent
            fd, name = tempfile.mkstemp(prefix=f".{dest.name}.pilotfish-", dir=temp_dir)
            temp = Path(name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temp, stat.S_IMODE(dest.stat().st_mode) if dest.is_file() else mode)
            staged.append((dest, temp, original, is_role, is_hook))
        for dest, _, original, _, _ in staged:
            actual = dest.read_bytes() if dest.is_file() else None
            if actual != original:
                raise InstallAbort(f"{dest} changed while install was planned")
        _assert_active_instruction_file(codex_home, policy_path)
        for dest, _, original, _, _ in staged:
            if original is not None:
                shutil.copy2(dest, dest.with_name(f"{dest.name}.pilotfish-codex-{stamp}"))
        applied: list[tuple[Path, bytes | None, bytes, int]] = []
        try:
            for dest, temp, original, is_role, is_hook in staged:
                payload = expected_post[dest]
                mode = stat.S_IMODE(dest.stat().st_mode) if dest.is_file() else 0o600
                if is_role:
                    _assert_agents_root(agents_root, codex_home)
                else:
                    if is_hook:
                        _assert_hook_targets(codex_home)
                _replace_staged(
                    temp,
                    dest,
                    original,
                    role_directory_fd=agents_fd if is_role else None,
                )
                applied.append((dest, original, payload, mode))
            for destination, expected in expected_post.items():
                if not destination.is_file() or destination.read_bytes() != expected:
                    raise InstallAbort("post-write target fingerprint mismatch")
            _assert_active_instruction_file(codex_home, policy_path)
        except (OSError, InstallAbort):
            for dest, original, payload, mode in reversed(applied):
                current = dest.read_bytes() if dest.is_file() else None
                if current != payload:
                    continue
                if original is None:
                    dest.unlink(missing_ok=True)
                else:
                    _atomic_write(dest, original, mode)
            raise
        return applied
    finally:
        if agents_fd is not None:
            os.close(agents_fd)
        for _, temp, _, _, _ in staged:
            temp.unlink(missing_ok=True)


def install(*, source_root: Path, codex_home: Path, dry_run: bool, check_codex: bool = True) -> int:
    if check_codex:
        try:
            completed = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=False)
        except OSError:
            completed = None
        version = parse_codex_version((completed.stdout + completed.stderr) if completed and completed.returncode == 0 else "")
        if version is None:
            print("error: version_parse_failed", file=sys.stderr); return 2
        if version != PINNED_CODEX_VERSION:
            print("error: version_not_pinned", file=sys.stderr); return 2
    config_path = codex_home / "config.toml"
    config_snapshot = config_path.read_bytes() if config_path.is_file() else None
    config_text, parsed_config = _decode_config(
        config_snapshot or b"", source="existing"
    )
    policy_template = (source_root / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8")
    policy_path = active_instruction_file(codex_home)
    policy_text = policy_path.read_text(encoding="utf-8") if policy_path.is_file() else ""
    state = _load_state(codex_home)
    owned = frozenset()
    migration_proven = False
    owned_hook_projection: str | None = None
    legacy_state = False
    proven_hook_script_fingerprint: str | None = None
    features = parsed_config.get("features", {}) if isinstance(parsed_config, dict) else {}
    legacy_v2 = isinstance(features, dict) and "multi_agent_v2" in features
    if state is not None:
        (
            owned,
            migration_proven,
            owned_hook_projection,
            legacy_state,
            proven_hook_script_fingerprint,
        ) = _validate_committed_state(
            state,
            home=codex_home,
            policy_path=policy_path,
            config_snapshot=config_snapshot,
        )
    elif legacy_v2:
        # Let the config validator classify malformed/disabled/extra legacy
        # forms before reporting the missing provenance gate.
        merge_config_text(config_text, migration_proven=False)
        raise InstallAbort("legacy V2 migration requires a committed install state")
    new_config, notes = merge_config_text(
        config_text,
        owned_legacy=owned,
        migration_proven=migration_proven,
    )
    new_policy, policy_action = merge_instruction_text(policy_text, policy_template)
    writes: list[tuple[Path, bytes, int, bytes | None]] = []
    if new_config != config_text:
        writes.append((config_path, new_config.encode(), 0o600, config_snapshot))
    agents = codex_home / "agents"
    _assert_agents_root(agents, codex_home)
    existing = list(agents.rglob("*.toml")) if agents.is_dir() else []
    for role in sorted(ROLES):
        source = source_root / "templates" / "agents" / f"{role}.toml"
        payload = source.read_bytes()
        target = agents / f"{role}.toml"
        current = target.read_bytes() if target.exists() else None
        if current is not None and current != payload:
            known = CANONICAL_ROLE_UPGRADE_DIGESTS.get(role, frozenset())
            if _sha256_bytes(current) not in known:
                raise InstallAbort(f"installed_role_drift: agents/{role}.toml requires explicit replacement approval")
            writes.append((target, payload, 0o600, current))
            notes.append(f"upgraded canonical role {role}")
        elif current is None:
            writes.append((target, payload, 0o600, None))
    if new_policy != policy_text:
        writes.append((policy_path, new_policy.encode(), 0o644, policy_text.encode() if policy_path.is_file() else None))
    hooks_registration = codex_home / "hooks.json"
    hooks_root = codex_home / "hooks"
    hook_script = hooks_root / "pilotfish_autoroute_gate.py"
    _assert_hook_targets(codex_home)
    source_registration = (source_root / "templates" / "hooks.json").read_bytes()
    current_registration = (
        hooks_registration.read_bytes() if hooks_registration.is_file() else None
    )
    try:
        validate_source_registration(source_registration)
        merged_registration, desired_hook_projection = merge_registration(
            current_registration,
            source_registration,
            owned_projection_id=owned_hook_projection,
        )
    except HookRegistrationError as exc:
        raise InstallAbort(f"hook registration rejected: {exc}") from exc
    if current_registration != merged_registration:
        writes.append(
            (
                hooks_registration,
                merged_registration,
                0o600,
                current_registration,
            )
        )
    source_hook_script = source_root / "hooks" / "pilotfish_autoroute_gate.py"
    hook_script_payload = source_hook_script.read_bytes()
    current_hook_script = hook_script.read_bytes() if hook_script.is_file() else None
    if current_hook_script is not None and current_hook_script != hook_script_payload:
        if (
            proven_hook_script_fingerprint is None
            or _sha256_bytes(current_hook_script) != proven_hook_script_fingerprint
        ):
            raise InstallAbort(
                "installed_hook_drift: hook script requires explicit replacement approval"
            )
        writes.append((hook_script, hook_script_payload, 0o600, current_hook_script))
        notes.append("upgraded state-proven hook script")
    elif current_hook_script is None:
        writes.append((hook_script, hook_script_payload, 0o600, None))
    planned_roles = {p.stem for p in existing} | set(ROLES)
    extras = planned_roles - ROLES
    if extras:
        raise InstallAbort(f"role_manifest_extra: {', '.join(sorted(extras))}")
    if legacy_v2:
        allowed_migration = {
            "config.toml",
            "agents/plan-verifier.toml",
            "agents/security-reviewer.toml",
            "agents/verifier.toml",
            "hooks.json",
            "hooks/pilotfish_autoroute_gate.py",
            policy_path.relative_to(codex_home).as_posix(),
        }
        changed_migration = {path.relative_to(codex_home).as_posix() for path, _, _, _ in writes}
        if not changed_migration <= allowed_migration:
            raise InstallAbort("legacy V2 migration would replace an unapproved primary target")
    errors, _ = validate_agents_config(tomllib.loads(new_config))
    if errors:
        raise InstallAbort("planned native config invalid: " + "; ".join(errors))
    inventory = [
        config_path,
        policy_path,
        *(agents / f"{role}.toml" for role in sorted(ROLES)),
        hooks_registration,
        hook_script,
    ]
    state_inventory = [path for path in inventory if path != hooks_registration]
    pre_targets: dict[str, dict[str, object]] = {}
    for path in inventory:
        relative = path.relative_to(codex_home).as_posix()
        current = (
            config_snapshot
            if path == config_path
            else path.read_bytes() if path.is_file() else None
        )
        pre_targets[relative] = {"present": current is not None,
                                 "sha256": _sha256_bytes(current) if current is not None else None,
                                 "bytes_b64": base64.b64encode(current).decode() if current is not None else None}
    write_payloads = {path: payload for path, payload, _, _ in writes}
    expected_inventory = {
        path.relative_to(codex_home).as_posix(): _sha256_bytes(
            write_payloads[path] if path in write_payloads else base64.b64decode(pre_targets[path.relative_to(codex_home).as_posix()]["bytes_b64"])
        )
        for path in inventory
    }
    state_pre_targets = {
        path.relative_to(codex_home).as_posix(): pre_targets[
            path.relative_to(codex_home).as_posix()
        ]
        for path in state_inventory
    }
    expected_state_inventory = {
        path.relative_to(codex_home).as_posix(): expected_inventory[
            path.relative_to(codex_home).as_posix()
        ]
        for path in state_inventory
    }
    state_needs_publication = state is None or legacy_state or (
        owned_hook_projection != desired_hook_projection
    )
    if dry_run:
        for note in notes:
            print(f"note: {note}")
        if not writes and not state_needs_publication:
            print("already up to date; nothing to change")
            return 0
        for path, _, _, _ in writes:
            print(f"would change primary: {path.relative_to(codex_home).as_posix()}")
        state_path = _state_path(codex_home)
        print(f"allowed transaction artifact: {state_path.name}.pending")
        print(f"allowed transaction artifact: {state_path.name}")
        for path, _, _, original in writes:
            if original is not None:
                relative = path.relative_to(codex_home).as_posix()
                print(f"allowed transaction artifact: {relative}.pilotfish-codex-<timestamp>")
        return 0
    if writes or state_needs_publication:
        pending = _state_path(codex_home).with_suffix(".json.pending")
        pending_record = {
            "status": "pending",
            "original_targets": state_pre_targets,
            "owned_legacy": {
                path: {
                    "original_present": True,
                    "original_sha256": _sha256_bytes(config_text.encode()),
                    "original_bytes_b64": base64.b64encode(config_text.encode()).decode(),
                }
                for path in owned
            },
        }
        pending_payload = json.dumps(pending_record, sort_keys=True).encode() + b"\n"
        _atomic_write(pending, pending_payload, 0o600)
        state_path = _state_path(codex_home)
        state_original = state_path.read_bytes() if state_path.is_file() else None
        applied: list[tuple[Path, bytes | None, bytes, int]] = []
        state_payload: bytes | None = None
        try:
            applied = _commit(
                writes,
                _stamp(),
                agents_root=agents,
                hooks_root=hooks_root,
                codex_home=codex_home,
                policy_path=policy_path,
            )
            _assert_active_instruction_file(codex_home, policy_path)
            for path in inventory:
                relative = path.relative_to(codex_home).as_posix()
                if not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_inventory[relative]:
                    raise InstallAbort("post-write transaction fingerprint mismatch")
            _assert_active_instruction_file(codex_home, policy_path)
            for path in inventory:
                relative = path.relative_to(codex_home).as_posix()
                if not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_inventory[relative]:
                    raise InstallAbort("post-write state publication fingerprint mismatch")
            ownership = dict(pending_record["owned_legacy"])
            record = {
                "state_version": 2,
                "status": "committed",
                "target_fingerprints": expected_state_inventory,
                "original_targets": state_pre_targets,
                "owned_legacy": ownership,
                "hook_registration": projection_state(desired_hook_projection),
            }
            state_payload = json.dumps(record, sort_keys=True).encode() + b"\n"
            _assert_active_instruction_file(codex_home, policy_path)
            _atomic_write_if_unchanged(
                state_path,
                state_payload,
                0o600,
                state_original,
            )
            if not state_path.is_file() or state_path.read_bytes() != state_payload:
                raise InstallAbort("published install state changed before verification")
            _assert_active_instruction_file(codex_home, policy_path)
            if any(not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_inventory[path.relative_to(codex_home).as_posix()] for path in inventory):
                raise InstallAbort("post-sidecar transaction fingerprint mismatch")
            if not pending.is_file() or pending.read_bytes() != pending_payload:
                raise InstallAbort("pending install state changed before removal")
            pending.unlink()
        except BaseException as exc:
            current_state = state_path.read_bytes() if state_path.is_file() else None
            if state_payload is not None and current_state == state_payload:
                if state_original is None:
                    state_path.unlink(missing_ok=True)
                else:
                    _atomic_write(state_path, state_original, 0o600)
            for path, original, payload, mode in reversed(applied):
                current = path.read_bytes() if path.is_file() else None
                if current != payload:
                    continue
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write(path, original, mode)
            aborted = dict(pending_record, status="aborted", error=type(exc).__name__)
            aborted_payload = json.dumps(aborted, sort_keys=True).encode() + b"\n"
            if pending.is_file() and pending.read_bytes() == pending_payload:
                _atomic_write(pending, aborted_payload, 0o600)
            raise
    for note in notes:
        print(f"note: {note}")
    print("changed native target" if writes else "already up to date; nothing to change")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        return install(source_root=Path(__file__).resolve().parents[1], codex_home=args.codex_home, dry_run=args.dry_run)
    except InstallAbort as exc:
        print(f"aborted: {exc}", file=sys.stderr); return 2
    except OSError as exc:
        print(f"error: install I/O failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
