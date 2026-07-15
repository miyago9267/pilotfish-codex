# PROGRESS — subagent-issue

## Phase 0 — Research and reconciliation (done)

- [x] Reproduce the affected ChatGPT-auth reserved-schema failure with bare
      metadata exposure.
- [x] Verify `tool_namespace = "agents"` restores `agent_type` in the spawn
      schema.
- [x] Prove Terra/low parent to Luna/low scout routing from rollout evidence.
- [x] Prove Sol/xhigh parent to Luna/low scout routing and record exact parent
      and child session IDs.
- [x] Verify headless MultiAgentV2 spawning and exact child correlation through
      `sub_agent_activity` plus `session_meta.parent_thread_id`.
- [x] Verify Codex `0.144.4` defaults V2 concurrency to four including root.
- [x] Verify the same source rejects legacy `agents.max_threads` when V2 is
      locally enabled; retain the no-`enabled` install rule.
- [x] Confirm upstream alpha work exposes direct model and effort overrides but
      does not yet restore native named-role routing by default.
- [x] Review project templates, installer, validator, orchestration policy, and
      dispatch-verification gaps.
- [x] Incorporate Claude advice: configurable concurrency, evidenced enable
      conflict, Sol-parent baseline, reconciliation ownership, and committed
      draft history.
- [x] Correct the old smoke assumption: child ID comes from the correlated
      parent activity event, not the spawn result or mtime guessing.
- [x] Merge `subagent-issue-claude` and `subagent-issue-codex` into this single
      implementation source.

## Phase 1 — Config and installation

- [x] C1-C3 packaged adapter, installer merge, and operator guidance
- [x] C4-C6 static validation, warnings, and fixtures

## Phase 2 — Orchestration policy

- [x] P1-P3 isolated transport and typed, bounded call shape
- [x] P4-P6 fail-closed behavior, recursion bound, and policy tests

## Phase 3 — Capability and runtime proof

- [x] R1-R5 adapter smoke, exact-child evidence, and verdicts
- [x] R6-R7 native probe, parsing tests, and offline fixtures

## Phase 4 — Documentation reconciliation

- [x] D1-D2 README and architecture documentation
- [x] D3-D4 dispatch-verification and capability-source corrections

## Phase 5 — Upstream exit

- [x] U1-U2 current stable/native capability check and adapter-free proof
- [x] U3-U5 adapter-retention gate, rollback, and contingency contract

## Final verification

- [x] V1 targeted tests: 50 passing
- [x] V2 Markdown, compile, static validator, strict doctor, and diff checks
- [x] V3 live smoke with operator opt-in
- [x] V4 final progress and changelog

## Decisions

- Role TOMLs remain the stable routing core.
- The three-key V2 block is a temporary, machine-layer adapter.
- Packaged concurrency defaults to 4; Pilotfish accepts `1..8` with warnings
  for non-default cost or disabled-delegation behavior.
- Runtime support is capability-driven: `adapter-required`, `native-ready`,
  `unsupported`, or `not-exercised`.
- Native delegation fails closed when typed role routing cannot be proven.
- Normal tests remain offline; live smoke is explicit and quota-spending.
- Native migration changes the adapter and transport section, not role routing.
- An external scheduler remains a separate contingency, not current scope.

## Current gate

Status is Complete. The final requirement-by-requirement audit passed on
2026-07-15.

## Live evidence

- `ADAPTER_OK` on Codex `0.144.4`: Terra parent
  `019f6676-164b-7d61-ab96-9e7e3ef316f5` spawned exact Luna child
  `019f6676-32d0-7742-ae4d-d3b6c14f7c41` through `scout`.
- Adapter-free native probe returned
  `SKIPPED: native_schema_introspection_unavailable` before quota or spawning;
  the temporary adapter remains required.
- Global config static validation and `codex --strict-config doctor --summary`
  passed after adding explicit concurrency 4. The rollback backup is
  `~/.codex/backups/config.toml.before-pilotfish-codex-v1.2-e2e-20260715`.
- Installed `scout.toml` now matches the repository template in full; its
  rollback backup is
  `~/.codex/backups/scout.toml.before-pilotfish-codex-v1.2-e2e-20260715`.
