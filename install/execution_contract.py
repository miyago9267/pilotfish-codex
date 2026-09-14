"""Project and validate the interaction boundary for one user outcome."""

from __future__ import annotations

from typing import Any


ALLOWED_TASK_MODES = frozenset({"execute", "explore_then_plan", "co_discover"})
ALLOWED_INTENT_CONFIDENCE = frozenset({"clear", "partial", "unclear"})
ALLOWED_CHANGE_IMPACT = frozenset({"trivial", "low", "material", "high", "critical"})
ALLOWED_REVERSIBILITY = frozenset({"yes", "partial", "no"})
ALLOWED_EXECUTION_SCOPES = frozenset({"step", "slice", "outcome"})
ALLOWED_EXPLICIT_SCOPES = frozenset({"unspecified", *ALLOWED_EXECUTION_SCOPES})
ALLOWED_CONTINUATION_MODES = frozenset(
    {"attended_until_acceptance", "explicit_unattended"}
)
ALLOWED_STOP_CONDITIONS = frozenset(
    {"named_boundary", "acceptance", "material_gate", "decision"}
)
CONTRACT_FIELDS = frozenset(
    {"execution_scope", "continuation_mode", "stop_condition"}
)


class ExecutionContractError(ValueError):
    """The execution boundary is malformed or internally inconsistent."""


def validate_execution_contract(value: Any) -> dict[str, str]:
    """Validate one projected execution contract and return it unchanged."""
    if not isinstance(value, dict) or set(value) != CONTRACT_FIELDS:
        raise ExecutionContractError("execution contract shape is invalid")
    for field, allowed in (
        ("execution_scope", ALLOWED_EXECUTION_SCOPES),
        ("continuation_mode", ALLOWED_CONTINUATION_MODES),
        ("stop_condition", ALLOWED_STOP_CONDITIONS),
    ):
        if not isinstance(value[field], str) or value[field] not in allowed:
            raise ExecutionContractError(f"execution contract {field} is invalid")

    scope = value["execution_scope"]
    stop_condition = value["stop_condition"]
    if stop_condition == "acceptance" and scope != "outcome":
        raise ExecutionContractError("acceptance requires outcome scope")
    if stop_condition == "named_boundary" and scope == "outcome":
        raise ExecutionContractError("named boundary requires step or slice scope")
    if stop_condition == "decision" and scope == "outcome":
        raise ExecutionContractError("decision requires a bounded slice")
    return value


def project_execution_contract(
    *,
    task_mode: str,
    intent_confidence: str,
    change_impact: str,
    reversible: str,
    approval_required: bool,
    explicit_scope: str = "unspecified",
    unattended_requested: bool = False,
) -> dict[str, str]:
    """Project route signals into a scope, presence mode, and stop condition.

    The projection treats an explicit step or slice as a user boundary. A clear
    execute request defaults to the full outcome and stops at acceptance. Risk
    gates take precedence over both boundaries.
    """
    for value, name, allowed in (
        (task_mode, "task_mode", ALLOWED_TASK_MODES),
        (intent_confidence, "intent_confidence", ALLOWED_INTENT_CONFIDENCE),
        (change_impact, "change_impact", ALLOWED_CHANGE_IMPACT),
        (reversible, "reversible", ALLOWED_REVERSIBILITY),
        (explicit_scope, "explicit_scope", ALLOWED_EXPLICIT_SCOPES),
    ):
        if not isinstance(value, str) or value not in allowed:
            raise ExecutionContractError(f"execution contract {name} is invalid")
    if type(approval_required) is not bool:
        raise ExecutionContractError("execution contract approval flag is invalid")
    if type(unattended_requested) is not bool:
        raise ExecutionContractError("execution contract unattended flag is invalid")

    clear_execute = task_mode == "execute" and intent_confidence == "clear"
    material_risk = (
        approval_required or change_impact in {"high", "critical"} or reversible == "no"
    )
    if clear_execute and material_risk and not approval_required:
        raise ExecutionContractError("material execute scope requires approval")
    if explicit_scope in {"step", "slice"}:
        execution_scope = explicit_scope
    elif explicit_scope == "outcome" and clear_execute:
        execution_scope = "outcome"
    else:
        execution_scope = "outcome" if clear_execute else "slice"

    if clear_execute and material_risk:
        stop_condition = "material_gate"
    elif not clear_execute:
        stop_condition = "decision"
    elif explicit_scope in {"step", "slice"}:
        stop_condition = "named_boundary"
    else:
        stop_condition = "acceptance"

    return validate_execution_contract(
        {
            "execution_scope": execution_scope,
            "continuation_mode": (
                "explicit_unattended"
                if unattended_requested
                else "attended_until_acceptance"
            ),
            "stop_condition": stop_condition,
        }
    )
