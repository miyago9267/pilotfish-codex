"""Validate bounded changes to the repository's agent prompt surfaces."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


MANIFEST_RELATIVE = Path("docs/specs/prompt-document-lock/LOCK.json")
VERSION_RELATIVE = Path("VERSION")
REQUIRED_SURFACE_PATHS = frozenset(
    {
        "templates/agents-md.bootstrap.md",
        "templates/agents-md.orchestration.md",
        "plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/references/orchestration-policy.md",
        "plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/SKILL.md",
        "plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/agents/openai.yaml",
        "plugin/plugins/pilotfish-codex/.codex-plugin/plugin.json",
        "templates/agents/executor.toml",
        "templates/agents/mech-executor.toml",
        "templates/agents/plan-verifier.toml",
        "templates/agents/scout.toml",
        "templates/agents/security-executor.toml",
        "templates/agents/security-reviewer.toml",
        "templates/agents/verifier.toml",
        "templates/hooks.json",
        "INSTALL_PROMPT.md",
    }
)
HARD_MAX_CHANGED_LINES = 32
HARD_MAX_CHANGED_CHARACTERS = 4000
HARD_MAX_CHANGE_RATIO = 0.35
HARD_MAX_BYTES = 60_000


class PromptLockError(ValueError):
    """Raised when a protected prompt surface violates the lock contract."""


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_relative_repo_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _validate_surface(surface: Any, index: int) -> None:
    if not isinstance(surface, dict):
        raise PromptLockError(f"surface {index}: expected an object")
    required = {
        "id",
        "path",
        "max_lines",
        "max_bytes",
        "max_changed_lines",
        "max_changed_characters",
        "max_change_ratio",
        "required_fragments",
    }
    missing = required - surface.keys()
    if missing:
        raise PromptLockError(f"surface {index}: missing fields {sorted(missing)}")
    if not isinstance(surface["id"], str) or not surface["id"]:
        raise PromptLockError(f"surface {index}: id must be a non-empty string")
    if not _is_relative_repo_path(surface["path"]):
        raise PromptLockError(f"surface {surface['id']}: path must stay inside the repository")
    for field in ("max_lines", "max_bytes", "max_changed_lines", "max_changed_characters"):
        if not _is_positive_int(surface[field]):
            raise PromptLockError(f"surface {surface['id']}: {field} must be a positive integer")
    if surface["max_bytes"] > HARD_MAX_BYTES:
        raise PromptLockError(f"surface {surface['id']}: max_bytes exceeds the hard ceiling")
    if surface["max_changed_lines"] > HARD_MAX_CHANGED_LINES:
        raise PromptLockError(f"surface {surface['id']}: max_changed_lines exceeds the hard ceiling")
    if surface["max_changed_characters"] > HARD_MAX_CHANGED_CHARACTERS:
        raise PromptLockError(
            f"surface {surface['id']}: max_changed_characters exceeds the hard ceiling"
        )
    ratio = surface["max_change_ratio"]
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0 < ratio <= HARD_MAX_CHANGE_RATIO:
        raise PromptLockError(f"surface {surface['id']}: max_change_ratio exceeds the hard ceiling")
    fragments = surface["required_fragments"]
    if not isinstance(fragments, list) or not fragments or not all(
        isinstance(fragment, str) and fragment for fragment in fragments
    ):
        raise PromptLockError(f"surface {surface['id']}: required_fragments must be non-empty strings")


def _validate_lock_shape(lock: Any) -> dict[str, Any]:
    if not isinstance(lock, dict):
        raise PromptLockError("lock manifest must be an object")
    if lock.get("schema_version") != 1:
        raise PromptLockError("unsupported prompt lock schema")
    if lock.get("status") != "active":
        raise PromptLockError("prompt lock must be active")
    if lock.get("manifest_immutable") is not True:
        raise PromptLockError("prompt lock manifest must be immutable")
    if not isinstance(lock.get("update_protocol"), str) or "--allow-lock-update" not in lock["update_protocol"]:
        raise PromptLockError("prompt lock must declare its explicit update protocol")
    version_gate = lock.get("version_gate")
    if not isinstance(version_gate, dict) or version_gate.get("path") != VERSION_RELATIVE.as_posix():
        raise PromptLockError("prompt lock must declare the VERSION gate")
    if version_gate.get("require_change_for_protected_surfaces") is not True:
        raise PromptLockError("prompt lock VERSION gate must be enabled")
    surfaces = lock.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise PromptLockError("prompt lock must contain surfaces")
    ids: set[str] = set()
    paths: set[str] = set()
    for index, surface in enumerate(surfaces):
        _validate_surface(surface, index)
        if surface["id"] in ids:
            raise PromptLockError(f"duplicate prompt lock surface id: {surface['id']}")
        if surface["path"] in paths:
            raise PromptLockError(f"duplicate prompt lock surface path: {surface['path']}")
        ids.add(surface["id"])
        paths.add(surface["path"])
    missing_paths = REQUIRED_SURFACE_PATHS - paths
    if missing_paths:
        raise PromptLockError(f"prompt lock removed required surfaces: {sorted(missing_paths)}")
    mirrors = lock.get("mirrors")
    if not isinstance(mirrors, list) or not mirrors:
        raise PromptLockError("prompt lock must declare mirrored policy files")
    for index, mirror in enumerate(mirrors):
        if not isinstance(mirror, dict) or not _is_relative_repo_path(mirror.get("left")) or not _is_relative_repo_path(
            mirror.get("right")
        ):
            raise PromptLockError(f"mirror {index}: paths must stay inside the repository")
    return lock


def load_lock(root: Path) -> dict[str, Any]:
    """Load and validate the repository lock manifest."""

    path = root / MANIFEST_RELATIVE
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PromptLockError(f"missing lock manifest: {MANIFEST_RELATIVE}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptLockError(f"invalid lock manifest: {MANIFEST_RELATIVE}") from exc
    return _validate_lock_shape(lock)


def _diff_metrics(before: str, after: str) -> dict[str, int | float]:
    old_lines = before.splitlines()
    new_lines = after.splitlines()
    line_matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    changed_lines = 0
    added_lines = 0
    removed_lines = 0
    for tag, old_start, old_end, new_start, new_end in line_matcher.get_opcodes():
        if tag == "equal":
            continue
        removed_lines += old_end - old_start
        added_lines += new_end - new_start
        changed_lines += (old_end - old_start) + (new_end - new_start)

    changed_characters = 0
    for tag, old_start, old_end, new_start, new_end in line_matcher.get_opcodes():
        if tag != "equal":
            changed_characters += sum(len(line) for line in old_lines[old_start:old_end])
            changed_characters += sum(len(line) for line in new_lines[new_start:new_end])
    total_characters = len(before) + len(after)
    return {
        "changed_lines": changed_lines,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "changed_characters": changed_characters,
        "change_ratio": changed_characters / total_characters if total_characters else 0.0,
    }


def check_change_budget(surface: dict[str, Any], before: str, after: str) -> dict[str, int | float]:
    """Check one surface and return redacted diff metrics."""

    metrics = _diff_metrics(before, after)
    label = surface.get("id") or surface.get("path") or "surface"
    limits = (
        ("changed_lines", surface["max_changed_lines"]),
        ("changed_characters", surface["max_changed_characters"]),
        ("change_ratio", surface["max_change_ratio"]),
    )
    for metric, limit in limits:
        if metrics[metric] > limit:
            raise PromptLockError(
                f"{label}: change budget exceeded for {metric} "
                f"({metrics[metric]} > {limit})"
            )
    return metrics


def _git_show(root: Path, base_ref: str, relative_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{relative_path}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _git_ref_exists(root: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode == 0


def _default_base_ref(root: Path) -> str | None:
    configured = os.environ.get("PROMPT_LOCK_BASE", "").strip()
    if configured:
        return configured
    return "HEAD" if _git_ref_exists(root, "HEAD") else None


def _resolve_repo_file(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = (root / relative_path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise PromptLockError(f"surface path escapes the repository: {relative_path}") from exc
    if not resolved_path.is_file():
        raise PromptLockError(f"protected surface is missing: {relative_path}")
    return resolved_path


def _validate_surface_content(root: Path, surface: dict[str, Any]) -> str:
    relative_path = surface["path"]
    path = _resolve_repo_file(root, relative_path)
    try:
        raw = path.read_bytes()
        content = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PromptLockError(f"protected surface is unreadable: {relative_path}") from exc
    if len(raw) > surface["max_bytes"]:
        raise PromptLockError(f"{surface['id']}: absolute size limit exceeded")
    if len(content.splitlines()) > surface["max_lines"]:
        raise PromptLockError(f"{surface['id']}: absolute line limit exceeded")
    normalized_content = " ".join(content.split()).casefold()
    for index, fragment in enumerate(surface["required_fragments"], start=1):
        if " ".join(fragment.split()).casefold() not in normalized_content:
            raise PromptLockError(f"{surface['id']}: required fragment {index} is missing")
    return content


def _validate_mirrors(root: Path, lock: dict[str, Any]) -> None:
    for index, mirror in enumerate(lock["mirrors"], start=1):
        left = _resolve_repo_file(root, mirror["left"])
        right = _resolve_repo_file(root, mirror["right"])
        if left.read_bytes() != right.read_bytes():
            raise PromptLockError(f"mirror {index} diverged: {mirror['left']} and {mirror['right']}")


def validate_lock(
    root: Path,
    base_ref: str | None = None,
    *,
    allow_lock_update: bool = False,
) -> dict[str, Any]:
    """Validate current surfaces and, when available, their Git diff budget."""

    root = root.resolve()
    lock = load_lock(root)
    contents = {
        surface["path"]: _validate_surface_content(root, surface)
        for surface in lock["surfaces"]
    }
    _validate_mirrors(root, lock)

    base_ref = base_ref or _default_base_ref(root)
    if base_ref and not base_ref.strip("0"):
        base_ref = "HEAD^" if _git_ref_exists(root, "HEAD^") else None
    if not base_ref:
        return {
            "status": "ok",
            "surface_count": len(contents),
            "base_diff": "skipped-no-base",
            "surfaces": [],
        }

    base_manifest = _git_show(root, base_ref, MANIFEST_RELATIVE.as_posix())
    if base_manifest is None:
        return {
            "status": "ok",
            "surface_count": len(contents),
            "base_diff": "skipped-new-lock",
            "surfaces": [],
        }

    current_manifest = (root / MANIFEST_RELATIVE).read_text(encoding="utf-8")
    if current_manifest != base_manifest and not allow_lock_update:
        raise PromptLockError(
            "LOCK.json changed; use --allow-lock-update only for an explicitly approved policy renewal"
        )

    reports: list[dict[str, Any]] = []
    for surface in lock["surfaces"]:
        relative_path = surface["path"]
        before = _git_show(root, base_ref, relative_path) or ""
        metrics = check_change_budget(surface, before, contents[relative_path])
        reports.append({"id": surface["id"], "path": relative_path, **metrics})
    if any(report["changed_characters"] for report in reports):
        current_version = _resolve_repo_file(root, VERSION_RELATIVE.as_posix()).read_text(encoding="utf-8").strip()
        base_version = (_git_show(root, base_ref, VERSION_RELATIVE.as_posix()) or "").strip()
        if not base_version or current_version == base_version:
            raise PromptLockError("protected prompt changed without a VERSION update")
    return {
        "status": "ok",
        "surface_count": len(contents),
        "base_diff": "checked",
        "surfaces": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--allow-lock-update", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        report = validate_lock(
            args.root,
            base_ref=args.base_ref or None,
            allow_lock_update=args.allow_lock_update,
        )
    except PromptLockError as exc:
        print(f"prompt-document-lock: error: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "prompt-document-lock: ok "
            f"surfaces={report['surface_count']} base_diff={report['base_diff']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
