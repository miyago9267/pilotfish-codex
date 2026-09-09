#!/usr/bin/env python3
"""Offline-first usage-routing benchmark harness.

The harness keeps the benchmark contract deliberately small and deterministic.
Normal operation only reads the checked-in manifest/fixtures and can build
synthetic binding receipts.  Network and quota-consuming work is behind the
explicit ``--live --yes --benchmark-yes`` gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import signal
import shutil
import statistics
import stat
import subprocess
import tempfile
import time
import tomllib
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from routing_contract import build_routing_context, validate_routing_context


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "templates"
MANIFEST_VERSION = "usage-routing-v1"
MANIFEST_PATH = ROOT / "docs" / "benchmarks" / MANIFEST_VERSION / "manifest.json"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "benchmark_routing"
ROLE_NAMES = (
    "executor",
    "mech-executor",
    "plan-verifier",
    "scout",
    "security-executor",
    "security-reviewer",
    "verifier",
)
TRIAL_CAP = 36
LIVE_TRIAL_BATCH = 6
DEFAULT_TRIALS = LIVE_TRIAL_BATCH
DEFAULT_LIVE_MAX_COST_USD = 1.00
BENCHMARK_WAIT_TIMEOUT_MS = 120_000
LIVE_ESTIMATE_INPUT_TOKENS = 20_000
LIVE_ESTIMATE_OUTPUT_TOKENS = 4_000
PARENT_MODEL = "gpt-5.6-luna"
PARENT_EFFORT = "medium"
PARENT_PROMPT = (
    "Run this benchmark task exactly as written. First classify the work surface "
    "as routine, pure-judgment, or tool/cross-system-heavy. Keep routine work "
    "on the current low-cost role binding; use an Astra candidate only when the "
    "named tool or evidence trigger applies, never for difficulty alone. You are "
    "bound to the smallest sufficient change: use only the named-input tool "
    "allowlist, stop at max_tool_calls=20 or max_wall_seconds=600, and stop "
    "once the acceptance evidence is sufficient. Report primary_flow, "
    "claim_relevant_edges, external_evidence, tool_actions, and any "
    "inconclusive_reason in the redacted receipt. You are "
    "the parent and must direct exactly one native typed child using "
    "agent_type=ROLE; do not create any second child, do not use an untyped "
    "fallback, and return a terminal JSON receipt with the redacted routing "
    "context."
)
REVIEW_VERDICTS = frozenset({"accept", "reject", "inconclusive"})
CHAIN_ORDERS = ("LTS", "LS", "TS", "S")
NATIVE_V2_BENCHMARK_CONFIG = (
    b'model = "gpt-5.6-luna"\n'
    b'model_reasoning_effort = "medium"\n'
    b'plan_mode_reasoning_effort = "xhigh"\n\n'
    b"[features]\n"
    b"default_mode_request_user_input = true\n\n"
    b"[features.multi_agent_v2]\n"
    b"enabled = true\n"
    b"max_concurrent_threads_per_session = 4\n"
    b"min_wait_timeout_ms = 1000\n"
    b"max_wait_timeout_ms = 120000\n"
    b"default_wait_timeout_ms = 120000\n"
)


class BenchmarkError(ValueError):
    """A fail-closed benchmark input or evidence error."""


class ReceiptError(BenchmarkError):
    pass


class MetricsUnavailable(BenchmarkError):
    pass


@dataclass(frozen=True)
class TrialHome:
    """Credential-bearing run home and credential-free analysis home."""

    home: Path
    analysis_home: Path
    auth_path: Path | None
    config_sha256: str
    role_manifest_sha256: str
    policy_sha256: str

    def hashes(self, *, fixture_path: Path, prompt: str) -> dict[str, str]:
        return {
            "config_sha256": self.config_sha256,
            "role_manifest_sha256": self.role_manifest_sha256,
            "policy_sha256": self.policy_sha256,
            "fixture_sha256": sha256_file(fixture_path),
            "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
        }


@dataclass(frozen=True)
class Candidate:
    model: str
    reasoning_effort: str

    def as_dict(self) -> dict[str, str]:
        return {"model": self.model, "reasoning_effort": self.reasoning_effort}


# These are candidate projections only. The installed role TOMLs remain the
# production binding until a matched cohort earns promotion.
def _template_candidate(role: str) -> Candidate:
    path = TEMPLATE_ROOT / "agents" / f"{role}.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BenchmarkError(f"role template binding unavailable: {role}") from exc
    model, effort = data.get("model"), data.get("model_reasoning_effort")
    if not isinstance(model, str) or not isinstance(effort, str) or not model or not effort:
        raise BenchmarkError(f"role template binding invalid: {role}")
    return Candidate(model, effort)


ROLE_CANDIDATES: dict[str, tuple[Candidate, Candidate]] = {
    "security-reviewer": (
        _template_candidate("security-reviewer"),
        Candidate("gpt-6-astra", "high"),
    ),
    "verifier": (
        _template_candidate("verifier"),
        Candidate("gpt-6-astra", "high"),
    ),
    "executor": (
        _template_candidate("executor"),
        Candidate("gpt-6-astra", "high"),
    ),
    "semantic-adjudicator": (
        Candidate("gpt-5.6-sol", "high"),
        Candidate("gpt-6-astra", "high"),
    ),
}
BASELINE_ONLY_ROLES = frozenset({"mech-executor", "scout"})
BASELINE_ONLY_BINDINGS = {
    "mech-executor": Candidate("gpt-5.6-luna", "medium"),
    "scout": Candidate("gpt-5.6-luna", "low"),
}


def _baseline_candidate(role: str) -> Candidate:
    configured = _template_candidate(role)
    expected = BASELINE_ONLY_BINDINGS[role]
    if configured != expected:
        raise BenchmarkError(f"baseline-only role binding drift: {role}")
    return configured


def select_role_candidate(
    role: str,
    *,
    complexity: str = "routine",
    tool_actions: int = 0,
    external_evidence: bool = False,
    disagreement: bool = False,
) -> tuple[Candidate, str]:
    """Return the bounded candidate projection for one role invocation.

    This does not mutate the installed role manifest or bypass native role
    binding. It is the deterministic policy seam used by cohort preparation.
    """
    if complexity not in {"routine", "cross_system", "critical", "long_horizon"}:
        raise BenchmarkError("unsupported task complexity")
    if type(tool_actions) is not int or tool_actions < 0:
        raise BenchmarkError("tool_actions must be a non-negative integer")
    if role in BASELINE_ONLY_ROLES:
        return _baseline_candidate(role), "baseline-only"
    if role not in ROLE_CANDIDATES:
        raise BenchmarkError(f"role has no Astra candidate: {role}")
    baseline, astra = ROLE_CANDIDATES[role]
    if role == "semantic-adjudicator":
        return (astra, "disagreement") if disagreement else (baseline, "baseline")
    tool_heavy = tool_actions > 0 or external_evidence
    if tool_heavy or complexity == "cross_system":
        return astra, "tool-complexity"
    if complexity == "long_horizon":
        return astra, "long-horizon"
    return baseline, "baseline"


def candidate_projection() -> dict[str, list[dict[str, str]]]:
    """Return the bounded role candidate matrix for offline inspection."""
    projection = {
        role: [candidate.as_dict() for candidate in candidates]
        for role, candidates in sorted(ROLE_CANDIDATES.items())
    }
    projection.update(
        {
            role: [_baseline_candidate(role).as_dict()]
            for role in sorted(BASELINE_ONLY_ROLES)
        }
    )
    return projection


def price_usage(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
) -> float:
    """Price one native usage record in USD using the current list rules."""
    if model not in MODEL_PRICES:
        raise MetricsUnavailable(f"unknown model price: {model}")
    values = (input_tokens, output_tokens, cached_input_tokens, cache_write_input_tokens)
    if any(type(value) is not int or value < 0 for value in values):
        raise MetricsUnavailable("token usage must be non-negative integers")
    if cached_input_tokens + cache_write_input_tokens > input_tokens:
        raise MetricsUnavailable("cache usage exceeds input usage")
    input_price, output_price = MODEL_PRICES[model]
    surcharge = input_tokens > LONG_CONTEXT_INPUT_THRESHOLD
    input_multiplier = LONG_CONTEXT_INPUT_MULTIPLIER if surcharge else 1.0
    output_multiplier = LONG_CONTEXT_OUTPUT_MULTIPLIER if surcharge else 1.0
    uncached = input_tokens - cached_input_tokens - cache_write_input_tokens
    return (
        uncached * input_price * input_multiplier
        + cached_input_tokens * input_price * CACHE_READ_MULTIPLIER * input_multiplier
        + cache_write_input_tokens * input_price * CACHE_WRITE_MULTIPLIER * input_multiplier
        + output_tokens * output_price * output_multiplier
    ) / 1_000_000


def estimate_task_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
    workload: str = "agentic",
) -> float:
    """Estimate cost after a declared task-level token-efficiency prior.

    Recorded native usage must use :func:`price_usage` directly. This helper is
    intentionally separate so a prior can never be applied twice to telemetry.
    """
    try:
        factor = TOKEN_EFFICIENCY_FACTORS[workload][model]
    except KeyError as exc:
        raise MetricsUnavailable("unknown workload or model efficiency prior") from exc
    return price_usage(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_input_tokens=cache_write_input_tokens,
    ) * factor


def failure_class_for_receipt(status: str, reason_code: str) -> str:
    """Map platform safety halts separately from model uncertainty."""
    if reason_code == "platform_halt":
        return "capability_gap"
    if status == "NATIVE_OK":
        return "none"
    return "execution"


CANDIDATES: dict[str, tuple[Candidate, Candidate, Candidate]] = {
    "routine": (
        Candidate("gpt-5.6-luna", "medium"),
        Candidate("gpt-5.6-terra", "high"),
        Candidate("gpt-5.6-sol", "high"),
    ),
    "judgment": (
        Candidate("gpt-5.6-luna", "xhigh"),
        Candidate("gpt-5.6-terra", "xhigh"),
        Candidate("gpt-5.6-sol", "high"),
    ),
}

LIVE_COHORTS = ("routine", "judgment")

# USD per million tokens. These are the September 2026 list prices used by the
# native rollout ledger. Cache reads are billed at 10% of input and cache writes
# at 125%; long-context requests apply the documented input/output surcharge.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (4.00, 20.00),
    "gpt-6-astra": (10.00, 50.00),
}
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25
LONG_CONTEXT_INPUT_THRESHOLD = 272_000
LONG_CONTEXT_INPUT_MULTIPLIER = 2.0
LONG_CONTEXT_OUTPUT_MULTIPLIER = 1.5
TOKEN_EFFICIENCY_FACTORS: dict[str, dict[str, float]] = {
    "agentic": {
        "gpt-5.6-luna": 1.0,
        "gpt-5.6-terra": 1.0,
        "gpt-5.6-sol": 1.0,
        "gpt-6-astra": 1 / 3,
    },
    "reasoning": {
        "gpt-5.6-luna": 1.0,
        "gpt-5.6-terra": 1.0,
        "gpt-5.6-sol": 1.0,
        # The raw Astra/Sol list-price ratio is 2.5x.  The measured
        # intelligence-task ratio is 1.75x, so the declared token-efficiency
        # prior is 1.75 / 2.5 rather than the 0.9 coding prior.
        "gpt-6-astra": 0.7,
    },
}


def _validate_live_trial_count(trials: int) -> None:
    if (
        type(trials) is not int
        or trials < LIVE_TRIAL_BATCH
        or trials > TRIAL_CAP
        or trials % LIVE_TRIAL_BATCH != 0
    ):
        raise BenchmarkError(
            "live mode requires a balanced trial count of "
            f"{LIVE_TRIAL_BATCH}, {LIVE_TRIAL_BATCH * 2}, ... {TRIAL_CAP}"
        )


def _validate_live_budget(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise BenchmarkError("live max cost must be a finite positive number")
    return float(value)


@dataclass(frozen=True)
class UsageMetrics:
    """Normalized usage from a native ledger or CodexBar cross-check."""

    input: float
    output: float
    cached_read: float
    cached_write: float
    total: float
    cost: float
    primary_usage: float
    weighted_tokens: float = 0.0
    reasoning_output: float = 0.0
    source: str = "proxy"

    def as_dict(self) -> dict[str, float | str]:
        return {
            "In": self.input,
            "Out": self.output,
            "CR": self.cached_read,
            "CW": self.cached_write,
            "total": self.total,
            "cost": self.cost,
            "primary_usage": self.primary_usage,
            "weighted_tokens": self.weighted_tokens,
            "reasoning_output": self.reasoning_output,
            "source": self.source,
        }


@dataclass(frozen=True)
class TrialObservation:
    case_id: str
    candidate: str
    verdict: str
    metrics: UsageMetrics | None
    elapsed_seconds: float
    hard_case_success: bool = True
    cohort: str | None = None


@dataclass(frozen=True)
class ChainResult:
    chain: str
    accepted: bool
    settled_primary_usage: float | None
    settled_time_seconds: float | None
    tiers_used: int
    hard_cases_successful: bool
    metric_source: str | None


@dataclass(frozen=True)
class Recommendation:
    chain: str
    median_primary_usage: float
    p95_settled_time_seconds: float
    tiers: int
    terra_retained: bool
    metric_source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "median_primary_usage": self.median_primary_usage,
            "p95_settled_time_seconds": self.p95_settled_time_seconds,
            "tiers": self.tiers,
            "terra_retained": self.terra_retained,
            "metric_source": self.metric_source,
        }


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise BenchmarkError(f"cannot hash fixture: {path}") from exc


def _case_specs() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for cohort, role in (("routine", "mech-executor"), ("judgment", "executor")):
        for number in range(1, 7):
            case_id = f"{cohort}-{number:02d}"
            fixture_id = f"fixture-{case_id}"
            fixture_path = f"tests/fixtures/benchmark_routing/{case_id}.json"
            cases.append(
                {
                    "id": case_id,
                    "cohort": cohort,
                    "role": role,
                    "fixture": {
                        "id": fixture_id,
                        "revision": "1",
                        "hash": "",
                        "path": fixture_path,
                    },
                    "prompt": (
                        f"{cohort.title()} benchmark case {number:02d}: perform the "
                        "fixture task in the disposable workspace. Write only the "
                        "strict result.json artifact; never include model identity."
                    ),
                    "artifact_contract": {
                        "format": "json",
                        "required_keys": ["case_id", "accepted", "artifact"],
                        "fixture_required_keys": [
                            "fixture_version",
                            "case_id",
                            "task",
                            "input",
                            "expected_artifact",
                        ],
                    },
                    "acceptance_command": (
                        "python3 -m benchmark_routing --accept-result result.json "
                        "--fixture fixture.json"
                    ),
                    "review_rubric": [
                        "artifact satisfies the declared contract",
                        "receipt proves the named typed child binding",
                        "no handoff context is used by reruns",
                    ],
                    "hard_case": number == 6,
                }
            )
    return cases


def build_manifest(*, fixture_root: Path = FIXTURE_ROOT) -> dict[str, Any]:
    """Build and validate the versioned manifest from checked-in fixtures."""

    cases = _case_specs()
    for case in cases:
        fixture = case["fixture"]
        path = ROOT / fixture["path"]
        if fixture_root != FIXTURE_ROOT:
            path = fixture_root / Path(fixture["path"]).name
        fixture["hash"] = sha256_file(path)
    manifest = {
        "version": MANIFEST_VERSION,
        "candidate_matrix": {
            cohort: [candidate.as_dict() for candidate in candidates]
            for cohort, candidates in CANDIDATES.items()
        },
        "cases": cases,
    }
    validate_manifest(manifest, fixture_root=fixture_root)
    return manifest


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"invalid benchmark manifest: {path}") from exc
    validate_manifest(data)
    return data


def validate_manifest(
    manifest: Mapping[str, Any], *, fixture_root: Path = FIXTURE_ROOT
) -> None:
    if not isinstance(manifest, Mapping) or manifest.get("version") != MANIFEST_VERSION:
        raise BenchmarkError("manifest version is invalid")
    if set(manifest) != {"version", "candidate_matrix", "cases"}:
        raise BenchmarkError("manifest keys are invalid")
    matrix = manifest.get("candidate_matrix")
    if matrix != {
        cohort: [candidate.as_dict() for candidate in candidates]
        for cohort, candidates in CANDIDATES.items()
    }:
        raise BenchmarkError("candidate matrix is invalid")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 12:
        raise BenchmarkError("manifest must contain exactly 12 cases")
    seen: set[str] = set()
    cohorts: dict[str, int] = {"routine": 0, "judgment": 0}
    required_case_keys = {
        "id",
        "cohort",
        "role",
        "fixture",
        "prompt",
        "artifact_contract",
        "acceptance_command",
        "review_rubric",
        "hard_case",
    }
    required_fixture_keys = {"id", "revision", "hash", "path"}
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != required_case_keys:
            raise BenchmarkError("case keys are invalid")
        case_id = case["id"]
        cohort = case["cohort"]
        role = case["role"]
        if not isinstance(case_id, str) or case_id in seen:
            raise BenchmarkError("case IDs must be unique strings")
        if cohort not in CANDIDATES or role != {"routine": "mech-executor", "judgment": "executor"}[cohort]:
            raise BenchmarkError("case cohort/role is invalid")
        if not isinstance(case["prompt"], str) or not case["prompt"]:
            raise BenchmarkError("case prompt is invalid")
        if not isinstance(case["artifact_contract"], Mapping):
            raise BenchmarkError("artifact contract is invalid")
        if not isinstance(case["acceptance_command"], str) or not case["acceptance_command"]:
            raise BenchmarkError("acceptance command is invalid")
        if not isinstance(case["review_rubric"], list) or not case["review_rubric"]:
            raise BenchmarkError("review rubric is invalid")
        if type(case["hard_case"]) is not bool:
            raise BenchmarkError("hard_case must be boolean")
        fixture = case["fixture"]
        if not isinstance(fixture, Mapping) or set(fixture) != required_fixture_keys:
            raise BenchmarkError("fixture metadata is invalid")
        fixture_path = fixture_root / Path(str(fixture["path"])).name
        if Path(str(fixture["path"])).name != str(fixture["path"]).split("/")[-1]:
            raise BenchmarkError("fixture path is invalid")
        if not isinstance(fixture["hash"], str) or len(fixture["hash"]) != 64:
            raise BenchmarkError("fixture hash is invalid")
        if fixture["hash"] != sha256_file(fixture_path):
            raise BenchmarkError(f"fixture hash mismatch: {case_id}")
        if not isinstance(fixture["id"], str) or not fixture["id"]:
            raise BenchmarkError("fixture ID is invalid")
        if not isinstance(fixture["revision"], str) or not fixture["revision"]:
            raise BenchmarkError("fixture revision is invalid")
        try:
            fixture_data = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BenchmarkError(f"fixture is invalid: {case_id}") from exc
        required_fixture_data = {
            "fixture_version",
            "case_id",
            "task",
            "input",
            "expected_artifact",
        }
        if (
            not isinstance(fixture_data, Mapping)
            or set(fixture_data) != required_fixture_data
            or fixture_data["fixture_version"] != fixture["revision"]
            or fixture_data["case_id"] != case_id
        ):
            raise BenchmarkError(f"fixture content is invalid: {case_id}")
        seen.add(case_id)
        cohorts[cohort] += 1
    if cohorts != {"routine": 6, "judgment": 6}:
        raise BenchmarkError("manifest cohort counts are invalid")
    if sum(1 for case in cases if case["hard_case"]) != 2:
        raise BenchmarkError("manifest hard-case count is invalid")


def select_live_matrix(
    manifest: Mapping[str, Any], trials: int
) -> list[tuple[Mapping[str, Any], Candidate]]:
    """Select a balanced, matched subset without weakening the full manifest."""

    _validate_live_trial_count(trials)
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise BenchmarkError("manifest cases are unavailable")
    cases_by_cohort: dict[str, list[Mapping[str, Any]]] = {
        cohort: [] for cohort in LIVE_COHORTS
    }
    for case in cases:
        if not isinstance(case, Mapping):
            raise BenchmarkError("manifest case is invalid")
        cohort = case.get("cohort")
        if isinstance(cohort, str) and cohort in cases_by_cohort:
            cases_by_cohort[str(cohort)].append(case)
    cases_per_cohort = trials // LIVE_TRIAL_BATCH
    if any(len(cases_by_cohort[cohort]) < cases_per_cohort for cohort in LIVE_COHORTS):
        raise BenchmarkError("manifest does not contain enough matched cases")

    matrix: list[tuple[Mapping[str, Any], Candidate]] = []
    for cohort in LIVE_COHORTS:
        for case in cases_by_cohort[cohort][:cases_per_cohort]:
            matrix.extend((case, candidate) for candidate in CANDIDATES[cohort])
    return matrix


def estimate_live_cost(
    matrix: Sequence[tuple[Mapping[str, Any], Candidate]],
    *,
    input_tokens: int = LIVE_ESTIMATE_INPUT_TOKENS,
    output_tokens: int = LIVE_ESTIMATE_OUTPUT_TOKENS,
) -> float:
    """Estimate parent-plus-child spend before a paid matrix starts.

    This is a planning envelope, not provider-side billing enforcement. Native
    observed cost is checked after every completed trial as a second circuit
    breaker.
    """

    values = (input_tokens, output_tokens)
    if any(type(value) is not int or value < 0 for value in values):
        raise BenchmarkError("live estimate token envelope must be non-negative integers")
    total = 0.0
    for _case, candidate in matrix:
        total += price_usage(
            PARENT_MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        total += price_usage(
            candidate.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    return total


def live_budget_summary(
    matrix: Sequence[tuple[Mapping[str, Any], Candidate]],
    *,
    trials: int,
    max_cost_usd: float,
    observed_cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Return redacted budget evidence suitable for a checkpoint or report."""

    _validate_live_trial_count(trials)
    if len(matrix) != trials:
        raise BenchmarkError("live matrix and trial count do not match")
    max_cost = _validate_live_budget(max_cost_usd)
    if (
        isinstance(observed_cost_usd, bool)
        or not isinstance(observed_cost_usd, (int, float))
        or not math.isfinite(float(observed_cost_usd))
        or observed_cost_usd < 0
    ):
        raise BenchmarkError("observed live cost is invalid")
    return {
        "mode": "full" if trials == TRIAL_CAP else "sparse",
        "trial_count": trials,
        "max_cost_usd": max_cost,
        "estimated_cost_usd": round(estimate_live_cost(matrix), 6),
        "observed_cost_usd": round(float(observed_cost_usd), 6),
        "estimate_envelope": {
            "input_tokens_per_rollout": LIVE_ESTIMATE_INPUT_TOKENS,
            "output_tokens_per_rollout": LIVE_ESTIMATE_OUTPUT_TOKENS,
            "rollouts_per_trial": 2,
        },
    }


