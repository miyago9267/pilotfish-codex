# PROGRESS — automatic-model-routing

## Status

- Overall: implemented and published locally; live model selection unverified
- Current phase: post-install acceptance
- Last updated: 2026-09-21

## Evidence

- The source role manifest binds `sol-executor`, `verifier`, `plan-verifier`,
  `security-reviewer`, and `security-executor` to `gpt-5.6-sol@high`; only the
  deep `executor` binding uses `gpt-6-astra@high`.
- The hook emits a redacted `atomic`/`guarded`/`judgment`/`deep_judgment` route
  signal with trigger, purpose, escalation conditions, and exact typed dispatch
  fields; only high-confidence deep judgment opens Astra `executor`.
- Routine design, tool choice, interpretation, QA, and bounded implementation
  use Sol; ordinary tools and uncertainty stay on a cheap guarded Luna path.
- A Stop-hook continuation now respects `stop_hook_active` and clears its route
  marker instead of re-locking the session.
- The earlier active-role repair preserved Luna/Sol bindings; this spec now
  makes the Sol middle tier explicit for automatic implementation routing.
- `codex --strict-config doctor --summary` passed on Codex `0.154.0`; installer
  state v4 reports the previous integrated Plugin `1.8.0-rc.8`; rc.9 will
  replace the automatic middle tier with Sol before global reinstallation.

## Slice tracking

- [x] Route signal and anti-tunnel tests
- [x] Hook marker and one-shot escalation
- [x] Three-tier role bindings and policy synchronization
- [x] Local verification and active-home dry-run
- [x] Commit/release decision

## Verification boundary

Static route checks and typed-dispatch correlation prove the contract and installed
binding. They do not prove that a live model chooses the route for every natural
language task; that remains a separately authorized live probe.
