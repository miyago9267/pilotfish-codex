#!/usr/bin/env python3
"""Route atomic work cheaply and retry one missing strong-role escalation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = 2
REQUIRED_TASK = "automatic_plan_review"
ROUTE_SCHEMA = 1
ROUTE_REQUIRED_TASK = "automatic_model_route"
MARKER_DIRECTORY = ".pilotfish-autoroute-gate"
MAX_HOOK_INPUT_BYTES = 1_048_576
MAX_PROMPT_CHARS = 65_536
MAX_MARKER_BYTES = 4_096
MAX_TRANSCRIPT_BYTES = 16 * 1_048_576
MAX_SCAN_ENTRIES = 32_768
MAX_SCAN_CANDIDATES = 256
MAX_SCAN_BYTES = 64 * 1_048_576
MAX_SCAN_DEPTH = 8
SCAN_MTIME_SLOP_SECONDS = 5
SCAN_DATE_SLOP_SECONDS = 86_400
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
TASK_NAME_RE = re.compile(r"^[a-z0-9_]+$")

BLOCK_REASON = (
    "Status: WAITING_FOR_REVIEW. Required independent Plan review is missing. "
    "This is an internal review dependency, not a user decision. Call the "
    "typed plan-verifier role now, wait for its result, and then continue "
    "from the review gate. Until a valid result arrives, allow only "
    "read-only local inspection or preparation; do not create, rotate, or "
    "revoke credentials, modify secrets or variables, push, deploy, or make "
    "any other external or irreversible write. Do not emit PAUSED_NEEDS_USER "
    "or ask the user solely because this review is pending."
)
BLOCK_OUTPUT = {"decision": "block", "reason": BLOCK_REASON}
MODEL_ROUTE_OUTPUT = {
    "decision": "block",
    "reason": (
        "Status: ROUTE_ESCALATION_REQUIRED. This turn needs design, tool use, "
        "interpretation, or multiple steps. Automatically call the typed "
        "`executor` role now; it is the strong `gpt-6-astra@high` binding. "
        "Do not ask the user to request a role or choose the next phase. "
        "Keep the existing goal, target, acceptance, and stop condition."
    ),
}

_PLAN_RE = re.compile(
    r"(?:\b(?:plan|planning|pre-approval|approval|approve|readiness|proposal)\b|"
    r"計畫|規劃|方案|核准|批准|審核)",
    re.IGNORECASE,
)
_CATEGORY_PATTERNS = {
    "data": re.compile(
        r"\b(?:data|database|schema|serialization|migration|pii|personal data|"
        r"backup|restore)\b|資料|數據|資料庫|結構描述|序列化|遷移|移轉",
        re.IGNORECASE,
    ),
    "external": re.compile(
        r"\b(?:external|third[- ]party|remote system|send (?:email|message)|"
        r"external mutation|external action)\b|外部系統|第三方|對外",
        re.IGNORECASE,
    ),
    "irreversible": re.compile(
        r"\b(?:destructive|irreversible|delete|drop|truncate|purge|overwrite|"
        r"force[- ]push)\b|破壞性|不可逆|刪除|清除|覆寫",
        re.IGNORECASE,
    ),
    "release": re.compile(
        r"\b(?:release|deploy|deployment|production|rollout|publish|shipping)\b|"
        r"發布|發佈|部署|上線|正式環境",
        re.IGNORECASE,
    ),
    "security": re.compile(
        r"\b(?:security|secure|trust boundary|authentication|authorization|"
        r"authn|authz|credential|secret|permission|iam|cryptography|crypto|"
        r"encryption|vulnerabilit(?:y|ies))\b|安全|信任邊界|身分驗證|身份驗證|"
        r"認證|授權|憑證|密鑰|祕密|秘密|權限|加密|漏洞",
        re.IGNORECASE,
    ),
}
_MARKER_KEYS = frozenset(
    {
        "schema",
        "session_id",
        "turn_id",
        "categories",
        "required_task",
        "attempted",
        "blocker_fingerprint",
    }
)
_ROUTE_MARKER_KEYS = frozenset(
    {
        "schema",
        "session_id",
        "turn_id",
        "required_task",
        "required_role",
        "route",
        "attempted",
        "route_fingerprint",
    }
)
_REVIEW_INTENT_PATTERNS = {
    "fast": re.compile(
        r"(?:快一點|快點|省時間|省錢|節省(?:時間|成本|token)|"
        r"不要額外(?:審查|review|思考)|先不要額外(?:審查|review)|"
        r"as fast as possible|save (?:time|money|tokens)|"
        r"minimi[sz]e cost|skip (?:the )?extra review)",
        re.IGNORECASE,
    ),
    "strict": re.compile(
        r"(?:嚴格(?:審查|review)|完整(?:驗證|測試|審查)|全面(?:審查|驗證)|"
        r"thorough(?:ly)? review|strict review|full verification|"
        r"test thoroughly|be rigorous)",
        re.IGNORECASE,
    ),
    "default": re.compile(
        r"(?:照預設|按預設模式|依照預設|use the default|default mode)",
        re.IGNORECASE,
    ),
}
_REVIEW_INTENT_NEGATION = re.compile(
    r"(?:不要|別|不必|do not|don't|never)\s*"
    r"(?:快|快速|quick|strict|嚴格|完整|thorough|rigorous)",
    re.IGNORECASE,
)
_QUOTED_SEGMENT = re.compile(
    r'"[^"\n]*"|\'[^\'\n]*\'|`[^`\n]*`|「[^」\n]*」|『[^』\n]*』'
)
_ATOMIC_COMMAND = re.compile(
    r"^\s*(?:請|请|please\s+)?(?:執行|执行|run|execute|check|檢查|检查|"
    r"查看|顯示|显示|列出|show|list)\s+(?:`[^`\n]+`|"
    r"[A-Za-z0-9_./:@+=,-]+(?:\s+[A-Za-z0-9_./:@+=,-]+)*)"
    r"[。.!！?？]*\s*$",
    re.IGNORECASE,
)
_ATOMIC_DIRECT_ACTION = re.compile(
    r"^\s*(?:請|请|please\s+)?(?:修正|修复|修復|fix|改正)\s*"
    r"[^。.!！?？]*(?:拼字|拼寫|拼写|typo|spelling|格式化|format|"
    r"formatting|格式)[^。.!！?？]*"
    r"[^。.!！?？]*[。.!！?？]*\s*$",
    re.IGNORECASE,
)
_ATOMIC_UNSAFE = re.compile(
    r"\b(?:rm|delete|drop|truncate|purge|force[- ]?push|deploy|production|"
    r"sudo|chmod|credential|secret|token|password)\b|刪除|删除|清除|覆寫|"
    r"覆写|部署|正式環境|正式环境|憑證|凭证|密碼|密码|祕密|秘密",
    re.IGNORECASE,
)
_ATOMIC_CONNECTOR = re.compile(
    r"\b(?:and|then|after|also|multiple|both)\b|然後|然后|再|以及|並且|并且|"
    r"同時|同时|接著|接着",
    re.IGNORECASE,
)
_JUDGMENT_HINTS = re.compile(
    r"設計|设计|規劃|规划|實作|实现|修復|修复|診斷|诊断|分析|比較|比较|"
    r"選擇|选择|解讀|解读|原因|為什麼|为什么|how|why|design|plan|diagnos|"
    r"debug|architect|tool|工具|流程|方案|策略|多步|跨檔|跨文件|跨系統|跨系统",
    re.IGNORECASE,
)


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(IDENTIFIER_RE.fullmatch(value))


def classify_prompt(prompt: object) -> tuple[str, ...]:
    """Return only stable policy category labels; never retain prompt text."""
    if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
        return ()
    if _PLAN_RE.search(prompt) is None:
        return ()
    return tuple(
        sorted(
            category
            for category, pattern in _CATEGORY_PATTERNS.items()
            if pattern.search(prompt) is not None
        )
    )


def classify_review_intent(prompt: object) -> str | None:
    """Extract only clear explicit review preferences from a user prompt.

    This is intentionally narrower than task or risk classification. Quoted
    examples, negated cues, and conflicting preferences abstain to the normal
    risk policy instead of guessing a mode.
    """
    if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
        return None
    text = _QUOTED_SEGMENT.sub(" ", prompt)
    if _REVIEW_INTENT_NEGATION.search(text):
        return None
    matches = [
        intent
        for intent, pattern in _REVIEW_INTENT_PATTERNS.items()
        if pattern.search(text) is not None
    ]
    return matches[0] if len(matches) == 1 else None


def classify_execution_route(prompt: object) -> str:
    """Choose a conservative cheap-vs-strong route without retaining prompt text."""
    if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
        return "judgment"
    text = prompt.strip()
    if (
        (_ATOMIC_COMMAND.fullmatch(text) or _ATOMIC_DIRECT_ACTION.fullmatch(text))
        and _ATOMIC_UNSAFE.search(text) is None
        and _ATOMIC_CONNECTOR.search(text) is None
        and _JUDGMENT_HINTS.search(text) is None
    ):
        return "atomic"
    return "judgment"


def execution_route_reason(prompt: object, route: str) -> str:
    """Return a stable redacted reason for the selected route."""
    if route == "atomic":
        return "single_action"
    if not isinstance(prompt, str):
        return "uncertain"
    if _JUDGMENT_HINTS.search(prompt) is not None:
        return "design_or_interpretation"
    if _ATOMIC_CONNECTOR.search(prompt) is not None:
        return "multiple_steps"
    if _ATOMIC_UNSAFE.search(prompt) is not None:
        return "authority_or_irreversible_boundary"
    return "uncertain"


def _route_signal(payload: dict[str, Any], prompt: object) -> dict[str, Any]:
    route = classify_execution_route(prompt)
    categories = classify_prompt(prompt)
    security_route = route == "judgment" and "security" in categories
    if security_route:
        required_role = "security-reviewer"
        model_policy = "specialized"
        model_snapshot = "gpt-5.6-sol@high"
    elif route == "atomic":
        required_role = "none"
        model_policy = "cheap"
        model_snapshot = "gpt-5.6-luna@medium"
    else:
        required_role = "executor"
        model_policy = "strong"
        model_snapshot = "gpt-6-astra@high"
    return {
        "schema": ROUTE_SCHEMA,
        "session_id": payload["session_id"],
        "turn_id": payload["turn_id"],
        "route": route,
        "model_policy": model_policy,
        "required_role": required_role,
        "model_snapshot": model_snapshot,
        "reason": execution_route_reason(prompt, route),
    }


def _blocker_fingerprint(
    prompt: object,
    categories: tuple[str, ...],
) -> str | None:
    """Identify the same blocker without persisting prompt content."""
    if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
        return None
    normalized = re.sub(r"\s+", " ", prompt.strip()).casefold()
    material = json.dumps(
        {"categories": list(categories), "prompt": normalized},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _review_intent_output(
    payload: dict[str, Any],
    intent: str | None,
    categories: tuple[str, ...],
) -> dict[str, Any] | None:
    if intent is None:
        return None
    optional_review = {
        "fast": "skip",
        "default": "existing_policy",
        "strict": "expanded",
    }[intent]
    signal = {
        "schema": 1,
        "session_id": payload["session_id"],
        "turn_id": payload["turn_id"],
        "review_intent": intent,
        "source": "explicit",
        "scope": "turn",
        "confidence": "clear",
        "risk_categories": list(categories),
        "optional_review": optional_review,
    }
    context = "Pilotfish review intent signal: " + json.dumps(
        signal, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def _combined_prompt_output(
    payload: dict[str, Any],
    prompt: object,
    intent: str | None,
    categories: tuple[str, ...],
) -> dict[str, Any]:
    route_signal = _route_signal(payload, prompt)
    contexts = [
        "Pilotfish automatic model route: "
        + json.dumps(route_signal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ]
    review_output = _review_intent_output(payload, intent, categories)
    if review_output is not None:
        contexts.append(review_output["hookSpecificOutput"]["additionalContext"])
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(contexts),
        }
    }


def requires_sol_review(categories: tuple[str, ...]) -> bool:
    """Apply the bounded selective-switch trigger for high-reasoning review."""
    return bool(categories) and ("security" in categories or len(categories) >= 2)


def route_reason(
    categories: tuple[str, ...],
    *,
    luna_uncertain: bool = False,
    unresolved_critical: bool = False,
) -> str:
    """Return the auditable reason for a Luna-first/Sol-second-opinion route."""
    if "security" in categories:
        return "security_boundary"
    if unresolved_critical:
        return "unresolved_critical"
    if luna_uncertain:
        return "luna_uncertainty"
    if len(categories) >= 2:
        return "multiple_material_risks"
    return "luna_default"


def _marker_directory(codex_home: Path, *, create: bool) -> Path | None:
    directory = codex_home / MARKER_DIRECTORY
    try:
        home = codex_home.resolve(strict=True)
        if not home.is_dir():
            return None
        if create:
            directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return None
        if not directory.resolve(strict=True).is_relative_to(home):
            return None
        if create and os.name != "nt":
            os.chmod(directory, 0o700)
        elif not create and os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o700:
            return None
        return directory
    except OSError:
        return None


def _marker_path(codex_home: Path, session_id: str, *, create: bool) -> Path | None:
    directory = _marker_directory(codex_home, create=create)
    if directory is None:
        return None
    filename = hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".json"
    return directory / filename


def _route_marker_path(codex_home: Path, session_id: str, *, create: bool) -> Path | None:
    path = _marker_path(codex_home, session_id, create=create)
    if path is None:
        return None
    return path.with_name(path.stem + ".route.json")


def _unlink_marker(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _remove_review_marker(codex_home: Path, session_id: str) -> None:
    _unlink_marker(_marker_path(codex_home, session_id, create=False))


def _remove_route_marker(codex_home: Path, session_id: str) -> None:
    _unlink_marker(_route_marker_path(codex_home, session_id, create=False))


def _remove_marker(codex_home: Path, session_id: str) -> None:
    _remove_review_marker(codex_home, session_id)
    _remove_route_marker(codex_home, session_id)


def _atomic_marker_write_at(path: Path, marker: dict[str, Any]) -> bool:
    payload = json.dumps(marker, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    if len(payload) > MAX_MARKER_BYTES:
        return False
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".marker-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        if path.exists() and path.is_symlink():
            return False
        os.replace(temporary, path)
        temporary = None
        return True
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _atomic_marker_write(codex_home: Path, marker: dict[str, Any]) -> bool:
    path = _marker_path(codex_home, marker["session_id"], create=True)
    return path is not None and _atomic_marker_write_at(path, marker)


def _atomic_route_marker_write(codex_home: Path, marker: dict[str, Any]) -> bool:
    path = _route_marker_path(codex_home, marker["session_id"], create=True)
    return path is not None and _atomic_marker_write_at(path, marker)


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _load_marker(codex_home: Path, session_id: str) -> dict[str, Any] | None:
    path = _marker_path(codex_home, session_id, create=False)
    if path is None:
        return None
    try:
        info = path.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or (
                os.name != "nt"
                and stat.S_IMODE(info.st_mode) != 0o600
            )
            or info.st_size > MAX_MARKER_BYTES
        ):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                return None
            payload = _read_bounded(descriptor, MAX_MARKER_BYTES)
        finally:
            os.close(descriptor)
        if len(payload) > MAX_MARKER_BYTES:
            return None
        marker = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(marker, dict) or set(marker) != _MARKER_KEYS:
        return None
    categories = marker.get("categories")
    if (
        marker.get("schema") != SCHEMA
        or marker.get("session_id") != session_id
        or not _valid_identifier(marker.get("turn_id"))
        or not isinstance(marker.get("attempted"), bool)
        or marker.get("required_task") != REQUIRED_TASK
        or not isinstance(marker.get("blocker_fingerprint"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", marker["blocker_fingerprint"])
        or not isinstance(categories, list)
        or categories != sorted(set(categories))
        or any(category not in _CATEGORY_PATTERNS for category in categories)
        or not categories
    ):
        return None
    return marker


def _load_route_marker(codex_home: Path, session_id: str) -> dict[str, Any] | None:
    path = _route_marker_path(codex_home, session_id, create=False)
    if path is None:
        return None
    try:
        info = path.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or (os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600)
            or info.st_size > MAX_MARKER_BYTES
        ):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                return None
            payload = _read_bounded(descriptor, MAX_MARKER_BYTES)
        finally:
            os.close(descriptor)
        if len(payload) > MAX_MARKER_BYTES:
            return None
        marker = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(marker, dict) or set(marker) != _ROUTE_MARKER_KEYS:
        return None
    if (
        marker.get("schema") != ROUTE_SCHEMA
        or marker.get("session_id") != session_id
        or not _valid_identifier(marker.get("turn_id"))
        or marker.get("required_task") != ROUTE_REQUIRED_TASK
        or marker.get("required_role") != "executor"
        or marker.get("route") != "judgment"
        or not isinstance(marker.get("attempted"), bool)
        or not isinstance(marker.get("route_fingerprint"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", marker["route_fingerprint"])
    ):
        return None
    return marker


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
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_transcript(
    codex_home: Path,
    transcript_value: object,
) -> list[dict[str, Any]] | None:
    if not isinstance(transcript_value, str) or not transcript_value:
        return None
    transcript = Path(transcript_value)
    if not transcript.is_absolute():
        return None
    sessions = codex_home / "sessions"
    descriptor: int | None = None
    try:
        home = codex_home.resolve(strict=True)
        sessions_info = sessions.lstat()
        if stat.S_ISLNK(sessions_info.st_mode) or not stat.S_ISDIR(sessions_info.st_mode):
            return None
        sessions_real = sessions.resolve(strict=True)
        if not sessions_real.is_relative_to(home):
            return None
        before = transcript.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_size > MAX_TRANSCRIPT_BYTES
        ):
            return None
        transcript.resolve(strict=True).relative_to(sessions_real)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(transcript, flags)
        opened = os.fstat(descriptor)
        if _stat_fingerprint(opened) != _stat_fingerprint(before):
            return None
        payload = _read_bounded(descriptor, MAX_TRANSCRIPT_BYTES)
        after_fd = os.fstat(descriptor)
        after_path = transcript.lstat()
        if (
            len(payload) > MAX_TRANSCRIPT_BYTES
            or _stat_fingerprint(after_fd) != _stat_fingerprint(before)
            or _stat_fingerprint(after_path) != _stat_fingerprint(before)
        ):
            return None
    except (OSError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        lines = payload.decode("utf-8").splitlines()
        if not lines:
            return None
        events = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not all(isinstance(event, dict) for event in events):
        return None
    return events


def _epoch(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    epoch = float(value)
    return epoch if math.isfinite(epoch) and epoch >= 0 else None


def _timestamp_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    epoch = parsed.timestamp()
    return epoch if math.isfinite(epoch) and epoch >= 0 else None


def _root_task_started_epoch(
    events: list[dict[str, Any]],
    *,
    session_id: str,
    turn_id: str,
) -> float | None:
    sessions = [
        event["payload"]
        for event in events
        if event.get("type") == "session_meta"
        and isinstance(event.get("payload"), dict)
    ]
    if len(sessions) != 1 or sessions[0].get("id") != session_id:
        return None
    boundaries = [
        event["payload"]
        for event in events
        if event.get("type") == "event_msg"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("type") == "task_started"
    ]
    if not boundaries or boundaries[-1].get("turn_id") != turn_id:
        return None
    return _epoch(boundaries[-1].get("started_at"))


def _terminal_review_output(text: object) -> bool:
    if text == "READY":
        return True
    if not isinstance(text, str) or not text.startswith("REVISE\n"):
        return False
    if text != text.strip():
        return False
    lines = [line for line in text.splitlines()[1:] if line]
    fields = ("Blocker:", "Evidence:", "Minimum revision:", "Acceptance check:")
    if not lines or len(lines) % len(fields):
        return False
    for index, line in enumerate(lines):
        field = fields[index % len(fields)]
        if not line.startswith(field) or not line[len(field) :].strip():
            return False
    return True


def _linked_child_status(
    events: list[dict[str, Any]],
    *,
    parent_id: str,
    root_started_at: float,
    allowed_child_id: str | None,
) -> int:
    """Return 1 for valid, 0 for unrelated, and -1 for invalid candidate."""
    session_events = [event for event in events if event.get("type") == "session_meta"]
    linked = [
        event
        for event in session_events
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("parent_thread_id") == parent_id
    ]
    if not linked:
        return 0
    if len(session_events) != 1 or len(linked) != 1:
        return -1
    session_event = linked[0]
    session = session_event["payload"]
    role = session.get("agent_role")
    if role != "plan-verifier":
        return 0 if isinstance(role, str) and role else -1
    child_id = session.get("id")
    if not _valid_identifier(child_id) or child_id == parent_id:
        return -1
    if allowed_child_id is not None and child_id != allowed_child_id:
        return -1
    session_started_at = _timestamp_epoch(session_event.get("timestamp"))
    if (
        session_started_at is None
        or session_started_at < root_started_at
    ):
        return -1
    for event in events:
        if event.get("type") in {
            "session_meta",
            "turn_context",
            "event_msg",
            "response_item",
        } and not isinstance(event.get("payload"), dict):
            return -1
    contexts = [event["payload"] for event in events if event.get("type") == "turn_context"]
    if len(contexts) != 1 or contexts[0].get("model") != "gpt-5.6-sol" or contexts[0].get("effort") != "high":
        return -1
    if any(
        event.get("type") == "event_msg"
        and event["payload"].get("type")
        in {"error", "task_failed", "turn_aborted", "turn_cancelled"}
        for event in events
    ):
        return -1
    starts = [
        (index, event["payload"])
        for index, event in enumerate(events)
        if event.get("type") == "event_msg"
        and event["payload"].get("type") == "task_started"
    ]
    completes = [
        (index, event["payload"])
        for index, event in enumerate(events)
        if event.get("type") == "event_msg"
        and event["payload"].get("type") == "task_complete"
    ]
    if len(starts) != 1 or len(completes) != 1:
        return -1
    start_index, start = starts[0]
    child_started_at = _epoch(start.get("started_at"))
    if (
        not _valid_identifier(start.get("turn_id"))
        or child_started_at is None
        or child_started_at < root_started_at
        or completes[0][0] <= start_index
        or completes[0][1].get("turn_id") != start.get("turn_id")
    ):
        return -1
    messages = [
        (index, event["payload"])
        for index, event in enumerate(events)
        if event.get("type") == "response_item"
        and event["payload"].get("type") == "message"
        and event["payload"].get("role") == "assistant"
    ]
    if len(messages) != 1 or not start_index < messages[0][0] < completes[0][0]:
        return -1
    content = messages[0][1].get("content")
    if (
        not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], dict)
        or content[0].get("type") != "output_text"
        or not _terminal_review_output(content[0].get("text"))
    ):
        return -1
    return 1


class _ScanRejected(Exception):
    """Evidence that cannot be trusted; the gate must not be suppressed."""


class _ScanExhausted(_ScanRejected):
    """A scan budget ran out before the tree was covered.

    Kept fail-closed on purpose: an unfinished scan is indistinguishable from a
    scan whose budget was deliberately consumed, so it may never stand in for a
    proven review. Date pruning keeps the budgets far away from ordinary use.
    """


def _scan_cutoff(root_started_at: float) -> tuple[int, int, int]:
    """Return the earliest UTC date whose session subtree can hold evidence."""
    stamp = datetime.fromtimestamp(
        max(root_started_at - SCAN_DATE_SLOP_SECONDS, 0), tz=timezone.utc
    )
    return (stamp.year, stamp.month, stamp.day)


def _prunable_subtree(parts: tuple[str, ...], cutoff: tuple[int, int, int]) -> bool:
    """Report whether a `sessions/YYYY/MM/DD` subtree predates the current turn.

    Any component that is not a well-formed date segment disables pruning for
    that subtree, so an unexpected layout is walked rather than skipped.
    """
    widths = (4, 2, 2)
    if not parts or len(parts) > len(widths):
        return False
    values: list[int] = []
    for index, part in enumerate(parts):
        if len(part) != widths[index] or not part.isdigit():
            return False
        values.append(int(part))
    if len(values) > 1 and not 1 <= values[1] <= 12:
        return False
    if len(values) > 2 and not 1 <= values[2] <= 31:
        return False
    latest = (values[0], values[1] if len(values) > 1 else 12, values[2] if len(values) > 2 else 31)
    return latest < cutoff


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    """Fingerprint a directory without its mtime, which live sessions change."""
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid)


def _decode_jsonl(payload: bytes) -> list[dict[str, Any]]:
    try:
        lines = payload.decode("utf-8").splitlines()
        if not lines:
            raise _ScanRejected
        events = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ScanRejected from exc
    if not all(isinstance(event, dict) for event in events):
        raise _ScanRejected
    return events


def _read_scanned_jsonl(
    directory_fd: int | Path,
    name: str,
    expected: os.stat_result,
) -> list[dict[str, Any]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        if isinstance(directory_fd, Path):
            path = directory_fd / name
            descriptor = os.open(path, flags)
        else:
            path = None
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        if (
            _stat_fingerprint(opened) != _stat_fingerprint(expected)
            or not _same_owner(opened, expected.st_uid)
        ):
            raise _ScanRejected
        payload = _read_bounded(descriptor, MAX_TRANSCRIPT_BYTES)
        after_fd = os.fstat(descriptor)
        if path is not None:
            after_path = os.stat(path, follow_symlinks=False)
        else:
            after_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            len(payload) > MAX_TRANSCRIPT_BYTES
            or _stat_fingerprint(after_fd) != _stat_fingerprint(expected)
            or _stat_fingerprint(after_path) != _stat_fingerprint(expected)
            or not _same_owner(after_fd, expected.st_uid)
            or not _same_owner(after_path, expected.st_uid)
        ):
            raise _ScanRejected
        return _decode_jsonl(payload)
    except OSError as exc:
        raise _ScanRejected from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _same_owner(info: os.stat_result, current_uid: int | None) -> bool:
    """Use NTFS ACL inheritance where Windows has no POSIX uid mapping."""
    return os.name == "nt" or info.st_uid == current_uid


def _intrinsic_child_review_proven_windows(
    codex_home: Path,
    *,
    parent_id: str,
    root_started_at: float,
    allowed_child_id: str | None,
) -> bool:
    """Scan Windows sessions without POSIX dir_fd APIs."""
    sessions = codex_home / "sessions"
    state = {"entries": 0, "candidates": 0, "bytes": 0}
    cutoff = _scan_cutoff(root_started_at)
    valid_children = 0

    def scan(directory: Path, depth: int, parts: tuple[str, ...]) -> None:
        nonlocal valid_children
        if depth > MAX_SCAN_DEPTH:
            raise _ScanExhausted
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise _ScanRejected from exc
        for entry in entries:
                state["entries"] += 1
                if state["entries"] > MAX_SCAN_ENTRIES:
                    raise _ScanExhausted
                try:
                    # DirEntry.stat() returns zero device/inode fields on some
                    # Windows filesystems; use the path stat so the later
                    # open/read identity check compares like with like.
                    info = os.stat(entry.path, follow_symlinks=False)
                except OSError as exc:
                    raise _ScanRejected from exc
                if stat.S_ISLNK(info.st_mode):
                    continue
                name = entry.name
                if stat.S_ISDIR(info.st_mode):
                    child_parts = parts + (name,)
                    if _prunable_subtree(child_parts, cutoff):
                        continue
                    child = directory / name
                    scan(child, depth + 1, child_parts)
                    try:
                        after = child.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise _ScanRejected from exc
                    if _directory_identity(after) != _directory_identity(info):
                        raise _ScanRejected
                    continue
                if not stat.S_ISREG(info.st_mode) or not name.endswith(".jsonl"):
                    continue
                if info.st_mtime + SCAN_MTIME_SLOP_SECONDS < root_started_at:
                    continue
                state["candidates"] += 1
                state["bytes"] += info.st_size
                if (
                    state["candidates"] > MAX_SCAN_CANDIDATES
                    or state["bytes"] > MAX_SCAN_BYTES
                ):
                    raise _ScanExhausted
                if info.st_size > MAX_TRANSCRIPT_BYTES:
                    raise _ScanRejected
                events = _read_scanned_jsonl(directory, name, info)
                status = _linked_child_status(
                    events,
                    parent_id=parent_id,
                    root_started_at=root_started_at,
                    allowed_child_id=allowed_child_id,
                )
                if status < 0:
                    raise _ScanRejected
                valid_children += status

    try:
        root_info = sessions.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            return False
        home = codex_home.resolve(strict=True)
        if not sessions.resolve(strict=True).is_relative_to(home):
            return False
        scan(sessions, 0, ())
        after = sessions.lstat()
        if _directory_identity(after) != _directory_identity(root_info):
            return False
    except (OSError, _ScanRejected):
        return False
    return valid_children == 1


def _intrinsic_child_review_proven(
    codex_home: Path,
    *,
    parent_id: str,
    root_started_at: float,
    allowed_child_id: str | None,
) -> bool:
    if os.name == "nt":
        return _intrinsic_child_review_proven_windows(
            codex_home,
            parent_id=parent_id,
            root_started_at=root_started_at,
            allowed_child_id=allowed_child_id,
        )
    getuid = getattr(os, "getuid", None)
    current_uid = getuid() if getuid is not None else None
    sessions = codex_home / "sessions"
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd: int | None = None
    state = {"entries": 0, "candidates": 0, "bytes": 0}
    cutoff = _scan_cutoff(root_started_at)
    valid_children = 0

    def scan(directory_fd: int, depth: int, parts: tuple[str, ...]) -> None:
        nonlocal valid_children
        if depth > MAX_SCAN_DEPTH:
            raise _ScanExhausted
        names: list[str] = []
        try:
            with os.scandir(directory_fd) as iterator:
                for entry in iterator:
                    state["entries"] += 1
                    if state["entries"] > MAX_SCAN_ENTRIES:
                        raise _ScanExhausted
                    names.append(entry.name)
        except OSError as exc:
            raise _ScanRejected from exc
        for name in sorted(names):
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise _ScanRejected from exc
            if stat.S_ISLNK(info.st_mode) or not _same_owner(info, current_uid):
                continue
            if stat.S_ISDIR(info.st_mode):
                child_parts = parts + (name,)
                if _prunable_subtree(child_parts, cutoff):
                    continue
                child_fd: int | None = None
                try:
                    try:
                        child_fd = os.open(name, flags, dir_fd=directory_fd)
                    except OSError:
                        continue
                    opened = os.fstat(child_fd)
                    if (
                        (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                        or not _same_owner(opened, current_uid)
                    ):
                        raise _ScanRejected
                    scan(child_fd, depth + 1, child_parts)
                    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if _directory_identity(after) != _directory_identity(info):
                        raise _ScanRejected
                finally:
                    if child_fd is not None:
                        os.close(child_fd)
                continue
            if not stat.S_ISREG(info.st_mode) or not name.endswith(".jsonl"):
                continue
            if info.st_mtime + SCAN_MTIME_SLOP_SECONDS < root_started_at:
                continue
            state["candidates"] += 1
            state["bytes"] += info.st_size
            if (
                state["candidates"] > MAX_SCAN_CANDIDATES
                or state["bytes"] > MAX_SCAN_BYTES
            ):
                raise _ScanExhausted
            if info.st_size > MAX_TRANSCRIPT_BYTES:
                raise _ScanRejected
            events = _read_scanned_jsonl(directory_fd, name, info)
            status = _linked_child_status(
                events,
                parent_id=parent_id,
                root_started_at=root_started_at,
                allowed_child_id=allowed_child_id,
            )
            if status < 0:
                raise _ScanRejected
            valid_children += status

    try:
        root_info = sessions.lstat()
        if (
            stat.S_ISLNK(root_info.st_mode)
            or not stat.S_ISDIR(root_info.st_mode)
            or not _same_owner(root_info, current_uid)
        ):
            return False
        home = codex_home.resolve(strict=True)
        if not sessions.resolve(strict=True).is_relative_to(home):
            return False
        root_fd = os.open(sessions, flags)
        opened = os.fstat(root_fd)
        if (
            (opened.st_dev, opened.st_ino) != (root_info.st_dev, root_info.st_ino)
            or not _same_owner(opened, current_uid)
        ):
            return False
        scan(root_fd, 0, ())
        after = sessions.lstat()
        if _directory_identity(after) != _directory_identity(root_info):
            return False
    except (OSError, _ScanRejected):
        return False
    finally:
        if root_fd is not None:
            os.close(root_fd)
    return valid_children == 1


def _direct_child_filter(
    events: list[dict[str, Any]],
    *,
    session_id: str,
    turn_id: str,
    required_role: str = "plan-verifier",
    required_task: str = REQUIRED_TASK,
) -> tuple[bool, str | None]:
    sessions = [
        event["payload"]
        for event in events
        if event.get("type") == "session_meta"
        and isinstance(event.get("payload"), dict)
    ]
    if len(sessions) != 1 or sessions[0].get("id") != session_id:
        return False, None
    boundaries = [
        (index, event["payload"].get("turn_id"))
        for index, event in enumerate(events)
        if event.get("type") == "event_msg"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("type") == "task_started"
    ]
    if not boundaries or boundaries[-1][1] != turn_id:
        return False, None
    segment = events[boundaries[-1][0] :]
    calls: list[tuple[int, str]] = []
    for index, event in enumerate(segment):
        payload = event.get("payload")
        if (
            event.get("type") != "response_item"
            or not isinstance(payload, dict)
            or payload.get("type") != "function_call"
            or payload.get("name") != "spawn_agent"
        ):
            continue
        try:
            arguments = json.loads(payload.get("arguments", ""))
        except (TypeError, json.JSONDecodeError):
            return False, None
        if not isinstance(arguments, dict):
            return False, None
        if arguments.get("agent_type") != required_role:
            continue
        if (
            set(arguments) != {"message", "agent_type", "task_name", "fork_turns"}
            or not isinstance(arguments.get("message"), str)
            or not arguments["message"].strip()
            or not isinstance(arguments.get("task_name"), str)
            or TASK_NAME_RE.fullmatch(arguments["task_name"]) is None
            or arguments.get("fork_turns") not in {"none", "1", "2", "3"}
        ):
            return False, None
        if arguments["task_name"] != required_task:
            return False, None
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            calls.append((index, call_id))
    if not calls:
        return True, None
    if len(calls) != 1:
        return False, None
    call_index, call_id = calls[0]
    activities = [
        payload
        for index, event in enumerate(segment)
        if index > call_index
        and event.get("type") == "event_msg"
        and isinstance((payload := event.get("payload")), dict)
        and payload.get("type") == "sub_agent_activity"
        and payload.get("kind") == "started"
        and payload.get("event_id") == call_id
        and isinstance(payload.get("agent_thread_id"), str)
        and bool(payload["agent_thread_id"])
    ]
    if len(activities) != 1:
        return False, None
    child_id = activities[0].get("agent_thread_id")
    if not _valid_identifier(child_id):
        return False, None
    return True, child_id


def _handle_prompt(payload: dict[str, Any], codex_home: Path) -> dict[str, Any] | None:
    session_id = payload.get("session_id")
    turn_id = payload.get("turn_id")
    if not _valid_identifier(session_id):
        return None
    if payload.get("agent_id") is not None or payload.get("agent_type") is not None:
        _remove_marker(codex_home, session_id)
        return None
    prompt = payload.get("prompt")
    categories = classify_prompt(prompt)
    intent = classify_review_intent(prompt)
    if not _valid_identifier(turn_id):
        _remove_marker(codex_home, session_id)
        return None
    route_signal = _route_signal(payload, prompt)
    if requires_sol_review(categories):
        fingerprint = _blocker_fingerprint(prompt, categories)
        previous = _load_marker(codex_home, session_id)
        if (
            fingerprint is not None
            and previous is not None
            and previous["blocker_fingerprint"] == fingerprint
        ):
            marker = dict(previous)
            marker["turn_id"] = turn_id
        else:
            marker = {
                "schema": SCHEMA,
                "session_id": session_id,
                "turn_id": turn_id,
                "categories": list(categories),
                "required_task": REQUIRED_TASK,
                "attempted": False,
                "blocker_fingerprint": fingerprint,
            }
        if not _atomic_marker_write(codex_home, marker):
            _remove_marker(codex_home, session_id)
        else:
            _remove_route_marker(codex_home, session_id)
    elif route_signal["required_role"] == "executor":
        _remove_review_marker(codex_home, session_id)
        fingerprint = _blocker_fingerprint(
            prompt,
            ("model_route", route_signal["reason"]),
        )
        previous = _load_route_marker(codex_home, session_id)
        if (
            fingerprint is not None
            and previous is not None
            and previous["route_fingerprint"] == fingerprint
        ):
            marker = dict(previous)
            marker["turn_id"] = turn_id
        else:
            marker = {
                "schema": ROUTE_SCHEMA,
                "session_id": session_id,
                "turn_id": turn_id,
                "required_task": ROUTE_REQUIRED_TASK,
                "required_role": "executor",
                "route": "judgment",
                "attempted": False,
                "route_fingerprint": fingerprint,
            }
        if not _atomic_route_marker_write(codex_home, marker):
            _remove_route_marker(codex_home, session_id)
    else:
        _remove_marker(codex_home, session_id)
    return _combined_prompt_output(payload, prompt, intent, categories)


def _handle_stop(payload: dict[str, Any], codex_home: Path) -> dict[str, str] | None:
    session_id = payload.get("session_id")
    turn_id = payload.get("turn_id")
    if not _valid_identifier(session_id) or not _valid_identifier(turn_id):
        return None
    marker = _load_marker(codex_home, session_id)
    route_marker = None if marker is not None else _load_route_marker(codex_home, session_id)
    if marker is None and route_marker is None:
        _remove_marker(codex_home, session_id)
        return None
    active_marker = marker if marker is not None else route_marker
    if active_marker["turn_id"] != turn_id:
        _remove_marker(codex_home, session_id)
        return None
    events = _read_transcript(codex_home, payload.get("transcript_path"))
    if events is None:
        _remove_marker(codex_home, session_id)
        return None
    if route_marker is not None:
        direct_chain_valid, allowed_child_id = _direct_child_filter(
            events,
            session_id=session_id,
            turn_id=turn_id,
            required_role="executor",
            required_task=ROUTE_REQUIRED_TASK,
        )
        if direct_chain_valid and allowed_child_id is not None:
            _remove_route_marker(codex_home, session_id)
            return None
        if active_marker["attempted"]:
            return None
        active_marker["attempted"] = True
        if not _atomic_route_marker_write(codex_home, active_marker):
            _remove_route_marker(codex_home, session_id)
            return None
        return dict(MODEL_ROUTE_OUTPUT)
    direct_chain_valid, allowed_child_id = _direct_child_filter(
        events,
        session_id=session_id,
        turn_id=turn_id,
    )
    root_started_at = _root_task_started_epoch(
        events,
        session_id=session_id,
        turn_id=turn_id,
    )
    if (
        direct_chain_valid
        and root_started_at is not None
        and _intrinsic_child_review_proven(
            codex_home,
            parent_id=session_id,
            root_started_at=root_started_at,
            allowed_child_id=allowed_child_id,
        )
    ):
        _remove_marker(codex_home, session_id)
        return None
    if payload.get("stop_hook_active") is not False:
        _remove_marker(codex_home, session_id)
        return None
    if marker["attempted"]:
        return None
    marker["attempted"] = True
    if not _atomic_marker_write(codex_home, marker):
        _remove_marker(codex_home, session_id)
        return None
    return dict(BLOCK_OUTPUT)


def handle(
    payload: object,
    *,
    codex_home: Path | None = None,
) -> dict[str, str] | None:
    """Handle one native hook envelope without emitting sensitive diagnostics."""
    if not isinstance(payload, dict):
        return None
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        return _handle_prompt(payload, home)
    if event == "Stop":
        return _handle_stop(payload, home)
    return None


SELFTEST_OK = f"pilotfish-autoroute-gate schema={SCHEMA} launchable"


def main(argv: list[str] | None = None) -> int:
    """Read one bounded JSON hook envelope and print only protocol output."""
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--selftest"]:
        sys.stdout.write(SELFTEST_OK + "\n")
        return 0
    if arguments:
        return 0
    try:
        raw = sys.stdin.buffer.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw) > MAX_HOOK_INPUT_BYTES:
            return 0
        payload = json.loads(raw)
        output = handle(payload)
        if output is not None:
            sys.stdout.write(json.dumps(output, separators=(",", ":")) + "\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