def observed_live_cost(rows: Sequence[Mapping[str, Any]]) -> float:
    """Sum native costs while tolerating redacted test doubles without cost."""

    total = 0.0
    for row in rows:
        if not isinstance(row, Mapping):
            raise BenchmarkError("live trial row is invalid")
        metrics = row.get("metrics")
        if metrics is None:
            continue
        if not isinstance(metrics, Mapping):
            raise BenchmarkError("live metrics are invalid")
        cost = metrics.get("cost")
        if cost is None:
            continue
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or cost < 0
        ):
            raise BenchmarkError("live trial cost is invalid")
        total += float(cost)
    return total


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsUnavailable(f"CodexBar field {name} is not numeric")
    if value < 0:
        raise MetricsUnavailable(f"CodexBar field {name} is negative")
    return float(value)


CODEXBAR_FIELDS = frozenset({
    "inputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheCreationTokens",
    "totalTokens",
    "totalCost",
})
CODEXBAR_REQUIRED_TOTAL_FIELDS = frozenset(
    {"inputTokens", "outputTokens", "totalTokens", "totalCost"}
)
CODEXBAR_TOP_LEVEL_BASE = frozenset({"provider", "source", "updatedAt"})
CODEXBAR_TOP_LEVEL_ALLOWED = frozenset(
    {
        "provider",
        "source",
        "updatedAt",
        "sessionTokens",
        "sessionCostUSD",
        "last30DaysTokens",
        "last30DaysCostUSD",
        "totals",
        "daily",
    }
)


