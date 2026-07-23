#!/usr/bin/env python3
"""Install the one native Codex rust-v0.145.0 Pilotfish target.

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
from validate_agents import ROLES, validate_agent, validate_dir, validate_multi_agent_v2_config

PINNED_CODEX_VERSION = (0, 145, 0)
MARKER_BEGIN = "<!-- pilotfish-codex:begin -->"
MARKER_END = "<!-- pilotfish-codex:end -->"
NATIVE_TABLE = ("[features.multi_agent_v2]", "enabled = true", "max_concurrent_threads_per_session = 4")
LEGACY_PATHS = frozenset({
    "features.multi_agent", "features.multi_agent_v2.tool_namespace",
    "features.multi_agent_v2.hide_spawn_agent_metadata", "agents.max_threads",
    "agents.max_concurrent_threads_per_session",
})


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


def _inline_or_dotted_v2(text: str) -> bool:
    """Reject only forms whose rewrite would collide with a table header."""
    return bool(re.search(r"^\s*features\.multi_agent_v2\s*=|^\s*multi_agent_v2\s*=\s*\{", text, re.M))


def merge_config_text(text: str, *, owned_legacy: frozenset[str] = frozenset()) -> tuple[str, list[str]]:
    """Make the native V2 table while preserving unowned legacy settings."""
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
    v2 = features.get("multi_agent_v2")
    if v2 is not None and not isinstance(v2, (dict, bool)):
        raise InstallAbort("features.multi_agent_v2 must be a boolean or table")
    if _inline_or_dotted_v2(text):
        raise InstallAbort("features.multi_agent_v2 uses inline or dotted TOML syntax that cannot be safely rewritten")
    if v2 is False or (isinstance(v2, dict) and v2.get("enabled") is False):
        raise InstallAbort("features.multi_agent_v2 is explicitly disabled")
    concurrency = v2.get("max_concurrent_threads_per_session") if isinstance(v2, dict) else None
    if concurrency is not None and (type(concurrency) is not int or not 1 <= concurrency <= 8):
        raise InstallAbort("native V2 concurrency must be an integer from 1 to 8")
    fallback = agents.get("max_concurrent_threads_per_session")
    if fallback is not None and (type(fallback) is not int or fallback != 3):
        raise InstallAbort("agents.max_concurrent_threads_per_session conflicts with native V2 total 4")

    lines = text.splitlines(keepends=True)
    nl = _newline(text)
    notes: list[str] = []
    if "model" not in config:
        index = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
        lines[index:index] = [f'model = "gpt-5.6-sol"{nl}']
        notes.append("set model = gpt-5.6-sol")
    if isinstance(v2, bool):
        # Scalar true must be removed before the explicit table can exist.
        lines = [line for line in lines if not re.match(r"^\s*(?:features\.)?multi_agent_v2\s*=", line)]
        notes.append("converted scalar multi_agent_v2 to native table")
    lines = _set_table_key(lines, "features.multi_agent_v2", "enabled", "true", nl)
    lines = _set_table_key(lines, "features.multi_agent_v2", "max_concurrent_threads_per_session", "4", nl)
    notes.append("normalized native V2 total concurrency to 4")
    for table, key, path in (
        ("features", "multi_agent", "features.multi_agent"),
        ("features.multi_agent_v2", "tool_namespace", "features.multi_agent_v2.tool_namespace"),
        ("features.multi_agent_v2", "hide_spawn_agent_metadata", "features.multi_agent_v2.hide_spawn_agent_metadata"),
        ("agents", "max_threads", "agents.max_threads"),
        ("agents", "max_concurrent_threads_per_session", "agents.max_concurrent_threads_per_session"),
    ):
        if path in owned_legacy:
            lines = _remove_table_key(lines, table, key)
            notes.append(f"removed owned legacy key {path}")
        elif (table == "features" and key in features) or (table == "agents" and key in agents) or (isinstance(v2, dict) and table.endswith("v2") and key in v2):
            notes.append(f"legacy_key_unowned: preserved {path}")
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
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallAbort("install state is invalid; resolve it before writing") from exc
    if not isinstance(state, dict) or state.get("status") != "committed":
        raise InstallAbort("install state is not a committed transaction")
    return state


def _owned_legacy_from_state(state: dict | None, config_text: str, home: Path) -> frozenset[str]:
    """Trust cleanup ownership only after every committed target still matches."""
    if not state:
        return frozenset()
    targets = state.get("target_fingerprints")
    originals = state.get("original_targets")
    required_targets = {"config.toml", *(f"agents/{role}.toml" for role in ROLES)}
    if not isinstance(targets, dict) or not isinstance(originals, dict) or not required_targets <= set(targets) or set(targets) != set(originals):
        return frozenset()
    for relative, fingerprint in targets.items():
        original = originals.get(relative)
        if not isinstance(relative, str) or not isinstance(fingerprint, str) or not isinstance(original, dict) or not {"present", "sha256", "bytes_b64"} <= set(original):
            return frozenset()
        target = home / relative
        if not target.is_file() or _sha256_bytes(target.read_bytes()) != fingerprint:
            raise InstallAbort("committed install state is stale; operator resolution required")
    config_fingerprint = targets.get("config.toml")
    if config_fingerprint != _sha256_bytes(config_text.encode()):
        return frozenset()
    paths = state.get("owned_legacy", {})
    if not isinstance(paths, dict):
        raise InstallAbort("install state ownership evidence is malformed")
    trusted: set[str] = set()
    for path, evidence in paths.items():
        if path not in LEGACY_PATHS or not isinstance(evidence, dict):
            continue
        present, digest, encoded = (evidence.get("original_present"), evidence.get("original_sha256"), evidence.get("original_bytes_b64"))
        if not isinstance(present, bool) or not isinstance(digest, str) or not isinstance(encoded, str):
            continue
        try:
            original = base64.b64decode(encoded, validate=True)
        except ValueError:
            continue
        if not present or _sha256_bytes(original) != digest:
            continue
        trusted.add(path)
    return frozenset(trusted)


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


def _commit(writes: list[tuple[Path, bytes, int, bytes | None]], stamp: str,
            *, agents_root: Path, codex_home: Path, policy_path: Path) -> None:
    _assert_active_instruction_file(codex_home, policy_path)
    staged: list[tuple[Path, Path, bytes | None, bool]] = []
    expected_post = {_destination(path): payload for path, payload, _, _ in writes}
    agents_root.mkdir(parents=True, exist_ok=True)
    _assert_agents_root(agents_root, codex_home)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    agents_fd = os.open(agents_root, flags)
    try:
        for path, payload, mode, original in writes:
            is_role = path.parent == agents_root
            if is_role:
                _assert_agents_root(agents_root, codex_home)
            dest = _destination(path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp_dir = codex_home if is_role else dest.parent
            fd, name = tempfile.mkstemp(prefix=f".{dest.name}.pilotfish-", dir=temp_dir)
            temp = Path(name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temp, stat.S_IMODE(dest.stat().st_mode) if dest.is_file() else mode)
            staged.append((dest, temp, original, is_role))
        for dest, _, original, _ in staged:
            actual = dest.read_bytes() if dest.is_file() else None
            if actual != original:
                raise InstallAbort(f"{dest} changed while install was planned")
        _assert_active_instruction_file(codex_home, policy_path)
        for dest, _, original, _ in staged:
            if original is not None:
                shutil.copy2(dest, dest.with_name(f"{dest.name}.pilotfish-codex-{stamp}"))
        applied: list[tuple[Path, bytes | None]] = []
        try:
            for dest, temp, original, is_role in staged:
                if is_role:
                    _assert_agents_root(agents_root, codex_home)
                    os.replace(temp, dest.name, dst_dir_fd=agents_fd)
                else:
                    os.replace(temp, dest)
                applied.append((dest, original))
            for destination, expected in expected_post.items():
                if not destination.is_file() or destination.read_bytes() != expected:
                    raise InstallAbort("post-write target fingerprint mismatch")
            _assert_active_instruction_file(codex_home, policy_path)
        except (OSError, InstallAbort):
            for dest, original in reversed(applied):
                if original is None: dest.unlink(missing_ok=True)
                else: _atomic_write(dest, original, stat.S_IMODE(dest.stat().st_mode))
            raise
    finally:
        os.close(agents_fd)
        for _, temp, _, _ in staged:
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
    state = _load_state(codex_home)
    config_path = codex_home / "config.toml"
    config_text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    owned = _owned_legacy_from_state(state, config_text, codex_home) | _backup_owned_legacy(codex_home, config_text)
    new_config, notes = merge_config_text(config_text, owned_legacy=owned)
    policy_template = (source_root / "templates" / "agents-md.orchestration.md").read_text(encoding="utf-8")
    policy_path = active_instruction_file(codex_home)
    policy_text = policy_path.read_text(encoding="utf-8") if policy_path.is_file() else ""
    new_policy, policy_action = merge_instruction_text(policy_text, policy_template)
    writes: list[tuple[Path, bytes, int, bytes | None]] = []
    if new_config != config_text:
        writes.append((config_path, new_config.encode(), 0o600, config_text.encode() if config_path.is_file() else None))
    agents = codex_home / "agents"
    _assert_agents_root(agents, codex_home)
    existing = list(agents.rglob("*.toml")) if agents.is_dir() else []
    for role in sorted(ROLES):
        source = source_root / "templates" / "agents" / f"{role}.toml"
        payload = source.read_bytes()
        target = agents / f"{role}.toml"
        if target.exists() and target.read_bytes() != payload:
            raise InstallAbort(f"installed_role_drift: agents/{role}.toml requires explicit replacement approval")
        if not target.exists():
            writes.append((target, payload, 0o600, None))
    if new_policy != policy_text:
        writes.append((policy_path, new_policy.encode(), 0o644, policy_text.encode() if policy_path.is_file() else None))
    planned_roles = {p.stem for p in existing} | set(ROLES)
    extras = planned_roles - ROLES
    if extras:
        raise InstallAbort(f"role_manifest_extra: {', '.join(sorted(extras))}")
    errors, _ = validate_multi_agent_v2_config(tomllib.loads(new_config))
    if errors:
        raise InstallAbort("planned native config invalid: " + "; ".join(errors))
    inventory = [config_path, policy_path, *(agents / f"{role}.toml" for role in sorted(ROLES))]
    pre_targets: dict[str, dict[str, object]] = {}
    for path in inventory:
        relative = path.relative_to(codex_home).as_posix()
        current = path.read_bytes() if path.is_file() else None
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
    if dry_run:
        print("would change" if writes else "already up to date; nothing to change")
        return 0
    if writes:
        pending = _state_path(codex_home).with_suffix(".json.pending")
        pending_record = {"status": "pending", "original_targets": pre_targets,
                          "owned_legacy": {path: {"original_present": True, "original_sha256": _sha256_bytes(config_text.encode()),
                        "original_bytes_b64": base64.b64encode(config_text.encode()).decode()} for path in owned}}
        _atomic_write(pending, json.dumps(pending_record, sort_keys=True).encode() + b"\n", 0o600)
        state_path = _state_path(codex_home)
        state_published = False
        try:
            _commit(writes, _stamp(), agents_root=agents, codex_home=codex_home, policy_path=policy_path)
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
            ownership = {
                path: {"original_present": True, "original_sha256": _sha256_bytes(config_text.encode()),
                       "original_bytes_b64": base64.b64encode(config_text.encode()).decode()}
                for path in owned
            }
            record = {"status": "committed", "target_fingerprints": expected_inventory,
                      "original_targets": pre_targets, "owned_legacy": ownership}
            _assert_active_instruction_file(codex_home, policy_path)
            _atomic_write(state_path, json.dumps(record, sort_keys=True).encode() + b"\n", 0o600)
            state_published = True
            _assert_active_instruction_file(codex_home, policy_path)
            if any(not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_inventory[path.relative_to(codex_home).as_posix()] for path in inventory):
                raise InstallAbort("post-sidecar transaction fingerprint mismatch")
        except BaseException as exc:
            if state_published:
                state_path.unlink(missing_ok=True)
            for path in inventory:
                evidence = pre_targets[path.relative_to(codex_home).as_posix()]
                if evidence["present"]:
                    _atomic_write(path, base64.b64decode(evidence["bytes_b64"]), 0o600)
                else:
                    path.unlink(missing_ok=True)
            aborted = dict(pending_record, status="aborted", error=type(exc).__name__)
            _atomic_write(pending, json.dumps(aborted, sort_keys=True).encode() + b"\n", 0o600)
            raise
        pending.unlink()
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
