# TASKS — Port Hardening

Current batch. Check off per step; keep in sync with `PROGRESS.md`. Priority
order is P1 (security + boundary) before P2 (installer slimming).

## P1 — Security boundaries & test robustness

- [x] T1. Add an agent-TOML validator (`install/validate_agents.py`: key
      allowlist + enum checks) covering all seven roles. Satisfies AC-S3, AC-S4,
      AC-S5. (G2)
- [~] T2. Per-role sandbox contract — already covered by the existing
      `test_complete_codex_role_routing_map` (`sandbox_mode` asserted per role,
      `None` for the three executors). No new work needed. Satisfies AC-S1, AC-S2.
- [~] T3. Leaf-only property — already covered: existing tests assert
      `agents.max_depth = 1` and "cannot delegate" per role. Satisfies AC-S6.
- [ ] T4. (Deferred — not part of "fill the missing validation".) Relax brittle
      `assertRegex` on README / installer prose. Satisfies AC-B1, AC-B3. (G4)
- [x] T5. Add self-guard fixtures: unknown key, invalid `sandbox_mode`, invalid
      `web_search`, invalid `model_reasoning_effort`, missing required key, and
      blank instructions each fail the validator. Satisfies AC-B2.
- [x] T6. Fix installer wording: agent-file validity attributed to
      `install/validate_agents.py`, not `strict-config doctor`. Satisfies AC-I3.

## P2 — Installer slimming (secondary)

- [ ] T7. Extract the v1.0.x migration into a clearly gated section that runs
      only on detected legacy state. Satisfies AC-I2.
- [ ] T8. Trim the fresh-install path to the AC-I1 allowed-touch set and verify
      it with a fresh-home filesystem snapshot. Satisfies AC-I1.

## Out of scope (defer to author)

- Role structure, phase lifecycle, Remora model/effort map, `explore`
  retirement, SHA-pinned retired assets, runtime enforcement hooks.
