# PROGRESS — subagent-issue-claude

## Phase 0 — Analysis & live verification (done)

- [x] Reproduce the ChatGPT-auth 400 with bare
      `hide_spawn_agent_metadata = false` (confirms #32031).
- [x] Verify `tool_namespace = "agents"` restores the full spawn schema
      including `agent_type`.
- [x] Prove end-to-end dispatch: headless spawn of `scout` ran on
      `gpt-5.6-luna` (child rollout `turn_context` evidence).
- [x] Verify the upstream fix (PR #32749 / 0.145.0-alpha.7) is absent from
      stable 0.144.4 and does not cover `agent_type`.
- [x] Record findings as this spec.

## Phase 1 — G1/G2: templates, installer, policy prose

- [ ] T1 config snippet block
- [ ] T2 installer merge contract
- [ ] T3 static validation
- [ ] T4 orchestration call-shape prose

## Phase 2 — G3: runtime smoke proof

- [ ] T5 headless smoke test with SKIP fallback
- [ ] T6 re-verify trigger documented

## Phase 3 — G4/G5: reconciliation & upstream watch

- [ ] T7 dispatch-verification updates
- [ ] T8 upstream exit criteria
