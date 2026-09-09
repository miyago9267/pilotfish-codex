#!/usr/bin/env python3
"""Atomically materialize a confined native Codex smoke home.

This program deliberately has no verifier import or subprocess launch.  Any
failure is reported as ``stage_materialization_failed`` and leaves no published
destination or copied credentials/runtime data.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import os
import re
import shutil
import stat
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_registration import (
    CURRENT_PROJECTION_ID,
    HookRegistrationError,
    semantic_projection_digest,
    strict_json_loads,
    validate_projection_state,
    validate_source_registration,
)
from validate_agents import ROLES, validate_dir

HASHED_TOP_LEVEL = frozenset({
    "config.toml",
    "AGENTS.md",
    "AGENTS.override.md",
    "agents",
    "hooks.json",
    "hooks",
})
REQUIRED_RUNTIME_FILES = frozenset({"auth.json"})
PROJECTED_TOP_LEVEL = HASHED_TOP_LEVEL | REQUIRED_RUNTIME_FILES
HOOK_SCRIPT = Path("hooks/pilotfish_autoroute_gate.py")
SOURCE_HOOK_REGISTRATION = Path(__file__).resolve().parents[1] / "templates" / "hooks.json"
ROLLBACK_STAMP_RE = re.compile(r"^(?:\d{8}-\d{6}|\d{8}-\d{6}-\d{6})$")
LEGACY_ROLE_ROLLBACK_STAMP_RE = re.compile(r"^\d{8}$")
SMOKE_CONFIG = (
    b'model = "gpt-5.6-luna"\n'
    b'model_reasoning_effort = "medium"\n'
    b'plan_mode_reasoning_effort = "xhigh"\n\n'
    b"max_concurrent_threads_per_session = 3\n\n"
    b"[features]\n"
    b"default_mode_request_user_input = true\n\n"
)


class StageError(RuntimeError):
    pass


def project_config_bytes(content: bytes) -> bytes:
    """Return the canonical Codex 0.147 config required by smoke."""
    try:
        config = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise StageError("required config is invalid") from exc
    features = config.get("features", {})
    if not isinstance(features, dict) or "multi_agent" in features or "multi_agent_v2" in features:
        raise StageError("legacy multi-agent config is unavailable")
    if features.get("default_mode_request_user_input") is not True:
        raise StageError("native default-mode decision cards are unavailable")
    agents = config.get("agents", {})
    if not isinstance(agents, dict):
        raise StageError("agents must be a role table")
    if agents:
        raise StageError("native agents table must be empty; role declarations are staged from agents/")
    if config.get("max_concurrent_threads_per_session") != 3:
        raise StageError("required root concurrency config is unavailable")
    if (
        config.get("model") != "gpt-5.6-luna"
        or config.get("model_reasoning_effort") != "medium"
        or config.get("plan_mode_reasoning_effort") != "xhigh"
    ):
        raise StageError("required Luna routing config is unavailable")
    return SMOKE_CONFIG


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


def _nested(a: Path, b: Path) -> bool:
    try:
        a.relative_to(b)
        return True
    except ValueError:
        return False


def canonical_home_pair(active: Path, staged: Path) -> tuple[Path, Path]:
    if not active.is_absolute() or not staged.is_absolute():
        raise StageError("homes must be absolute")
    try:
        active_real = active.resolve(strict=True)
    except OSError as exc:
        raise StageError("active home is unavailable") from exc
    if not active_real.is_dir() or not os.access(active_real, os.R_OK | os.X_OK):
        raise StageError("active home is unreadable")
    if staged.exists() or staged.is_symlink():
        raise StageError("staged destination already exists")
    try:
        staged_parent = staged.parent.resolve(strict=True)
    except OSError as exc:
        raise StageError("staged destination parent is unavailable") from exc
    staged_real = staged_parent / staged.name
    if active_real == staged_real or _nested(active_real, staged_real) or _nested(staged_real, active_real):
        raise StageError("active and staged homes must be distinct and non-nested")
    return active_real, staged_real


def _regular_source(path: Path, active: Path) -> os.stat_result:
    try:
        relative = path.relative_to(active)
        resolved = path.resolve(strict=True)
        st = path.lstat()
    except (OSError, ValueError) as exc:
        raise StageError(f"unsafe source {path}") from exc
    if path.is_symlink() or not resolved.is_relative_to(active) or _nested(resolved, active) is False:
        raise StageError(f"source escapes active home: {relative}")
    if not stat.S_ISREG(st.st_mode):
        raise StageError(f"source is not a regular file: {relative}")
    return st


def _directory_source(path: Path, active: Path) -> os.stat_result:
    try:
        relative = path.relative_to(active)
        resolved = path.resolve(strict=True)
        source_stat = path.lstat()
    except (OSError, ValueError) as exc:
        raise StageError(f"unsafe source directory {path}") from exc
    if path.is_symlink() or not resolved.is_relative_to(active):
        raise StageError(f"source directory escapes active home: {relative}")
    if not stat.S_ISDIR(source_stat.st_mode):
        raise StageError(f"source is not a directory: {relative}")
    if not os.access(path, os.R_OK | os.X_OK):
        raise StageError(f"source directory is unreadable: {relative}")
    return source_stat


def _copy_regular(
    source: Path,
    destination: Path,
    active: Path,
) -> tuple[Path, tuple[int, ...]]:
    before = _regular_source(source, active)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open(source, flags)
        after_open = os.fstat(fd)
        if _stat_fingerprint(before) != _stat_fingerprint(after_open):
            raise StageError("source replaced while staging")
        with (
            os.fdopen(fd, "rb", closefd=False) as reader,
            destination.open("xb") as writer,
        ):
            shutil.copyfileobj(reader, writer)
            writer.flush(); os.fsync(writer.fileno())
        after = source.lstat()
        if _stat_fingerprint(before) != _stat_fingerprint(after):
            raise StageError("source changed while staging")
        os.chmod(destination, 0o600)
    except FileExistsError as exc:
        raise StageError("staging destination collision") from exc
    except OSError as exc:
        raise StageError(
            f"staging I/O failed for source: {source.relative_to(active)}"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
    return source, _stat_fingerprint(before)


def _read_proven_policy_symlink(
    source: Path,
    active: Path,
    expected_digest: str | None,
) -> tuple[bytes, tuple[tuple[Path, tuple[int, ...]], ...]]:
    """Read the effective external policy only when installer state owns it."""
    try:
        relative = source.relative_to(active)
        link_before = source.lstat()
    except (OSError, ValueError) as exc:
        raise StageError("effective policy symlink is unavailable") from exc
    if (
        relative not in {
            Path("AGENTS.md"),
            Path("AGENTS.override.md"),
            Path("pilotfish/AGENTS.md"),
        }
        or not stat.S_ISLNK(link_before.st_mode)
    ):
        raise StageError("unapproved policy symlink")
    if expected_digest is None:
        raise StageError("effective policy symlink requires committed provenance")

    fd: int | None = None
    try:
        link_value = os.readlink(source)
        target = source.resolve(strict=True)
        target_before = target.lstat()
        if stat.S_ISLNK(target_before.st_mode) or not stat.S_ISREG(target_before.st_mode):
            raise StageError("effective policy symlink target is not a regular file")
        if not os.access(target, os.R_OK):
            raise StageError("effective policy symlink target is unreadable")
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        if _stat_fingerprint(opened) != _stat_fingerprint(target_before):
            raise StageError("effective policy target changed while staging")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read()
        if (
            _stat_fingerprint(os.fstat(fd)) != _stat_fingerprint(target_before)
            or _stat_fingerprint(target.lstat()) != _stat_fingerprint(target_before)
            or _stat_fingerprint(source.lstat()) != _stat_fingerprint(link_before)
            or os.readlink(source) != link_value
            or source.resolve(strict=True) != target
        ):
            raise StageError("effective policy target changed while staging")
    except OSError as exc:
        raise StageError("effective policy target changed while staging") from exc
    finally:
        if fd is not None:
            os.close(fd)

    if hashlib.sha256(payload).hexdigest() != expected_digest:
        raise StageError("effective policy does not match committed provenance")
    return payload, (
        (source, _stat_fingerprint(link_before)),
        (target, _stat_fingerprint(target_before)),
    )


def _copy_proven_policy_symlink(
    source: Path,
    destination: Path,
    active: Path,
    expected_digest: str,
) -> tuple[tuple[Path, tuple[int, ...]], ...]:
    payload, snapshots = _read_proven_policy_symlink(
        source,
        active,
        expected_digest,
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(destination, 0o600)
    except (FileExistsError, OSError) as exc:
        raise StageError("staging effective policy failed") from exc
    _revalidate_sources(snapshots)
    return snapshots


def _copy_projected_config(
    source: Path,
    destination: Path,
    active: Path,
) -> tuple[Path, tuple[int, ...]]:
    before = _regular_source(source, active)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open(source, flags)
        after_open = os.fstat(fd)
        if _stat_fingerprint(before) != _stat_fingerprint(after_open):
            raise StageError("source replaced while staging")
        with os.fdopen(fd, "rb", closefd=False) as reader:
            projected = project_config_bytes(reader.read())
        after_read = os.fstat(fd)
        after_path = source.lstat()
        if (
            _stat_fingerprint(before) != _stat_fingerprint(after_read)
            or _stat_fingerprint(before) != _stat_fingerprint(after_path)
        ):
            raise StageError("source changed while staging")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with destination.open("xb") as writer:
            writer.write(projected)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(destination, 0o600)
    except FileExistsError as exc:
        raise StageError("staging destination collision") from exc
    except OSError as exc:
        raise StageError(
            f"staging I/O failed for source: {source.relative_to(active)}"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
    return source, _stat_fingerprint(before)


def _read_stable_regular(source: Path) -> tuple[bytes, tuple[int, ...]]:
    """Read a trusted source/sidecar without following a replacement symlink."""
    try:
        before = source.lstat()
    except OSError as exc:
        raise StageError("required external input is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise StageError("required external input must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open(source, flags)
        opened = os.fstat(fd)
        if _stat_fingerprint(opened) != _stat_fingerprint(before):
            raise StageError("required external input changed while reading")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read()
        if (
            _stat_fingerprint(os.fstat(fd)) != _stat_fingerprint(before)
            or _stat_fingerprint(source.lstat()) != _stat_fingerprint(before)
        ):
            raise StageError("required external input changed while reading")
        return payload, _stat_fingerprint(before)
    except OSError as exc:
        raise StageError("required external input changed while reading") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _active_hook_state(
    active: Path,
    active_hooks: bytes,
) -> tuple[
    str,
    tuple[Path, tuple[int, ...]] | None,
    dict[str, object] | None,
]:
    state_path = active.with_name(f"{active.name}.pilotfish-install-state.json")
    if not state_path.exists():
        source_hooks, _ = _read_stable_regular(SOURCE_HOOK_REGISTRATION)
        if active_hooks != source_hooks:
            raise StageError("co-owned active hooks.json requires committed state")
        return CURRENT_PROJECTION_ID, None, None
    payload, fingerprint = _read_stable_regular(state_path)
    try:
        state = strict_json_loads(payload, source="install state")
        expected_keys = {
            "state_version",
            "status",
            "target_fingerprints",
            "original_targets",
            "owned_legacy",
            "hook_registration",
            "policy_ownership",
        }
        expected_v3_keys = expected_keys | {"plugin", "runtime_status", "rollback_backups"}
        expected_v4_keys = expected_v3_keys | {"reconciliation"}
        if (
            not isinstance(state, dict)
            or set(state) not in (
                expected_keys, expected_keys - {"policy_ownership"},
                expected_v3_keys, expected_v4_keys,
            )
            or type(state.get("state_version")) is not int
            or state["state_version"] not in (2, 3, 4)
            or state.get("status") != "committed"
        ):
            raise HookRegistrationError("install state is not committed v2/v3/v4")
        projection_id = validate_projection_state(state["hook_registration"])
        if projection_id != CURRENT_PROJECTION_ID:
            raise HookRegistrationError("active hook projection is not current")
    except HookRegistrationError as exc:
        raise StageError(f"active hook ownership state is invalid: {exc}") from exc
    return projection_id, (state_path, fingerprint), state


def _state_policy_digest(
    state: dict[str, object] | None,
    policy_name: str,
) -> str:
    if state is None:
        raise StageError("effective policy symlink requires committed provenance")
    targets = state.get("target_fingerprints")
    originals = state.get("original_targets")
    expected_targets = {
        "config.toml",
        policy_name,
        HOOK_SCRIPT.as_posix(),
        *(f"agents/{role}.toml" for role in ROLES),
    }
    if (
        not isinstance(targets, dict)
        or not isinstance(originals, dict)
        or set(targets) != expected_targets
        or set(originals) != expected_targets
    ):
        raise StageError("effective policy provenance manifest is invalid")
    digest = targets.get(policy_name)
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise StageError("effective policy provenance fingerprint is invalid")
    return digest


def _active_policy_digest(active: Path, policy_name: str) -> str:
    try:
        active_hooks, _ = _read_stable_required(active / "hooks.json", active)
    except StageError as exc:
        raise StageError("effective policy provenance is unavailable") from exc
    _, _, state = _active_hook_state(active, active_hooks)
    return _state_policy_digest(state, policy_name)


def _stage_clean_hook_registration(
    destination: Path,
) -> tuple[tuple[Path, tuple[int, ...]], str]:
    payload, fingerprint = _read_stable_regular(SOURCE_HOOK_REGISTRATION)
    try:
        validate_source_registration(payload)
    except HookRegistrationError as exc:
        raise StageError(f"source hooks.json is invalid: {exc}") from exc
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with destination.open("xb") as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(destination, 0o600)
    except (FileExistsError, OSError) as exc:
        raise StageError("staging clean hooks.json failed") from exc
    return (
        (SOURCE_HOOK_REGISTRATION, fingerprint),
        hashlib.sha256(payload).hexdigest(),
    )


def _rollback_backup(relative: Path) -> bool:
    name = relative.name
    marker = ".pilotfish-v1.2-pristine"
    if name.endswith(marker):
        name = name[: -len(marker)]
    base, separator, stamp = name.rpartition(".pilotfish-codex-")
    if not separator or not (
        ROLLBACK_STAMP_RE.fullmatch(stamp)
        or (
            relative.parts[0] == "agents"
            and LEGACY_ROLE_ROLLBACK_STAMP_RE.fullmatch(stamp)
        )
    ):
        return False
    if len(relative.parts) == 1:
        return base in {"config.toml", "AGENTS.md", "AGENTS.override.md"} and (
            not relative.name.endswith(marker) or base == "config.toml"
        )
    if relative.parent == HOOK_SCRIPT.parent:
        return (
            base == HOOK_SCRIPT.name
            and not relative.name.endswith(marker)
        )
    return (
        relative.parts[0] == "agents"
        and not relative.name.endswith(marker)
        and base in {f"{role}.toml" for role in ROLES}
    )


def _projected_entries(root: Path) -> list[Path]:
    """Enumerate only required and explicitly allowlisted active-home inputs."""
    entries: list[Path] = []
    for name in sorted(PROJECTED_TOP_LEVEL):
        candidate = root / name
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StageError(f"projected source is unavailable: {name}") from exc
        entries.append(candidate)
        if stat.S_ISDIR(candidate_stat.st_mode):
            try:
                entries.extend(
                    sorted(
                        candidate.rglob("*"),
                        key=lambda path: path.relative_to(root).as_posix(),
                    )
                )
            except OSError as exc:
                raise StageError(f"projected source is unreadable: {name}") from exc
    return entries


def _projection_snapshot(
    root: Path,
) -> tuple[tuple[Path, tuple[int, ...] | None], ...]:
    snapshot: list[tuple[Path, tuple[int, ...] | None]] = []
    for name in sorted(PROJECTED_TOP_LEVEL):
        source = root / name
        try:
            fingerprint = _stat_fingerprint(source.lstat())
        except FileNotFoundError:
            fingerprint = None
        except OSError as exc:
            raise StageError(f"projected source is unavailable: {name}") from exc
        snapshot.append((source, fingerprint))
    return tuple(snapshot)


def explicit_layout_error(
    home: Path,
    *,
    allow_rollback_backups: bool,
    project_active_root: bool = False,
) -> str | None:
    """Return the first entry outside the selected smoke-home boundary."""
    try:
        root = home.resolve(strict=True)
        if not root.is_dir():
            return "home is not a directory"
        entries = (
            _projected_entries(root)
            if project_active_root
            else sorted(
                root.rglob("*"),
                key=lambda path: path.relative_to(root).as_posix(),
            )
        )
    except (OSError, StageError):
        return "home layout is unavailable"

    top_names = {entry.name for entry in entries if entry.parent == root}
    if not {"config.toml", "agents", "hooks.json", "hooks"} <= top_names:
        return "missing mandatory config, role manifest, or hook artifacts"
    user_policies = [
        root / name
        for name in ("AGENTS.override.md", "AGENTS.md")
        if (root / name).is_file() and (root / name).read_text(encoding="utf-8").strip()
    ]
    source_policy = root / "pilotfish" / "AGENTS.md"
    if len(user_policies) > 1:
        return "both policy files are non-empty"
    if not user_policies and not source_policy.is_file():
        return "no effective or source-only policy file is available"

    top_files = (HASHED_TOP_LEVEL - {"agents", "hooks"}) | REQUIRED_RUNTIME_FILES
    top_directories = {"agents", "hooks", "pilotfish"}
    nested_agent_directories: set[Path] = set()
    manifest_directories: set[Path] = set()
    hook_files: set[Path] = set()
    for entry in entries:
        relative = entry.relative_to(root)
        try:
            source_stat = entry.lstat()
        except FileNotFoundError:
            return f"unapproved entry: {relative.as_posix()}"
        except OSError:
            return f"unapproved entry: {relative.as_posix()}"
        is_active_policy_symlink = (
            project_active_root
            and len(relative.parts) == 1
            and relative.name in {"AGENTS.md", "AGENTS.override.md"}
            and stat.S_ISLNK(source_stat.st_mode)
        )
        try:
            resolved = entry.resolve(strict=True)
            if is_active_policy_symlink:
                resolved_stat = resolved.lstat()
                if (
                    stat.S_ISLNK(resolved_stat.st_mode)
                    or not stat.S_ISREG(resolved_stat.st_mode)
                    or not os.access(resolved, os.R_OK)
                ):
                    return f"unapproved entry: {relative.as_posix()}"
            elif stat.S_ISLNK(source_stat.st_mode) or not resolved.is_relative_to(root):
                return f"unapproved entry: {relative.as_posix()}"
        except OSError:
            return f"unapproved entry: {relative.as_posix()}"
        is_file = stat.S_ISREG(source_stat.st_mode) or is_active_policy_symlink
        is_directory = stat.S_ISDIR(source_stat.st_mode)
        if not is_file and not is_directory:
            return f"unapproved entry: {relative.as_posix()}"
        if is_file and not os.access(entry, os.R_OK):
            return f"unapproved entry: {relative.as_posix()}"
        if is_directory and not os.access(entry, os.R_OK | os.X_OK):
            return f"unapproved entry: {relative.as_posix()}"

        if len(relative.parts) == 1:
            if relative.name in top_files:
                if not is_file:
                    return f"unapproved entry: {relative.as_posix()}"
                continue
            if relative.name in top_directories:
                if not is_directory:
                    return f"unapproved entry: {relative.as_posix()}"
                continue
            if allow_rollback_backups and _rollback_backup(relative) and is_file:
                continue
            return f"unapproved entry: {relative.as_posix()}"

        if relative.parts[0] == "hooks":
            if is_directory:
                return f"unapproved entry: {relative.as_posix()}"
            if allow_rollback_backups and _rollback_backup(relative):
                continue
            if relative != HOOK_SCRIPT:
                return f"unapproved entry: {relative.as_posix()}"
            hook_files.add(relative)
            continue
        if relative.parts[0] == "pilotfish":
            if relative != Path("pilotfish/AGENTS.md") or not is_file:
                return f"unapproved entry: {relative.as_posix()}"
            continue
        if relative.parts[0] != "agents":
            return f"unapproved entry: {relative.as_posix()}"
        if is_directory:
            nested_agent_directories.add(relative)
            continue
        if relative.name.endswith(".toml"):
            parent = relative.parent
            while parent != Path("agents"):
                manifest_directories.add(parent)
                parent = parent.parent
            continue
        if allow_rollback_backups and _rollback_backup(relative):
            continue
        return f"unapproved entry: {relative.as_posix()}"

    empty_manifest_directories = nested_agent_directories - manifest_directories
    if empty_manifest_directories:
        relative = min(empty_manifest_directories, key=lambda path: path.as_posix())
        return f"unapproved entry: {relative.as_posix()}"
    if hook_files != {HOOK_SCRIPT}:
        return "missing mandatory hook script"
    return None


def _copy_tree(
    source: Path,
    destination: Path,
    active: Path,
    *,
    omit_rollback_backups: bool = False,
) -> list[tuple[Path, tuple[int, ...]]]:
    before = _directory_source(source, active)
    snapshots: list[tuple[Path, tuple[int, ...]]] = [
        (source, _stat_fingerprint(before))
    ]
    destination.mkdir(mode=0o700)
    try:
        children = sorted(source.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise StageError(
            f"source directory is unreadable: {source.relative_to(active)}"
        ) from exc
    for child in children:
        if omit_rollback_backups and _rollback_backup(child.relative_to(active)):
            continue
        target = destination / child.name
        if child.is_symlink():
            raise StageError("source symlink is not allowed")
        if child.is_dir():
            snapshots.extend(
                _copy_tree(
                    child,
                    target,
                    active,
                    omit_rollback_backups=omit_rollback_backups,
                )
            )
        else:
            snapshots.append(_copy_regular(child, target, active))
    try:
        after = source.lstat()
    except OSError as exc:
        raise StageError("source directory changed while staging") from exc
    if _stat_fingerprint(before) != _stat_fingerprint(after):
        raise StageError("source directory changed while staging")
    return snapshots


def _copy_inputs(
    active: Path,
    temporary: Path,
) -> tuple[
    tuple[tuple[Path, tuple[int, ...]], ...],
    tuple[tuple[Path, tuple[int, ...] | None], ...],
]:
    layout_error = explicit_layout_error(
        active,
        allow_rollback_backups=True,
        project_active_root=True,
    )
    if layout_error:
        raise StageError(layout_error)
    try:
        active_hooks, _ = _read_stable_required(active / "hooks.json", active)
    except StageError as exc:
        raise StageError("source replaced while staging") from exc
    projection_id, state_snapshot, install_state = _active_hook_state(
        active,
        active_hooks,
    )
    try:
        semantic_projection_digest(active_hooks, projection_id)
    except HookRegistrationError as exc:
        raise StageError(f"active hooks.json ownership is invalid: {exc}") from exc
    projection_snapshot = _projection_snapshot(active)
    user_policies = [
        active / name
        for name in ("AGENTS.override.md", "AGENTS.md")
        if (active / name).is_file() and (active / name).read_text(encoding="utf-8").strip()
    ]
    if len(user_policies) > 1:
        raise StageError("both policy files are non-empty")
    policy = user_policies[0] if user_policies else active / "pilotfish" / "AGENTS.md"
    if not policy.is_file():
        raise StageError("no effective or source-only policy file is available")
    policy_relative = policy.relative_to(active)
    policy_digest: str | None = None
    snapshots = [
        _copy_projected_config(
            active / "config.toml",
            temporary / "config.toml",
            active,
        ),
    ]
    if policy.is_symlink():
        policy_digest = _state_policy_digest(install_state, policy_relative.as_posix())
        snapshots.extend(
            _copy_proven_policy_symlink(
                policy,
                temporary / policy_relative,
                active,
                policy_digest,
            )
        )
    else:
        snapshots.append(_copy_regular(policy, temporary / policy_relative, active))
    snapshots.extend(
        _copy_tree(
            active / "agents",
            temporary / "agents",
            active,
            omit_rollback_backups=True,
        )
    )
    clean_hook_snapshot, _ = _stage_clean_hook_registration(
        temporary / "hooks.json"
    )
    if state_snapshot is not None:
        snapshots.append(state_snapshot)
    snapshots.append(clean_hook_snapshot)
    snapshots.extend(
        _copy_tree(
            active / "hooks",
            temporary / "hooks",
            active,
            omit_rollback_backups=True,
        )
    )
    problems = validate_dir(temporary / "agents", expected_names=ROLES)
    if problems:
        raise StageError("invalid role manifest: " + "; ".join(problems))
    for name in sorted(REQUIRED_RUNTIME_FILES):
        source = active / name
        try:
            source_stat = source.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StageError(f"projected source is unavailable: {name}") from exc
        snapshots.append(_copy_regular(source, temporary / name, active))
    layout_error = explicit_layout_error(temporary, allow_rollback_backups=False)
    if layout_error:
        raise StageError(layout_error)
    return tuple(snapshots), projection_snapshot


def _revalidate_sources(
    snapshots: tuple[tuple[Path, tuple[int, ...]], ...],
) -> None:
    for source, expected in snapshots:
        try:
            current = source.lstat()
        except OSError as exc:
            raise StageError("source changed before staging publication") from exc
        if _stat_fingerprint(current) != expected:
            raise StageError("source changed before staging publication")


def _revalidate_projection(
    snapshot: tuple[tuple[Path, tuple[int, ...] | None], ...],
) -> None:
    for source, expected in snapshot:
        try:
            current = _stat_fingerprint(source.lstat())
        except FileNotFoundError:
            current = None
        except OSError as exc:
            raise StageError("active projection changed before publication") from exc
        if current != expected:
            raise StageError("active projection changed before publication")


def _read_stable_required(
    source: Path,
    root: Path,
) -> tuple[bytes, tuple[int, ...]]:
    before = _regular_source(source, root)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open(source, flags)
        opened = os.fstat(fd)
        if _stat_fingerprint(opened) != _stat_fingerprint(before):
            raise StageError("required input replaced while hashing")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            content = handle.read()
        after_fd = os.fstat(fd)
        after_path = source.lstat()
        if (
            _stat_fingerprint(after_fd) != _stat_fingerprint(before)
            or _stat_fingerprint(after_path) != _stat_fingerprint(before)
        ):
            raise StageError("required input changed while hashing")
        return content, _stat_fingerprint(before)
    except OSError as exc:
        raise StageError("required input is unavailable") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _required_input_projection(root: Path) -> tuple[str, str, str, str, str, str]:
    """Hash config, policy, role manifest, and exact hook artifacts."""
    policy_paths = (
        root / "AGENTS.override.md",
        root / "AGENTS.md",
        root / "pilotfish" / "AGENTS.md",
    )
    policy_projection: list[tuple[Path, tuple[int, ...] | None]] = []
    for path in policy_paths:
        try:
            fingerprint = _stat_fingerprint(path.lstat())
        except FileNotFoundError:
            fingerprint = None
        except OSError as exc:
            raise StageError("effective policy is unavailable") from exc
        policy_projection.append((path, fingerprint))
    user_policies = [
        path
        for path in policy_paths[:2]
        if path.is_file() and path.read_text(encoding="utf-8").strip()
    ]
    if len(user_policies) > 1:
        raise StageError("both policy files are non-empty")
    policies = user_policies or [policy_paths[2]]
    if not policies[0].is_file():
        raise StageError("no effective or source-only policy file is available")

    config_content, config_fingerprint = _read_stable_required(
        root / "config.toml",
        root,
    )
    if policies[0].is_symlink():
        policy_content, policy_snapshots = _read_proven_policy_symlink(
            policies[0],
            root,
            _active_policy_digest(root, policies[0].relative_to(root).as_posix()),
        )
    else:
        policy_content, policy_fingerprint = _read_stable_required(
            policies[0],
            root,
        )
        policy_snapshots = ((policies[0], policy_fingerprint),)
    hooks_content, hooks_fingerprint = _read_stable_required(
        root / "hooks.json",
        root,
    )
    hook_script_content, hook_script_fingerprint = _read_stable_required(
        root / HOOK_SCRIPT,
        root,
    )
    hooks_root = root / "hooks"
    hooks_root_fingerprint = _stat_fingerprint(
        _directory_source(hooks_root, root)
    )
    agents = root / "agents"
    agents_fingerprint = _stat_fingerprint(_directory_source(agents, root))
    try:
        manifest_paths = tuple(
            sorted(
                agents.rglob("*.toml"),
                key=lambda path: path.relative_to(agents).as_posix(),
            )
        )
    except OSError as exc:
        raise StageError("role manifest is unavailable") from exc
    if not manifest_paths:
        raise StageError("role manifest is unavailable")

    directories = {agents}
    for path in manifest_paths:
        parent = path.parent
        while True:
            directories.add(parent)
            if parent == agents:
                break
            parent = parent.parent
    directory_snapshots = [
        (
            directory,
            (
                agents_fingerprint
                if directory == agents
                else _stat_fingerprint(_directory_source(directory, root))
            ),
        )
        for directory in sorted(directories)
    ]

    manifest_entries: list[tuple[Path, bytes]] = []
    file_snapshots: list[tuple[Path, tuple[int, ...]]] = []
    for path in manifest_paths:
        content, fingerprint = _read_stable_required(path, root)
        manifest_entries.append((path.relative_to(agents), content))
        file_snapshots.append((path, fingerprint))

    _revalidate_sources(
        (
            (root / "config.toml", config_fingerprint),
            *policy_snapshots,
            (root / "hooks.json", hooks_fingerprint),
            (root / HOOK_SCRIPT, hook_script_fingerprint),
            (hooks_root, hooks_root_fingerprint),
            *file_snapshots,
            *directory_snapshots,
        )
    )
    _revalidate_projection(tuple(policy_projection))
    try:
        manifest_paths_after = tuple(
            sorted(
                agents.rglob("*.toml"),
                key=lambda path: path.relative_to(agents).as_posix(),
            )
        )
    except OSError as exc:
        raise StageError("role manifest changed while hashing") from exc
    if manifest_paths_after != manifest_paths:
        raise StageError("role manifest changed while hashing")

    manifest_digest = hashlib.sha256()
    for relative, content in manifest_entries:
        encoded = relative.as_posix().encode("utf-8")
        manifest_digest.update(len(encoded).to_bytes(8, "big"))
        manifest_digest.update(encoded)
        manifest_digest.update(len(content).to_bytes(8, "big"))
        manifest_digest.update(content)
    try:
        hooks_projection = semantic_projection_digest(
            hooks_content,
            CURRENT_PROJECTION_ID,
        )
    except HookRegistrationError as exc:
        raise StageError(f"required hook registration is invalid: {exc}") from exc
    return (
        hashlib.sha256(project_config_bytes(config_content)).hexdigest(),
        policies[0].name,
        hashlib.sha256(policy_content).hexdigest(),
        manifest_digest.hexdigest(),
        hooks_projection,
        hashlib.sha256(hook_script_content).hexdigest(),
    )


def publish_no_replace(
    temporary: Path,
    destination: Path,
    active: Path,
    source_snapshots: tuple[tuple[Path, tuple[int, ...]], ...],
    projection_snapshot: tuple[tuple[Path, tuple[int, ...] | None], ...],
) -> None:
    """Use Darwin's exclusive atomic directory rename, never overwriting."""
    if sys.platform != "darwin":
        raise StageError("atomic no-replace publication is unavailable")
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    renameatx_np = getattr(libc, "renameatx_np", None)
    if renameatx_np is None:
        raise StageError("atomic no-replace publication is unavailable")
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    # Darwin: AT_FDCWD and RENAME_EXCL.  RENAME_EXCL is the no-replace flag.
    _revalidate_sources(source_snapshots)
    _revalidate_projection(projection_snapshot)
    try:
        active_required = _required_input_projection(active)
        staged_required = _required_input_projection(temporary)
    except StageError as exc:
        raise StageError("required inputs changed before publication") from exc
    if active_required != staged_required:
        raise StageError("required inputs changed before publication")
    staged_hooks, _ = _read_stable_required(
        temporary / "hooks.json",
        temporary,
    )
    source_hooks, _ = _read_stable_regular(SOURCE_HOOK_REGISTRATION)
    if staged_hooks != source_hooks:
        raise StageError("clean staged hooks.json changed before publication")
    _revalidate_sources(source_snapshots)
    result = renameatx_np(-2, os.fsencode(temporary), -2, os.fsencode(destination), 0x00000004)
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise StageError("staged destination appeared during publication")
        raise StageError(f"atomic no-replace publication failed: {os.strerror(error)}")


