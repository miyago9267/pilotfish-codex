---
id: spec-astra-main-session-budget
title: Astra main-session budget mode
status: draft
created: 2026-09-10
updated: 2026-09-10
author: Miyago
approved_by:
tags: [astra, routing, usage, prompt]
priority: high
---

<!-- markdownlint-disable MD025 -->

# Astra main-session budget mode

## Requirements

- Provide an explicit opt-in mode for a user who wants `gpt-6-astra` as the
  main session model. The default installation remains Luna-first.
- Use Astra for synthesis, planning, and difficult judgment while routing
  routine, mechanical, and bounded execution work to the existing Luna roles.
- Keep `plan-verifier` on the completed `gpt-5.6-sol@high` contract. The mode
  must not rewrite security, approval, release, or typed-dispatch boundaries.
- Default Astra effort to `high`; do not default to `xhigh` or `max`.
- Add a budget-aware default prompt: use named inputs, avoid full-history
  replay, make one sufficient pass, avoid speculative research and retries,
  delegate mechanical work, and stop when acceptance evidence is sufficient.
- State the budget as an operational guard, not as a provider-enforced quota.
  If the host cannot expose a hard token cap, the implementation must say so.
- Keep the mode session-scoped and user-controlled. Pilotfish must never switch
  the main model to Astra because a task is merely difficult.
- Preserve a fail-soft path: an unavailable profile or model falls back to the
  existing Luna/Sol policy without claiming Astra was used.

## Architecture / Plan

### Decisions

- **Decision:** Model the feature as an explicit main-session preference layered
  over the existing capability-first router.
  - **Reason:** Codex exposes native `--model` and `--profile` overrides, while
    the installer must not silently mutate the user's active model preference.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)
- **Decision:** Use an `astra-thinking` operating contract rather than a new
  universal role.
  - **Reason:** The value is a topology—Astra synthesizes while cheaper roles
    do repeatable work—not another child identity or an unconditional upgrade.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)
- **Decision:** The first slice uses prompt and routing policy guards, with no
  claim of hard provider quota enforcement.
  - **Reason:** Codex's local config exposes model and effort, but this repo has
    no verified native token-budget key. Invented keys would fail strict config.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)
- **Decision:** Set Astra and Plan-mode effort to `high`, cap fan-out at one
  optional child in the opt-in profile, and retain the existing role bindings.
  - **Reason:** `high` is the documented cost/quality point in the v2 analysis;
    limiting fan-out and delegating routine work address usage without changing
    mandatory review coverage.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)

### Interaction contract

When the user explicitly selects Astra as the main model, the main session
adopts `astra-thinking`:

1. Frame the outcome and acceptance once; do not restate the full prompt.
2. Inspect only named or claim-relevant inputs and use a bounded tool allowlist.
3. Delegate mechanical or repetitive work to `mech-executor` or `scout`; use
   `executor` or `verifier` only when their existing boundary applies.
4. Keep required Sol review, approval, security, release, and fresh-verifier
   gates unchanged.
5. Stop after sufficient evidence; a new pass requires a changed claim,
   concrete failure, or explicit user request.

The prompt may recommend a budget such as `max_tool_calls=12` and
`max_wall_seconds=300`, but receipts must label it as an advisory policy unless
the host exposes an independently verified enforcement surface.

## Tasks

- [ ] S0: Review this contract and confirm the opt-in scope and budget values.
- [ ] S1: Add the native `astra-thinking` config/profile template and install
  documentation without changing the active user's model by default.
- [ ] S2: Update the default bootstrap/orchestration prompt and packaged policy
  with the Astra main-session contract and minimality rules.
- [ ] S3: Add offline routing/prompt tests for Astra main mode, Luna delegation,
  Sol plan-verifier preservation, and fail-soft unavailable-model behavior.
- [ ] S4: Run validators, targeted tests, and a fresh read-only verifier; update
  the changelog only after the contract is accepted.

## Files

- `docs/specs/astra-main-session-budget/SPEC.md` - this contract.
- `templates/config.snippet.toml` - native configuration documentation.
- `templates/agents-md.bootstrap.md` - short always-on routing guard.
- `templates/agents-md.orchestration.md` - detailed routing and prompt policy.
- `plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/references/`
  `orchestration-policy.md` - packaged policy copy.
- `tests/test_astra_routing.py` and `tests/test_templates.py` - regression coverage.
- `README.md` and `INSTALL.md` - user-facing opt-in instructions.

## Notes

The v2 analysis measured Astra as materially more expensive than Luna for pure
reasoning while showing a stronger advantage on tool-heavy work. This mode is
therefore an explicit choice for users who value Astra's thinking quality; its
cost control comes from effort selection, compact context, bounded fan-out, and
cheap-role delegation. It is not evidence that Astra is cheaper than Luna and
does not authorize paid benchmark runs.
