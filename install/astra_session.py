"""Validate the explicit, zero-write Astra main-session contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


ASTRA_MAIN_MODEL = "gpt-6-astra"
ASTRA_MAIN_EFFORT = "high"
ASTRA_PLAN_EFFORT = "high"
ASTRA_CHILD_CONCURRENCY = 1
ASTRA_ADVISORY_MAX_TOOL_CALLS = 12
ASTRA_ADVISORY_MAX_WALL_SECONDS = 300

_REQUIRED_OVERRIDES = frozenset(
    {
        "model",
        "model_reasoning_effort",
        "plan_mode_reasoning_effort",
        "max_concurrent_threads_per_session",
    }
)
_DEFAULT_OVERRIDES = {
    "model": ASTRA_MAIN_MODEL,
    "model_reasoning_effort": ASTRA_MAIN_EFFORT,
    "plan_mode_reasoning_effort": ASTRA_PLAN_EFFORT,
    "max_concurrent_threads_per_session": ASTRA_CHILD_CONCURRENCY,
}
_RESERVED_OVERRIDE_FLAGS = frozenset(
    {"--model", "--config", "--profile", "-m", "-c", "-p", "--oss", "--local-provider"}
)
_RESERVED_OVERRIDE_PREFIXES = (
    "--model=",
    "--config=",
    "--profile=",
    "--local-provider=",
    "-m=",
    "-c=",
    "-p=",
)


class AstraActivationError(ValueError):
    """Raised when Astra cannot be activated safely for a session."""


@dataclass(frozen=True)
class AstraActivation:
    """The validated launch-time overrides for one Astra session."""

    model: str = ASTRA_MAIN_MODEL
    model_reasoning_effort: str = ASTRA_MAIN_EFFORT
    plan_mode_reasoning_effort: str = ASTRA_PLAN_EFFORT
    max_concurrent_threads_per_session: int = ASTRA_CHILD_CONCURRENCY

    @property
    def model_snapshot(self) -> str:
        return f"{self.model}@{self.model_reasoning_effort}"

    @property
    def command_tokens(self) -> tuple[str, ...]:
        return (
            "--model",
            self.model,
            "-c",
            f'model_reasoning_effort="{self.model_reasoning_effort}"',
            "-c",
            f'plan_mode_reasoning_effort="{self.plan_mode_reasoning_effort}"',
            "-c",
            f"max_concurrent_threads_per_session={self.max_concurrent_threads_per_session}",
        )


def validate_activation(
    overrides: Mapping[str, object],
    *,
    available_models: Iterable[str] | None = None,
) -> AstraActivation:
    """Validate overrides and model availability before any task dispatch."""
    if not isinstance(overrides, Mapping) or set(overrides) != _REQUIRED_OVERRIDES:
        raise AstraActivationError("invalid Astra session override keys")

    expected = _DEFAULT_OVERRIDES
    for key, value in expected.items():
        if type(value) is not type(overrides[key]) or value != overrides[key]:
            raise AstraActivationError(f"invalid Astra session override: {key}")

    if available_models is not None:
        try:
            models = set(available_models)
        except TypeError as exc:
            raise AstraActivationError("invalid available model list") from exc
        if ASTRA_MAIN_MODEL not in models:
            raise AstraActivationError("Astra model is unavailable")

    return AstraActivation(
        model=ASTRA_MAIN_MODEL,
        model_reasoning_effort=ASTRA_MAIN_EFFORT,
        plan_mode_reasoning_effort=ASTRA_PLAN_EFFORT,
        max_concurrent_threads_per_session=ASTRA_CHILD_CONCURRENCY,
    )


def build_codex_command(
    codex_bin: str = "codex",
    extra_args: Iterable[str] = (),
) -> tuple[str, ...]:
    """Build a non-mutating Codex command with the approved Astra overrides."""
    if not isinstance(codex_bin, str) or not codex_bin.strip():
        raise AstraActivationError("invalid Codex executable")
    if isinstance(extra_args, str):
        raise AstraActivationError("extra arguments must be an iterable")
    extras = tuple(extra_args)
    if not all(isinstance(arg, str) for arg in extras):
        raise AstraActivationError("extra arguments must be strings")
    if any(
        arg in _RESERVED_OVERRIDE_FLAGS
        or arg.startswith(_RESERVED_OVERRIDE_PREFIXES)
        or (arg.startswith(("-m", "-c", "-p")) and not arg.startswith("--"))
        for arg in extras
    ):
        raise AstraActivationError("reserved Astra session override flag")
    activation = validate_activation(_DEFAULT_OVERRIDES)
    return (codex_bin, *activation.command_tokens, *extras)
