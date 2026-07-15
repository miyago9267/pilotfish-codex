# TASKS — subagent-issue-claude

Current batch. Check off per step; keep in sync with `PROGRESS.md`.

## G1 — ship the config block

- [ ] T1. Add the `[features.multi_agent_v2]` block (`hide_spawn_agent_metadata
      = false`, `tool_namespace = "agents"`) to `templates/config.snippet.toml`
      with a comment linking upstream #31814 and the rollback instruction.
- [ ] T2. Extend the installer merge contract (`install/AGENT-INSTALL.md`) to
      manage the new table alongside `features.multi_agent`, `max_threads`,
      `max_depth`.
- [ ] T3. Extend static validation (`install/validate_agents.py` or a sibling
      check) to assert the snippet contains both keys with the exact expected
      values.

## G2 — call-shape contract in policy prose

- [ ] T4. Update `templates/agents-md.orchestration.md`: role spawns MUST pass
      `agent_type`, MUST pass `fork_turns='none'` unless context is explicitly
      needed (omitted `fork_turns` = full-history fork, which rejects
      overrides), and `task_name` must match `[a-z0-9_]+`. Note the tools are
      namespaced `agents.*` under this config.

## G3 — runtime smoke proof

- [ ] T5. Script a headless smoke test: `codex exec` spawns
      `agent_type='scout'`, `fork_turns='none'`, then asserts the child
      rollout's `turn_context.model == gpt-5.6-luna`. SKIP (not fail) when
      spawn tools are absent or auth is unavailable. Document that it costs
      real quota and is manual/opt-in.
- [ ] T6. Document the re-verify trigger: run the smoke test after every
      `codex update` or model change.

## G4 — reconcile dispatch-verification

- [ ] T7. Update `docs/specs/dispatch-verification/SPEC.md`: Gap A superseded
      under MAv2 + this config (headless spawn works, evidence 2026-07-15);
      Gap B gains the rollout `turn_context.model` proof method used here.

## G5 — upstream watch

- [ ] T8. Record exit criteria: when a stable release exposes `agent_type`
      (not just `expose_spawn_agent_model_overrides`) or documents
      `tool_namespace`, re-test with the workaround removed and decide whether
      to drop the block. Track #31814 and 0.145.x stable notes.
