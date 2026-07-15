# TASKS — subagent-issue

Implementation and verification completed on 2026-07-15.

## Phase 1 — Config and installation

- [x] C1. Add the three-key `[features.multi_agent_v2]` adapter to
      `templates/config.snippet.toml`; recommend concurrency 4 and omit
      `enabled`.
- [x] C2. Extend `install/AGENT-INSTALL.md` with an idempotent, TOML-aware merge
      contract that preserves unrelated features and legacy `[agents]` keys.
- [x] C3. Document the two-key schema dependency, new-session requirement,
      concurrency cost warning, rollback, and linked upstream issues.
- [x] C4. Extend `install/validate_agents.py` to validate the adapter shape:
      both schema keys, namespace `agents`, no forced V2 enable, and integer
      concurrency in `1..8`.
- [x] C5. Warn rather than fail when concurrency is valid but differs from 4;
      distinguish `1` as delegation-disabled and values above 4 as higher-cost.
- [x] C6. Add offline fixtures for valid, partial, malformed, out-of-range, and
      unrelated-key-preservation cases.

## Phase 2 — Stable orchestration contract

- [x] P1. Isolate the spawn transport inside
      `templates/agents-md.orchestration.md`; keep semantic named-role rules
      independent of the current namespace.
- [x] P2. Configure the affected-release transport as `agents.spawn_agent` and
      require `agent_type`, `task_name`, and `fork_turns` on every delegation.
- [x] P3. Require `task_name` to match `[a-z0-9_]+`; default
      `fork_turns = "none"` and permit only a bounded positive integer string.
- [x] P4. Add the fail-closed rule: never retry a rejected named role as an
      untyped child and never duplicate a role's model or effort in policy.
- [x] P5. Preserve the main-session-only delegation rule so workers cannot
      recursively create uncontrolled fan-out.
- [x] P6. Add policy tests for the transport marker, typed call shape, bounded
      context, TOML-owned routing, and untyped-spawn prohibition.

## Phase 3 — Capability and runtime proof

- [x] R1. Implement `install/verify_dispatch.py` as an explicit manual command
      with no third-party Python dependencies.
- [x] R2. Preflight auth, config, concurrency, and installed-versus-repository
      scout routing before launching a model call.
- [x] R3. Exercise the adapter through a Terra/low parent and a self-contained
      `scout` brief; capture the exact parent session and spawn call ID.
- [x] R4. Resolve the child from the correlated `sub_agent_activity` event and
      verify its `session_meta.parent_thread_id`, model, and effort.
- [x] R5. Emit `ADAPTER_OK`, `NATIVE_OK`, `SKIPPED`, or `FAILED` with stable
      reason codes. Use `adapter_not_exercised` when V1 is active.
- [x] R6. Add an adapter-free native gate that does not mutate user config or
      remove the adapter by version inference. Until safe schema introspection
      exists, it skips before quota or spawning.
- [x] R7. Unit-test rollout parsing, exact-child correlation, capability-state
      selection, and verdicts with fixtures. Normal tests must not spend quota.

## Phase 4 — Documentation reconciliation

- [x] D1. Add a README compatibility note with install, new-session, cost,
      failure, manual smoke, and rollback instructions.
- [x] D2. Update `docs/design.md` with the three ownership layers, compatibility
      states, fail-closed behavior, and static-versus-live proof boundary.
- [x] D3. Reconcile `docs/specs/dispatch-verification`: replace the outdated
      headless-no-subagents gap for V2 and add exact rollout child proof to the
      remaining enforcement gap.
- [x] D4. Document that `features list` and version checks are non-authoritative
      hints; live schema and child evidence decide support.

## Phase 5 — Upstream exit and contingency

- [x] U1. Record current stable `0.144.4` as not native-ready; alpha model
      overrides do not satisfy the future stable `agent_type` gate.
- [x] U2. Run the isolated adapter-free probe. It returned
      `SKIPPED: native_schema_introspection_unavailable`, so adapter removal
      remains forbidden.
- [x] U3. Enforce that `hide_spawn_agent_metadata` and `tool_namespace` remain
      until `NATIVE_OK`; keep concurrency as a separately revalidated key.
- [x] U4. Limit future migration to the isolated transport section and adapter;
      preserve role TOMLs, semantic policy, and one-cycle rollback guidance.
- [x] U5. If neither adapter nor native route works, fail closed and open a new
      spec for an external scheduler; do not silently fall back to Sol children.

## Final verification

- [x] V1. Run targeted config, validator, policy, parser, and fixture tests.
- [x] V2. Run Markdown lint and `git diff --check` on touched files.
- [x] V3. Run the quota-spending smoke only with explicit operator opt-in and
      record both verified and unverified surfaces.
- [x] V4. Update `PROGRESS.md` and changelog documentation with the outcome.
