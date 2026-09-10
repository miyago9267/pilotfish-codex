---
id: spec-operating-presets
title: Operating presets for capability-aware Pilotfish routing
status: draft
created: 2026-09-10
updated: 2026-09-10
author: Miyago
approved_by:
tags: [routing, presets, usage, cost, astra]
priority: high
---

<!-- markdownlint-disable MD025 -->

# Operating presets for capability-aware Pilotfish routing

## Requirements

- Provide four user-selectable operating presets: `economy`, `fast`,
  `precise`, and `quality`.
- Keep the preset as a routing-policy layer. Model preference remains a
  separate, explicit choice so a preset never silently changes the main
  session to Astra.
- Keep the existing `review_intent` signal (`fast`, `default`, `strict`)
  turn-scoped and map preset behavior to it instead of creating a second
  review classifier.
- Preserve the completed `plan-verifier` contract at
  `gpt-5.6-sol@high`, the Luna-only `mech-executor` and `scout` bindings, and
  every approval, security, release, and fresh-verifier gate.
- Make `economy` the explicit low-usage policy: Luna-first, no optional Astra,
  and optional review/retry work minimized while mandatory controls remain.
- Make `fast` optimize wall-clock latency, `precise` optimize evidence and
  correctness confidence, and `quality` optimize the complete outcome for
  complex work through stronger review and verification.
- Allow Astra only through the existing explicit main-session opt-in or a
  separately approved capability-triggered candidate path. A preset alone
  must not create an Astra dispatch.
- Keep the no-preset behavior byte- and policy-compatible with the current
  Luna/Sol routing until this contract is implemented and evaluated.
- Use offline deterministic tests for the first implementation. Do not add a
  paid or live Astra cohort until the preset semantics and cost guard are
  stable.

## Architecture / Plan

### Policy layers

The routing decision has four ordered layers:

1. Mandatory safety, authority, approval, release, and verification gates.
2. Explicit model preference, including the existing zero-write Astra
   main-session activation.
3. The session `operating_preset`, with an explicit current-turn override when
   supported.
4. Existing risk policy and the current Luna/Sol default when no preset is
   selected.

The preset projection may set model candidate order, effort ceiling, optional
review/retry behavior, discovery and evidence budgets, safe fan-out, and the
stop condition. It must not rewrite role TOMLs, native typed dispatch, or
permission boundaries.

### Preset contract

| Preset | Primary objective | Baseline policy | Astra policy |
| --- | --- | --- | --- |
| `economy` | Minimize usage cost | Luna-first; `review_intent=fast`; skip optional review and retry work | Off by default |
| `fast` | Minimize wall-clock time | `review_intent=fast`; bounded discovery; skip non-required review | Explicit opt-in or approved capability trigger |
| `precise` | Maximize evidence-backed correctness | `review_intent=default`; claim checks; one bounded retry or fresh verification when risk requires it | Candidate only on matched tool/cross-system evidence or explicit opt-in |
| `quality` | Maximize complex-task outcome | `review_intent=strict`; complete review, context, and fresh verification path | Candidate only on matched capability evidence or explicit main-session opt-in |

`fast` and `economy` share the existing fast review intent but optimize
different resources: `fast` spends only what is needed to reduce elapsed time,
while `economy` minimizes model and call usage even when the task takes longer.
`precise` raises the evidence floor. `quality` permits the fullest review path;
neither label is a promise that Astra is superior for pure reasoning.

### Non-negotiable routing invariants

- `plan-verifier` remains `gpt-5.6-sol@high` in every preset.
- `mech-executor` and `scout` remain on their installed Luna bindings and never
  receive an Astra override.
- A preset cannot bypass a required security reviewer, approval, release gate,
  or fresh verifier.
- The main model changes only through the user's explicit model/session choice
  or the existing capability-triggered candidate contract; task difficulty
  alone is insufficient.
- Invalid preset or model input fails closed before work or dispatch receipt.
- Advisory budgets remain advisory unless the host exposes a verified native
  enforcement mechanism. No invented config key is part of this slice.

### Decisions

- **Decision:** Add one `operating_preset` layer instead of four installed
  profiles or new roles.
  - **Reason:** The four choices change routing strategy and review depth; the
    existing roles and typed boundaries already express the execution topology.
  - **By:** Miyago (2026-09-10)
- **Decision:** Keep model preference separate from preset selection.
  - **Reason:** Users who deliberately want Astra can opt in without making
    `quality` or `fast` an accidental high-cost model switch.
  - **By:** Miyago (2026-09-10)
- **Decision:** Reuse `review_intent` as an internal turn-scoped projection.
  - **Reason:** `review_intent` already defines the optional review contract;
    duplicating its classifier would create precedence and drift problems.
  - **By:** Miyago (2026-09-10)
- **Decision:** Preserve the current default until offline evidence supports a
  preset rollout.
  - **Reason:** A new user-facing selector must not change existing cost,
    safety, or role behavior during its design phase.
  - **By:** Miyago (2026-09-10)

### Verification strategy

The first implementation must expose a pure offline projection function and a
small matrix covering all four presets, no-preset behavior, explicit model
selection, and current-turn review overrides. The matrix must assert:

- mandatory gates and the Sol `plan-verifier` binding survive every projection;
- `economy` never emits an Astra candidate by default;
- no preset silently changes the main model;
- `fast` and `economy` remain distinguishable by latency versus usage policy;
- `precise` and `quality` differ by evidence floor and review completeness;
- invalid values fail closed before any dispatch receipt;
- packaged policy and prompt copies remain synchronized.

Live probes, if later authorized, are sparse confirmation only. They cannot
promote a preset or replace the offline contract without a matched cost and
quality evaluation.

## Tasks

- [x] S0: Record the four-preset contract, layering, precedence, cost guard,
  and preserved role/gate invariants.
- [ ] S1: Implement the offline `operating_preset` projection without adding
  arbitrary native config keys or changing role bindings.
- [ ] S2: Add deterministic projection, precedence, fail-closed, and prompt
  synchronization tests.
- [ ] S3: Update user-facing launch documentation only after the projection
  contract passes offline verification.
- [ ] S4: Re-evaluate usage and quality with an explicitly authorized,
  low-density cohort; keep Astra disabled in `economy`.

## Files

- `docs/specs/operating-presets/SPEC.md` - this contract.
- `install/operating_preset.py` - planned pure policy projection module.
- `install/intent_review_matrix.py` - existing review-intent projection seam.
- `templates/agents-md.bootstrap.md` - compact default routing guard.
- `templates/agents-md.orchestration.md` - detailed preset and precedence
  policy after implementation approval.
- `plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/` - packaged
  policy and prompt copies.
- `tests/test_operating_presets.py` - planned offline contract tests.

## Notes

The Astra v2 analysis shows the useful split clearly: pure reasoning does not
currently justify Astra's cost over Sol, while tool-heavy, MCP, computer-use,
and cross-system work can justify a capability-triggered candidate. This spec
therefore treats `quality` as stronger evidence and review, not as an automatic
Astra switch. The completed
[`astra-main-session-budget`](../astra-main-session-budget/SPEC.md) spec remains
the authority for explicit Astra main-session activation.
