# PROGRESS — dispatch-verification

## Phase 0 — Verification (done)

- [x] Confirm Codex `multi_agent` mechanism, subagent tooling, and TOML schema
      match pilotfish templates (Codex CLI 0.144.4).
- [x] Confirm `codex exec` exposes no `spawn_agent` even with flags forced.
- [x] Confirm `tests/test_policy.py` covers only template self-consistency, not
      runtime dispatch.
- [x] Record findings as this spec.

## Phase 1 — Gap A: document headless boundary

- [ ] A1 README note
- [ ] A2 design.md known-boundary + evidence
- [ ] A3 headless notice (or decision to skip)

## Phase 2 — Gap B: runtime proof

- [ ] B1 app-server multi-agent surface spike
- [ ] B2 single-role (`scout`) e2e with SKIP fallback
- [ ] B3 all-six-roles binding e2e

## Phase 3 — Gap B: optional enforcement

- [ ] B4 `SubagentStart` mismatch guard (opt-in)
- [ ] B5 guard fixture test
- [ ] B6 enable-the-guard docs
- [ ] design.md "Deliberately left out" row updated

## Notes

- Baseline plumbing (roles load, schema matches, per-role model binding) is
  sound and out of scope. This spec only closes the proof + boundary gaps.
- ADR-2 open risk: app-server JSON-RPC is experimental; e2e must skip cleanly
  when the surface is absent or changed.