def _normalize_codexbar_total_fields(totals: Mapping[str, Any]) -> dict[str, float]:
    """Validate one totals object without allowing silent schema drift."""

    if (
        not CODEXBAR_REQUIRED_TOTAL_FIELDS <= set(totals)
        or not set(totals) <= CODEXBAR_FIELDS
    ):
        raise MetricsUnavailable("CodexBar totals schema is unavailable")
    values = {
        name: _number(totals[name], name)
        for name in CODEXBAR_REQUIRED_TOTAL_FIELDS
    }
    values["cacheReadTokens"] = _number(
        totals.get("cacheReadTokens", 0), "cacheReadTokens"
    )
    values["cacheCreationTokens"] = _number(
        totals.get("cacheCreationTokens", 0), "cacheCreationTokens"
    )
    return values


def normalize_codexbar_totals(payload: Sequence[Mapping[str, Any]]) -> UsageMetrics:
    """Normalize one documented CodexBar one-element result array.

    CodexBar's JSON output is intentionally accepted only at this boundary;
    captured Codex JSONL is audit material and never substitutes for totals.
    """

    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)) or len(payload) != 1:
        raise MetricsUnavailable("CodexBar totals schema is unavailable")
    record = payload[0]
    if (
        not isinstance(record, Mapping)
        or not CODEXBAR_TOP_LEVEL_BASE <= set(record)
        or not set(record) <= CODEXBAR_TOP_LEVEL_ALLOWED
    ):
        raise MetricsUnavailable("CodexBar totals schema is unavailable")
    if record.get("provider") != "codex" or not isinstance(record.get("source"), str) or not record["source"]:
        raise MetricsUnavailable("CodexBar provider/source is invalid")
    if not isinstance(record.get("updatedAt"), str) or not record["updatedAt"]:
        raise MetricsUnavailable("CodexBar updatedAt is invalid")
    totals = record.get("totals")
    if totals is None and "daily" in record:
        daily = record.get("daily")
        if not isinstance(daily, Sequence) or isinstance(daily, (str, bytes)) or not daily:
            raise MetricsUnavailable("CodexBar daily totals are missing")
        buckets = []
        for bucket in daily:
            if not isinstance(bucket, Mapping):
                raise MetricsUnavailable("CodexBar daily totals are invalid")
            buckets.append(bucket.get("totals", bucket))
        normalized_buckets = [
            _normalize_codexbar_total_fields(bucket) for bucket in buckets
        ]
        # Aggregate only documented token/cost fields; no direct uppercase fallback.
        totals = {
            name: sum(bucket[name] for bucket in normalized_buckets)
            for name in CODEXBAR_FIELDS
        }
    if not isinstance(totals, Mapping):
        raise MetricsUnavailable("CodexBar totals are missing")
    values = _normalize_codexbar_total_fields(totals)
    if values["totalTokens"] != values["inputTokens"] + values["outputTokens"] + values["cacheReadTokens"] + values["cacheCreationTokens"]:
        raise MetricsUnavailable("CodexBar token identity is invalid")
    weighted = (
        values["inputTokens"]
        + values["cacheReadTokens"] * CACHE_READ_MULTIPLIER
        + values["cacheCreationTokens"] * CACHE_WRITE_MULTIPLIER
        + values["outputTokens"]
    )
    return UsageMetrics(
        input=values["inputTokens"],
        output=values["outputTokens"],
        cached_read=values["cacheReadTokens"],
        cached_write=values["cacheCreationTokens"],
        total=values["totalTokens"],
        cost=values["totalCost"],
        primary_usage=values["totalCost"],
        weighted_tokens=weighted,
    )


def parse_codexbar_json(text: str | bytes) -> UsageMetrics:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MetricsUnavailable("CodexBar JSON is invalid") from exc
    return normalize_codexbar_totals(payload)


def deduplicate_codexbar_metrics(
    metrics: Iterable[UsageMetrics], *, seen: set[tuple[float, ...]] | None = None
) -> list[UsageMetrics]:
    """Drop duplicate snapshots without counting Codex JSONL audit events."""

    known = seen if seen is not None else set()
    unique: list[UsageMetrics] = []
    for metric in metrics:
        key = (
            metric.input,
            metric.output,
            metric.cached_read,
            metric.cached_write,
            metric.total,
            metric.cost,
        )
        if key not in known:
            known.add(key)
            unique.append(metric)
    return unique


