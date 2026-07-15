#!/usr/bin/env python3
"""Non-interactive Pilotfish installer for `~/.codex/`.

This is the scripted route; `AGENT-INSTALL.md` remains the agent-guided route
and stays the authoritative merge contract. Both routes install the same
files: the config keys from `templates/config.snippet.toml`, the seven role
TOMLs, and one marked `### Orchestration` block in the active global
instruction file.

The config merge is text-based and minimal: unrelated keys, tables, comments,
and formatting are preserved byte for byte. Anything that needs a human
decision (a forced `enabled = true`, unmatched markers, `multi_agent = false`)
aborts with exit code 2 instead of guessing.

Usage:
    python3 install/install.py [--codex-home DIR] [--dry-run]
"""

from __future__ import annotations

import argparse
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
from validate_agents import (  # noqa: E402
    validate_agent,
    validate_multi_agent_v2_config,
)

ROLES = (
    "scout",
    "plan-verifier",
    "security-reviewer",
    "mech-executor",
    "executor",
    "verifier",
    "security-executor",
)
MIN_CODEX_VERSION = (0, 144, 1)
VERIFIED_CODEX_VERSION = (0, 144, 4)
ADAPTER_BLOCK = (
    "[features.multi_agent_v2]\n"
    "hide_spawn_agent_metadata = false\n"
    'tool_namespace = "agents"\n'
    "max_concurrent_threads_per_session = 4\n"
)
MARKER_BEGIN = "<!-- pilotfish-codex:begin -->"
MARKER_END = "<!-- pilotfish-codex:end -->"


class InstallAbort(Exception):
    """A state that needs a human decision; nothing has been written."""