def _cleanup_temporary(path: Path) -> None:
    """Remove copied auth/runtime data; cleanup failure is a staging failure."""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        # Retry without shutil so a partial permission failure cannot leave auth.
        try:
            for root, directories, files in os.walk(path, topdown=False):
                for name in files:
                    candidate = Path(root) / name
                    os.chmod(candidate, 0o600)
                    candidate.unlink()
                for name in directories:
                    candidate = Path(root) / name
                    os.chmod(candidate, 0o700)
                    candidate.rmdir()
            os.chmod(path, 0o700)
            path.rmdir()
        except OSError as exc:
            raise StageError("unrecoverable staging cleanup; sensitive temporary data remains") from exc
    if path.exists():
        raise StageError("unrecoverable staging cleanup; sensitive temporary data remains")


def materialize(active_home: Path, staged_home: Path) -> Path:
    active, staged = canonical_home_pair(active_home, staged_home)
    temporary: Path | None = None
    try:
        temporary = Path(tempfile.mkdtemp(prefix=f".{staged.name}.pilotfish-stage-", dir=staged.parent))
        source_snapshots, projection_snapshot = _copy_inputs(active, temporary)
        publish_no_replace(
            temporary,
            staged,
            active,
            source_snapshots,
            projection_snapshot,
        )
        temporary = None
        return staged
    except Exception as exc:
        if temporary is not None:
            try:
                _cleanup_temporary(temporary)
            except StageError as cleanup_error:
                raise cleanup_error from exc
        if isinstance(exc, StageError):
            raise
        raise StageError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-codex-home", type=Path, required=True)
    parser.add_argument("--staged-codex-home", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        staged = materialize(args.active_codex_home, args.staged_codex_home)
    except StageError as exc:
        print(f"stage_materialization_failed: {exc}", file=sys.stderr)
        return 1
    print(staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
