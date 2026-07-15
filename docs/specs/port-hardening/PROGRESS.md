# PROGRESS — Port Hardening

## Phase 0 — Review & spec (done)

- [x] Review PR #1 diff, baseline (`main` = six roles, `test_policy.py` only),
      and new `test_templates.py`.
- [x] Live-verify config legality on Codex 0.144.4 (strict-config catches
      unknowns; port config keys legal; `web_search = "live"` valid enum;
      `strict-config` does not cover agent files).
- [x] Record the accepted upstream design and the one missing static-validation
      gap.

## Phase 1 — Fill the missing static validation (done)

- [x] T1 agent-TOML validator (`install/validate_agents.py`: allowlist + enum),
      20/20 tests green, validator passes the seven templates.
- [x] T2 per-role sandbox contract — covered by existing tests.
- [x] T3 leaf-only structural assert — covered by existing tests.
- [x] T5 self-guard fixtures (unknown key + three bad enums + missing/blank).
- [x] T6 installer validation-wording fix (attributes agent check to validator).

## Open question

- Runtime e2e feasibility remains open and is tracked only in the related
  `dispatch-verification` spec.
