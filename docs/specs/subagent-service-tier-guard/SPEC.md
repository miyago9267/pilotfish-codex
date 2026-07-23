---
id: spec-subagent-service-tier-guard
title: Sub-agent service tier guard
historical_note: Namespace-specific examples are historical; the service-tier guard remains backend-neutral under the native migration.
status: complete
created: 2026-07-16
updated: 2026-07-16
author: Miyago
approved_by: Miyago
tags:
  - multi-agent
  - cost-control
  - service-tier
priority: high
---

## Requirements

### Problem

Pilotfish exposes the MultiAgentV2 metadata required for named-role dispatch:

```toml
[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
```

The exposed metadata also includes `service_tier`. A model can therefore add a
per-child Fast service-tier override even though Pilotfish only needs
`agent_type` for role routing. Fast mode has a material credit multiplier, so
an unrequested override is a cost-control failure.

### Required behavior

- Installed orchestration policy must require every named-role
  `spawn_agent` call to omit `service_tier`.
- A parent session that is already using Fast mode may continue to pass that
  tier through normal upstream inheritance. This spec prevents child-only
  escalation; it does not silently downgrade a user-selected parent mode.
- Offline and live dispatch verification must fail closed when the observed
  `spawn_agent` arguments contain a `service_tier` key, regardless of its
  value.
- The verifier failure must use a stable, machine-readable reason:
  `service_tier_override_forbidden`.
- Existing `agent_type`, namespace, model, and reasoning-effort verification
  must remain unchanged.
- Documentation must distinguish policy and verification controls from a hard
  runtime block.

### Non-goals

- Do not add a hook that claims to block `spawn_agent`; current `PreToolUse`
  hooks cannot cancel the tool call.
- Do not hide all spawn metadata, because named-role dispatch currently
  requires `agent_type` to remain exposed.
- Do not change the upstream model catalog, Fast-mode pricing, or Responses API
  behavior.
- Do not prevent Fast inheritance when Miyago deliberately enables Fast mode
  for the parent session.
- Do not prove the anecdotal frequency of autonomous Fast selection. The
  exposed cost-bearing capability and the missing guard are sufficient for
  this safety change.

## Architecture / Plan

### Control layers

| Layer | Responsibility | Enforcement strength |
| --- | --- | --- |
| Installed `AGENTS.md` policy | Tell the orchestrator never to pass a child-level `service_tier` | Preventive, model-enforced |
| Dispatch verifier | Reject recorded calls that contain the forbidden override | Deterministic, fail-closed verification |
| Regression tests | Lock the argument-inspection behavior | Deterministic, offline |
| Upstream Codex | Eventually provide selective schema hiding or a blocking hook | Not currently available |

The first three layers are feasible in this repository. They reduce accidental
cost escalation without presenting the current hook system as a security
boundary. They cannot intercept every ordinary runtime call after the model
has ignored policy; hard interception remains an upstream dependency.

### Feasibility evidence

