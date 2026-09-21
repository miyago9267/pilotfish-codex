# PROGRESS — automatic-model-routing

## Status

- Overall: implemented and published locally; live model selection unverified
- Current phase: post-install acceptance
- Last updated: 2026-09-21

## Evidence

- The source role manifest binds `executor` and `verifier` to `gpt-6-astra@high`;
  `mech-executor` and `scout` remain cheap Luna roles.
- The hook emits a redacted `atomic`/`judgment` route signal and retries one
  missing typed `executor` escalation without asking the user to name a role.
- The earlier active-role repair preserved Luna/Sol bindings; this spec supersedes
  that decision for the new routing surface.
- `codex --strict-config doctor --summary` passed on Codex `0.154.0`; installer
  state v4 reports integrated Plugin `1.8.0-rc.6` and both active homes expose
  the Astra strong bindings.

## Slice tracking

- [x] Route signal and anti-tunnel tests
- [x] Hook marker and one-shot escalation
- [x] Strong role bindings and policy synchronization
- [x] Local verification and active-home dry-run
- [x] Commit/release decision

## Verification boundary

Static route checks and typed-dispatch correlation prove the contract and installed
binding. They do not prove that a live model chooses the route for every natural
language task; that remains a separately authorized live probe.
