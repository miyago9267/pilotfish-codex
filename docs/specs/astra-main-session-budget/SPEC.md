---
id: spec-astra-main-session-budget
title: Astra main-session budget mode
status: completed
created: 2026-09-10
updated: 2026-09-10
author: Miyago
approved_by: Miyago (S0 approval, 2026-09-10)
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
- Preserve a fail-closed activation path: an unavailable model or invalid
  session override stops before work begins. Removing the override returns to
  the existing Luna/Sol policy; no automatic fallback may claim Astra usage.

## Architecture / Plan

### Decisions

- **Decision:** Activate the feature with zero-write native session flags, not a
  managed profile file.
  - **Reason:** Codex exposes `--model` and `-c` overrides; this preserves the
    user's base config bytes and avoids a second ownership/rollback manifest.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)
- **Decision:** Use an `astra-thinking` operating contract rather than a new
  universal role.
  - **Reason:** The value is a topology—Astra synthesizes while cheaper roles
    do repeatable work—not another child identity or an unconditional upgrade.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)
- **Decision:** The first slice uses prompt and routing policy guards, with no
  claim of provider quota enforcement or automatic model fallback.
  - **Reason:** Codex's local config exposes model and effort, but this repo has
    no verified native token-budget key. Invented keys would fail strict config.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)
- **Decision:** Set Astra and Plan-mode effort to `high`, cap fan-out at one
  optional child in the opt-in session, and retain the existing role bindings.
  - **Reason:** `high` is the documented cost/quality point in the v2 analysis;
    limiting fan-out and delegating routine work address usage without changing
    mandatory review coverage.
  - **By:** Codex proposal, pending Miyago approval (2026-09-10)

### Activation contract

The documented opt-in command is:

```bash
codex --model gpt-6-astra \
  -c model_reasoning_effort="high" \
  -c plan_mode_reasoning_effort="high" \
  -c agents.max_concurrent_threads_per_session=1
```

These are session-only overrides. The base `$CODEX_HOME/config.toml`, active
policy, role files, hooks, and installer state are not written. The command
must be rejected before task work when Astra is unavailable or an override is
invalid; the documented recovery is to start a normal `codex` session without
these flags. A release or production action still needs its existing approval.

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

The prompt recommends `max_tool_calls=12` and `max_wall_seconds=300` for the
main Astra session. These are advisory policy limits; the native session flag
enforces only one optional child. This slice does not add a main-session
typed-dispatch receipt field: existing child receipts and their strict schema
remain unchanged. The prompt and documentation must label the two budgets as
advisory rather than implying provider enforcement.

## Acceptance

- The session command selects `gpt-6-astra@high` for the main and Plan modes and
  sets one optional child without editing the base config.
- A normal session without the flags remains Luna/medium with Plan xhigh, and
  all four Luna baseline roles plus `plan-verifier` Sol/high remain unchanged.
- The packaged prompt contains the Astra thinking contract, compact-context and
  stop rules, Luna delegation path, unchanged mandatory gates, and explicit
  advisory wording for the 12-call/300-second limits.
- Synthetic invalid-override and unavailable-model activation tests stop before
  task work or an Astra dispatch receipt; only a separately started no-flags
  session returns to Luna.
- Existing child receipts and strict receipt-schema tests remain unchanged.
- Targeted tests, strict-config, role validation, base-config byte comparison,
  prompt assertions, and a zero-write rollback round-trip pass.

## Rollback

Stop the Astra session and start `codex` without the four overrides. Because the
activation is zero-write, rollback removes no managed artifact and restores the
base configuration byte-for-byte. Any future wrapper or profile installer is a
separate, explicitly reviewed scope and must add its own ownership and backup
contract before shipping.

## Tasks

- [x] S0: Review this contract and confirm the opt-in scope and budget values.
- [x] S1: Document and test the zero-write native session command without
  changing the active user's model by default.
- [x] S2: Update the default bootstrap/orchestration prompt and packaged policy
  with the Astra main-session contract and minimality rules.
- [x] S3: Add offline routing/prompt tests for Astra main mode, Luna delegation,
  Sol plan-verifier preservation, and fail-closed unavailable-model behavior.
  Invalid overrides must stop before task work or an Astra dispatch receipt;
  recovery requires a separately started no-flags session.
- [x] S4: Run validators, targeted tests, and a fresh read-only verifier; update
  the changelog only after the contract is accepted.

## Files

- `docs/specs/astra-main-session-budget/SPEC.md` - this contract.
- `install/astra_session.py` - offline validation and command construction for
  the zero-write session overrides.
- `templates/config.snippet.toml` - native configuration reference.
- `templates/agents-md.bootstrap.md` - short always-on routing guard.
- `templates/agents-md.orchestration.md` - detailed routing and prompt policy.
- `plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/references/`
  `orchestration-policy.md` - packaged policy copy.
- `tests/test_astra_routing.py` and `tests/test_templates.py` - regression coverage.
- `README.md` and `INSTALL.md` - user-facing zero-write opt-in instructions.

## Notes

The v2 analysis measured Astra as materially more expensive than Luna for pure
reasoning while showing a stronger advantage on tool-heavy work. This mode is
therefore an explicit choice for users who value Astra's thinking quality; its
cost control comes from effort selection, compact context, bounded fan-out, and
cheap-role delegation. It is not evidence that Astra is cheaper than Luna and
does not authorize paid benchmark runs.
