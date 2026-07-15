# TASKS — Port Hardening

Completed batch. Kept as the execution record for `48e291f`.

## Static validation and existing boundary coverage

- [x] T1. Add an agent-TOML validator (`install/validate_agents.py`: key
      allowlist + enum checks) covering all seven roles. Satisfies AC-S3, AC-S4,
      AC-S5. (G2)
- [x] T2. Per-role sandbox contract — covered by the existing
      `test_complete_codex_role_routing_map` (`sandbox_mode` asserted per role,
      `None` for the three executors). No new work needed. Satisfies AC-S1, AC-S2.
- [x] T3. Leaf-only property — covered by existing tests that assert
      `agents.max_depth = 1` and "cannot delegate" per role. Satisfies AC-S6.
- [x] T5. Add self-guard fixtures: unknown key, invalid `sandbox_mode`, invalid
      `web_search`, invalid `model_reasoning_effort`, missing required key, and
      blank instructions each fail the validator. Satisfies AC-B2.
- [x] T6. Fix installer wording: agent-file validity attributed to
      `install/validate_agents.py`, not `strict-config doctor`.

## Tracked elsewhere

- Runtime dispatch and e2e enforcement remain in the `dispatch-verification`
  spec.
