#!/usr/bin/env python3
"""Install the native Codex Pilotfish contract without a release lock.

This route refuses malformed version output and ambiguous ownership. It never
selects the retired adapter route. Existing user bytes are preserved unless a
committed Pilotfish sidecar proves that a legacy path is installer-owned.
"""

from __future__ import annotations

import argparse
import base64
import copy
from dataclasses import dataclass
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
    windows_compatibility_warnings,
)
from validate_agents import ROLES, validate_agent, validate_agents_config

IS_WINDOWS = sys.platform == "win32"
MARKER_BEGIN = "<!-- pilotfish-codex:begin -->"
MARKER_END = "<!-- pilotfish-codex:end -->"
OLD_V2_KEYS = frozenset({"enabled", "max_concurrent_threads_per_session"})
LEGACY_PATHS = frozenset({
    "features.multi_agent", "features.multi_agent_v2.tool_namespace",
    "features.multi_agent_v2.hide_spawn_agent_metadata", "agents.max_threads",
    "agents.max_concurrent_threads_per_session",
})
CANONICAL_ROLE_UPGRADE_DIGESTS = {
    "plan-verifier": frozenset({
        "6cb7b398c28269d9019a181e5faacd255d9bccc384b8bee2a99a4ca41b9d53fc",
        "5d46fbeda04d159a84614d9f69c6b30c30d4a53a5577d023bddfb3da77a6b6f9",
        "b4d2a70d8b762f574c05b7e1fa285b05796ebae3f506e331c736d9cd504e6723",
        "dd3b318d3b771227c38110275b68d50c5fccf2ead0d5e4c9876909b773a5748c",
        "c552938705065c826da9a3cbaf09c2fbbaa9fde4adb1f691a59b694d8468f541",
        "e29dff16ee22d8dcf60f214c7226eba52e9c1d5fca475d47ca750c8850a32852",
        "5cfd8630f9807a45eb18bfd587ab12dc41e8c06de82872ec6aa87f2c3e4c8fe0",
    }),
    "security-reviewer": frozenset({
        "94d7de12d1cb197c98e83c2f78d402cf3fb393e860feee1e146f5b6294075d27",
    }),
    "security-executor": frozenset({
        "1424995ef9b2a3d63a424a75ebf563fa329bf7badbbf5fe8eadc2c69649d3068",
        "90568cf473e0e8025bfbd2a22a9c46d4db6d6b4ed0d344c975f4116365da9ce0",
    }),
    "verifier": frozenset({
        "4e93fd5660b5f08c0362f632ef2a4f0b85ac33176a6def57fc768aeda95e136d",
        "5d46fbeda04d159a84614d9f69c6b30c30d4a53a5577d023bddfb3da77a6b6f9",
        "b4d2a70d8b762f574c05b7e1fa285b05796ebae3f506e331c736d9cd504e6723",
        "9478638b7456b6e4120ecd5a59408431d886c87ae1a7391aade61bc84d722e2e",
        "07e9864edc5734644557bff9c26a41476a30620779980658954e07ff865c9cb8",
    }),
}


class InstallAbort(Exception):
    """The caller must resolve this state before any target write."""


@dataclass(frozen=True)
class PolicyTargetIdentity:
    """Identity of the policy path and its resolved write target."""

    link_path: Path
    target_path: Path
    policy_root: Path | None
    symlink: bool
    link_dev: int | None
    link_ino: int | None
    target_dev: int
    target_ino: int
    target_sha256: str


MIN_COMPATIBLE_CODEX_VERSION = (0, 147, 0)
PILOTFISH_PLUGIN_NAME = "pilotfish-codex"
PILOTFISH_PLUGIN_VERSION = "1.8.0-rc.1"
RUNTIME_STATUSES = frozenset({"integrated", "integrated-plugin-unavailable"})
RECONCILIATION_STATE_VERSION = 4


def codex_version_token(output: str) -> str | None:
    """Extract exactly one semantic version token for evidence recording."""
    tokens = re.findall(
        r"(?<![0-9A-Za-z_.-])(\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?)(?![0-9A-Za-z_.-])",
        output,
    )
    return tokens[0] if len(tokens) == 1 else None


def parse_codex_version(output: str) -> tuple[int, int, int] | None:
    """Parse exactly one semantic version, retaining only its numeric base."""
    token = codex_version_token(output)
    if token is None:
        return None
    return tuple(int(part) for part in token.split("-", 1)[0].split("."))  # type: ignore[return-value]


_PLUGIN_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _plugin_version_key(
    value: str,
) -> tuple[int, int, int, int, tuple[tuple[int, int, str], ...]] | None:
    """Return a comparable SemVer precedence key for plugin versions."""
    match = _PLUGIN_VERSION_RE.fullmatch(value)
    if match is None:
        return None
    prerelease = match.group(4)
    if prerelease is None:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), 1, ())
    identifiers: list[tuple[int, int, str]] = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            if len(identifier) > 1 and identifier.startswith("0"):
                return None
            identifiers.append((0, int(identifier), ""))
        else:
            identifiers.append((1, 0, identifier))
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        0,
        tuple(identifiers),
    )


def is_parseable_codex_output(output: str) -> bool:
    """Validate one version token without imposing a release pin."""
    version = parse_codex_version(output)
    return codex_version_token(output) is not None and version is not None


def is_compatible_codex_output(output: str) -> bool:
    """Accept the minimum native contract version and every later release."""
    version = parse_codex_version(output)
    return version is not None and version >= MIN_COMPATIBLE_CODEX_VERSION


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _capture_policy_identity(
    policy_path: Path,
    *,
    follow_policy_symlink: bool,
    policy_root: Path | None,
) -> PolicyTargetIdentity | None:
    """Capture an exact policy target before planning any policy write."""
    if not policy_path.exists() and not policy_path.is_symlink():
        return None
    if policy_path.is_symlink():
        if not follow_policy_symlink:
            raise InstallAbort(
                "active policy path is a symlink; explicit policy integration is required"
            )
        if policy_root is None:
            raise InstallAbort(
                "policy-root is required when following an active policy symlink"
            )
        try:
            root = policy_root.resolve(strict=True)
        except OSError as exc:
            raise InstallAbort("configured policy root is unavailable") from exc
        if not root.is_dir():
            raise InstallAbort("configured policy root is not a directory")
        try:
            target = policy_path.resolve(strict=True)
        except OSError as exc:
            raise InstallAbort("active policy symlink target is unavailable") from exc
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise InstallAbort("policy target escapes configured root") from exc
        link_stat = policy_path.lstat()
        target_stat = target.stat()
        if not stat.S_ISREG(target_stat.st_mode):
            raise InstallAbort("active policy symlink target is not a regular file")
        return PolicyTargetIdentity(
            link_path=policy_path,
            target_path=target,
            policy_root=root,
            symlink=True,
            link_dev=link_stat.st_dev,
            link_ino=link_stat.st_ino,
            target_dev=target_stat.st_dev,
            target_ino=target_stat.st_ino,
            target_sha256=_sha256_bytes(target.read_bytes()),
        )
    if not policy_path.is_file():
        raise InstallAbort("active policy path is not a regular file")
    target = policy_path.resolve(strict=True)
    target_stat = target.stat()
    return PolicyTargetIdentity(
        link_path=policy_path,
        target_path=target,
        policy_root=None,
        symlink=False,
        link_dev=None,
        link_ino=None,
        target_dev=target_stat.st_dev,
        target_ino=target_stat.st_ino,
        target_sha256=_sha256_bytes(target.read_bytes()),
    )


