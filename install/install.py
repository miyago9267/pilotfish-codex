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
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_agents import validate_config, validate_dir  # noqa: E402

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


def _set_key_in_table(
    lines: list[str], header: str, key: str, value: str
) -> list[str]:
    """Insert or replace `key = value` inside `[header]`, appending the table
    if it does not exist. Returns a new line list."""
    span = _table_span(lines, header)
    if span is None:
        block = [f"[{header}]", f"{key} = {value}"]
        return lines + ([""] if lines and lines[-1].strip() else []) + block
    start, end = span
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for index in range(start + 1, end):
        if pattern.match(lines[index]):
            lines = lines.copy()
            lines[index] = f"{key} = {value}"
            return lines
    return lines[: start + 1] + [f"{key} = {value}"] + lines[start + 1 :]


def merge_config_text(text: str) -> tuple[str, list[str]]:
    """Merge the Pilotfish keys into one config document.

    Returns (new_text, notes). Raises InstallAbort on states the scripted
    route must not decide."""
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise InstallAbort(f"existing config.toml is invalid TOML: {exc}")

    notes: list[str] = []
    lines = text.splitlines()
    features = config.get("features", {})
    adapter = features.get("multi_agent_v2", {})

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
        lines = lines[:insert_at] + ['model = "gpt-5.6-sol"'] + lines[insert_at:]
        notes.append('set model = "gpt-5.6-sol"')

    if "multi_agent" not in features:
        lines = _set_key_in_table(lines, "features", "multi_agent", "true")
        notes.append("set features.multi_agent = true")

    if not isinstance(adapter, dict) or not adapter:
        lines = lines + ([""] if lines and lines[-1].strip() else [])
        lines += ADAPTER_BLOCK.strip().splitlines()
        notes.append("installed the MultiAgentV2 adapter table")
    else:
        if adapter.get("hide_spawn_agent_metadata") is not False:
            lines = _set_key_in_table(
                lines, "features.multi_agent_v2", "hide_spawn_agent_metadata", "false"
            )
            notes.append("repaired hide_spawn_agent_metadata = false")
        if adapter.get("tool_namespace") != "agents":
            lines = _set_key_in_table(
                lines, "features.multi_agent_v2", "tool_namespace", '"agents"'
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
            )
            notes.append("set max_concurrent_threads_per_session = 4")

    agents_table = config.get("agents", {})
    if "max_threads" not in agents_table:
        lines = _set_key_in_table(lines, "agents", "max_threads", "3")
        notes.append("set agents.max_threads = 3")
    if "max_depth" not in agents_table:
        lines = _set_key_in_table(lines, "agents", "max_depth", "1")
        notes.append("set agents.max_depth = 1")

    new_text = "\n".join(lines)
    if text.endswith("\n") or not text:
        new_text += "\n"

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
    return datetime.now().strftime("%Y%m%d-%H%M%S")


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

    codex_home.mkdir(parents=True, exist_ok=True)

    # 1. config.toml
    config_path = codex_home / "config.toml"
    config_text = (
        config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    )
    new_config, notes = merge_config_text(config_text)
    if new_config != config_text:
        if not dry_run:
            if config_path.is_file():
                shutil.copy2(
                    config_path,
                    config_path.with_name(f"config.toml.pilotfish-codex-{stamp}"),
                )
            config_path.write_text(new_config, encoding="utf-8")
        changed.append(f"config.toml: {'; '.join(notes)}")

    # 2. role TOMLs
    agents_dir = codex_home / "agents"
    for role in ROLES:
        source = source_root / "templates" / "agents" / f"{role}.toml"
        if not source.is_file():
            print(f"error: missing template {source}", file=sys.stderr)
            return 1
        target = agents_dir / f"{role}.toml"
        payload = source.read_text(encoding="utf-8")
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current == payload:
            continue
        if not dry_run:
            agents_dir.mkdir(parents=True, exist_ok=True)
            if current is not None:
                shutil.copy2(
                    target, target.with_name(f"{role}.toml.pilotfish-codex-{stamp}")
                )
            target.write_text(payload, encoding="utf-8")
        changed.append(
            f"agents/{role}.toml: {'updated (backup kept)' if current else 'installed'}"
        )

    # 3. orchestration policy block
    policy_block = (
        source_root / "templates" / "agents-md.orchestration.md"
    ).read_text(encoding="utf-8")
    instruction_path = active_instruction_file(codex_home)
    instruction_text = (
        instruction_path.read_text(encoding="utf-8")
        if instruction_path.is_file()
        else ""
    )
    new_instructions, action = merge_instruction_text(instruction_text, policy_block)
    if new_instructions != instruction_text:
        if not dry_run:
            if instruction_path.is_file():
                shutil.copy2(
                    instruction_path,
                    instruction_path.with_name(
                        f"{instruction_path.name}.pilotfish-codex-{stamp}"
                    ),
                )
            instruction_path.write_text(new_instructions, encoding="utf-8")
        changed.append(f"{instruction_path.name}: {action} orchestration block")

    # 4. validate the outcome (source of truth in dry runs)
    config_errors, config_warnings = (
        validate_config(config_path)
        if not dry_run
        else validate_config(source_root / "templates" / "config.snippet.toml")
    )
    problems = list(config_errors)
    if not dry_run:
        problems += validate_dir(agents_dir)
    for warning in config_warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print("error: post-install validation failed", file=sys.stderr)
        return 1

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


if __name__ == "__main__":
    raise SystemExit(main())