def parse_codex_version(output: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _table_span(lines: list[str], header: str) -> tuple[int, int] | None:
    """Return (header_index, end_exclusive) for one `[header]` table."""
    start = None
    for index, line in enumerate(lines):
        if line.split("#", 1)[0].strip() == f"[{header}]":
            start = index
            break
    if start is None:
        return None
    for index in range(start + 1, len(lines)):
        stripped = lines[index].split("#", 1)[0].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return start, index
    return start, len(lines)


def _first_table_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return index
    return len(lines)


def _line_ending(line: str) -> str:
    for ending in ("\r\n", "\n", "\r"):
        if line.endswith(ending):
            return ending
    return ""


def _preferred_newline(text: str) -> str:
    match = re.search(r"\r\n|\n|\r", text)
    return match.group(0) if match else "\n"


def _append_block(
    lines: list[str], block: list[str], newline: str
) -> list[str]:
    result = lines.copy()
    if result:
        if not _line_ending(result[-1]):
            result[-1] += newline
        if result[-1].strip():
            result.append(newline)
    result.extend(f"{line}{newline}" for line in block)
    return result


def _set_key_in_table(
    lines: list[str], header: str, key: str, value: str, newline: str
) -> list[str]:
    """Insert or replace `key = value` inside `[header]`, appending the table
    if it does not exist. Returns a new line list."""
    span = _table_span(lines, header)
    if span is None:
        block = [f"[{header}]", f"{key} = {value}"]
        return _append_block(lines, block, newline)
    start, end = span
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for index in range(start + 1, end):
        if pattern.match(lines[index]):
            lines = lines.copy()
            ending = _line_ending(lines[index]) or newline
            lines[index] = f"{key} = {value}{ending}"
            return lines
    prefix = lines[: start + 1]
    if prefix and not _line_ending(prefix[-1]):
        prefix = prefix.copy()
        prefix[-1] += newline
    return prefix + [f"{key} = {value}{newline}"] + lines[start + 1 :]


def merge_config_text(text: str) -> tuple[str, list[str]]:
    """Merge the Pilotfish keys into one config document.

    Returns (new_text, notes). Raises InstallAbort on states the scripted
    route must not decide."""
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise InstallAbort(f"existing config.toml is invalid TOML: {exc}")

    notes: list[str] = []
    lines = text.splitlines(keepends=True)
    newline = _preferred_newline(text)
    features = config.get("features", {})
    if not isinstance(features, dict):
        raise InstallAbort("features must be a TOML table")
    adapter = features.get("multi_agent_v2", {})
    if "multi_agent_v2" in features and not isinstance(adapter, dict):
        raise InstallAbort("features.multi_agent_v2 must be a TOML table")

    if isinstance(adapter, dict) and adapter.get("enabled") is True:
        raise InstallAbort(
            "features.multi_agent_v2.enabled = true is set; remove it or run "
            "the agent-guided install to decide this explicitly"
        )
    if features.get("multi_agent") is False:
        raise InstallAbort(
            "features.multi_agent = false is set; the scripted route does not "
            "override an explicit user opt-out"
        )

    if "model" not in config:
        insert_at = _first_table_index(lines)
        if insert_at > 0 and not _line_ending(lines[insert_at - 1]):
            lines = lines.copy()
            lines[insert_at - 1] += newline
        lines = (
            lines[:insert_at]
            + [f'model = "gpt-5.6-sol"{newline}']
            + lines[insert_at:]
        )
        notes.append('set model = "gpt-5.6-sol"')

    if "multi_agent" not in features:
        lines = _set_key_in_table(
            lines, "features", "multi_agent", "true", newline
        )
        notes.append("set features.multi_agent = true")

    if not isinstance(adapter, dict) or not adapter:
        lines = _append_block(lines, ADAPTER_BLOCK.strip().splitlines(), newline)
        notes.append("installed the MultiAgentV2 adapter table")
    else:
        if adapter.get("hide_spawn_agent_metadata") is not False:
            lines = _set_key_in_table(
                lines,
                "features.multi_agent_v2",
                "hide_spawn_agent_metadata",
                "false",
                newline,
            )
            notes.append("repaired hide_spawn_agent_metadata = false")
        if adapter.get("tool_namespace") != "agents":
            lines = _set_key_in_table(
                lines,
                "features.multi_agent_v2",
                "tool_namespace",
                '"agents"',
                newline,
            )
            notes.append('repaired tool_namespace = "agents"')
        concurrency = adapter.get("max_concurrent_threads_per_session")
        if type(concurrency) is int and 1 <= concurrency <= 8:
            if concurrency != 4:
                notes.append(
                    f"kept user concurrency {concurrency} (recommended 4)"
                )
        else:
            lines = _set_key_in_table(
                lines,
                "features.multi_agent_v2",
                "max_concurrent_threads_per_session",
                "4",
                newline,
            )
            notes.append("set max_concurrent_threads_per_session = 4")

    agents_table = config.get("agents", {})
    if not isinstance(agents_table, dict):
        raise InstallAbort("agents must be a TOML table")
    if "max_threads" not in agents_table:
        lines = _set_key_in_table(
            lines, "agents", "max_threads", "3", newline
        )
        notes.append("set agents.max_threads = 3")
    if "max_depth" not in agents_table:
        lines = _set_key_in_table(lines, "agents", "max_depth", "1", newline)
        notes.append("set agents.max_depth = 1")

    new_text = "".join(lines)

    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:  # defense against a bad edit
        raise InstallAbort(f"merge produced invalid TOML, aborting: {exc}")
    return new_text, notes


def merge_instruction_text(text: str, block: str) -> tuple[str, str]:
    """Insert or replace the marked orchestration block.

    Returns (new_text, action). Raises InstallAbort on unmatched or multiple
    marker pairs."""
    begins = text.count(MARKER_BEGIN)
    ends = text.count(MARKER_END)
    if begins != ends or begins > 1:
        raise InstallAbort(
            "instruction file has unmatched or multiple pilotfish-codex "
            "marker pairs; fix it manually or run the agent-guided install"
        )
    block = block.rstrip("\n")
    if begins == 1:
        start = text.index(MARKER_BEGIN)
        end = text.index(MARKER_END) + len(MARKER_END)
        if start > end - len(MARKER_END):
            raise InstallAbort("pilotfish-codex markers are out of order")
        return text[:start] + block + text[end:], "replaced"
    prefix = text if not text or text.endswith("\n\n") else text.rstrip("\n") + "\n\n"
    return prefix + block + "\n", "appended"


def active_instruction_file(codex_home: Path) -> Path:
    override = codex_home / "AGENTS.override.md"
    if override.is_file() and override.read_text(encoding="utf-8").strip():
        return override
    return codex_home / "AGENTS.md"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _validate_config_text(text: str, path: Path) -> tuple[list[str], list[str]]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [f"{path}: invalid TOML — {exc}"], []
    errors, warnings = validate_multi_agent_v2_config(data)
    return (
        [f"{path}: {message}" for message in errors],
        [f"{path}: {message}" for message in warnings],
    )


def _validate_agent_text(path: Path, text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [f"{path.name}: invalid TOML — {exc}"]
    problems: list[str] = []
    if data.get("name") != path.stem:
        problems.append(
            f"{path.name}: name '{data.get('name')}' does not match filename"
        )
    problems.extend(f"{path.name}: {message}" for message in validate_agent(data))
    return problems


def _destination(path: Path) -> Path:
    if path.is_symlink():
        try:
            return path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise InstallAbort(f"refusing to write through broken symlink {path}") from exc
    return path


def _backup_path(path: Path, stamp: str) -> Path:
    base = path.with_name(f"{path.name}.pilotfish-codex-{stamp}")
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{suffix}")
        suffix += 1
    return candidate


def _commit_writes(
    writes: list[tuple[Path, str, int, str | None]], stamp: str
) -> None:
    """Stage every payload before atomically replacing any target.

    Existing symlinks remain symlinks: the replacement is applied to their
    resolved target, while the backup stays beside the configured path.
    """
    staged: list[tuple[Path, Path, Path, Path | None, bool, str | None]] = []
    try:
        for path, text, default_mode, expected in writes:
            destination = _destination(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.pilotfish-",
                dir=destination.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                mode = (
                    stat.S_IMODE(destination.stat().st_mode)
                    if destination.is_file()
                    else default_mode
                )
                os.chmod(temporary, mode)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            existed = path.is_file()
            backup = _backup_path(path, stamp) if existed else None
            staged.append((path, destination, temporary, backup, existed, expected))

        for path, _, _, _, _, expected in staged:
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != expected:
                raise InstallAbort(f"{path} changed while the install was being planned")

        for path, _, _, backup, existed, _ in staged:
            if existed and backup is not None:
                shutil.copy2(path, backup)

        applied: list[tuple[Path, Path, Path | None, bool]] = []
        try:
            for _, destination, temporary, backup, existed, _ in staged:
                os.replace(temporary, destination)
                applied.append((destination, temporary, backup, existed))
        except OSError:
            for destination, _, backup, existed in reversed(applied):
                if existed and backup is not None:
                    shutil.copy2(backup, destination)
                else:
                    destination.unlink(missing_ok=True)
            raise
    finally:
        for _, _, temporary, _, _, _ in staged:
            temporary.unlink(missing_ok=True)


def install(
    *,
    source_root: Path,
    codex_home: Path,
    dry_run: bool,
    check_codex: bool = True,
) -> int:
    changed: list[str] = []
    stamp = _stamp()

    if check_codex:
        try:
            completed = subprocess.run(
                ["codex", "--version"], capture_output=True, text=True, check=False
            )
        except OSError:
            completed = None
        version = (
            parse_codex_version(completed.stdout + completed.stderr)
            if completed and completed.returncode == 0
            else None
        )
        if version is None:
            print("error: codex CLI not found or version unparsable", file=sys.stderr)
            return 2
        if version < MIN_CODEX_VERSION:
            print(
                f"error: codex {'.'.join(map(str, version))} is older than the "
                f"required {'.'.join(map(str, MIN_CODEX_VERSION))}",
                file=sys.stderr,
            )
            return 2
        if version != VERIFIED_CODEX_VERSION:
            print(
                "warning: the MultiAgentV2 adapter is verified on "
                f"{'.'.join(map(str, VERIFIED_CODEX_VERSION))}; on "
                f"{'.'.join(map(str, version))} treat it as unverified until "
                "the live smoke passes",
                file=sys.stderr,
            )

    writes: list[tuple[Path, str, int, str | None]] = []

    # Plan config.toml without changing the target.
    config_path = codex_home / "config.toml"
    if config_path.is_symlink():
        _destination(config_path)
    config_exists = config_path.is_file()
    config_text = config_path.read_text(encoding="utf-8") if config_exists else ""
    new_config, notes = merge_config_text(config_text)
    if new_config != config_text:
        writes.append(
            (config_path, new_config, 0o600, config_text if config_exists else None)
        )
        changed.append(f"config.toml: {'; '.join(notes)}")

    # Plan role TOMLs. Differing same-name roles require the guided route.
    agents_dir = codex_home / "agents"
    planned_agents: dict[Path, str] = {}
    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.toml")):
            text = path.read_text(encoding="utf-8")
            planned_agents[path] = text
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                continue
            declared_name = data.get("name")
            if declared_name in ROLES and path.name != f"{declared_name}.toml":
                raise InstallAbort(
                    f"{path.name} also declares role '{declared_name}'; run the "
                    "agent-guided install to resolve the collision"
                )

    for role in ROLES:
        source = source_root / "templates" / "agents" / f"{role}.toml"
        if not source.is_file():
            print(f"error: missing template {source}", file=sys.stderr)
            return 1
        target = agents_dir / f"{role}.toml"
        if target.is_symlink():
            _destination(target)
        payload = source.read_text(encoding="utf-8")
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current is not None and current != payload:
            raise InstallAbort(
                f"agents/{role}.toml differs from the packaged role; run the "
                "agent-guided install to review and approve that overwrite"
            )
        planned_agents[target] = payload
        if current is None:
            writes.append((target, payload, 0o600, None))
            changed.append(f"agents/{role}.toml: installed")

    # Plan the orchestration block before any write can occur.
    policy_path = source_root / "templates" / "agents-md.orchestration.md"
    if not policy_path.is_file():
        print(f"error: missing template {policy_path}", file=sys.stderr)
        return 1
    policy_block = policy_path.read_text(encoding="utf-8")
    if policy_block.count(MARKER_BEGIN) != 1 or policy_block.count(MARKER_END) != 1:
        print(f"error: invalid marker pair in template {policy_path}", file=sys.stderr)
        return 1

    override_path = codex_home / "AGENTS.override.md"
    if override_path.is_symlink():
        _destination(override_path)
    instruction_path = active_instruction_file(codex_home)
    if instruction_path.is_symlink():
        _destination(instruction_path)
    instruction_exists = instruction_path.is_file()
    instruction_text = (
        instruction_path.read_text(encoding="utf-8") if instruction_exists else ""
    )
    new_instructions, action = merge_instruction_text(instruction_text, policy_block)
    if new_instructions != instruction_text:
        writes.append(
            (
                instruction_path,
                new_instructions,
                0o644,
                instruction_text if instruction_exists else None,
            )
        )
        changed.append(f"{instruction_path.name}: {action} orchestration block")

    # Validate the exact planned bytes. A validation failure cannot leave a
    # partial install because the commit phase has not started yet.
    config_errors, config_warnings = _validate_config_text(new_config, config_path)
    problems = list(config_errors)
    for path, text in sorted(planned_agents.items()):
        problems.extend(_validate_agent_text(path, text))
    for warning in config_warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print("error: planned install validation failed", file=sys.stderr)
        return 1

    if not dry_run and writes:
        _commit_writes(writes, stamp)

    prefix = "would change" if dry_run else "changed"
    if changed:
        for entry in changed:
            print(f"{prefix}: {entry}")
    else:
        print("already up to date; nothing to change")
    if not dry_run and changed:
        print(
            "\nNext steps:\n"
            "  1. Start a NEW Codex session (a running session keeps the old "
            "spawn schema).\n"
            "  2. Optional live routing proof (spends real quota):\n"
            "     python3 install/verify_dispatch.py --live --yes"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser.add_argument("--codex-home", type=Path, default=default_home)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    source_root = Path(__file__).resolve().parents[1]
    try:
        return install(
            source_root=source_root,
            codex_home=args.codex_home,
            dry_run=args.dry_run,
        )
    except InstallAbort as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: install I/O failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
