"""Static validator for Codex agent TOML files.

`codex --strict-config doctor` validates `config.toml` only; it never loads
`agents/*.toml`. This closes that gap: it parses each agent file and rejects
unknown keys, missing required keys, and out-of-enum values before a broken
role reaches a live session.

Enum values track Codex CLI 0.144.x: SandboxMode and WebSearchMode are fixed
CLI enums; reasoning effort is accepted per model catalog at runtime, so the
set here is the port's supported tiers, not a guarantee for an arbitrary model.

Usage:
    python3 install/validate_agents.py [--config <config.toml>] [<agents-dir> ...]

With no arguments, validates both `templates/config.snippet.toml` and
`templates/agents`. Exits non-zero and prints one `file: message` line per
problem. Non-default but supported concurrency values print warnings.
"""

from __future__ import annotations

import argparse
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
V2_CONCURRENCY_MIN = 1
V2_CONCURRENCY_MAX = 8
V2_CONCURRENCY_RECOMMENDED = 4


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


def validate_multi_agent_v2_config(config: dict) -> tuple[list[str], list[str]]:
    """Validate Pilotfish's temporary MultiAgentV2 adapter contract."""
    errors: list[str] = []
    warnings: list[str] = []

    features = config.get("features")
    if not isinstance(features, dict):
        return ["features.multi_agent_v2 table is missing"], warnings

    adapter = features.get("multi_agent_v2")
    if not isinstance(adapter, dict):
        return ["features.multi_agent_v2 table is missing"], warnings

    if adapter.get("hide_spawn_agent_metadata") is not False:
        errors.append("hide_spawn_agent_metadata must be false")

    if adapter.get("tool_namespace") != "agents":
        errors.append("tool_namespace must be 'agents' when spawn metadata is exposed")

    if adapter.get("enabled") is True:
        errors.append(
            "enabled must not be forced while legacy agents.max_threads is retained"
        )

    concurrency = adapter.get("max_concurrent_threads_per_session")
    if type(concurrency) is not int or not (
        V2_CONCURRENCY_MIN <= concurrency <= V2_CONCURRENCY_MAX
    ):
        errors.append(
            "concurrency must be an integer from "
            f"{V2_CONCURRENCY_MIN} to {V2_CONCURRENCY_MAX}"
        )
        return errors, warnings

    if concurrency == 1:
        warnings.append("concurrency 1 disables child delegation")
    elif concurrency > V2_CONCURRENCY_RECOMMENDED:
        warnings.append(
            f"concurrency {concurrency} allows higher cost; recommended value is "
            f"{V2_CONCURRENCY_RECOMMENDED}"
        )
    elif concurrency != V2_CONCURRENCY_RECOMMENDED:
        warnings.append(
            f"concurrency {concurrency} is valid; recommended value is "
            f"{V2_CONCURRENCY_RECOMMENDED}"
        )

    return errors, warnings


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


def validate_config(path: Path) -> tuple[list[str], list[str]]:
    """Parse and validate one Pilotfish-capable Codex config file."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return [f"{path}: config file not found"], []
    except tomllib.TOMLDecodeError as exc:
        return [f"{path}: invalid TOML — {exc}"], []

    errors, warnings = validate_multi_agent_v2_config(data)
    return (
        [f"{path}: {message}" for message in errors],
        [f"{path}: {message}" for message in warnings],
    )


def _default_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "agents"


def _default_config() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "config.snippet.toml"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("agents_dirs", nargs="*", type=Path)
    args = parser.parse_args(argv)

    targets = args.agents_dirs or [_default_dir()]
    config_path = args.config
    if config_path is None and not argv:
        config_path = _default_config()

    problems: list[str] = []
    warnings: list[str] = []
    if config_path is not None:
        config_problems, config_warnings = validate_config(config_path)
        problems.extend(config_problems)
        warnings.extend(config_warnings)

    for target in targets:
        problems.extend(validate_dir(target))

    for line in warnings:
        print(f"warning: {line}", file=sys.stderr)

    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        print(f"\n{len(problems)} problem(s) found", file=sys.stderr)
        return 1

    print("all Pilotfish config and agent TOMLs valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