def codexbar_binary_evidence(executable: str = "codexbar") -> dict[str, str]:
    path = shutil.which(executable)
    if not path:
        return {"version": "unavailable", "sha256": "unavailable"}
    binary = Path(path)
    try:
        digest = sha256_file(binary)
        result = subprocess.run(
            [str(binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = (result.stdout or result.stderr).strip().splitlines()[0]
    except (OSError, IndexError, subprocess.SubprocessError):
        return {"version": "unavailable", "sha256": "unavailable"}
    return {"version": version or "unavailable", "sha256": digest}


def collect_codexbar_metrics(
    codex_home: Path, *, executable: str = "codexbar"
) -> tuple[UsageMetrics | None, dict[str, str]]:
    """Run CodexBar under one trial home; invalid/missing output fails soft."""

    evidence = codexbar_binary_evidence(executable)
    env = _sanitized_env(codex_home)
    try:
        result = subprocess.run(
            [executable, "cost", "--provider", "codex", "--format", "json", "--refresh"],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None, evidence
    if result.returncode != 0:
        return None, evidence
    try:
        return parse_codexbar_json(result.stdout), evidence
    except MetricsUnavailable:
        return None, evidence


def _native_usage_integer(usage: Mapping[str, Any], field: str) -> int:
    value = usage.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MetricsUnavailable("native rollout token usage is invalid")
    return value


def _latest_native_usage(session_path: Path) -> dict[str, int] | None:
    if session_path.is_symlink() or not session_path.is_file():
        raise MetricsUnavailable("native rollout session log is invalid")
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    latest: dict[str, int] | None = None
    try:
        lines = session_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MetricsUnavailable("native rollout session log is unreadable") from exc
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping) or event.get("type") != "event_msg":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        usage = info.get("total_token_usage") if isinstance(info, Mapping) else None
        if isinstance(usage, Mapping):
            latest = {field: _native_usage_integer(usage, field) for field in fields}
    if latest is None:
        return None
    if latest["total_tokens"] != latest["input_tokens"] + latest["output_tokens"]:
        raise MetricsUnavailable("native rollout token identity is invalid")
    if latest["cached_input_tokens"] + latest["cache_write_input_tokens"] > latest["input_tokens"]:
        raise MetricsUnavailable("native rollout cache usage is invalid")
    return latest


def collect_native_rollout_metrics(
    sessions_root: Path,
    candidate: Candidate,
    *,
    parent_rollout: Path | None = None,
    child_rollout: Path | None = None,
) -> UsageMetrics:
    """Price the latest cumulative usage record for the parent and one child.

    Native ``output_tokens`` already includes ``reasoning_output_tokens``.  The
    latter is validated for schema stability but intentionally never added a
    second time.
    """

    if not sessions_root.is_dir() or PARENT_MODEL not in MODEL_PRICES or candidate.model not in MODEL_PRICES:
        raise MetricsUnavailable("native rollout usage is unavailable")
    if (parent_rollout is None) != (child_rollout is None):
        raise MetricsUnavailable("native rollout binding evidence is incomplete")
    if parent_rollout is None:
        session_paths = sorted(sessions_root.rglob("*.jsonl"))
        if len(session_paths) != 2:
            raise MetricsUnavailable("native rollout requires parent and one child usage")
        parent_rollout, child_rollout = session_paths
    parent_usage = _latest_native_usage(parent_rollout)
    child_usage = _latest_native_usage(child_rollout)
    if parent_usage is None or child_usage is None:
        raise MetricsUnavailable("native rollout requires parent and one child usage")
    latest_records = ((parent_usage, PARENT_MODEL), (child_usage, candidate.model))
    input_tokens = sum(
        record["input_tokens"]
        - record["cached_input_tokens"]
        - record["cache_write_input_tokens"]
        for record, _model in latest_records
    )
    cached_read = sum(record["cached_input_tokens"] for record, _model in latest_records)
    cached_write = sum(record["cache_write_input_tokens"] for record, _model in latest_records)
    output_tokens = sum(record["output_tokens"] for record, _model in latest_records)
    reasoning_output = sum(
        record["reasoning_output_tokens"] for record, _model in latest_records
    )
    total_tokens = sum(record["total_tokens"] for record, _model in latest_records)
    cost = sum(
        price_usage(
            model,
            input_tokens=record["input_tokens"],
            output_tokens=record["output_tokens"],
            cached_input_tokens=record["cached_input_tokens"],
            cache_write_input_tokens=record["cache_write_input_tokens"],
        )
        for record, model in latest_records
    )
    weighted_tokens = (
        input_tokens
        + cached_read * CACHE_READ_MULTIPLIER
        + cached_write * CACHE_WRITE_MULTIPLIER
        + output_tokens
    )
    return UsageMetrics(
        input=float(input_tokens),
        output=float(output_tokens),
        cached_read=float(cached_read),
        cached_write=float(cached_write),
        total=float(total_tokens),
        cost=cost,
        primary_usage=cost,
        weighted_tokens=weighted_tokens,
        reasoning_output=float(reasoning_output),
        source="native-rollout-proxy",
    )


def parse_review_verdict(value: Mapping[str, Any] | str | bytes) -> dict[str, str]:
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise BenchmarkError("review verdict JSON is invalid") from exc
    if not isinstance(value, Mapping) or set(value) not in ({"verdict", "rationale"}, {"status", "rationale"}):
        raise BenchmarkError("review verdict must contain verdict and rationale only")
    verdict = value.get("verdict", value.get("status"))
    rationale = value["rationale"]
    if verdict not in REVIEW_VERDICTS or not isinstance(rationale, str) or not rationale.strip():
        raise BenchmarkError("review verdict is missing or inconclusive")
    return {"verdict": verdict, "rationale": rationale.strip()}


def verdict_accepts(value: Mapping[str, Any] | str | bytes) -> bool:
    try:
        return parse_review_verdict(value)["verdict"] == "accept"
    except BenchmarkError:
        return False


def _extract_participants(receipt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("participants", "threads", "agents"):
        value = receipt.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    parent = receipt.get("parent")
    child = receipt.get("child")
    if isinstance(parent, Mapping) and isinstance(child, Mapping):
        return [parent, child]
    return []


def validate_binding_receipt(
    receipt: Mapping[str, Any] | str | bytes,
    *,
    expected_role: str,
    expected_candidate: Candidate,
) -> dict[str, Any]:
    """Require a native V2 receipt for exactly one correctly bound child."""

    if isinstance(receipt, (str, bytes)):
        try:
            receipt = json.loads(receipt)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReceiptError("receipt JSON is invalid") from exc
    if not isinstance(receipt, Mapping):
        raise ReceiptError("receipt is not an object")
    routing = receipt.get("routing")
    if not isinstance(routing, Mapping):
        raise ReceiptError("receipt routing context is missing")
    try:
        validate_routing_context(routing)
    except ValueError as exc:
        raise ReceiptError("receipt routing context is invalid") from exc
    if receipt.get("status") != "NATIVE_OK":
        raise ReceiptError("native V2 receipt is not successful")
    if receipt.get("native_v2") is False or receipt.get("typed") is False:
        raise ReceiptError("receipt is not native typed V2")
    participants = _extract_participants(receipt)
    if len(participants) != 2:
        raise ReceiptError("receipt must contain exactly parent and one child")
    parent = receipt.get("parent") if isinstance(receipt.get("parent"), Mapping) else participants[0]
    child = receipt.get("child") if isinstance(receipt.get("child"), Mapping) else participants[1]
    if parent is child:
        raise ReceiptError("parent and child evidence are not distinct")
    child_role = child.get("role", child.get("agent_type"))
    child_model = child.get("model")
    child_effort = child.get("reasoning_effort", child.get("effort"))
    if child_role != expected_role:
        raise ReceiptError("child role binding mismatch")
    if (child_model, child_effort) != (expected_candidate.model, expected_candidate.reasoning_effort):
        raise ReceiptError("child model/effort binding mismatch")
    if (
        routing["role"] != expected_role
        or routing["model_candidate"] != expected_candidate.model
        or routing["model_snapshot"] != f"{expected_candidate.model}@{expected_candidate.reasoning_effort}"
    ):
        raise ReceiptError("receipt routing candidate mismatch")
    parent_model = parent.get("model")
    parent_effort = parent.get("reasoning_effort", parent.get("effort"))
    if (parent_model, parent_effort) != (PARENT_MODEL, PARENT_EFFORT):
        raise ReceiptError("parent binding mismatch")
    count = receipt.get("child_count", receipt.get("children_count", receipt.get("spawn_count", 1)))
    if isinstance(receipt.get("children"), list):
        count = len(receipt["children"])
    if count != 1:
        raise ReceiptError("receipt reports more than one child")
    return dict(receipt)


def build_binding_receipt(
    role: str,
    candidate: Candidate,
    *,
    case_id: str = "dry-run",
    complexity: str = "routine",
    escalation_reason: str = "baseline",
    permission_profile: str | None = None,
) -> dict[str, Any]:
    if role not in ROLE_NAMES:
        raise ReceiptError("unknown role")
    if permission_profile is None:
        permission_profile = (
            "read-only"
            if role in {"scout", "plan-verifier", "security-reviewer"}
            else "workspace-write"
        )
    try:
        routing = build_routing_context(
            runtime="codex",
            role=role,
            model_candidate=candidate.model,
            model_snapshot=f"{candidate.model}@{candidate.reasoning_effort}",
            complexity=complexity,
            escalation_reason=escalation_reason,
            permission_profile=permission_profile,
            claim={"case_id": case_id, "role": role},
        )
    except ValueError as exc:
        raise ReceiptError("routing context is invalid") from exc
    return {
        "version": 2,
        "status": "NATIVE_OK",
        "native_v2": True,
        "typed": True,
        "case_id": case_id,
        "parent": {"model": PARENT_MODEL, "reasoning_effort": PARENT_EFFORT, "role": "parent"},
        "child": {
            "model": candidate.model,
            "reasoning_effort": candidate.reasoning_effort,
            "role": role,
            "agent_type": role,
        },
        "participants": [
            {"model": PARENT_MODEL, "reasoning_effort": PARENT_EFFORT, "role": "parent"},
            {"model": candidate.model, "reasoning_effort": candidate.reasoning_effort, "role": role},
        ],
        "child_count": 1,
        "fork_turns": "none",
        "routing": routing,
    }


def build_dry_run_receipts(*, role: str = "mech-executor") -> list[dict[str, Any]]:
    """Build all three candidate receipts without network or persistent writes."""

    cohort = "routine" if role == "mech-executor" else "judgment"
    return [
        build_binding_receipt(role, candidate, case_id=f"dry-run-{cohort}-{index}")
        for index, candidate in enumerate(CANDIDATES[cohort], start=1)
    ]


def validate_result_artifact(fixture_path: Path, result_path: Path) -> dict[str, Any]:
    """Validate only the strict result schema against one trusted fixture."""

    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError("result artifact is unavailable") from exc
    fixture_keys = {"fixture_version", "case_id", "task", "input", "expected_artifact"}
    result_keys = {"case_id", "accepted", "artifact"}
    if not isinstance(fixture, Mapping) or set(fixture) != fixture_keys:
        raise BenchmarkError("fixture schema is invalid")
    if not isinstance(result, Mapping) or set(result) != result_keys:
        raise BenchmarkError("result schema is invalid")
    if result.get("case_id") != fixture.get("case_id") or result.get("accepted") is not True:
        raise BenchmarkError("result acceptance is invalid")
    if result.get("artifact") != fixture.get("expected_artifact"):
        raise BenchmarkError("result artifact does not match fixture")
    serialized = json.dumps(result["artifact"], sort_keys=True, separators=(",", ":"))
    if any(identity in serialized.lower() for identity in ("gpt-5.6", "model_identity", "provider_identity")):
        raise BenchmarkError("result artifact contains model identity")
    return {
        "case_id": str(result["case_id"]),
        "accepted": True,
        "artifact_sha256": sha256_bytes(serialized.encode("utf-8")),
    }


@contextmanager
def disposable_case_workspace(
    fixture_path: Path, *, parent_dir: Path | None = None
) -> Iterator[Path]:
    """Copy one trusted fixture into a private per-trial workspace."""

    parent = parent_dir or Path(tempfile.gettempdir())
    if parent_dir is not None:
        _ensure_private_dir(parent)
    workspace = Path(tempfile.mkdtemp(prefix="pilotfish-case-", dir=parent))
    os.chmod(workspace, 0o700)
    try:
        fixture_bytes = fixture_path.read_bytes()
        _write_private(workspace / "fixture.json", fixture_bytes)
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_manifest_acceptance(
    case: Mapping[str, Any], workspace: Path
) -> dict[str, Any]:
    """Run deterministic acceptance, retaining a safe reject as trial evidence."""

    command = shlex.split(str(case["acceptance_command"]))
    env = _sanitized_env(workspace)
    env["PYTHONPATH"] = str(ROOT / "install")
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return {"accepted": False, "reason_code": "acceptance_command_failed"}
    if completed.returncode != 0:
        return {"accepted": False, "reason_code": "acceptance_command_failed"}
    try:
        return validate_result_artifact(workspace / "fixture.json", workspace / "result.json")
    except BenchmarkError:
        return {"accepted": False, "reason_code": "result_artifact_invalid"}


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _prepare_report_destination(destination: Path) -> Path:
    """Create a private report directory and reject an existing target."""

    if not destination.name or destination.name in {".", ".."}:
        raise BenchmarkError("result report path is invalid")
    parent = destination.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise BenchmarkError("result report directory is unavailable") from exc
    if parent.is_symlink() or not parent.is_dir() or destination.exists() or destination.is_symlink():
        raise BenchmarkError("result report destination already exists or is invalid")
    return parent


def write_result_report(destination: Path, payload: Mapping[str, Any]) -> None:
    """Create one private JSON report without replacing an earlier result."""

    parent = _prepare_report_destination(destination)
    temporary = parent / f".{destination.name}.{os.getpid()}.tmp"
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    try:
        _write_private(temporary, encoded)
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise BenchmarkError("result report destination already exists") from exc
    except OSError as exc:
        raise BenchmarkError("result report could not be written") from exc
    finally:
        temporary.unlink(missing_ok=True)


def write_checkpoint_report(destination: Path, payload: Mapping[str, Any]) -> None:
    """Atomically refresh a private, resumable live-run checkpoint."""

    if not destination.name or destination.name in {".", ".."}:
        raise BenchmarkError("checkpoint report path is invalid")
    parent = destination.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise BenchmarkError("checkpoint report directory is unavailable") from exc
    if parent.is_symlink() or not parent.is_dir() or destination.is_symlink():
        raise BenchmarkError("checkpoint report destination is invalid")
    temporary = parent / f".{destination.name}.{os.getpid()}.tmp"
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    try:
        _write_private(temporary, encoded)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except OSError as exc:
        raise BenchmarkError("checkpoint report could not be written") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _replace_role_binding(payload: bytes, candidate: Candidate) -> bytes:
    """Change only root model/effort TOML lines; preserve instructions byte-for-byte."""

    text = payload.decode("utf-8")
    lines = text.splitlines(keepends=True)
    changed: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("model ="):
            prefix = line[: len(line) - len(stripped)]
            ending = "\n" if line.endswith("\n") else ""
            rendered.append(f'{prefix}model = "{candidate.model}"{ending}')
            changed.add("model")
        elif stripped.startswith("model_reasoning_effort ="):
            prefix = line[: len(line) - len(stripped)]
            ending = "\n" if line.endswith("\n") else ""
            rendered.append(f'{prefix}model_reasoning_effort = "{candidate.reasoning_effort}"{ending}')
            changed.add("model_reasoning_effort")
        else:
            rendered.append(line)
    if changed != {"model", "model_reasoning_effort"}:
        raise BenchmarkError("designated role binding is incomplete")
    return "".join(rendered).encode("utf-8")


def _role_manifest_hash(home: Path) -> str:
    digest = hashlib.sha256()
    for role in ROLE_NAMES:
        digest.update(role.encode("utf-8"))
        digest.update((home / "agents" / f"{role}.toml").read_bytes())
    return digest.hexdigest()


def _validate_instruction_preservation(before: bytes, after: bytes) -> None:
    before_text = before.decode("utf-8")
    after_text = after.decode("utf-8")
    marker = "developer_instructions = "
    if marker not in before_text or marker not in after_text:
        raise BenchmarkError("role developer instructions are missing")
    before_tail = before_text[before_text.index(marker) :]
    after_tail = after_text[after_text.index(marker) :]
    # The first two binding lines are the only permitted mutations.
    before_instr = before_tail[before_tail.find("\"\"\"") :]
    after_instr = after_tail[after_tail.find("\"\"\"") :]
    if before_instr != after_instr:
        raise BenchmarkError("developer instructions changed")


def _fingerprint(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def copy_auth_secure(source: Path, destination: Path) -> None:
    """Copy an explicitly-authorized 0600 auth file without following links."""

    try:
        link_stat = source.lstat()
    except OSError as exc:
        raise BenchmarkError("auth source unavailable") from exc
    if stat.S_ISLNK(link_stat.st_mode) or not stat.S_ISREG(link_stat.st_mode):
        raise BenchmarkError("auth source must be a regular non-symlink file")
    expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
    if (
        (expected_uid is not None and link_stat.st_uid != expected_uid)
        or (os.name != "nt" and stat.S_IMODE(link_stat.st_mode) != 0o600)
    ):
        raise BenchmarkError("auth source must be owner-only 0600")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except OSError as exc:
        raise BenchmarkError("auth source cannot be opened safely") from exc
    try:
        first = os.fstat(fd)
        if (
            not stat.S_ISREG(first.st_mode)
            or (expected_uid is not None and first.st_uid != expected_uid)
            or (os.name != "nt" and stat.S_IMODE(first.st_mode) != 0o600)
            or _fingerprint(first) != _fingerprint(link_stat)
        ):
            raise BenchmarkError("auth source changed before copy")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(fd)
        after_path = source.lstat()
        if _fingerprint(after_fd) != _fingerprint(first) or _fingerprint(after_path) != _fingerprint(first):
            raise BenchmarkError("auth source changed during copy")
        payload = b"".join(chunks)
    except OSError as exc:
        raise BenchmarkError("auth source read failed") from exc
    finally:
        os.close(fd)
    _write_private(destination, payload)


def snapshot_home(path: Path) -> dict[str, tuple[int, str]]:
    """Capture a small deterministic tree snapshot for mutation detection."""

    if not path.exists():
        return {}
    result: dict[str, tuple[int, str]] = {}
    if not path.is_dir():
        raise BenchmarkError("permanent CODEX_HOME is not a directory")
    for item in sorted(path.rglob("*")):
        relative = str(item.relative_to(path))
        try:
            st = item.lstat()
        except OSError as exc:
            raise BenchmarkError("permanent home snapshot failed") from exc
        if stat.S_ISDIR(st.st_mode):
            result[relative] = (stat.S_IMODE(st.st_mode), "dir")
        elif stat.S_ISREG(st.st_mode):
            result[relative] = (stat.S_IMODE(st.st_mode), sha256_file(item))
        else:
            result[relative] = (stat.S_IMODE(st.st_mode), "special")
    return result


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


@contextmanager
def temporary_trial_home(
    role: str,
    candidate: Candidate,
    *,
    auth_source: Path | None = None,
    parent_dir: Path | None = None,
    permanent_home: Path | None = None,
    native_v2_compat: bool = False,
) -> Iterator[TrialHome]:
    """Materialize a private trial home and remove it (including auth) on exit.

    The compatibility config is restricted to live benchmark homes because the
    installed Codex 0.153+ CLI rejects the repository's production-era root
    concurrency key in strict mode. Production templates remain unchanged.
    """

    if role not in ROLE_NAMES:
        raise BenchmarkError("unknown role")
    parent = parent_dir or Path(tempfile.gettempdir())
    if parent_dir is not None:
        _ensure_private_dir(parent)
    cleanup_stale_run_dirs(parent)
    run_root = Path(tempfile.mkdtemp(prefix="pilotfish-benchmark-", dir=parent))
    os.chmod(run_root, 0o700)
    _write_private(run_root / "pid", str(os.getpid()).encode("ascii"))
    home = run_root / "codex"
    analysis = run_root / "analysis"
    _ensure_private_dir(home)
    _ensure_private_dir(analysis)
    auth_path: Path | None = None
    before_permanent = snapshot_home(permanent_home) if permanent_home else None
    try:
        config = (
            NATIVE_V2_BENCHMARK_CONFIG
            if native_v2_compat
            else (TEMPLATE_ROOT / "config.snippet.toml").read_bytes()
        )
        policy = (TEMPLATE_ROOT / "agents-md.orchestration.md").read_bytes()
        _write_private(home / "config.toml", config)
        _write_private(home / "AGENTS.md", policy)
        for name in ROLE_NAMES:
            source = TEMPLATE_ROOT / "agents" / f"{name}.toml"
            role_bytes = source.read_bytes()
            if name == role:
                mutated = _replace_role_binding(role_bytes, candidate)
                _validate_instruction_preservation(role_bytes, mutated)
                role_bytes = mutated
            _write_private(home / "agents" / f"{name}.toml", role_bytes)
        _ensure_private_dir(home / "sessions")
        _ensure_private_dir(home / "sqlite")
        if auth_source is not None:
            auth_path = home / "auth.json"
            copy_auth_secure(auth_source, auth_path)
        yield TrialHome(
            home=home,
            analysis_home=analysis,
            auth_path=auth_path,
            config_sha256=sha256_file(home / "config.toml"),
            role_manifest_sha256=_role_manifest_hash(home),
            policy_sha256=sha256_file(home / "AGENTS.md"),
        )
    finally:
        # Never leave credentials behind, including analyzer/process failures.
        if auth_path is not None:
            try:
                auth_path.unlink(missing_ok=True)
            except OSError:
                pass
        if before_permanent is not None and permanent_home is not None:
            if snapshot_home(permanent_home) != before_permanent:
                raise BenchmarkError("permanent CODEX_HOME was mutated")
        shutil.rmtree(run_root, ignore_errors=True)


def _sanitized_env(home: Path, analysis_home: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        upper = key.upper()
        if upper in {
            "CODEX_HOME",
            "CODEX_SQLITE_HOME",
            "CODEX_AUTH_SOURCE",
            "CODEX_AUTH_FILE",
            "AUTH_SOURCE",
        } or "AUTH_SOURCE" in upper or "AUTH" in upper or "TOKEN" in upper:
            env.pop(key, None)
    env["CODEX_HOME"] = str(home)
    env["CODEX_SQLITE_HOME"] = str((analysis_home or home) / "sqlite")
    return env


def _copy_required_session_logs(source: Path, destination: Path) -> None:
    """Copy only session JSONL into a temporary credential-free analyzer home."""

    sessions = source / "sessions"
    if not sessions.is_dir():
        return
    target = destination / "sessions"
    _ensure_private_dir(target)
    for item in sessions.rglob("*.jsonl"):
        relative = item.relative_to(sessions)
        output = target / relative
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = item.read_bytes()
        _write_private(output, payload)


def _terminate_process_group(process: subprocess.Popen[Any], *, force: bool = False) -> None:
    try:
        signal_to_send = signal.SIGKILL if force else signal.SIGTERM
        os.killpg(process.pid, signal_to_send)
    except (OSError, ProcessLookupError):
        try:
            process.kill() if force else process.terminate()
        except OSError:
            pass


def build_benchmark_codex_command(
    *, codex_bin: str, cwd: Path, role: str, prompt: str
) -> list[str]:
    """Reuse the native V2 command contract while pinning benchmark parent effort."""

    try:
        from verify_dispatch import build_codex_command
    except ImportError as exc:
        raise BenchmarkError("native dispatch command helper unavailable") from exc
    command = build_codex_command(
        codex_bin=codex_bin,
        cwd=cwd,
        parent_model=PARENT_MODEL,
        role=role,
    )
    try:
        effort_index = command.index("-c") + 1
        command[effort_index] = 'model_reasoning_effort="medium"'
        sandbox_index = command.index("-s") + 1
        command[sandbox_index] = "workspace-write"
    except (ValueError, IndexError) as exc:
        raise BenchmarkError("native dispatch command contract changed") from exc
    command[-1] = prompt
    return command


def build_case_prompt(case: Mapping[str, Any], workspace: Path) -> str:
    role = str(case["role"])
    try:
        from verify_dispatch import task_name_for_role
    except ImportError as exc:
        raise BenchmarkError("native dispatch task helper unavailable") from exc
    task_name = task_name_for_role(role)
    child_message = (
        "In the current workspace, read fixture.json and write result.json. "
        "result.json must be exactly {case_id, accepted, artifact}; accepted "
        "must be true and artifact must match expected_artifact."
    )
    return (
        "Call spawn_agent exactly once with "
        f"message='{child_message}', agent_type='{role}', "
        f"task_name='{task_name}', fork_turns='none'. "
        f"Then call wait_agent exactly once with timeout_ms={BENCHMARK_WAIT_TIMEOUT_MS} so the child "
        f"can complete in workspace {workspace}. Do not use an untyped fallback, "
        "a second spawn, or any child override."
    )


def run_codex_process(
    trial: TrialHome,
    prompt: str,
    *,
    executable: str = "codex",
    timeout: float = 300.0,
    cwd: Path | None = None,
    role: str = "scout",
) -> tuple[int, str]:
    """Run one Codex process group; raw output is returned in memory only."""

    env = _sanitized_env(trial.home)
    command = build_benchmark_codex_command(
        codex_bin=executable, cwd=cwd or ROOT, role=role, prompt=prompt
    )
    process = subprocess.Popen(
        command,
        cwd=str(cwd or ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process, force=True)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process, force=True)
        raise BenchmarkError("Codex trial timed out") from exc
    except KeyboardInterrupt as exc:
        _terminate_process_group(process, force=True)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process, force=True)
        raise BenchmarkError("Codex trial interrupted") from exc
    if process.returncode != 0:
        raise BenchmarkError("Codex trial failed")
    return process.returncode, stdout


def parse_redacted_receipt_jsonl(payload: str) -> dict[str, Any]:
    """Extract a receipt from JSONL without persisting or echoing raw events."""

    for line in payload.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, Mapping) and item.get("status") == "NATIVE_OK":
            # Keep only the allow-listed binding fields; never leak raw text/path/token.
            allowed = {
                "status",
                "version",
                "native_v2",
                "typed",
                "parent",
                "child",
                "participants",
                "child_count",
                "children_count",
                "spawn_count",
                "fork_turns",
            }
            return {key: item[key] for key in allowed if key in item}
    raise ReceiptError("native receipt unavailable")


def parse_native_dispatch_receipt(
    home: Path,
    stdout: str,
    *,
    role: str,
    candidate: Candidate,
    case_id: str,
) -> dict[str, Any]:
    """Use the existing V2 rollout/evidence parser; never trust a JSONL item."""

    try:
        from verify_dispatch import RoleBinding, inspect_available_evidence
    except ImportError as exc:
        raise ReceiptError("native dispatch evidence helper unavailable") from exc
    observed, boundary = inspect_available_evidence(
        home,
        stdout,
        RoleBinding(candidate.model, candidate.reasoning_effort),
        role,
        expected_wait_timeout_ms=BENCHMARK_WAIT_TIMEOUT_MS,
    )
    if not boundary or observed is None:
        raise ReceiptError("native dispatch evidence unavailable")
    if observed.status != "NATIVE_OK":
        raise ReceiptError(f"native dispatch rejected: {observed.reason_code}")
    receipt = build_binding_receipt(role, candidate, case_id=case_id)
    receipt.update(
        {
            "reason_code": observed.reason_code,
            "task_name": observed.task_name,
            "parent_ref": observed.parent_ref,
            "child_ref": observed.child_ref,
            "fork_turns": observed.fork_turns,
        }
    )
    return validate_binding_receipt(
        receipt, expected_role=role, expected_candidate=candidate
    )


def locate_native_parent_child_rollouts(home: Path, stdout: str) -> tuple[Path, Path]:
    """Resolve exactly the parent and child JSONL selected by native evidence."""

    try:
        from verify_dispatch import (
            EvidenceError,
            child_thread_from_parent,
            child_rollouts_for_parent,
            load_jsonl,
            locate_rollout,
            parse_exec_thread_id,
        )
        sessions_root = home / "sessions"
        parent_id = parse_exec_thread_id(stdout)
        parent_rollout = locate_rollout(sessions_root, parent_id)
        parent_events = load_jsonl(parent_rollout)
        try:
            child_id = child_thread_from_parent(parent_events)
        except EvidenceError:
            linked_children = child_rollouts_for_parent(sessions_root, parent_id)
            if len(linked_children) != 1:
                raise
            child_id = next(iter(linked_children))
        child_rollout = locate_rollout(sessions_root, child_id)
    except (ImportError, EvidenceError) as exc:
        raise MetricsUnavailable("native rollout binding evidence is unavailable") from exc
    return parent_rollout, child_rollout


def run_live_trial(
    role: str,
    candidate: Candidate,
    *,
    prompt: str,
    fixture_path: Path,
    auth_source: Path,
    case: Mapping[str, Any] | None = None,
    codex_executable: str = "codex",
    codexbar_executable: str = "codexbar",
    permanent_home: Path | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Run Codex with auth, then analyze usage in a separate auth-free home."""

    before = snapshot_home(permanent_home) if permanent_home else None
    with temporary_trial_home(
        role,
        candidate,
        auth_source=auth_source,
        permanent_home=permanent_home,
        native_v2_compat=True,
    ) as trial:
        workspace_context = (
            disposable_case_workspace(fixture_path)
            if case is not None
            else nullcontext(None)
        )
        with workspace_context as workspace:
            run_prompt = build_case_prompt(case, workspace) if case is not None else prompt
            model_started = time.monotonic()
            try:
                _returncode, raw_stdout = run_codex_process(
                    trial,
                    run_prompt,
                    executable=codex_executable,
                    timeout=timeout,
                    cwd=workspace or ROOT,
                    role=role,
                )
            finally:
                if trial.auth_path is not None:
                    trial.auth_path.unlink(missing_ok=True)
            model_wall_seconds = time.monotonic() - model_started
            if case is not None:
                artifact_packet = run_manifest_acceptance(case, workspace)
            else:
                artifact_packet = None
        # Session logs may be analyzed only after the credential is gone.
        receipt = parse_native_dispatch_receipt(
            trial.home,
            raw_stdout,
            role=role,
            candidate=candidate,
            case_id=str(case["id"]) if case is not None else "live-unscoped",
        )
        parent_rollout, child_rollout = locate_native_parent_child_rollouts(
            trial.home, raw_stdout
        )
        sessions_root = (trial.home / "sessions").resolve()
        _copy_required_session_logs(trial.home, trial.analysis_home)
        analysis_sessions = trial.analysis_home / "sessions"
        metrics = collect_native_rollout_metrics(
            analysis_sessions,
            candidate,
            parent_rollout=analysis_sessions / parent_rollout.resolve().relative_to(sessions_root),
            child_rollout=analysis_sessions / child_rollout.resolve().relative_to(sessions_root),
        )
        codexbar_metrics, binary = collect_codexbar_metrics(
            trial.analysis_home, executable=codexbar_executable
        )
        evidence = trial.hashes(fixture_path=fixture_path, prompt=prompt)
        evidence.update(
            {
                "codexbar_version": binary["version"],
                "codexbar_sha256": binary["sha256"],
                "codexbar_crosscheck_available": codexbar_metrics is not None,
            }
        )
        evidence["receipt"] = receipt
        evidence["metrics"] = metrics.as_dict()
        evidence["model_wall_seconds"] = model_wall_seconds
        if artifact_packet is not None:
            evidence["artifact_packet"] = artifact_packet
    if before is not None and permanent_home is not None and snapshot_home(permanent_home) != before:
        raise BenchmarkError("permanent CODEX_HOME was mutated")
    return evidence


def cleanup_stale_run_dirs(parent: Path) -> int:
    """Remove only known benchmark dirs whose recorded PID is no longer active."""

    removed = 0
    if not parent.is_dir():
        return removed
    for path in parent.glob("pilotfish-benchmark-*"):
        if not path.is_dir():
            continue
        pid_file = path / "pid"
        if not pid_file.exists():
            continue
        try:
            pid = int(pid_file.read_text().strip())
            if pid > 0:
                os.kill(pid, 0)
                continue
        except PermissionError:
            continue
        except (OSError, ValueError):
            pass
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


def validate_quota_snapshot(snapshot: Mapping[str, Any]) -> None:
    if not isinstance(snapshot, Mapping):
        raise MetricsUnavailable("quota snapshot is invalid")
    if snapshot.get("source") != "quota":
        raise MetricsUnavailable("quota source marker is missing")
    if snapshot.get("exclusive_attestation") is not True:
        raise MetricsUnavailable("quota exclusivity attestation is required")
    if not isinstance(snapshot.get("cohort"), str) or not snapshot["cohort"]:
        raise MetricsUnavailable("quota cohort is missing")
    if isinstance(snapshot.get("primary_usage"), bool) or not isinstance(snapshot.get("primary_usage"), (int, float)):
        raise MetricsUnavailable("quota primary usage is invalid")


def ensure_cohort_metric_consistency(observations: Iterable[TrialObservation]) -> str:
    by_cohort: dict[str, set[str]] = {}
    for observation in observations:
        if observation.metrics is None:
            raise MetricsUnavailable("metrics unavailable")
        cohort = observation.cohort or "unknown"
        by_cohort.setdefault(cohort, set()).add(observation.metrics.source)
    sources = {next(iter(values)) for values in by_cohort.values() if len(values) == 1}
    if any(len(values) != 1 for values in by_cohort.values()) or len(sources) != 1:
        raise MetricsUnavailable("metric sources are inconsistent")
    return next(iter(sources))


def _candidate_map() -> dict[str, Candidate]:
    return {"L": CANDIDATES["routine"][0], "T": CANDIDATES["routine"][1], "S": CANDIDATES["routine"][2]}


def simulate_posthoc_reruns(
    observations: Mapping[str, Sequence[TrialObservation]],
    *,
    orders: Sequence[str] = CHAIN_ORDERS,
) -> dict[str, list[ChainResult]]:
    """Simulate clean LTS/LS/TS/S attempts with no context handoff."""

    candidates = _candidate_map()
    if tuple(orders) != CHAIN_ORDERS:
        raise BenchmarkError("rerun order must be exactly LTS, LS, TS, S")
    flat = [item for values in observations.values() for item in values]
    source = ensure_cohort_metric_consistency(flat)
    results: dict[str, list[ChainResult]] = {order: [] for order in orders}
    case_ids = sorted(observations)
    for order in orders:
        for case_id in case_ids:
            by_candidate = {item.candidate: item for item in observations[case_id]}
            usage = 0.0
            elapsed = 0.0
            accepted = False
            hard_success = True
            used = 0
            for letter in order:
                if letter not in candidates or letter not in by_candidate:
                    continue
                item = by_candidate[letter]
                if item.metrics is None:
                    raise MetricsUnavailable("metrics unavailable")
                used += 1
                usage += item.metrics.primary_usage
                elapsed += item.elapsed_seconds
                hard_success = hard_success and item.hard_case_success
                if item.verdict == "accept" and item.hard_case_success:
                    accepted = True
                    break
            results[order].append(
                ChainResult(
                    chain=order,
                    accepted=accepted,
                    settled_primary_usage=usage if accepted else None,
                    settled_time_seconds=elapsed if accepted else None,
                    tiers_used=used,
                    hard_cases_successful=hard_success if accepted else False,
                    metric_source=source,
                )
            )
    return results


def _p95(values: Sequence[float]) -> float:
    if not values:
        raise BenchmarkError("no settled values")
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * 0.95
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def recommend_chain(results: Mapping[str, Sequence[ChainResult]]) -> Recommendation:
    candidates: list[Recommendation] = []
    for chain in CHAIN_ORDERS:
        rows = list(results.get(chain, ()))
        if not rows or any(not row.accepted or not row.hard_cases_successful for row in rows):
            continue
        sources = {row.metric_source for row in rows}
        if len(sources) != 1 or None in sources:
            continue
        usage = [float(row.settled_primary_usage) for row in rows if row.settled_primary_usage is not None]
        times = [float(row.settled_time_seconds) for row in rows if row.settled_time_seconds is not None]
        if len(usage) != len(rows) or len(times) != len(rows):
            continue
        candidates.append(
            Recommendation(
                chain=chain,
                median_primary_usage=statistics.median(usage),
                p95_settled_time_seconds=_p95(times),
                tiers=len(chain),
                terra_retained="T" in chain,
                metric_source=next(iter(sources)),
            )
        )
    if not candidates:
        raise BenchmarkError("no fully accepted chain with hard-case success")
    best_usage = min(row.median_primary_usage for row in candidates)
    usage_window = [row for row in candidates if row.median_primary_usage <= best_usage * 1.05]
    return min(
        usage_window,
        key=lambda row: (row.p95_settled_time_seconds, row.tiers, CHAIN_ORDERS.index(row.chain)),
    )


def ingest_review_report(
    reviews: Sequence[Mapping[str, Any]],
    *,
    manifest: Mapping[str, Any] | None = None,
    artifact_packets: Mapping[str, Mapping[str, Any]] | None = None,
    quota_exclusive_attestation: bool = False,
) -> dict[str, Any]:
    """Validate 36 anonymized verdict packets and recommend only when settled."""

    manifest_data = manifest or load_manifest()
    cases = {str(case["id"]): case for case in manifest_data["cases"]}
    if len(reviews) != 36:
        raise BenchmarkError("review ingestion requires exactly 36 verdicts")
    observations: dict[str, list[TrialObservation]] = {}
    seen: set[tuple[str, str]] = set()
    all_verdicts_settled = True
    for review in reviews:
        required = {
            "case_id",
            "tier",
            "verdict",
            "rationale",
            "fixture_sha256",
            "metric_source",
            "acceptance",
            "primary_usage",
            "elapsed_seconds",
            "hard_case_success",
        }
        if not isinstance(review, Mapping) or set(review) != required:
            raise BenchmarkError("review packet schema is invalid")
        case_id = review["case_id"]
        tier = review["tier"]
        if case_id not in cases or tier not in {"L", "T", "S"}:
            raise BenchmarkError("review case or tier is invalid")
        key = (case_id, tier)
        if key in seen:
            raise BenchmarkError("duplicate review packet")
        seen.add(key)
        case = cases[case_id]
        if review["fixture_sha256"] != case["fixture"]["hash"]:
            raise BenchmarkError("review fixture hash mismatch")
        source = review["metric_source"]
        if source not in {"proxy", "native-rollout-proxy", "quota"}:
            raise BenchmarkError("review metric source is invalid")
        if source == "quota" and not quota_exclusive_attestation:
            raise BenchmarkError("quota source requires explicit exclusivity attestation")
        try:
            verdict = parse_review_verdict(
                {"verdict": review["verdict"], "rationale": review["rationale"]}
            )["verdict"]
        except BenchmarkError as exc:
            raise BenchmarkError("review verdict is invalid") from exc
        acceptance = review["acceptance"]
        if not isinstance(acceptance, Mapping):
            raise BenchmarkError("deterministic acceptance evidence is invalid")
        if acceptance.get("accepted") is True:
            if (
                set(acceptance) != {"accepted", "artifact_sha256"}
                or not isinstance(acceptance.get("artifact_sha256"), str)
                or len(acceptance["artifact_sha256"]) != 64
            ):
                raise BenchmarkError("deterministic acceptance evidence is invalid")
            if artifact_packets is not None:
                packet = artifact_packets.get(case_id)
                if not isinstance(packet, Mapping) or packet.get("artifact_sha256") != acceptance["artifact_sha256"]:
                    raise BenchmarkError("artifact packet does not match review")
        elif acceptance.get("accepted") is False:
            if (
                set(acceptance) != {"accepted", "reason_code"}
                or not isinstance(acceptance.get("reason_code"), str)
                or not acceptance["reason_code"]
                or verdict != "reject"
            ):
                raise BenchmarkError("deterministic rejection evidence is invalid")
        else:
            raise BenchmarkError("deterministic acceptance evidence is invalid")
        if verdict == "inconclusive":
            all_verdicts_settled = False
        if isinstance(review["primary_usage"], bool) or not isinstance(review["primary_usage"], (int, float)) or review["primary_usage"] < 0:
            raise BenchmarkError("review primary usage is invalid")
        if isinstance(review["elapsed_seconds"], bool) or not isinstance(review["elapsed_seconds"], (int, float)) or review["elapsed_seconds"] < 0:
            raise BenchmarkError("review elapsed time is invalid")
        if type(review["hard_case_success"]) is not bool:
            raise BenchmarkError("review hard-case flag is invalid")
        metrics = UsageMetrics(
            input=float(review["primary_usage"]),
            output=0.0,
            cached_read=0.0,
            cached_write=0.0,
            total=float(review["primary_usage"]),
            cost=0.0,
            primary_usage=float(review["primary_usage"]),
            source=source,
        )
        observations.setdefault(case_id, []).append(
            TrialObservation(
                case_id=case_id,
                candidate=tier,
                verdict=verdict,
                metrics=metrics,
                elapsed_seconds=float(review["elapsed_seconds"]),
                hard_case_success=review["hard_case_success"],
                cohort=str(case["cohort"]),
            )
        )
    expected = {(case_id, tier) for case_id in cases for tier in {"L", "T", "S"}}
    if seen != expected:
        raise BenchmarkError("review packets do not cover every case and tier")
    if not all_verdicts_settled:
        return {
            "version": MANIFEST_VERSION,
            "status": "inconclusive",
            "recommendation": None,
        }
    try:
        simulated = simulate_posthoc_reruns(observations)
        recommendation = recommend_chain(simulated)
    except BenchmarkError:
        return {
            "version": MANIFEST_VERSION,
            "status": "unsettled",
            "recommendation": None,
        }
    return {
        "version": MANIFEST_VERSION,
        "status": "settled",
        "recommendation": recommendation.as_dict(),
    }


def enforce_live_gates(
    *,
    live: bool,
    yes: bool,
    benchmark_yes: bool,
    trials: int,
    max_cost_usd: float = DEFAULT_LIVE_MAX_COST_USD,
    environ: Mapping[str, str] | None = None,
) -> None:
    if not live:
        return
    if not yes or not benchmark_yes:
        raise BenchmarkError("live mode requires --yes and --benchmark-yes")
    env = os.environ if environ is None else environ
    if env.get("CI", "").lower() not in {"", "0", "false", "no"}:
        raise BenchmarkError("live mode is refused in CI")
    _validate_live_trial_count(trials)
    _validate_live_budget(max_cost_usd)


def validate_live_codex_binary(executable: str) -> None:
    """Reject a Codex binary whose version output cannot be parsed."""

    try:
        from install import is_parseable_codex_output
    except ImportError as exc:
        raise BenchmarkError("native version helper unavailable") from exc
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BenchmarkError("Codex binary is unavailable") from exc
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0 or not is_parseable_codex_output(output):
        raise BenchmarkError("Codex binary version is unavailable or invalid")


# Stable descriptive aliases used by offline callers and downstream tests.
parse_codexbar_totals = normalize_codexbar_totals
normalize_usage = normalize_codexbar_totals
parse_receipt = validate_binding_receipt
simulate_reruns = simulate_posthoc_reruns
choose_recommendation = recommend_chain
materialize_trial_home = temporary_trial_home
ingest_reviews = ingest_review_report


def run_live(
    *,
    trials: int,
    auth_source: Path | None = None,
    yes: bool = False,
    benchmark_yes: bool = False,
    environ: Mapping[str, str] | None = None,
    codex_executable: str = "codex",
    checkpoint_path: Path | None = None,
    max_cost_usd: float = DEFAULT_LIVE_MAX_COST_USD,
) -> dict[str, Any]:
    """Run a balanced live matrix with a sparse default and a cost circuit breaker."""

    enforce_live_gates(
        live=True,
        yes=yes,
        benchmark_yes=benchmark_yes,
        trials=trials,
        max_cost_usd=max_cost_usd,
        environ=environ,
    )
    if auth_source is None:
        raise BenchmarkError("live mode requires explicit --auth-source")
    max_cost = _validate_live_budget(max_cost_usd)
    manifest = load_manifest()
    matrix = select_live_matrix(manifest, trials)
    estimated_cost = estimate_live_cost(matrix)
    budget = live_budget_summary(
        matrix,
        trials=trials,
        max_cost_usd=max_cost,
    )
    if estimated_cost > max_cost:
        if checkpoint_path is not None:
            write_checkpoint_report(
                checkpoint_path,
                {
                    "version": MANIFEST_VERSION,
                    "status": "failed",
                    "trials": [],
                    "recommendation": None,
                    "budget": budget,
                    "failure": {
                        "reason_code": "preflight_budget_exceeded",
                        "reason": "estimated live cost exceeds max-cost-usd",
                    },
                },
            )
        raise BenchmarkError(
            "estimated live cost exceeds --max-cost-usd; lower trials or raise the explicit cap"
        )
    validate_live_codex_binary(codex_executable)
    rows: list[dict[str, Any]] = []
    # Trial order is stable: selected routine cases, then judgment cases; each
    # case receives Luna, Terra, then Sol as one matched unit.
    for case, candidate in matrix:
        role = str(case["role"])
        prompt = PARENT_PROMPT.replace("ROLE", role) + "\nTask: " + str(case["prompt"])
        try:
            evidence = run_live_trial(
                role,
                candidate,
                prompt=prompt,
                fixture_path=ROOT / str(case["fixture"]["path"]),
                auth_source=auth_source,
                case=case,
                codex_executable=codex_executable,
            )
        except BenchmarkError as exc:
            # Deliberately generic: stdout/stderr/session data never enters artifacts.
            if checkpoint_path is not None:
                write_checkpoint_report(
                    checkpoint_path,
                    {
                        "version": MANIFEST_VERSION,
                        "status": "failed",
                        "trials": rows,
                        "recommendation": None,
                        "budget": live_budget_summary(
                            matrix,
                            trials=trials,
                            max_cost_usd=max_cost,
                            observed_cost_usd=observed_live_cost(rows),
                        ),
                        "failure": {
                            "case_id": str(case["id"]),
                            "candidate": candidate.as_dict(),
                            "reason": str(exc),
                        },
                    },
                )
            raise BenchmarkError(f"live trial failed for {case['id']}: {exc}") from None
        rows.append({"case_id": case["id"], "candidate": candidate.as_dict(), **evidence})
        try:
            observed_cost = observed_live_cost(rows)
        except BenchmarkError as exc:
            if checkpoint_path is not None:
                write_checkpoint_report(
                    checkpoint_path,
                    {
                        "version": MANIFEST_VERSION,
                        "status": "failed",
                        "trials": rows,
                        "recommendation": None,
                        "budget": live_budget_summary(
                            matrix,
                            trials=trials,
                            max_cost_usd=max_cost,
                        ),
                        "failure": {
                            "case_id": str(case["id"]),
                            "candidate": candidate.as_dict(),
                            "reason": str(exc),
                        },
                    },
                )
            raise
        budget = live_budget_summary(
            matrix,
            trials=trials,
            max_cost_usd=max_cost,
            observed_cost_usd=observed_cost,
        )
        if observed_cost > max_cost:
            if checkpoint_path is not None:
                write_checkpoint_report(
                    checkpoint_path,
                    {
                        "version": MANIFEST_VERSION,
                        "status": "failed",
                        "trials": rows,
                        "recommendation": None,
                        "budget": budget,
                        "failure": {
                            "case_id": str(case["id"]),
                            "candidate": candidate.as_dict(),
                            "reason_code": "observed_budget_exceeded",
                            "reason": "observed native cost exceeds max-cost-usd",
                        },
                    },
                )
            raise BenchmarkError(
                f"observed live cost exceeded --max-cost-usd after {case['id']}"
            )
        if checkpoint_path is not None:
            write_checkpoint_report(
                checkpoint_path,
                {
                    "version": MANIFEST_VERSION,
                    "status": "running",
                    "trials": rows,
                    "recommendation": None,
                    "budget": budget,
                },
            )
    return {
        "version": MANIFEST_VERSION,
        "trials": rows,
        "recommendation": None,
        "budget": budget,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=False)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--accept-result", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--benchmark-yes", action="store_true")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--max-cost-usd", type=float, default=DEFAULT_LIVE_MAX_COST_USD)
    parser.add_argument("--auth-source", type=Path)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.accept_result is not None or args.fixture is not None:
            if args.accept_result is None or args.fixture is None:
                raise BenchmarkError("--accept-result and --fixture are required together")
            packet = validate_result_artifact(args.fixture, args.accept_result)
            print(json.dumps(packet, sort_keys=True))
            return 0
        if not args.dry_run and not args.live:
            raise BenchmarkError("choose --dry-run or --live")
        enforce_live_gates(
            live=args.live,
            yes=args.yes,
            benchmark_yes=args.benchmark_yes,
            trials=args.trials,
            max_cost_usd=args.max_cost_usd,
        )
        if args.dry_run:
            dry_manifest = load_manifest()
            dry_matrix = select_live_matrix(dry_manifest, args.trials)
            payload = {
                "version": MANIFEST_VERSION,
                "receipts": build_dry_run_receipts(),
                "candidate_projection": candidate_projection(),
                "live_budget": live_budget_summary(
                    dry_matrix,
                    trials=args.trials,
                    max_cost_usd=args.max_cost_usd,
                ),
                "network": False,
            }
            if args.output is not None:
                write_result_report(args.output, payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        checkpoint_path = None
        if args.output is not None:
            _prepare_report_destination(args.output)
            checkpoint_path = args.output.with_name(f".{args.output.name}.partial")
        payload = run_live(
            trials=args.trials,
            auth_source=args.auth_source,
            yes=args.yes,
            benchmark_yes=args.benchmark_yes,
            codex_executable=args.codex_bin,
            checkpoint_path=checkpoint_path,
            max_cost_usd=args.max_cost_usd,
        )
        if args.output is not None:
            write_result_report(args.output, payload)
            if checkpoint_path is not None:
                checkpoint_path.unlink(missing_ok=True)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except BenchmarkError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
