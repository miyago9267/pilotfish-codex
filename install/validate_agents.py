"""Static validator for Codex agent TOML files.

`codex --strict-config doctor` validates `config.toml` only; it never loads
`agents/*.toml`. This closes that gap: it parses each agent file and rejects
unknown keys, missing required keys, and out-of-enum values before a broken
role reaches a live session.

Enum values track Codex CLI 0.144.x: SandboxMode and WebSearchMode are fixed
CLI enums; reasoning effort is accepted per model catalog at runtime, so the
set here is the port's supported tiers, not a guarantee for an arbitrary model.

Usage:
    python3 install/validate_agents.py [<agents-dir> ...]

Defaults to `templates/agents` relative to the repository root. Exits non-zero
and prints one `file: message` line per problem.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


ALLOWED_KEYS = {
    "name",
    "description",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
    "web_search",
    "developer_instructions",
    "nickname_candidates",
}

REQUIRED_KEYS = {
    "name",
    "description",
    "model",
    "model_reasoning_effort",
    "developer_instructions",
}

SANDBOX_MODES = {"read-only", "workspace-write", "danger-full-access"}
WEB_SEARCH_MODES = {"disabled", "cached", "indexed", "live", "custom"}
REASONING_EFFORTS = {"low", "medium", "high", "max"}


def validate_agent(data: dict) -> list[str]:
    """Return a list of contract violations for one parsed agent TOML."""
    errors: list[str] = []

    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        errors.append(f"unknown key(s): {', '.join(sorted(unknown))}")

    missing = REQUIRED_KEYS - set(data)
    if missing:
        errors.append(f"missing required key(s): {', '.join(sorted(missing))}")

    for key, blank in (("name", "name"), ("developer_instructions", "developer_instructions")):
        if key in data and not str(data[key]).strip():
            errors.append(f"{blank} cannot be blank")

    sandbox = data.get("sandbox_mode")
    if sandbox is not None and sandbox not in SANDBOX_MODES:
        errors.append(f"sandbox_mode '{sandbox}' not in {sorted(SANDBOX_MODES)}")

    web_search = data.get("web_search")
    if web_search is not None and web_search not in WEB_SEARCH_MODES:
        errors.append(f"web_search '{web_search}' not in {sorted(WEB_SEARCH_MODES)}")

    effort = data.get("model_reasoning_effort")
    if effort is not None and effort not in REASONING_EFFORTS:
        errors.append(
            f"model_reasoning_effort '{effort}' not in {sorted(REASONING_EFFORTS)}"
        )

    return errors


def validate_dir(agents_dir: Path) -> list[str]:
    """Validate every `*.toml` in a directory; return `file: message` lines."""
    problems: list[str] = []
    files = sorted(agents_dir.glob("*.toml"))
    if not files:
        return [f"{agents_dir}: no agent TOML files found"]

    for path in files:
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{path.name}: invalid TOML — {exc}")
            continue

        stem_mismatch = data.get("name") != path.stem
        if stem_mismatch:
            problems.append(
                f"{path.name}: name '{data.get('name')}' does not match filename"
            )

        for message in validate_agent(data):
            problems.append(f"{path.name}: {message}")

    return problems


def _default_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "agents"


def main(argv: list[str]) -> int:
    targets = [Path(arg) for arg in argv] or [_default_dir()]
    problems: list[str] = []
    for target in targets:
        problems.extend(validate_dir(target))

    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        print(f"\n{len(problems)} problem(s) found", file=sys.stderr)
        return 1

    print("all agent TOMLs valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