def _assert_policy_identity(
    identity: PolicyTargetIdentity | None,
    *,
    expected_sha256: str | None = None,
) -> None:
    """Reject a policy link/target replacement or concurrent content change."""
    if identity is None:
        return
    current = _capture_policy_identity(
        identity.link_path,
        follow_policy_symlink=identity.symlink,
        policy_root=identity.policy_root,
    )
    if current is None or (
        current.link_path != identity.link_path
        or current.target_path != identity.target_path
        or current.policy_root != identity.policy_root
        or current.symlink != identity.symlink
        or current.link_dev != identity.link_dev
        or current.link_ino != identity.link_ino
    ):
        raise InstallAbort("policy target changed while install was planned")
    if expected_sha256 is None:
        if current.target_dev != identity.target_dev or current.target_ino != identity.target_ino:
            raise InstallAbort("policy target changed while install was planned")
        expected_sha256 = identity.target_sha256
    if current.target_sha256 != expected_sha256:
        raise InstallAbort("policy target changed while install was planned")


def _policy_identity_record(identity: PolicyTargetIdentity | None) -> dict[str, object] | None:
    if identity is None:
        return None
    return {
        "link_path": str(identity.link_path),
        "target_path": str(identity.target_path),
        "policy_root": str(identity.policy_root) if identity.policy_root else "",
        "symlink": identity.symlink,
        "link_dev": identity.link_dev,
        "link_ino": identity.link_ino,
        "target_dev": identity.target_dev,
        "target_ino": identity.target_ino,
        "target_sha256": identity.target_sha256,
    }


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


def _set_root_key(lines: list[str], key: str, value: str, nl: str) -> list[str]:
    """Set a TOML root key without placing it inside the next table."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    table_start = next(
        (index for index, line in enumerate(lines) if line.split("#", 1)[0].strip().startswith("[")),
        len(lines),
    )
    result = list(lines)
    for index in range(table_start):
        if pattern.match(result[index]):
            ending = "\r\n" if result[index].endswith("\r\n") else "\n"
            result[index] = f"{key} = {value}{ending}"
            return result
    insertion = table_start
    if insertion > 0 and result[insertion - 1].strip():
        result.insert(insertion, nl)
        insertion += 1
    result.insert(insertion, f"{key} = {value}{nl}")
    return result


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
    """Render Codex 0.147's native routing and decision-card settings."""
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
    if agents and set(agents) != OLD_V2_KEYS:
        raise InstallAbort("agents table has unsupported or unowned keys")
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
    if set(agents) == OLD_V2_KEYS:
        if agents.get("enabled") is not True:
            raise InstallAbort("agents.enabled conflicts with native migration")
        if agents.get("max_concurrent_threads_per_session") != 3:
            raise InstallAbort("agents.max_concurrent_threads_per_session conflicts with native child concurrency 3")
    root_concurrency = config.get("max_concurrent_threads_per_session")
    if root_concurrency is not None and (type(root_concurrency) is not int or root_concurrency != 3):
        raise InstallAbort("root max_concurrent_threads_per_session conflicts with native child concurrency 3")
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
        notes.append("migrated exact legacy V2 table to root child concurrency")
    if set(agents) == OLD_V2_KEYS:
        lines = _remove_table(lines, "agents")
        notes.append("migrated legacy agents concurrency table to root child concurrency")
    if "features.multi_agent" in owned_legacy:
        lines = _remove_table_key(lines, "features", "multi_agent")
        notes.append("removed owned legacy key features.multi_agent")
    lines = _set_table_key(lines, "features", "default_mode_request_user_input", "true", nl)
    notes.append("enabled native default-mode decision cards")
    lines = _set_root_key(lines, "max_concurrent_threads_per_session", "3", nl)
    notes.append("normalized root child concurrency to 3")
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


def _decode_instruction_bytes(raw: bytes | None) -> tuple[str, str]:
    if raw is None:
        return "", "\n"
    text = raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), newline


def _encode_instruction_text(text: str, newline: str) -> bytes:
    if newline == "\r\n":
        text = text.replace("\n", "\r\n")
    return text.encode("utf-8")


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


def _policy_ownership(home: Path, user_policy: Path, pilotfish_policy: Path) -> dict[str, dict[str, str]]:
    user_bytes = user_policy.read_bytes() if user_policy.is_file() else None
    pilotfish_bytes = pilotfish_policy.read_bytes() if pilotfish_policy.is_file() else None
    return {
        "user_policy": {
            "path": user_policy.relative_to(home).as_posix(),
            "owner": "user" if user_bytes is not None else "none",
            "status": "blocked-symlink" if user_policy.is_symlink() else "integrated",
            "sha256": _sha256_bytes(user_bytes) if user_bytes is not None else "",
        },
        "pilotfish_policy": {
            "path": pilotfish_policy.relative_to(home).as_posix(),
            "owner": "pilotfish",
            "status": "integrated",
            "sha256": _sha256_bytes(pilotfish_bytes) if pilotfish_bytes is not None else "",
        },
    }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _plugin_source_digest(plugin_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in plugin_root.rglob("*") if path.is_file()):
        digest.update(path.relative_to(plugin_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _codex_cli() -> str:
    for candidate in ("codex", "codex.exe", "codex.cmd"):
        if shutil.which(candidate):
            return candidate
    return "codex"


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(left)))) == os.path.normcase(
        os.path.realpath(os.path.abspath(str(right)))
    )


def _plugin_descriptor(source_root: Path, status: str) -> dict[str, str]:
    plugin_root = source_root / "plugin"
    return {
        "name": PILOTFISH_PLUGIN_NAME,
        "version": PILOTFISH_PLUGIN_VERSION,
        "status": status,
        "source_sha256": _plugin_source_digest(plugin_root)
        if plugin_root.is_dir() else "",
    }