| Question | Evidence | Result |
| --- | --- | --- |
| Is `service_tier` exposed by the compatibility setting? | OpenAI Codex PR [#22139](https://github.com/openai/codex/pull/22139) adds `service_tier` to both `spawn_agent` schemas and hides it with the other metadata only when metadata hiding is enabled. | Confirmed |
| Is the cost impact material? | The official [Speed documentation](https://learn.chatgpt.com/docs/agent-configuration/speed) documents higher Fast-mode credit consumption, including a 2.5x multiplier for GPT-5.6. | Confirmed |
| Can a project hook hard-block the override? | The official [Hooks documentation](https://learn.chatgpt.com/docs/hooks) states that `PreToolUse` does not support `continue`, `stopReason`, or `suppressOutput`; unsupported blocking fields fail the hook while the tool call continues. | Not feasible today |
| Did the original verifier detect the override? | A synthetic `agents.spawn_agent` fixture was amended with `service_tier="fast"` and passed to `inspect_dispatch`. The pre-change result was `ADAPTER_OK: verified_distinct_model`; the regression fixture now fails closed. | Gap reproduced and covered |
| Is there an implementation seam? | `inspect_dispatch` already parses the spawn arguments before validating namespace, role, context, model, and effort. A key-presence check can fail before child evidence is accepted. | Feasible |

### Decisions

- **Decision:** Forbid every explicit `service_tier` key on Pilotfish named-role
  calls.
  - **Reason:** Checking key presence is deterministic and avoids maintaining
    an incomplete allowlist of billable tier values.
  - **By:** Miyago (2026-07-16)
- **Decision:** Preserve upstream tier inheritance from the parent.
  - **Reason:** A parent-level Fast selection represents an explicit session
    choice; silently overriding it would be surprising and may not be possible
    through the exposed schema.
  - **By:** Miyago (2026-07-16)
- **Decision:** Do not ship a warning-only hook in this change.
  - **Reason:** It adds operational complexity without preventing the tool call
    or its cost.
  - **By:** Miyago (2026-07-16)
- **Decision:** Reconsider hard enforcement only when upstream exposes either
  selective metadata visibility or cancellable `PreToolUse` semantics.
  - **Reason:** Those are the two mechanisms that can remove or intercept the
    cost-bearing argument before execution.
  - **By:** Miyago (2026-07-16)

### Acceptance criteria

- **AC-1:** Generated orchestration guidance explicitly says that installed
  named roles must omit `service_tier`.
- **AC-2:** A fixture containing `"service_tier": "fast"` returns
  `FAILED: service_tier_override_forbidden`.
- **AC-3:** A fixture containing any other explicit `service_tier` value also
  returns the same failure.
- **AC-4:** A fixture with no `service_tier` retains the existing
  `ADAPTER_OK: verified_distinct_model` result.
- **AC-5:** Existing namespace, role, model, effort, correlation, and path
  boundary tests continue to pass.
- **AC-6:** Normal verification remains offline and does not spawn a real agent
  or consume model quota.
- **AC-7:** User-facing documentation does not describe hooks as an effective
  runtime block and records the parent-tier inheritance boundary.

### Rollout and rollback

- Ship as a patch-level cost-safety change with no configuration migration.
- Existing users receive the policy update through the normal Pilotfish
  reinstall or upgrade path.
- Keep the verifier check local to explicit spawn arguments, so removing it is
  a one-condition rollback if upstream changes the schema contract.
- Track upstream hooks and MultiAgentV2 schema changes before replacing this
  layered guard.

## Tasks

- [x] Phase 0: Reproduce the current verifier gap and validate official hook
  limitations.
- [x] Phase 1: Add failing offline fixtures for explicit `service_tier`
  overrides.
- [x] Phase 2: Make `inspect_dispatch` fail closed with
  `service_tier_override_forbidden`.
- [x] Phase 3: Add the omission rule and inheritance boundary to orchestration
  policy and user-facing documentation.
- [x] Phase 4: Run targeted dispatch tests and Markdown checks.
- [x] Phase 5: Update the bilingual changelog and patch-release notes.

## Files

- `templates/agents-md.orchestration.md` - add the durable named-role omission
  rule.
- `install/verify_dispatch.py` - reject explicit service-tier overrides.
- `tests/test_verify_dispatch.py` - add fail-closed regression fixtures.
- `README.md` - document the protection and its runtime boundary.
- `CHANGELOG.md` - record the cost-safety behavior in English and Chinese.
- `docs/specs/subagent-service-tier-guard/SPEC.md` - track decisions,
  acceptance criteria, and implementation progress.

## Notes

The feasibility verdict is **conditional go**:

- Policy, deterministic verification, tests, and documentation are implementable
  without changing the existing compatibility adapter.
- Hard runtime prevention is not implementable with the current public hook
  contract. Until upstream provides a blocking surface, ordinary dispatch is
  still policy-governed and the verifier proves violations after observing the
  recorded call.
- No live model call is required for implementation verification; synthetic
  rollout fixtures cover the new decision point.

Implementation verification on 2026-07-16:

- `tests/test_verify_dispatch.py`: 41 passed.
- `tests/test_policy.py`: 5 passed.
- `tests/test_templates.py`: 22 passed.
- Python compilation and `git diff --check`: passed.
- Markdown lint for the four touched Markdown files: passed. The repository-wide
  lint remains blocked by 15 pre-existing errors under `.ai/`, which this spec
  does not modify.
- Fresh-context review initially found one overstrong README sentence and one
  missing falsey-value fixture. Both were corrected; re-review returned
  `CONFIRMED`.
