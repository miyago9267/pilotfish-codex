# TASKS — subagent-issue-codex

Implementation starts only after Miyago approves this Codex spec or reconciles
it with the parallel Claude spec.

## Phase 1 — Config and install contract

- [ ] C1. Add `[features.multi_agent_v2]` to
      `templates/config.snippet.toml` with
      `hide_spawn_agent_metadata = false`, `tool_namespace = "agents"`, and
      `max_concurrent_threads_per_session = 4`. Do not set `enabled`.
- [ ] C2. Document why the namespace key is inseparable from metadata exposure,
      link #31814/#32031, and include a rollback instruction.
- [ ] C3. Extend `install/AGENT-INSTALL.md` so the merge contract owns all three
      V2 keys without overwriting unrelated feature settings.
- [ ] C4. Extend static validation to reject a missing key, a wrong namespace,
      bare metadata exposure, an explicit V2 enable, or concurrency other than
      four.
- [ ] C5. Add fixtures covering the valid block and every invalid combination.

## Phase 2 — Orchestration policy

- [ ] P1. Update `templates/agents-md.orchestration.md` to use
      `agents.spawn_agent` for named roles and require `agent_type`.
- [ ] P2. Require `task_name` to match `[a-z0-9_]+` and default
      `fork_turns = "none"`; permit only a bounded positive turn count when
      recent context is necessary.
- [ ] P3. Add the fail-closed rule: never retry a rejected named role as an
      untyped spawn and never override the model of an existing named role.
- [ ] P4. Add policy tests for namespace, call shape, bounded context, TOML-owned
      routing, and the untyped-spawn prohibition.

## Phase 3 — Opt-in runtime proof

- [ ] R1. Implement `install/verify_dispatch.py` as a manual smoke command with
      no third-party Python dependencies.
- [ ] R2. Preflight Codex version/auth/config and compare installed scout routing
      with `templates/agents/scout.toml` before spending quota.
- [ ] R3. Spawn a self-contained scout through a Terra/low parent and capture
      the exact parent and child thread IDs.
- [ ] R4. Assert parent MultiAgent version, `agents.spawn_agent` namespace and
      arguments, and child model/effort from rollout metadata.
- [ ] R5. Return `SKIPPED` for unavailable auth/model/tooling and `FAILED` for
      schema, role, namespace, or model mismatches.
- [ ] R6. Unit-test parsing and verdict logic with fixtures; do not call live
      models from the normal test suite.

## Phase 4 — Documentation and upstream exit

- [ ] D1. Add a README compatibility note with supported config, new-session
      requirement, cost warning, and manual smoke command.
- [ ] D2. Update `docs/design.md` with the V1/V2 routing seam, four-thread bound,
      fail-closed behavior, and separation of static versus live proof.
- [ ] D3. Document that `multi_agent_v2 = false` in `features list` does not
      prove the active turn is V1.
- [ ] D4. Define adapter exit criteria: a stable release must expose a supported
      named-role selector, preserve role TOML behavior, and pass the smoke with
      the adapter removed.
- [ ] D5. Re-run targeted static tests, the optional live smoke, and markdown
      lint; record verified and unverified surfaces.

## Coordination boundary

- [ ] X1. Before implementation, choose this spec or reconcile it with
      `subagent-issue-claude`; do not run two writers over the same templates.
- [ ] X2. Keep Claude's spec and `dispatch-verification` untouched unless Miyago
      assigns a separate reconciliation task.