def _installed_plugin_rows(codex_home: Path) -> list[dict[str, object]] | None:
    """Read Codex's installed-plugin inventory when the CLI exposes it."""
    environment = dict(os.environ)
    environment["CODEX_HOME"] = str(codex_home)
    try:
        discovered = subprocess.run(
            [_codex_cli(), "plugin", "list", "--json"],
            capture_output=True, text=True, check=False, env=environment,
        )
    except OSError:
        return None
    if discovered.returncode != 0:
        return None
    try:
        document = json.loads(discovered.stdout)
        rows = document.get("installed", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None
    return rows


def _assert_plugin_not_newer(
    *,
    source_root: Path,
    codex_home: Path,
    allow_downgrade: bool,
) -> None:
    """Refuse replacing an installed newer plugin without explicit approval."""
    if allow_downgrade or not (source_root / "plugin").is_dir():
        return
    rows = _installed_plugin_rows(codex_home)
    if rows is None:
        return
    source_version = _plugin_version_key(PILOTFISH_PLUGIN_VERSION)
    if source_version is None:
        raise InstallAbort("source plugin version is malformed")
    for row in rows:
        if (
            row.get("name") != PILOTFISH_PLUGIN_NAME
            or row.get("marketplaceName") != PILOTFISH_PLUGIN_NAME
        ):
            continue
        installed = row.get("version")
        if not isinstance(installed, str):
            raise InstallAbort("installed plugin version is malformed")
        installed_version = _plugin_version_key(installed)
        if installed_version is None:
            raise InstallAbort("installed plugin version is malformed")
        if installed_version > source_version:
            raise InstallAbort(
                "installed plugin is newer than source; explicit downgrade approval required"
            )


def _plugin_is_installed(*, source_root: Path, codex_home: Path) -> bool:
    plugin_root = source_root / "plugin"
    installed_plugins = _installed_plugin_rows(codex_home)
    if installed_plugins is None:
        return False
    return any(
        isinstance(item, dict)
        and item.get("name") == PILOTFISH_PLUGIN_NAME
        and item.get("marketplaceName") == PILOTFISH_PLUGIN_NAME
        and item.get("version") == PILOTFISH_PLUGIN_VERSION
        and item.get("enabled") is True
        and isinstance(item.get("marketplaceSource"), dict)
        and _same_path(Path(str(item["marketplaceSource"].get("source", ""))), plugin_root)
        for item in installed_plugins
    )


def _probe_plugin(*, source_root: Path, codex_home: Path, enabled: bool) -> dict[str, str]:
    if not enabled or not (source_root / "plugin").is_dir():
        return _plugin_descriptor(source_root, "unavailable")
    return _plugin_descriptor(
        source_root,
        "installed" if _plugin_is_installed(source_root=source_root, codex_home=codex_home)
        else "unavailable",
    )


def _install_plugin(
    *, source_root: Path, codex_home: Path, dry_run: bool, enabled: bool,
) -> dict[str, str]:
    """Install through Codex's marketplace/add contract, never an arbitrary path."""
    plugin_root = source_root / "plugin"
    if not plugin_root.is_dir():
        return _plugin_descriptor(source_root, "unavailable")
    source_digest = _plugin_source_digest(plugin_root)
    if not enabled:
        return _plugin_descriptor(source_root, "unavailable")
    result = {
        "name": PILOTFISH_PLUGIN_NAME,
        "version": PILOTFISH_PLUGIN_VERSION,
        "status": "planned" if dry_run else "unavailable",
        "source_sha256": source_digest,
    }
    if dry_run:
        return result
    environment = dict(os.environ)
    environment["CODEX_HOME"] = str(codex_home)
    try:
        marketplace = subprocess.run(
            [_codex_cli(), "plugin", "marketplace", "add", str(plugin_root), "--json"],
            capture_output=True, text=True, check=False, env=environment,
        )
        marketplaces = subprocess.run(
            [_codex_cli(), "plugin", "marketplace", "list", "--json"],
            capture_output=True, text=True, check=False, env=environment,
        )
        try:
            marketplace_rows = json.loads(marketplaces.stdout).get("marketplaces", [])
        except (json.JSONDecodeError, AttributeError):
            marketplace_rows = []
        marketplace_available = any(
            isinstance(item, dict)
            and item.get("name") == PILOTFISH_PLUGIN_NAME
            and _same_path(Path(str(item.get("root", ""))), plugin_root)
            for item in marketplace_rows
        )
        if marketplaces.returncode != 0 or not marketplace_available:
            return result
        installed = subprocess.run(
            [_codex_cli(), "plugin", "add", f"{PILOTFISH_PLUGIN_NAME}@{PILOTFISH_PLUGIN_NAME}", "--json"],
            capture_output=True, text=True, check=False, env=environment,
        )
    except OSError:
        return result
    if installed.returncode == 0 and _plugin_is_installed(
        source_root=source_root, codex_home=codex_home
    ):
        result["status"] = "installed"
    return result


def _remove_plugin(*, codex_home: Path) -> bool:
    environment = dict(os.environ)
    environment["CODEX_HOME"] = str(codex_home)
    try:
        removed = subprocess.run(
            [_codex_cli(), "plugin", "remove", f"{PILOTFISH_PLUGIN_NAME}@{PILOTFISH_PLUGIN_NAME}", "--json"],
            capture_output=True, text=True, check=False, env=environment,
        )
    except OSError:
        return False
    return removed.returncode == 0


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


def _home_relative_path(home: Path, relative: str, *, label: str) -> Path:
    """Resolve a manifest path while proving it remains inside Codex home."""
    candidate = home / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise InstallAbort(f"{label} escapes Codex home")
    try:
        candidate.resolve(strict=False).relative_to(home.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise InstallAbort(f"{label} escapes Codex home") from exc
    return candidate


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
    """Return only config state whose ownership belongs to Pilotfish.

    The main-session model and effort settings are user preferences. Pilotfish
    supplies defaults when absent but does not claim ownership of them.
    """
    return {
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


def _config_without_plugin_owned(data: dict) -> dict:
    """Drop only Pilotfish's marketplace/plugin entries for mutation checks."""
    result = copy.deepcopy(data)
    for table_name in ("plugins", "marketplaces", "marketplace"):
        table = result.get(table_name)
        if isinstance(table, dict):
            table.pop(PILOTFISH_PLUGIN_NAME, None)
            table.pop(f"{PILOTFISH_PLUGIN_NAME}@{PILOTFISH_PLUGIN_NAME}", None)
            if not table:
                result.pop(table_name, None)
        elif isinstance(table, list):
            result[table_name] = [
                entry for entry in table
                if not (
                    isinstance(entry, dict)
                    and entry.get("name") in {
                        PILOTFISH_PLUGIN_NAME,
                        f"{PILOTFISH_PLUGIN_NAME}@{PILOTFISH_PLUGIN_NAME}",
                    }
                )
            ]
            if not result[table_name]:
                result.pop(table_name, None)
    return result


def _validate_committed_state(
    state: dict,
    *,
    home: Path,
    policy_path: Path,
    config_snapshot: bytes | None,
    allow_policy_drift: bool = False,
) -> tuple[frozenset[str], bool, str, bool, str | None, frozenset[str]]:
    """Validate sidecar provenance, including event-bound hook ownership."""
    if not isinstance(state, dict) or state.get("status") != "committed":
        raise InstallAbort("install state is not a committed transaction")
    legacy_allowed = {
        "status", "target_fingerprints", "original_targets", "owned_legacy",
        "policy_ownership",
    }
    legacy_with_plugin = legacy_allowed | {"plugin", "runtime_status", "rollback_backups"}
    v2_allowed = legacy_allowed | {"state_version", "hook_registration", "policy_ownership"}
    v4_allowed = v2_allowed | {"reconciliation"}
    v2_pre_policy_ownership = (
        v2_allowed - {"policy_ownership"}
    )
    sha_re = re.compile(r"^[0-9a-f]{64}$")
    is_v2 = "state_version" in state
    if is_v2 and type(state["state_version"]) is int and state["state_version"] == 4:
        allowed_top = v4_allowed | {"plugin", "runtime_status", "rollback_backups"}
    elif is_v2 and type(state["state_version"]) is int and state["state_version"] == 3:
        allowed_top = v2_allowed | {"plugin", "runtime_status", "rollback_backups"}
    else:
        allowed_top = v2_allowed if is_v2 else legacy_allowed
    accepted_shapes = [allowed_top]
    if not is_v2:
        accepted_shapes.append(legacy_with_plugin)
    if is_v2 and state.get("state_version") == 2:
        accepted_shapes.append(v2_pre_policy_ownership)
    if set(state) not in accepted_shapes:
        raise InstallAbort("install state has missing or unknown fields")
    if is_v2 and (
        type(state["state_version"]) is not int or state["state_version"] not in (2, 3, 4)
    ):
        raise InstallAbort("install state version is malformed")
    if is_v2 and state["state_version"] == 4:
        if set(state) != v4_allowed | {"plugin", "runtime_status", "rollback_backups"}:
            raise InstallAbort("install state v4 fields are malformed")
        plugin = state.get("plugin")
        if not isinstance(plugin, dict) or set(plugin) != {
            "name", "version", "status", "source_sha256"
        } or not all(isinstance(value, str) for value in plugin.values()):
            raise InstallAbort("install state plugin status is malformed")
        if plugin["name"] != PILOTFISH_PLUGIN_NAME or plugin["status"] not in {
            "installed", "unavailable"
        } or (plugin["source_sha256"] and not re.fullmatch(r"[0-9a-f]{64}", plugin["source_sha256"])):
            raise InstallAbort("install state plugin status is malformed")
        if state["runtime_status"] not in RUNTIME_STATUSES:
            raise InstallAbort("install state runtime status is malformed")
        rollback_backups = state["rollback_backups"]
        if not isinstance(rollback_backups, dict) or not all(
            isinstance(key, str)
            and isinstance(value, dict)
            and set(value) == {"path", "sha256", "target_sha256"}
            and isinstance(value["path"], str)
            and isinstance(value["sha256"], str)
            and isinstance(value["target_sha256"], str)
            and not Path(value["path"]).is_absolute()
            and ".pilotfish-codex-" in value["path"]
            for key, value in rollback_backups.items()
        ):
            raise InstallAbort("install state rollback backup manifest is malformed")
    elif is_v2 and state["state_version"] == 3:
        if set(state) != v2_allowed | {"plugin", "runtime_status", "rollback_backups"}:
            raise InstallAbort("install state v3 fields are malformed")
        plugin = state.get("plugin")
        if not isinstance(plugin, dict) or set(plugin) != {
            "name", "version", "status", "source_sha256"
        } or not all(isinstance(value, str) for value in plugin.values()):
            raise InstallAbort("install state plugin status is malformed")
        if plugin["name"] != PILOTFISH_PLUGIN_NAME or plugin["status"] not in {
            "installed", "unavailable"
        } or (plugin["source_sha256"] and not re.fullmatch(r"[0-9a-f]{64}", plugin["source_sha256"])):
            raise InstallAbort("install state plugin status is malformed")
        if state["runtime_status"] not in RUNTIME_STATUSES:
            raise InstallAbort("install state runtime status is malformed")
        rollback_backups = state["rollback_backups"]
        if not isinstance(rollback_backups, dict) or not all(
            isinstance(key, str)
            and isinstance(value, str)
            and not Path(key).is_absolute()
            and Path(value).name == value
            and ".pilotfish-codex-" in value
            for key, value in rollback_backups.items()
        ):
            raise InstallAbort("install state rollback backup manifest is malformed")
    elif "plugin" in state:
        plugin = state["plugin"]
        if not isinstance(plugin, dict) or set(plugin) != {
            "name", "version", "status", "source_sha256"
        } or not all(isinstance(value, str) for value in plugin.values()):
            raise InstallAbort("install state plugin status is malformed")
        if "runtime_status" in state and state["runtime_status"] not in RUNTIME_STATUSES:
            raise InstallAbort("install state runtime status is malformed")
        if "rollback_backups" in state:
            rollback_backups = state["rollback_backups"]
            if not isinstance(rollback_backups, dict) or not all(
                isinstance(key, str)
                and isinstance(value, str)
                and not Path(key).is_absolute()
                and Path(value).name == value
                and ".pilotfish-codex-" in value
                for key, value in rollback_backups.items()
            ):
                raise InstallAbort("install state rollback backup manifest is malformed")
        if plugin["name"] != PILOTFISH_PLUGIN_NAME or plugin["status"] not in {
            "installed", "unavailable"
        } or (plugin["source_sha256"] and not re.fullmatch(r"[0-9a-f]{64}", plugin["source_sha256"])):
            raise InstallAbort("install state plugin status is malformed")
    if "policy_ownership" in state:
        policy_ownership = state["policy_ownership"]
        if not isinstance(policy_ownership, dict) or set(policy_ownership) != {
            "user_policy", "pilotfish_policy"
        }:
            raise InstallAbort("install state policy ownership is malformed")
        for entry_name in ("user_policy", "pilotfish_policy"):
            entry = policy_ownership[entry_name]
            if not isinstance(entry, dict) or set(entry) != {
                "path", "owner", "status", "sha256"
            }:
                raise InstallAbort("install state policy ownership is malformed")
            if not all(isinstance(entry[key], str) for key in entry):
                raise InstallAbort("install state policy ownership is malformed")
    targets = state.get("target_fingerprints")
    originals = state.get("original_targets")
    if not isinstance(targets, dict) or not isinstance(originals, dict):
        raise InstallAbort("install state target evidence is malformed")
    recorded = frozenset(targets)
    policy_relative = policy_path.relative_to(home).as_posix()
    accepted_drift: set[str] = set()
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
            if allow_policy_drift and relative == policy_relative:
                accepted_drift.add(relative)
                continue
            if allow_policy_drift and relative.startswith("agents/") and target.is_file():
                # Leave same-name role drift for the explicit role approval gate
                # in the planning pass; missing roles remain stale-state errors.
                continue
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
        _, reconstructed_parsed = _decode_config(
            reconstructed.encode(), source="reconstructed committed"
        )
        _, current_parsed = _decode_config(config_snapshot, source="current")
        if _routing_projection(current_parsed, owned) != _routing_projection(
            reconstructed_parsed, owned
        ):
            raise InstallAbort("committed config provenance cannot be reconstructed")
        expected_config = config_snapshot

    if _sha256_bytes(config_snapshot) != recorded_config_digest:
        accepted_drift.add("config.toml")
        _, expected_parsed = _decode_config(
            expected_config, source="reconstructed committed"
        )
        _, current_parsed = _decode_config(config_snapshot, source="current")
        if _routing_projection(current_parsed, owned) != _routing_projection(
            expected_parsed, owned
        ):
            raise InstallAbort("committed config routing projection is stale")
    if is_v2 and state["state_version"] == 4:
        reconciliation = state.get("reconciliation")
        if not isinstance(reconciliation, dict) or set(reconciliation) != {
            "accepted_targets",
            "previous_state_sha256",
            "previous_state_backup",
            "previous_target_fingerprints",
            "accepted_preimages",
            "post_merge_target_fingerprints",
        }:
            raise InstallAbort("install state reconciliation metadata is malformed")
        accepted_targets = reconciliation["accepted_targets"]
        if not isinstance(accepted_targets, list) or not all(
            isinstance(value, str) for value in accepted_targets
        ):
            raise InstallAbort("install state reconciliation targets are malformed")
        if (
            accepted_targets != sorted(set(accepted_targets))
            or not accepted_targets
            or not set(accepted_targets) <= {policy_relative, "config.toml"}
            or not set(accepted_targets) <= recorded
        ):
            raise InstallAbort("install state reconciliation targets are malformed")
        previous_state_sha256 = reconciliation["previous_state_sha256"]
        if not isinstance(previous_state_sha256, str) or (
            previous_state_sha256 and not sha_re.fullmatch(previous_state_sha256)
        ):
            raise InstallAbort("install state previous state digest is malformed")
        previous_state_backup = reconciliation["previous_state_backup"]
        if previous_state_backup is not None:
            if not isinstance(previous_state_backup, dict) or set(previous_state_backup) != {"path", "sha256"}:
                raise InstallAbort("install state previous state backup is malformed")
            backup_path = previous_state_backup["path"]
            backup_sha256 = previous_state_backup["sha256"]
            if (
                not isinstance(backup_path, str)
                or Path(backup_path).is_absolute()
                or ".pilotfish-codex-" not in backup_path
                or not isinstance(backup_sha256, str)
                or not sha_re.fullmatch(backup_sha256)
            ):
                raise InstallAbort("install state previous state backup is malformed")
            state_backup_path = _home_relative_path(
                _state_path(home).parent,
                backup_path,
                label="install state backup",
            )
            if (
                state_backup_path.is_symlink()
                or not state_backup_path.is_file()
                or _sha256_bytes(state_backup_path.read_bytes()) != backup_sha256
            ):
                raise InstallAbort("install state previous state backup is unavailable")
        elif previous_state_sha256:
            raise InstallAbort("install state previous state backup is missing")
        previous_targets = reconciliation["previous_target_fingerprints"]
        if not isinstance(previous_targets, dict) or set(previous_targets) - recorded or not all(
            isinstance(value, str) and sha_re.fullmatch(value)
            for value in previous_targets.values()
        ):
            raise InstallAbort("install state previous target fingerprints are malformed")
        preimages = reconciliation["accepted_preimages"]
        if not isinstance(preimages, dict) or set(preimages) != set(accepted_targets):
            raise InstallAbort("install state accepted preimages are malformed")
        identity_fields = {
            "link_path", "target_path", "policy_root", "symlink", "link_dev",
            "link_ino", "target_dev", "target_ino", "target_sha256",
        }
        for relative, preimage in preimages.items():
            if not isinstance(preimage, dict) or set(preimage) != identity_fields | {"sha256"}:
                raise InstallAbort("install state accepted preimage is malformed")
            if not isinstance(preimage["sha256"], str) or not sha_re.fullmatch(preimage["sha256"]):
                raise InstallAbort("install state accepted preimage is malformed")
            if (
                not all(isinstance(preimage[key], str) for key in ("link_path", "target_path", "policy_root", "target_sha256"))
                or not isinstance(preimage["symlink"], bool)
                or type(preimage["target_dev"]) is not int
                or type(preimage["target_ino"]) is not int
                or (preimage["link_dev"] is not None and type(preimage["link_dev"]) is not int)
                or (preimage["link_ino"] is not None and type(preimage["link_ino"]) is not int)
                or not sha_re.fullmatch(preimage["target_sha256"])
                or preimage["sha256"] != preimage["target_sha256"]
                or (
                    preimage["symlink"]
                    and (preimage["link_dev"] is None or preimage["link_ino"] is None)
                )
                or (
                    not preimage["symlink"]
                    and (preimage["link_dev"] is not None or preimage["link_ino"] is not None)
                )
            ):
                raise InstallAbort("install state accepted preimage is malformed")
            expected_link = policy_path if relative == policy_relative else home / relative
            try:
                expected_target = expected_link.resolve(strict=True)
            except OSError as exc:
                raise InstallAbort("install state accepted preimage is unavailable") from exc
            if preimage["link_path"] != str(expected_link):
                raise InstallAbort("install state accepted preimage path is malformed")
            if preimage["symlink"]:
                if relative != policy_relative or not expected_link.is_symlink():
                    raise InstallAbort("install state accepted preimage symlink identity is malformed")
                try:
                    root = Path(preimage["policy_root"]).resolve(strict=True)
                    expected_target.relative_to(root)
                except (OSError, ValueError) as exc:
                    raise InstallAbort("install state accepted preimage root is malformed") from exc
                if (
                    not root.is_dir()
                    or preimage["policy_root"] != str(root)
                    or preimage["target_path"] != str(expected_target)
                ):
                    raise InstallAbort("install state accepted preimage symlink identity is malformed")
            elif (
                expected_link.is_symlink()
                or preimage["policy_root"]
                or preimage["target_path"] != str(expected_target)
                or preimage["link_dev"] is not None
                or preimage["link_ino"] is not None
            ):
                raise InstallAbort("install state accepted preimage path is malformed")
        post_merge = reconciliation["post_merge_target_fingerprints"]
        if not isinstance(post_merge, dict) or set(post_merge) != recorded or any(
            post_merge.get(key) != targets.get(key) for key in recorded
        ):
            raise InstallAbort("install state post-merge fingerprints are malformed")
        rollback_backups = state["rollback_backups"]
        required_backups = set(accepted_targets)
        for relative in recorded:
            evidence = originals[relative]
            if evidence["present"] and evidence["sha256"] != targets[relative]:
                required_backups.add(relative)
        if set(rollback_backups) != required_backups:
            raise InstallAbort("install state rollback backup manifest is incomplete")
        if any(not originals[relative]["present"] for relative in accepted_targets):
            raise InstallAbort("install state accepted target has no original evidence")
        for relative, backup in rollback_backups.items():
            if relative not in recorded:
                raise InstallAbort("install state rollback backup target is unknown")
            path = _home_relative_path(
                home,
                backup["path"],
                label="install state rollback backup",
            )
            if (
                path.is_symlink()
                or not path.is_file()
                or not sha_re.fullmatch(backup["sha256"])
                or not sha_re.fullmatch(backup["target_sha256"])
                or _sha256_bytes(path.read_bytes()) != backup["sha256"]
                or backup["target_sha256"] != (originals[relative]["sha256"] or "")
            ):
                raise InstallAbort("install state rollback backup is unavailable")
    return (
        owned,
        migration_proven,
        hook_projection_id,
        not is_v2,
        hook_script_fingerprint,
        frozenset(accepted_drift),
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
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if not IS_WINDOWS:
            os.chmod(temp, stat.S_IMODE(mode))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _copy_backup_no_follow(
    source: Path,
    backup: Path,
    expected_original: bytes,
) -> None:
    """Create a rollback copy without following a raced backup symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    binary = getattr(os, "O_BINARY", 0)
    source_fd: int | None = None
    backup_fd: int | None = None
    try:
        try:
            source_fd = os.open(source, os.O_RDONLY | nofollow | binary)
            source_stat = os.fstat(source_fd)
        except OSError as exc:
            raise InstallAbort(f"rollback source changed: {source}") from exc
        if not stat.S_ISREG(source_stat.st_mode):
            raise InstallAbort(f"rollback source is not a regular file: {source}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        if payload != expected_original:
            raise InstallAbort(f"rollback source changed while copying: {source}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | binary
        try:
            backup_fd = os.open(backup, flags, 0o600)
        except FileExistsError as exc:
            raise InstallAbort(f"rollback backup path raced: {backup}") from exc
        except OSError as exc:
            raise InstallAbort(f"rollback backup is unavailable: {backup}") from exc
        view = memoryview(payload)
        while view:
            written = os.write(backup_fd, view)
            if written <= 0:
                raise InstallAbort(f"rollback backup write failed: {backup}")
            view = view[written:]
        os.fsync(backup_fd)
        created = os.fstat(backup_fd)
        if not stat.S_ISREG(created.st_mode):
            raise InstallAbort(f"rollback backup is not a regular file: {backup}")
        try:
            on_disk = backup.lstat()
        except OSError as exc:
            raise InstallAbort(f"rollback backup changed while copying: {backup}") from exc
        if (
            stat.S_ISLNK(on_disk.st_mode)
            or on_disk.st_dev != created.st_dev
            or on_disk.st_ino != created.st_ino
        ):
            raise InstallAbort(f"rollback backup changed while copying: {backup}")
    finally:
        if backup_fd is not None:
            os.close(backup_fd)
        if source_fd is not None:
            os.close(source_fd)


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


def _open_agents_directory(agents_root: Path) -> int | None:
    if IS_WINDOWS:
        return None
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(agents_root, flags)


def _write_destination(path: Path, policy_identity: PolicyTargetIdentity | None) -> Path:
    if (
        policy_identity is not None
        and policy_identity.symlink
        and path == policy_identity.link_path
    ):
        return policy_identity.target_path
    return _destination(path)


def _planned_backup_path(
    path: Path,
    *,
    codex_home: Path,
    policy_identity: PolicyTargetIdentity | None,
    stamp: str,
) -> Path:
    destination = _write_destination(path, policy_identity)
    if policy_identity is not None and path == policy_identity.link_path and policy_identity.symlink:
        backup = codex_home / f"{path.name}.pilotfish-codex-{stamp}"
    else:
        backup = destination.with_name(f"{destination.name}.pilotfish-codex-{stamp}")
    try:
        backup.relative_to(codex_home)
    except ValueError as exc:
        raise InstallAbort("rollback backup escapes Codex home") from exc
    return backup


def _planned_backup_paths(
    writes: list[tuple[Path, bytes, int, bytes | None]],
    *,
    codex_home: Path,
    policy_identity: PolicyTargetIdentity | None,
    stamp: str,
) -> dict[Path, Path]:
    result: dict[Path, Path] = {}
    for path, _, _, original in writes:
        if original is None:
            continue
        result[path] = _planned_backup_path(
            path,
            codex_home=codex_home,
            policy_identity=policy_identity,
            stamp=stamp,
        )
    return result


def _commit(writes: list[tuple[Path, bytes, int, bytes | None]], stamp: str,
            *, agents_root: Path, hooks_root: Path, codex_home: Path,
            policy_path: Path,
            policy_identity: PolicyTargetIdentity | None = None,
            backup_paths: dict[Path, Path] | None = None,
            unbacked_paths: frozenset[Path] = frozenset(),
            ) -> list[tuple[Path, bytes | None, bytes, int]]:
    _assert_active_instruction_file(codex_home, policy_path)
    _assert_hook_targets(codex_home)
    _assert_policy_identity(policy_identity)
    backup_paths = backup_paths or _planned_backup_paths(
        writes,
        codex_home=codex_home,
        policy_identity=policy_identity,
        stamp=stamp,
    )
    staged: list[tuple[Path, Path, Path, bytes | None, bool, bool]] = []
    expected_post = {
        _write_destination(path, policy_identity): payload
        for path, payload, _, _ in writes
    }
    agents_root.mkdir(parents=True, exist_ok=True)
    _assert_agents_root(agents_root, codex_home)
    hooks_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_hook_targets(codex_home)
    agents_fd: int | None = None
    try:
        # Windows cannot open a directory with os.open for the dir_fd form of
        # os.replace. Use the ordinary path-based replacement there; the
        # surrounding containment and fingerprint checks still apply.
        agents_fd = _open_agents_directory(agents_root)
        for path, payload, mode, original in writes:
            is_role = path.parent == agents_root
            is_hook = path == codex_home / "hooks.json" or path.parent == hooks_root
            if is_role:
                _assert_agents_root(agents_root, codex_home)
            if is_hook:
                _assert_hook_targets(codex_home)
            dest = _write_destination(path, policy_identity)
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp_dir = codex_home if is_role else dest.parent
            fd, name = tempfile.mkstemp(prefix=f".{dest.name}.pilotfish-", dir=temp_dir)
            temp = Path(name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temp, stat.S_IMODE(dest.stat().st_mode) if dest.is_file() else mode)
            staged.append((path, dest, temp, original, is_role, is_hook))
        _assert_policy_identity(policy_identity)
        for _, dest, _, original, _, _ in staged:
            actual = dest.read_bytes() if dest.is_file() else None
            if actual != original:
                raise InstallAbort(f"{dest} changed while install was planned")
        _assert_active_instruction_file(codex_home, policy_path)
        _assert_policy_identity(policy_identity)
        for source_path, dest, _, original, _, _ in staged:
            if original is not None:
                backup = backup_paths.get(source_path)
                if backup is None:
                    if source_path in unbacked_paths:
                        continue
                    raise InstallAbort("rollback backup path is missing")
                if backup.exists() or backup.is_symlink():
                    raise InstallAbort(f"rollback backup already exists: {backup}")
                _copy_backup_no_follow(dest, backup, original)
        applied: list[tuple[Path, bytes | None, bytes, int]] = []
        try:
            for _, dest, temp, original, is_role, is_hook in staged:
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
                if policy_identity is not None and dest == _write_destination(
                    policy_identity.link_path,
                    policy_identity,
                ):
                    _assert_policy_identity(
                        policy_identity,
                        expected_sha256=_sha256_bytes(payload),
                    )
            for destination, expected in expected_post.items():
                if not destination.is_file() or destination.read_bytes() != expected:
                    raise InstallAbort("post-write target fingerprint mismatch")
            _assert_active_instruction_file(codex_home, policy_path)
            policy_destination = (
                _write_destination(policy_identity.link_path, policy_identity)
                if policy_identity is not None
                else None
            )
            if policy_destination is not None and policy_destination in expected_post:
                _assert_policy_identity(
                    policy_identity,
                    expected_sha256=_sha256_bytes(expected_post[policy_destination]),
                )
            else:
                _assert_policy_identity(policy_identity)
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
        for _, _, temp, _, _, _ in staged:
            temp.unlink(missing_ok=True)


def install(
    *,
    source_root: Path,
    codex_home: Path,
    dry_run: bool,
    check_codex: bool = True,
    replace_drifted_roles: bool = False,
    replace_drifted_role: tuple[str, ...] = (),
    follow_policy_symlink: bool = False,
    policy_root: Path | None = None,
    reconcile_current: bool = False,
    allow_plugin_downgrade: bool = False,
) -> int:
    unknown_drift_roles = set(replace_drifted_role) - set(ROLES)
    if unknown_drift_roles:
        raise InstallAbort(
            "unknown drifted role: " + ", ".join(sorted(unknown_drift_roles))
        )
    approved_drift_roles = (
        set(ROLES) if replace_drifted_roles else set(replace_drifted_role)
    )
    if check_codex:
        try:
            completed = subprocess.run([_codex_cli(), "--version"], capture_output=True, text=True, check=False)
        except OSError:
            completed = None
        version = parse_codex_version((completed.stdout + completed.stderr) if completed and completed.returncode == 0 else "")
        if version is None:
            print("error: version_parse_failed", file=sys.stderr); return 2
        if version < MIN_COMPATIBLE_CODEX_VERSION:
            minimum = ".".join(str(part) for part in MIN_COMPATIBLE_CODEX_VERSION)
            print(f"error: version_below_minimum (requires >= {minimum})", file=sys.stderr); return 2
        _assert_plugin_not_newer(
            source_root=source_root,
            codex_home=codex_home,
            allow_downgrade=allow_plugin_downgrade,
        )
    config_path = codex_home / "config.toml"
    config_snapshot = config_path.read_bytes() if config_path.is_file() else None
    config_text, parsed_config = _decode_config(
        config_snapshot or b"", source="existing"
    )
    policy_template = (source_root / "templates" / "agents-md.bootstrap.md").read_text(encoding="utf-8")
    user_policy_path = active_instruction_file(codex_home)
    policy_identity = _capture_policy_identity(
        user_policy_path,
        follow_policy_symlink=follow_policy_symlink,
        policy_root=policy_root,
    )
    if not user_policy_path.is_symlink() and user_policy_path.is_file() and user_policy_path.stat().st_nlink > 1:
        raise InstallAbort(
            "active policy path is hard-linked; explicit policy integration is required"
        )
    policy_path = user_policy_path
    policy_bytes = (
        policy_identity.target_path.read_bytes()
        if policy_identity is not None
        else None
    )
    policy_text, policy_newline = _decode_instruction_bytes(policy_bytes)
    state = _load_state(codex_home)
    owned = frozenset()
    migration_proven = False
    owned_hook_projection: str | None = None
    legacy_state = False
    proven_hook_script_fingerprint: str | None = None
    accepted_drift: frozenset[str] = frozenset()
    features = parsed_config.get("features", {}) if isinstance(parsed_config, dict) else {}
    legacy_v2 = isinstance(features, dict) and "multi_agent_v2" in features
    if reconcile_current and state is None:
        raise InstallAbort("reconcile-current requires committed install state")
    if state is not None:
        (
            owned,
            migration_proven,
            owned_hook_projection,
            legacy_state,
            proven_hook_script_fingerprint,
            accepted_drift,
        ) = _validate_committed_state(
            state,
            home=codex_home,
            policy_path=policy_path,
            config_snapshot=config_snapshot,
            allow_policy_drift=reconcile_current,
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
    policy_payload = _encode_instruction_text(new_policy, policy_newline)
    policy_ownership = _policy_ownership(codex_home, user_policy_path, policy_path)
    if policy_identity is not None and policy_identity.symlink:
        policy_ownership["user_policy"]["status"] = "integrated-symlink-target"
    policy_ownership["pilotfish_policy"]["sha256"] = _sha256_bytes(policy_payload)
    plugin = _probe_plugin(
        source_root=source_root,
        codex_home=codex_home,
        enabled=check_codex,
    )
    plugin_was_installed = plugin["status"] == "installed"
    plugin_install_needed = check_codex and (
        plugin["status"] != "installed"
        or state is None
        or not isinstance(state.get("plugin") if state else None, dict)
        or state["plugin"].get("source_sha256") != plugin["source_sha256"]
    )
    if dry_run and plugin_install_needed:
        plugin["status"] = "planned"
    runtime_status = (
        "integrated" if plugin["status"] == "installed"
        else "integrated-plugin-unavailable"
    )
    notes.append(f"pilotfish plugin status: {plugin['status']}")
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
            if _sha256_bytes(current) not in known and role not in approved_drift_roles:
                raise InstallAbort(f"installed_role_drift: agents/{role}.toml requires explicit replacement approval")
            writes.append((target, payload, 0o600, current))
            notes.append(
                f"replaced drifted role {role} with upstream canonical bytes"
                if _sha256_bytes(current) not in known
                else f"upgraded canonical role {role}"
            )
        elif current is None:
            writes.append((target, payload, 0o600, None))
    if policy_payload != policy_bytes:
        writes.append((policy_path, policy_payload, 0o644, policy_bytes))
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
    windows_warnings = (
        windows_compatibility_warnings(
            load_registration(merged_registration, source="planned hooks.json")
        )
        if IS_WINDOWS
        else []
    )
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
    expected_inventory: dict[str, str] = {}
    for path in inventory:
        relative = path.relative_to(codex_home).as_posix()
        if path in write_payloads:
            expected_inventory[relative] = _sha256_bytes(write_payloads[path])
            continue
        original = pre_targets[relative]["bytes_b64"]
        if not isinstance(original, str):
            raise InstallAbort(f"inventory target is missing without a planned write: {relative}")
        expected_inventory[relative] = _sha256_bytes(base64.b64decode(original))
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
    policy_relative = policy_path.relative_to(codex_home).as_posix()
    state_path = _state_path(codex_home)
    state_original = state_path.read_bytes() if state_path.is_file() else None
    previous_reconciliation = (
        state.get("reconciliation")
        if state is not None and state.get("state_version") == RECONCILIATION_STATE_VERSION
        else None
    )
    previous_accepted_targets = (
        set(previous_reconciliation.get("accepted_targets", []))
        if isinstance(previous_reconciliation, dict)
        else set()
    )
    state_version = (
        RECONCILIATION_STATE_VERSION
        if reconcile_current
        or (policy_identity is not None and policy_identity.symlink)
        or (state is not None and state.get("state_version") == RECONCILIATION_STATE_VERSION)
        else 3
    )
    accepted_targets: set[str] = set()
    if state_version == RECONCILIATION_STATE_VERSION:
        accepted_targets.update(previous_accepted_targets)
        if reconcile_current:
            accepted_targets.update({policy_relative, "config.toml"})
        if policy_identity is not None and policy_identity.symlink:
            accepted_targets.add(policy_relative)
        if not accepted_targets <= set(expected_state_inventory):
            raise InstallAbort("reconciliation target is not part of the state inventory")
    accepted_preimages: dict[str, dict[str, object]] = {}
    for relative in sorted(accepted_targets):
        identity = (
            policy_identity
            if relative == policy_relative
            else _capture_policy_identity(
                config_path,
                follow_policy_symlink=False,
                policy_root=None,
            )
        )
        payload = policy_bytes if relative == policy_relative else config_snapshot
        if identity is None or payload is None:
            raise InstallAbort(f"reconciliation preimage is unavailable: {relative}")
        identity_record = _policy_identity_record(identity)
        if identity_record is None:
            raise InstallAbort(f"reconciliation identity is unavailable: {relative}")
        accepted_preimages[relative] = {
            "sha256": _sha256_bytes(payload),
            **identity_record,
        }
    reconciliation_previous_targets = (
        dict(state.get("target_fingerprints", {})) if state is not None else {}
    )
    state_needs_publication = state is None or legacy_state or (
        owned_hook_projection != desired_hook_projection
    ) or state is None or state.get("plugin") != plugin or state.get("runtime_status") != runtime_status or plugin_install_needed or (
        state is not None and state.get("state_version", 3) != state_version
    ) or (
        state is not None
        and state.get("target_fingerprints") != expected_state_inventory
    )
    if dry_run:
        for warning in windows_warnings:
            print(f"warning: {warning}")
        for note in notes:
            print(f"note: {note}")
        if not writes and not state_needs_publication:
            print("already up to date; nothing to change")
            return 0
        for path, _, _, _ in writes:
            print(f"would change primary: {path.relative_to(codex_home).as_posix()}")
        print(f"allowed transaction artifact: {state_path.name}.pending")
        print(f"allowed transaction artifact: {state_path.name}")
        for path, _, _, original in writes:
            if (
                original is not None
                and not (state_version == RECONCILIATION_STATE_VERSION and path == hooks_registration)
            ):
                backup = _planned_backup_path(
                    path,
                    codex_home=codex_home,
                    policy_identity=policy_identity,
                    stamp="<timestamp>",
                )
                print(
                    f"allowed transaction artifact: "
                    f"{backup.relative_to(codex_home).as_posix()}"
                )
        if state_version == RECONCILIATION_STATE_VERSION:
            planned_sources = {path for path, _, _, _ in writes}
            for relative in sorted(accepted_targets):
                source = policy_path if relative == policy_relative else config_path
                if source in planned_sources:
                    continue
                backup = _planned_backup_path(
                    source,
                    codex_home=codex_home,
                    policy_identity=policy_identity,
                    stamp="<timestamp>",
                )
                print(
                    f"allowed transaction artifact: "
                    f"{backup.relative_to(codex_home).as_posix()}"
                )
        if state_version == RECONCILIATION_STATE_VERSION and state_original is not None:
            print(f"allowed transaction artifact: {state_path.name}.pilotfish-codex-<timestamp>")
        return 0
    if writes or state_needs_publication:
        stamp = _stamp()
        backup_paths = _planned_backup_paths(
            writes,
            codex_home=codex_home,
            policy_identity=policy_identity,
            stamp=stamp,
        )
        unbacked_paths = (
            frozenset({hooks_registration})
            if state_version == RECONCILIATION_STATE_VERSION
            else frozenset()
        )
        backup_paths = {
            path: backup
            for path, backup in backup_paths.items()
            if path not in unbacked_paths
        }
        backup_originals = {
            path: original
            for path, _, _, original in writes
            if original is not None and path not in unbacked_paths
        }
        if state_version == RECONCILIATION_STATE_VERSION:
            for relative in sorted(accepted_targets):
                source = policy_path if relative == policy_relative else config_path
                if source in backup_paths:
                    continue
                encoded = pre_targets[relative]["bytes_b64"]
                if not isinstance(encoded, str):
                    raise InstallAbort(f"reconciliation backup source is unavailable: {relative}")
                original = base64.b64decode(encoded, validate=True)
                backup_paths[source] = _planned_backup_path(
                    source,
                    codex_home=codex_home,
                    policy_identity=policy_identity,
                    stamp=stamp,
                )
                backup_originals[source] = original
        if state_version == RECONCILIATION_STATE_VERSION:
            rollback_backups = {
                source.relative_to(codex_home).as_posix(): {
                    "path": backup.relative_to(codex_home).as_posix(),
                    "sha256": _sha256_bytes(backup_originals[source]),
                    "target_sha256": _sha256_bytes(backup_originals[source]),
                }
                for source, backup in backup_paths.items()
            }
        else:
            rollback_backups = {
                path.relative_to(codex_home).as_posix(): backup_paths[path].name
                for path, original in backup_originals.items()
                if path in {write[0] for write in writes}
            }
        pending = state_path.with_suffix(".json.pending")
        previous_state_backup = None
        state_backup_path: Path | None = None
        if state_version == RECONCILIATION_STATE_VERSION and state_original is not None:
            state_backup_path = state_path.parent / f"{state_path.name}.pilotfish-codex-{stamp}"
            if state_backup_path.exists() or state_backup_path.is_symlink():
                raise InstallAbort(f"previous install state backup already exists: {state_backup_path}")
            previous_state_backup = {
                "path": state_backup_path.name,
                "sha256": _sha256_bytes(state_original),
            }
        pending_record = {
            "status": "pending",
            "original_targets": state_pre_targets,
            "policy_ownership": policy_ownership,
            "plugin": plugin,
            "runtime_status": runtime_status,
            "rollback_backups": rollback_backups,
            "owned_legacy": {
                path: {
                    "original_present": True,
                    "original_sha256": _sha256_bytes(config_text.encode()),
                    "original_bytes_b64": base64.b64encode(config_text.encode()).decode(),
                }
                for path in owned
            },
        }
        if state_version == RECONCILIATION_STATE_VERSION:
            pending_record["reconciliation"] = {
                "accepted_targets": sorted(accepted_targets),
                "previous_state_sha256": _sha256_bytes(state_original) if state_original else "",
                "previous_state_backup": previous_state_backup,
                "previous_target_fingerprints": reconciliation_previous_targets,
                "accepted_preimages": accepted_preimages,
                "post_merge_target_fingerprints": expected_state_inventory,
            }
        pending_payload = json.dumps(pending_record, sort_keys=True).encode() + b"\n"
        _atomic_write(pending, pending_payload, 0o600)
        applied: list[tuple[Path, bytes | None, bytes, int]] = []
        state_payload: bytes | None = None
        plugin_activated = False
        try:
            if state_backup_path is not None:
                _atomic_write(state_backup_path, state_original or b"", 0o600)
            for source, backup in backup_paths.items():
                if source in {write[0] for write in writes}:
                    continue
                _assert_policy_identity(policy_identity)
                destination = _write_destination(source, policy_identity)
                expected_original = backup_originals[source]
                if not destination.is_file() or destination.read_bytes() != expected_original:
                    raise InstallAbort(
                        f"reconciliation target changed while install was planned: "
                        f"{source.relative_to(codex_home).as_posix()}"
                    )
                if backup.exists() or backup.is_symlink():
                    raise InstallAbort(f"rollback backup already exists: {backup}")
                _copy_backup_no_follow(destination, backup, expected_original)
            applied = _commit(
                writes,
                stamp,
                agents_root=agents,
                hooks_root=hooks_root,
                codex_home=codex_home,
                policy_path=user_policy_path,
                policy_identity=policy_identity,
                backup_paths=backup_paths,
                unbacked_paths=unbacked_paths,
            )
            _assert_active_instruction_file(codex_home, user_policy_path)
            if policy_identity is not None:
                _assert_policy_identity(
                    policy_identity,
                    expected_sha256=expected_inventory[policy_relative],
                )
            for path in inventory:
                relative = path.relative_to(codex_home).as_posix()
                if not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_inventory[relative]:
                    raise InstallAbort("post-write transaction fingerprint mismatch")
            _assert_active_instruction_file(codex_home, user_policy_path)
            if policy_identity is not None:
                _assert_policy_identity(
                    policy_identity,
                    expected_sha256=expected_inventory[policy_relative],
                )
            for path in inventory:
                relative = path.relative_to(codex_home).as_posix()
                if not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_inventory[relative]:
                    raise InstallAbort("post-write state publication fingerprint mismatch")
            if plugin_install_needed:
                plugin_config_before = config_path.read_bytes() if config_path.is_file() else None
                if plugin_config_before is None:
                    raise InstallAbort("config.toml disappeared before plugin installation")
                _, plugin_config_before_parsed = _decode_config(
                    plugin_config_before,
                    source="pre-plugin",
                )
                plugin = _install_plugin(
                    source_root=source_root,
                    codex_home=codex_home,
                    dry_run=False,
                    enabled=True,
                )
                runtime_status = (
                    "integrated" if plugin["status"] == "installed"
                    else "integrated-plugin-unavailable"
                )
                plugin_activated = not plugin_was_installed and plugin["status"] == "installed"
                # Codex records local marketplace registration in config.toml.
                # Include that host-side mutation in the committed fingerprint.
                current_config = config_path.read_bytes() if config_path.is_file() else None
                if current_config is None:
                    raise InstallAbort("config.toml disappeared during Plugin installation")
                try:
                    _, plugin_config_after_parsed = _decode_config(
                        current_config,
                        source="post-plugin",
                    )
                except InstallAbort as exc:
                    raise InstallAbort("foreign config mutation during plugin installation") from exc
                if _config_without_plugin_owned(plugin_config_before_parsed) != _config_without_plugin_owned(
                    plugin_config_after_parsed
                ):
                    raise InstallAbort("foreign config mutation during plugin installation")
                expected_inventory["config.toml"] = _sha256_bytes(current_config)
                expected_state_inventory["config.toml"] = expected_inventory["config.toml"]
                if state_version == RECONCILIATION_STATE_VERSION:
                    pending_record["reconciliation"]["post_merge_target_fingerprints"] = dict(
                        expected_state_inventory
                    )
            if state_version == RECONCILIATION_STATE_VERSION:
                for source, backup in backup_paths.items():
                    relative = source.relative_to(codex_home).as_posix()
                    if relative in rollback_backups and backup.is_file():
                        rollback_backups[relative]["sha256"] = _sha256_bytes(
                            backup.read_bytes()
                        )
            ownership = dict(pending_record["owned_legacy"])
            record = {
                "state_version": state_version,
                "status": "committed",
                "target_fingerprints": expected_state_inventory,
                "original_targets": state_pre_targets,
                "policy_ownership": policy_ownership,
                "plugin": plugin,
                "runtime_status": runtime_status,
                "rollback_backups": rollback_backups,
                "owned_legacy": ownership,
                "hook_registration": projection_state(desired_hook_projection),
            }
            if state_version == RECONCILIATION_STATE_VERSION:
                record["reconciliation"] = {
                    "accepted_targets": sorted(accepted_targets),
                    "previous_state_sha256": _sha256_bytes(state_original) if state_original else "",
                    "previous_state_backup": previous_state_backup,
                    "previous_target_fingerprints": reconciliation_previous_targets,
                    "accepted_preimages": accepted_preimages,
                    "post_merge_target_fingerprints": expected_state_inventory,
                }
            state_payload = json.dumps(record, sort_keys=True).encode() + b"\n"
            _assert_active_instruction_file(codex_home, user_policy_path)
            _atomic_write_if_unchanged(
                state_path,
                state_payload,
                0o600,
                state_original,
            )
            if not state_path.is_file() or state_path.read_bytes() != state_payload:
                raise InstallAbort("published install state changed before verification")
            _assert_active_instruction_file(codex_home, user_policy_path)
            if policy_identity is not None:
                _assert_policy_identity(
                    policy_identity,
                    expected_sha256=expected_inventory[policy_relative],
                )
            if any(not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_inventory[path.relative_to(codex_home).as_posix()] for path in inventory):
                raise InstallAbort("post-sidecar transaction fingerprint mismatch")
            if not pending.is_file() or pending.read_bytes() != pending_payload:
                raise InstallAbort("pending install state changed before removal")
            pending.unlink()
        except BaseException as exc:
            plugin_rollback = "not-required"
            if plugin_activated and plugin.get("status") == "installed":
                plugin_rollback = "removed" if _remove_plugin(codex_home=codex_home) else "failed"
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
            aborted["plugin_rollback"] = plugin_rollback
            aborted_payload = json.dumps(aborted, sort_keys=True).encode() + b"\n"
            if pending.is_file() and pending.read_bytes() == pending_payload:
                _atomic_write(pending, aborted_payload, 0o600)
            raise
    for warning in windows_warnings:
        print(f"warning: {warning}")
    for note in notes:
        print(f"note: {note}")
    print("changed native target" if writes else "already up to date; nothing to change")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace-drifted-roles",
        action="store_true",
        help="explicitly replace all customized same-name roles with upstream templates",
    )
    parser.add_argument(
        "--replace-drifted-role",
        action="append",
        default=[],
        choices=sorted(ROLES),
        help="explicitly replace one named customized role; may be repeated",
    )
    parser.add_argument(
        "--follow-policy-symlink",
        action="store_true",
        help="explicitly integrate the active policy symlink target",
    )
    parser.add_argument(
        "--policy-root",
        type=Path,
        help="contained root allowed for an active policy symlink target",
    )
    parser.add_argument(
        "--reconcile-current",
        action="store_true",
        help="accept selected current policy/config drift and publish reconciliation provenance",
    )
    parser.add_argument(
        "--allow-plugin-downgrade",
        action="store_true",
        help="explicitly permit replacing an installed newer Pilotfish plugin",
    )
    args = parser.parse_args(argv)
    try:
        return install(
            source_root=Path(__file__).resolve().parents[1],
            codex_home=args.codex_home,
            dry_run=args.dry_run,
            replace_drifted_roles=args.replace_drifted_roles,
            replace_drifted_role=tuple(args.replace_drifted_role),
            follow_policy_symlink=args.follow_policy_symlink,
            policy_root=args.policy_root,
            reconcile_current=args.reconcile_current,
            allow_plugin_downgrade=args.allow_plugin_downgrade,
        )
    except InstallAbort as exc:
        print(f"aborted: {exc}", file=sys.stderr); return 2
    except OSError as exc:
        print(f"error: install I/O failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
