# SPEC — MultiAgent V2 spawn_agent Metadata Regression (Claude analysis)

- Slug: `subagent-issue-claude`
- Status: Draft
- Owner: Miyago
- Created: 2026-07-15
- Analyst: Claude (kept separate from the parallel Codex self-analysis by
  request; supersedes overlapping findings in `dispatch-verification` where
  noted)
- Upstream: [openai/codex#31814](https://github.com/openai/codex/issues/31814)
  (canonical, open), [#32031](https://github.com/openai/codex/issues/32031)
  (open), [#31893](https://github.com/openai/codex/issues/31893) (closed as
  dup of #31814), [PR #32749](https://github.com/openai/codex/pull/32749)
  (merged 2026-07-13), [#32751](https://github.com/openai/codex/commit/92938d880eccbad1242a86a63f819f67780f68c0)

## Problem

GPT-5.6 Sol auto-selects the MultiAgent V2 collaboration surface regardless of
the local `multi_agent_v2` feature flag (verified: `codex features list` shows
`multi_agent_v2 = false` while a live Sol session runs the `/root` MAv2
developer prompt). MAv2 defaults `hide_spawn_agent_metadata = true`, which
strips `agent_type`, `model`, `reasoning_effort`, and `service_tier` from the
`spawn_agent` schema and tells the model all agents are "equally intelligent
and capable".

Impact on pilotfish-codex: the entire role-dispatch design depends on
`agent_type` selecting a `~/.codex/agents/<role>.toml` (which pins model,
effort, sandbox, and developer instructions). Under MAv2 defaults the
orchestrator cannot express `agent_type` at all, so every subagent silently
inherits Sol at the parent's effort. Nothing errors; routing is simply dead.

## Verified findings (2026-07-15, codex-cli 0.144.4, ChatGPT auth, gpt-5.6-sol/xhigh)

1. **Bare unhide fails under ChatGPT auth.** With only
   `[features.multi_agent_v2] hide_spawn_agent_metadata = false`, the backend
   rejects every request:
   `Invalid Value: 'tools'. Function 'collaboration.spawn_agent' is reserved
   for use by this model and must match the configured schema.` (HTTP 400).
   Confirms #32031; the widely shared one-line workaround is NOT sufficient.
2. **`tool_namespace = "agents"` unblocks it.** Renaming the tools out of the
   reserved `collaboration.*` namespace makes them ordinary client tools; the
   server no longer enforces the pinned schema. The model then sees
   `agents.spawn_agent` with the full property set: `task_name`, `message`,
   `agent_type`, `fork_turns`, `model`, `reasoning_effort`, `service_tier`.
3. **Dispatch is real end-to-end.** Spawning
   `agent_type='scout', fork_turns='none'` produced a child whose rollout
   `turn_context` records `"model":"gpt-5.6-luna"` (scout.toml binding), and
   the child self-reported `low` effort. Hard evidence, not model self-report
   alone.
4. **Headless delegation works under MAv2 + this config.** The proof above ran
   entirely through `codex exec`. This supersedes `dispatch-verification`
   Gap A ("codex exec exposes no spawn_agent"), which was verified before MAv2
   activation and under `features.multi_agent` v1 flags.
5. **Call-shape constraints** (router-enforced, worth encoding in policy
   prose): `fork_turns` must be the string `'none'`, `'all'`, or a positive
   integer string — omitted means full-history fork, which rejects
   model/agent_type overrides; `task_name` must match
   `[a-z0-9_]+`.
6. **Upstream fix is partial and not shipped to stable.** PR #32749 (in
   0.145.0-alpha.7, absent from the 0.144.4 binary — verified by strings)
   re-exposes only `model` + `reasoning_effort` via
   `expose_spawn_agent_model_overrides`; `agent_type` and `service_tier` stay
   hidden by default, so upstream alone does NOT restore pilotfish's named-role
   dispatch. #32751 additionally constrains child `model` to available presets.

## Decision (ADR)

**Adopt the two-key config block as the supported mitigation** and ship it in
the pilotfish install surface:

```toml
[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
```

Rationale: it is the only path today that restores `agent_type` (the field the
role design actually needs), it is proven end-to-end on ChatGPT auth, and the
upstream fix does not cover `agent_type`. Alternatives rejected: waiting for
upstream (indefinite, partial), pinning MAv1 (Sol's MAv2 selection is
server-side and not locally overridable), per-spawn `model` overrides without
roles (loses sandbox + developer_instructions bindings).

## Risks

- Both keys are undocumented fields of an under-development feature; any CLI
  update or server change can break or remove them. Re-verify after every
  `codex update` (see runtime smoke task).
- `tool_namespace` renames the tools out of the server's reserved collab
  feature; unknown side effects on server-side orchestration UX are possible.
  Observed working: spawn, wait, relay, close, child rollout logging.
- #32751-style preset validation may later reject models not in the account's
  preset list; pilotfish bindings (sol/terra/luna presets) currently conform.
- The MAv2 developer prompt still tells the model agents are equal; policy
  prose in `AGENTS.md` must keep carrying the role-selection contract.

## Goals

1. Ship the config block through templates + installer so fresh installs get
   working dispatch (G1).
2. Encode the MAv2 call-shape contract (`agent_type` required for role spawns,
   `fork_turns='none'` default, `task_name` charset) in orchestration prose
   (G2).
3. Provide a repeatable runtime smoke proof (spawn scout headless, assert
   child rollout model) so regressions surface on CLI updates (G3).
4. Reconcile `dispatch-verification`: mark Gap A superseded under MAv2 and
   record the new proof method for Gap B (G4).
5. Track upstream and define the exit criteria for dropping the workaround
   (G5).

## Non-goals

- Changing the role set, model bindings, or policy structure.
- Building the full SubagentStart enforcement guard (stays in
  `dispatch-verification` Phase 3).
- Supporting API-key auth paths (unverified here; ChatGPT auth is the target).
