# PROGRESS — Port Hardening

## Phase 0 — Review & spec (done)

- [x] Review PR #1 diff, baseline (`main` = six roles, `test_policy.py` only),
      and new `test_templates.py`.
- [x] Live-verify config legality on Codex 0.144.4 (strict-config catches
      unknowns; port config keys legal; `web_search = "live"` valid enum;
      `strict-config` does not cover agent files).
- [x] Record this spec, prioritizing security + boundary testing over installer
      slimming, deferring design/routing to the upstream author.

## Phase 1 — Fill the missing static validation (done)

- [x] T1 agent-TOML validator (`install/validate_agents.py`: allowlist + enum),
      20/20 tests green, validator passes the seven templates.
- [~] T2 per-role sandbox contract — already covered by existing tests.
- [~] T3 leaf-only structural assert — already covered by existing tests.
- [ ] T4 relax brittle prose assertions — deferred (not "missing validation").
- [x] T5 self-guard fixtures (unknown key + three bad enums + missing/blank).
- [x] T6 installer validation-wording fix (attributes agent check to validator).

## Phase 2 — Installer slimming (P2, not started)

- [ ] T7 gate v1.0.x migration behind legacy detection
- [ ] T8 trim and snapshot-test the fresh-install touch set

## Open questions

- Whether P2 slimming lands in this PR or a follow-up, given the author owns the
  installer design.
