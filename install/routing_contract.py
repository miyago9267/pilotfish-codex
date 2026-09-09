"""Provider-neutral routing metadata shared by dispatch and benchmarks.

The metadata records why a model candidate was selected without retaining the
prompt, transcript, paths, or other runtime-sensitive content.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


ROUTING_CONTEXT_KEYS = frozenset(
    {
        "runtime",
        "role",
        "model_candidate",
        "model_snapshot",
        "complexity",
        "escalation_reason",
        "permission_profile",
        "evidence_budget",
        "claim_fingerprint",
    }
)
EVIDENCE_BUDGET_KEYS = frozenset({"max_tool_calls", "max_wall_seconds", "context_scope"})
RUNTIMES = frozenset({"codex", "claude"})
COMPLEXITIES = frozenset({"routine", "cross_system", "critical", "long_horizon"})
ESCALATION_REASONS = frozenset(
    {"baseline", "explicit-risk", "disagreement", "long-horizon", "tool-complexity", "platform-halt"}
)
PERMISSION_PROFILES = frozenset(
    {"read-only", "workspace-write", "approved-security-write"}
)
UNKNOWN_MODEL = "unknown"
UNKNOWN_SNAPSHOT = "unavailable"
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class RoutingContractError(ValueError):
    """A routing context is missing, malformed, or unsafe."""


def claim_fingerprint(claim: Any) -> str:
    """Hash a claim into a stable redacted identifier."""
    try:
        canonical = json.dumps(
            claim,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RoutingContractError("claim is not JSON serializable") from exc
    return hashlib.sha256(canonical).hexdigest()


def build_routing_context(
    *,
    model_candidate: str,
    model_snapshot: str,
    complexity: str,
    escalation_reason: str,
    permission_profile: str,
    role: str = "unknown",
    runtime: str = "codex",
    evidence_budget: Mapping[str, Any] | None = None,
    claim: Any,
) -> dict[str, Any]:
    """Build a complete context while retaining only a claim fingerprint."""
    if evidence_budget is None:
        evidence_budget = {
            "max_tool_calls": 20,
            "max_wall_seconds": 600,
            "context_scope": "named-inputs-only",
        }
    if not isinstance(evidence_budget, Mapping):
        raise RoutingContractError("evidence budget is invalid")
    context = {
        "runtime": runtime,
        "role": role,
        "model_candidate": model_candidate,
        "model_snapshot": model_snapshot,
        "complexity": complexity,
        "escalation_reason": escalation_reason,
        "permission_profile": permission_profile,
        "evidence_budget": dict(evidence_budget),
        "claim_fingerprint": claim_fingerprint(claim),
    }
    validate_routing_context(context)
    return context


def validate_routing_context(value: Mapping[str, Any]) -> None:
    """Fail closed on unknown fields and unredacted routing metadata."""
    if not isinstance(value, Mapping) or set(value) != ROUTING_CONTEXT_KEYS:
        raise RoutingContractError("routing context keys are invalid")
    if not isinstance(value["runtime"], str) or value["runtime"] not in RUNTIMES:
        raise RoutingContractError("routing context runtime is invalid")
    if not isinstance(value["role"], str) or not value["role"].strip():
        raise RoutingContractError("routing context role is invalid")
    for field in ("role", "model_candidate", "model_snapshot"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise RoutingContractError(f"routing context {field} is invalid")
        if "/" in value[field] or "\\" in value[field] or "secret" in value[field].lower():
            raise RoutingContractError(f"routing context {field} is unsafe")
    if not isinstance(value["complexity"], str) or value["complexity"] not in COMPLEXITIES:
        raise RoutingContractError("routing context complexity is invalid")
    if not isinstance(value["escalation_reason"], str) or value["escalation_reason"] not in ESCALATION_REASONS:
        raise RoutingContractError("routing context escalation reason is invalid")
    if not isinstance(value["permission_profile"], str) or value["permission_profile"] not in PERMISSION_PROFILES:
        raise RoutingContractError("routing context permission profile is invalid")
    budget = value["evidence_budget"]
    if not isinstance(budget, Mapping) or set(budget) != EVIDENCE_BUDGET_KEYS:
        raise RoutingContractError("routing context evidence budget is invalid")
    if (
        type(budget["max_tool_calls"]) is not int
        or budget["max_tool_calls"] < 0
        or type(budget["max_wall_seconds"]) is not int
        or budget["max_wall_seconds"] <= 0
        or budget["context_scope"] != "named-inputs-only"
    ):
        raise RoutingContractError("routing context evidence budget is invalid")
    if not isinstance(value["claim_fingerprint"], str) or not FINGERPRINT_RE.fullmatch(
        value["claim_fingerprint"]
    ):
        raise RoutingContractError("routing context claim fingerprint is invalid")
