"""Fail-closed static validation for the native Codex role contract.

The validator intentionally validates Pilotfish's staged single-layer contract;
it does not claim to reproduce Codex's layered role loader.
"""

from __future__ import annotations

import argparse
import os
import tomllib
from pathlib import Path

ROLES = frozenset({
    "executor", "mech-executor", "plan-verifier", "scout",
    "security-executor", "security-reviewer", "verifier",
})
ALLOWED_KEYS = {
    "name", "description", "model", "model_reasoning_effort", "sandbox_mode",
    "web_search", "developer_instructions", "nickname_candidates",
}
REQUIRED_KEYS = {"name", "description", "model", "model_reasoning_effort", "developer_instructions"}
SANDBOX_MODES = {"read-only", "workspace-write", "danger-full-access"}
WEB_SEARCH_MODES = {"disabled", "cached", "indexed", "live", "custom"}
REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
AGENTS_CONCURRENCY_MIN = 1
AGENTS_CONCURRENCY_MAX = 8
AGENTS_CONCURRENCY_RECOMMENDED = 3
AGENTS_CONCURRENCY_KEY = "max_concurrent_threads_per_session"


def validate_agent(data: dict) -> list[str]:
    """Return local role-contract errors for one parsed TOML object."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["role TOML must be a table"]
    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        errors.append(f"unknown key(s): {', '.join(sorted(unknown))}")
    missing = REQUIRED_KEYS - set(data)
    if missing:
        errors.append(f"missing required key(s): {', '.join(sorted(missing))}")
    for key in ("name", "description", "model", "model_reasoning_effort", "developer_instructions"):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            errors.append(f"{key} cannot be blank")
    if data.get("sandbox_mode") is not None and data["sandbox_mode"] not in SANDBOX_MODES:
        errors.append(f"sandbox_mode '{data['sandbox_mode']}' is unsupported")
    if data.get("web_search") is not None and data["web_search"] not in WEB_SEARCH_MODES:
        errors.append(f"web_search '{data['web_search']}' is unsupported")
    if data.get("model_reasoning_effort") is not None and data["model_reasoning_effort"] not in REASONING_EFFORTS:
        errors.append(f"model_reasoning_effort '{data['model_reasoning_effort']}' is unsupported")
    return errors


def validate_agents_config(config: dict) -> tuple[list[str], list[str]]:
    """Validate Codex's [agents] child concurrency setting."""
    errors: list[str] = []
    warnings: list[str] = []
    features = config.get("features", {})
    if not isinstance(features, dict):
        errors.append("features must be a TOML table")
    elif "multi_agent_v2" in features:
        errors.append("legacy features.multi_agent_v2 must be migrated")
    elif features.get("default_mode_request_user_input") is not True:
        errors.append("native default-mode decision cards must be enabled")
    agents = config.get("agents", {})
    if not isinstance(agents, dict):
        errors.append("agents must be a role table")
        return errors, warnings
    if set(agents) - {AGENTS_CONCURRENCY_KEY}:
        errors.append("agents table has unsupported inline role keys")
    concurrency = agents.get(AGENTS_CONCURRENCY_KEY)
    if type(concurrency) is not int or not AGENTS_CONCURRENCY_MIN <= concurrency <= AGENTS_CONCURRENCY_MAX:
        errors.append("agents.max_concurrent_threads_per_session must be an integer from 1 to 8")
    elif concurrency != AGENTS_CONCURRENCY_RECOMMENDED:
        warnings.append(
            f"agents.max_concurrent_threads_per_session {concurrency} is normalized by the installer to 3"
        )
    if AGENTS_CONCURRENCY_KEY in config:
        errors.append("root concurrency key must be moved under [agents]")
    return errors, warnings


def validate_multi_agent_v2_config(config: dict) -> tuple[list[str], list[str]]:
    """Compatibility alias retained for callers while the schema is migrated."""
    return validate_agents_config(config)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def validate_dir(agents_dir: Path, *, expected_names: frozenset[str] | None = None) -> list[str]:
    """Validate recursively discovered roles and local containment/name rules."""
    problems: list[str] = []
    try:
        root = agents_dir.resolve(strict=True)
    except OSError:
        return [f"{agents_dir}: no agent TOML files found"]
    files = sorted(agents_dir.rglob("*.toml"))
    if not files:
        return [f"{agents_dir}: no agent TOML files found"]
    seen: set[str] = set()
    for path in files:
        if path.is_symlink() or not _inside(path, root):
            problems.append(f"{path.name}: role file escapes approved home")
            continue
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            problems.append(f"{path.name}: invalid TOML — {exc}")
            continue
        name = data.get("name")
        if name != path.stem:
            problems.append(f"{path.name}: name '{name}' does not match filename")
        if name in seen:
            problems.append(f"{path.name}: duplicate role name '{name}'")
        elif isinstance(name, str):
            seen.add(name)
        problems.extend(f"{path.name}: {message}" for message in validate_agent(data))
    if expected_names is not None and seen != expected_names:
        missing, extra = expected_names - seen, seen - expected_names
        if missing:
            problems.append(f"role manifest missing: {', '.join(sorted(missing))}")
        if extra:
            problems.append(f"role manifest extra: {', '.join(sorted(extra))}")
    return problems


def validate_config(path: Path) -> tuple[list[str], list[str]]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return [f"{path}: config file not found"], []
    except tomllib.TOMLDecodeError as exc:
        return [f"{path}: invalid TOML — {exc}"], []
    errors, warnings = validate_agents_config(data)
    return [f"{path}: {e}" for e in errors], [f"{path}: {w}" for w in warnings]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("agents_dirs", nargs="*", type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    config = args.config or (root / "templates" / "config.snippet.toml")
    dirs = args.agents_dirs or [root / "templates" / "agents"]
    errors, warnings = validate_config(config)
    for directory in dirs:
        errors.extend(validate_dir(directory, expected_names=ROLES))
    for warning in warnings:
        print(f"warning: {warning}", file=os.sys.stderr)
    if errors:
        print("\n".join(errors), file=os.sys.stderr)
        return 1
    print("all native Pilotfish config and agent TOMLs valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
