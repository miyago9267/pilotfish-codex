"""Strict, event-bound ownership helpers for native Codex hook groups."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any


class HookRegistrationError(ValueError):
    """Hook registration or ownership evidence is malformed or ambiguous."""


_LEGACY_PROJECTION_ID = "pilotfish-autoroute-v1"
CURRENT_PROJECTION_ID = "pilotfish-autoroute-v2"

_COMMAND = (
    '/usr/bin/env python3 "${CODEX_HOME:-$HOME/.codex}/hooks/'
    'pilotfish_autoroute_gate.py"'
)
_LEGACY_WINDOWS_COMMAND = (
    "python -c \"import os,runpy; from pathlib import Path; "
    "runpy.run_path(str(Path(os.environ.get('CODEX_HOME', "
    "Path.home()/'.codex'))/'hooks'/'pilotfish_autoroute_gate.py'), "
    "run_name='__main__')\""
)
_WINDOWS_COMMAND = (
    "uv run --no-project python -c \"import os,runpy; from pathlib import Path; "
    "runpy.run_path(str(Path(os.environ.get('CODEX_HOME', "
    "Path.home()/'.codex'))/'hooks'/'pilotfish_autoroute_gate.py'), "
    "run_name='__main__')\""
)
_LEGACY_GROUP: dict[str, Any] = {
    "hooks": [
        {
            "type": "command",
            "command": _COMMAND,
            "commandWindows": _LEGACY_WINDOWS_COMMAND,
            "timeout": 10,
        }
    ]
}
_CURRENT_GROUP: dict[str, Any] = {
    "hooks": [
        {
            "type": "command",
            "command": _COMMAND,
            "commandWindows": _WINDOWS_COMMAND,
            "timeout": 10,
        }
    ]
}

# Registry entries are immutable trust anchors.  Future releases add a new
# current entry and retain old entries here for migration/collision detection.
TRUSTED_PROJECTIONS: dict[str, dict[str, dict[str, Any]]] = {
    _LEGACY_PROJECTION_ID: {
        "UserPromptSubmit": _LEGACY_GROUP,
        "Stop": _LEGACY_GROUP,
    },
    CURRENT_PROJECTION_ID: {
        "UserPromptSubmit": _CURRENT_GROUP,
        "Stop": _CURRENT_GROUP,
    },
}

# Raw fingerprints are only a bridge from the exact pre-v2 installer schema.
# Group bodies are still derived from TRUSTED_PROJECTIONS, never from state.
LEGACY_RAW_REGISTRATIONS: dict[str, str] = {
    "a219000323daa83242acd03e1d23342b3cc19d04e36d8e53af1114f4f4f8ee56": (
        _LEGACY_PROJECTION_ID
    ),
    "eebb414251f5dc9630b2c7c0d8feec08f902f0102b2a45bbd45ef89229406af2": (
        CURRENT_PROJECTION_ID
    ),
    "f36c376a5d94055399c84cdcbb6e18509e5c7c97c16f06c3dd3a40d77dfcafcc": (
        CURRENT_PROJECTION_ID
    ),
}


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HookRegistrationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise HookRegistrationError(f"non-finite JSON number: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise HookRegistrationError(f"non-finite JSON number: {value}")
    return parsed


def strict_json_loads(payload: bytes | str, *, source: str) -> Any:
    """Decode RFC JSON while rejecting duplicate keys and non-finite numbers."""
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    except UnicodeDecodeError as exc:
        raise HookRegistrationError(f"{source} is not UTF-8 JSON") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_finite_float,
        )
    except HookRegistrationError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise HookRegistrationError(f"{source} is invalid JSON") from exc


def _type_strict_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _type_strict_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _type_strict_equal(a, b) for a, b in zip(left, right)
        )
    return bool(left == right)


def validate_registration(document: Any, *, source: str) -> dict[str, Any]:
    """Validate the native event -> matcher-group -> handler shape."""
    if not isinstance(document, dict):
        raise HookRegistrationError(f"{source} top-level value must be an object")
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        raise HookRegistrationError(f"{source} hooks must be an object")
    for event, groups in hooks.items():
        if not isinstance(event, str) or not event:
            raise HookRegistrationError(f"{source} hook event name is malformed")
        if not isinstance(groups, list):
            raise HookRegistrationError(f"{source} event {event} must be an array")
        for group in groups:
            if not isinstance(group, dict) or not group:
                raise HookRegistrationError(
                    f"{source} event {event} contains a malformed matcher group"
                )
            handlers = group.get("hooks")
            matcher = group.get("matcher")
            if "matcher" in group and not isinstance(matcher, str):
                raise HookRegistrationError(
                    f"{source} event {event} matcher must be a string"
                )
            if not isinstance(handlers, list) or not handlers:
                raise HookRegistrationError(
                    f"{source} event {event} matcher group has malformed handlers"
                )
            if any(not isinstance(handler, dict) or not handler for handler in handlers):
                raise HookRegistrationError(
                    f"{source} event {event} contains a malformed handler"
                )
            for handler in handlers:
                if not isinstance(handler.get("type"), str) or not handler["type"]:
                    raise HookRegistrationError(
                        f"{source} event {event} handler type is malformed"
                    )
                if not isinstance(handler.get("command"), str) or not handler["command"]:
                    raise HookRegistrationError(
                        f"{source} event {event} handler command is malformed"
                    )
                if "commandWindows" in handler and not isinstance(
                    handler["commandWindows"], str
                ):
                    raise HookRegistrationError(
                        f"{source} event {event} Windows command is malformed"
                    )
                if "timeout" in handler and (
                    type(handler["timeout"]) is not int or handler["timeout"] <= 0
                ):
                    raise HookRegistrationError(
                        f"{source} event {event} handler timeout is malformed"
                    )
    return document


def load_registration(payload: bytes | str, *, source: str) -> dict[str, Any]:
    return validate_registration(strict_json_loads(payload, source=source), source=source)


def windows_compatibility_warnings(document: dict[str, Any]) -> list[str]:
    """Return non-blocking warnings for command hooks without a Windows form."""
    warnings: list[str] = []
    for event, groups in document["hooks"].items():
        for index, group in enumerate(groups):
            matcher = group.get("matcher", "<all>")
            for handler_index, handler in enumerate(group["hooks"]):
                if handler.get("type") != "command" or "commandWindows" in handler:
                    continue
                command = handler["command"]
                warnings.append(
                    "Windows compatibility: "
                    f"hooks.{event}[{index}].hooks[{handler_index}] "
                    f"matcher={matcher!r} has no commandWindows; "
                    f"Windows may run the Unix command and time out ({command!r}). "
                    "Pilotfish preserved it and did not modify it."
                )
    return warnings


def _canonical_projection_bytes(projection_id: str) -> bytes:
    try:
        projection = TRUSTED_PROJECTIONS[projection_id]
    except KeyError as exc:
        raise HookRegistrationError("hook projection identifier is not allowlisted") from exc
    return json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def projection_digest(projection_id: str) -> str:
    return hashlib.sha256(_canonical_projection_bytes(projection_id)).hexdigest()


def projection_state(projection_id: str) -> dict[str, str | int]:
    # Version 1 is the schema of this state reference, not the hook release.
    return {
        "version": 1,
        "projection_id": projection_id,
        "projection_sha256": projection_digest(projection_id),
    }


def validate_projection_state(value: Any) -> str:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "projection_id",
        "projection_sha256",
    }:
        raise HookRegistrationError("hook projection state is malformed")
    if type(value["version"]) is not int or value["version"] != 1:
        raise HookRegistrationError("hook projection state version is malformed")
    projection_id = value["projection_id"]
    digest = value["projection_sha256"]
    if not isinstance(projection_id, str) or projection_id not in TRUSTED_PROJECTIONS:
        raise HookRegistrationError("hook projection identifier is not allowlisted")
    if not isinstance(digest, str) or digest != projection_digest(projection_id):
        raise HookRegistrationError("hook projection digest is invalid")
    return projection_id


def _locations(document: dict[str, Any], group: dict[str, Any]) -> list[tuple[str, int]]:
    return [
        (event, index)
        for event, groups in document["hooks"].items()
        for index, candidate in enumerate(groups)
        if _type_strict_equal(candidate, group)
    ]


def validate_owned_projection(document: dict[str, Any], projection_id: str) -> None:
    try:
        projection = TRUSTED_PROJECTIONS[projection_id]
    except KeyError as exc:
        raise HookRegistrationError("hook projection identifier is not allowlisted") from exc
    for expected_event, group in projection.items():
        same_event = [
            location for location in _locations(document, group)
            if location[0] == expected_event
        ]
        if len(same_event) != 1:
            raise HookRegistrationError(
                f"owned hook group for {expected_event} is missing, duplicated, or cross-event"
            )
        allowed_events = {
            event
            for event, candidate in projection.items()
            if _type_strict_equal(candidate, group)
        }
        if any(event not in allowed_events for event, _ in _locations(document, group)):
            raise HookRegistrationError(
                f"owned hook group for {expected_event} is missing, duplicated, or cross-event"
            )


def _contains_any_trusted_group(document: dict[str, Any]) -> bool:
    return any(
        _locations(document, group)
        for projection in TRUSTED_PROJECTIONS.values()
        for group in projection.values()
    )


def validate_source_registration(payload: bytes) -> dict[str, Any]:
    document = load_registration(payload, source="source hooks.json")
    projection = TRUSTED_PROJECTIONS[CURRENT_PROJECTION_ID]
    hooks = document["hooks"]
    if set(hooks) != set(projection):
        raise HookRegistrationError("source hooks.json is not the allowlisted current projection")
    for event, group in projection.items():
        groups = hooks[event]
        if len(groups) != 1 or not _type_strict_equal(groups[0], group):
            raise HookRegistrationError("source hooks.json is not the allowlisted current projection")
    return document


def merge_registration(
    current_payload: bytes | None,
    source_payload: bytes,
    *,
    owned_projection_id: str | None,
) -> tuple[bytes, str]:
    """Merge or upgrade only the exact event-bound Pilotfish matcher groups."""
    validate_source_registration(source_payload)
    desired_id = CURRENT_PROJECTION_ID
    desired = TRUSTED_PROJECTIONS[desired_id]
    if current_payload is None:
        if owned_projection_id is not None:
            raise HookRegistrationError("owned hooks.json is missing")
        return source_payload, desired_id

    document = load_registration(current_payload, source="existing hooks.json")
    if owned_projection_id is None:
        if _contains_any_trusted_group(document):
            raise HookRegistrationError(
                "unowned hooks.json contains a canonical Pilotfish group"
            )
        merged = copy.deepcopy(document)
        for event, group in desired.items():
            merged["hooks"].setdefault(event, []).append(copy.deepcopy(group))
    else:
        if owned_projection_id not in TRUSTED_PROJECTIONS:
            raise HookRegistrationError("hook projection identifier is not allowlisted")
        validate_owned_projection(document, owned_projection_id)
        merged = copy.deepcopy(document)
        if owned_projection_id != desired_id:
            for group in desired.values():
                if _locations(merged, group):
                    raise HookRegistrationError(
                        "desired hook group collides with an unowned canonical group"
                    )
            prior = TRUSTED_PROJECTIONS[owned_projection_id]
            for event, group in prior.items():
                index = next(
                    index
                    for index, candidate in enumerate(merged["hooks"][event])
                    if _type_strict_equal(candidate, group)
                )
                merged["hooks"][event][index] = copy.deepcopy(desired[event])

    validate_owned_projection(merged, desired_id)
    if owned_projection_id == desired_id:
        return current_payload, desired_id
    return (
        json.dumps(merged, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        + b"\n",
        desired_id,
    )


def semantic_projection_digest(payload: bytes, projection_id: str) -> str:
    document = load_registration(payload, source="active hooks.json")
    validate_owned_projection(document, projection_id)
    return projection_digest(projection_id)


def legacy_projection_id(raw_fingerprint: str) -> str:
    try:
        return LEGACY_RAW_REGISTRATIONS[raw_fingerprint]
    except KeyError as exc:
        raise HookRegistrationError(
            "legacy hooks.json fingerprint is not recognized"
        ) from exc
