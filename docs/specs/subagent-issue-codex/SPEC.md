# SPEC — MultiAgentV2 Cost-Safe Role Dispatch (Codex analysis)

- Slug: `subagent-issue-codex`
- Status: Ready for approval
- Owner: Miyago
- Created: 2026-07-15
- Updated: 2026-07-15
- Analyst: Codex
- Coordination: Independent from `subagent-issue-claude`; this planning turn
  does not modify Claude's spec or `dispatch-verification`.
- Upstream: [openai/codex#31814](https://github.com/openai/codex/issues/31814),
  [#32031](https://github.com/openai/codex/issues/32031),
  [#31893](https://github.com/openai/codex/issues/31893),
  [PR #32749](https://github.com/openai/codex/pull/32749),
  [commit #32751](https://github.com/openai/codex/commit/92938d880eccbad1242a86a63f819f67780f68c0)

## Outcome

pilotfish-codex can preserve native named-role scheduling on affected
MultiAgentV2 releases. The supported adapter must expose spawn metadata outside
the reserved collaboration namespace:

```toml
[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
max_concurrent_threads_per_session = 4
```

The first two keys restore `agent_type`. The explicit concurrency value keeps
the cost boundary at four active threads including root, or at most three
simultaneous children. The block deliberately omits `enabled`: Sol can select
MultiAgentV2 remotely, while explicitly enabling V2 conflicts with the existing
`[agents].max_threads` fallback in Codex `0.144.4`.

This adapter is a compatibility seam, not a permanent API. Runtime dispatch
must fail closed when the seam is missing or no longer works.

## Problem

The project's architecture assigns model, reasoning effort, sandbox, and role
instructions through `~/.codex/agents/<role>.toml`. MultiAgentV2 defaults hide
`agent_type`, `model`, `reasoning_effort`, and `service_tier` from
`collaboration.spawn_agent`. An untyped child inherits the parent model, so a
planned Luna or Terra worker can silently run as Sol.

The current project template enables legacy `multi_agent` and configures
`[agents]`, but does not install a MultiAgentV2 adapter. Static tests prove the
role files are internally consistent; they do not prove the active runtime
loaded those roles or used their models.

## Verified evidence

### Runtime behavior

- Local Codex CLI is `0.144.4` with ChatGPT auth.
- `codex features list` reported `multi_agent_v2 = false`, while a new live
  turn recorded `multi_agent_version = "v2"`. Local feature state alone cannot
  identify the active collaboration surface.
- With `hide_spawn_agent_metadata = false` and
  `tool_namespace = "agents"`, a Terra/low parent emitted
  `agents.spawn_agent` with `agent_type = "scout"` and
  `fork_turns = "none"`.
- The child rollout recorded `model = "gpt-5.6-luna"` and effort `low`, matching
  the installed `scout.toml`. Named-role model routing is real end to end.
- The current root session, started before the config change, still exposes the
  reserved collaboration schema. Config changes require a new session.

### Upstream behavior

- Bare `hide_spawn_agent_metadata = false` is rejected under affected
  ChatGPT-auth releases because `collaboration.spawn_agent` must match a
  server-reserved schema. The one-key workaround is insufficient.
- Moving tools to `agents.*` avoids the reserved schema check and exposes the
  complete client-owned spawn schema.
- PR #32749 adds `expose_spawn_agent_model_overrides` in the `0.145` alpha
  line, but still hides `agent_type` and `service_tier` by default. Direct model
  overrides do not restore role instructions or sandbox bindings.
- Model overrides are restricted to compatible available presets and cannot be
  treated as arbitrary routing.
- MultiAgentV2 defaults to four active threads per session including root. This
  supports at most three concurrent children, not root plus four children.

### Project exposure

- `templates/config.snippet.toml` has no MultiAgentV2 table.
- The installer merge contract manages only legacy multi-agent and agent depth
  or thread keys.
- The policy says named roles own routing, but does not specify the V2
  `agents.spawn_agent` call shape or an untyped-spawn prohibition.
- The existing tests validate templates only; no opt-in live routing smoke test
  exists.
- Installed role files can drift from repository templates. Runtime checks must
  report that drift instead of using a stale successful install as proof that a
  fresh install is correct.

## Requirements

1. Fresh installs shall receive the three-key MultiAgentV2 compatibility block
   without forcing `multi_agent_v2.enabled = true`.
2. Named roles shall continue to own model, effort, sandbox, and developer
   instructions. Policy prose shall not duplicate model IDs.
3. Role spawns shall call `agents.spawn_agent` with `agent_type`, a valid
   lowercase `task_name`, and explicit bounded `fork_turns`.
4. The default fork shall be `"none"`. A positive turn count is allowed only
   when the brief depends on recent context. Full-history or implicit forks
   shall not be used for routed workers.
5. If the `agents` namespace, `agent_type`, installed role, or expected child
   model cannot be verified, native delegation shall stop for that task. It
   shall not fall back to an untyped child that inherits the parent model.
6. Active concurrency shall stay capped at four threads including root.
7. A manual, opt-in smoke test shall prove at least one named role resolves to
   its installed model and shall distinguish runtime proof from packaging
   proof.
8. Stable upstream support for a named-role selector shall trigger a retest and
   an explicit decision before removing the adapter.

## Architecture and decisions

### ADR-1 — Keep role TOMLs as the routing module

Agent TOMLs already hide four coupled concerns behind one role name: model,
effort, sandbox, and developer instructions. `agent_type` preserves that deep
module. Embedding per-role model IDs in policy or direct spawn calls would
duplicate routing data and lose non-model behavior.

### ADR-2 — Use the three-key V2 adapter at the machine layer

The machine config owns runtime topology and tool exposure. The adapter belongs
there, while policy owns call discipline and role TOMLs own execution behavior.
`max_concurrent_threads_per_session = 4` makes the root-plus-three-worker bound
explicit and protects against upstream default changes.

### ADR-3 — Fail closed before an inherited-model spawn

An untyped child is a cost and behavior ambiguity. When the named-role route is
unavailable, the orchestrator keeps tightly coupled work locally or reports the
compatibility failure. It never retries the same task through an untyped native
spawn.

### ADR-4 — Use bounded, context-light worker briefs

V2 defaults omitted `fork_turns` to full history. Routed workers shall receive
`fork_turns = "none"` plus a self-contained brief by default. This reduces input
duplication and avoids override restrictions on full-history forks.

### ADR-5 — Separate static packaging proof from live runtime proof

Static validation compares repository templates and install contracts. The live
smoke compares installed role TOMLs with child rollout metadata. A preflight
reports template/install drift before spending quota. One successful child is
not evidence that every packaged role matches the current install.

### ADR-6 — Prefer native scheduling over an external dispatcher

The two-key namespace route has proven native agent scheduling and preserves
Codex lifecycle events. A subprocess or MCP scheduler would duplicate session,
auth, concurrency, and cancellation behavior. It remains a contingency only if
upstream removes the client-owned namespace route without a named-role
replacement.

## Runtime smoke contract

The opt-in smoke shall:

1. Verify Codex version, ChatGPT auth, config keys, and installed `scout.toml`.
2. Compare the installed scout model and effort with the repository template.
3. Start a low-cost Terra/low parent with a self-contained routing probe.
4. Require `multi_agent_version = "v2"` and an `agents.spawn_agent` call using
   `agent_type = "scout"`, `fork_turns = "none"`, and a valid task name.
5. Resolve the exact child thread ID from the spawn result.
6. Assert the child rollout model and effort match the installed role.
7. Report `SKIPPED` for unavailable auth, model, or V2 tooling; report `FAILED`
   for a routing mismatch.
8. Avoid broad scans of `~/.codex/sessions`; inspect only session IDs created by
   the probe and state that the command spends real quota.

## Risks

- `tool_namespace` and metadata exposure are under-development config. A CLI or
  backend update may invalidate the adapter.
- Renaming the namespace may change first-party collaboration UX even when
  spawn, wait, relay, and rollout logging continue to work.
- Account model presets can change independently of repository templates.
- A smoke test using the user's existing install can produce a false green if
  it does not first detect template/install drift.
- Exact Sol pricing, automatic decomposition policy, and Terminal-Bench figures
  were not established by the cited issues and are excluded from acceptance.

## Non-goals

- Changing the seven-role roster or model distribution.
- Editing `subagent-issue-claude` or reconciling `dispatch-verification` during
  this independent planning task.
- Running the quota-spending smoke test automatically in CI.
- Treating alpha-only direct model overrides as the primary route.
- Implementing an external scheduler while native named-role routing works.

## Acceptance

`TESTS.md` defines the full acceptance contract. Completion requires the config
adapter, installer and static validation, policy fail-closed behavior, an
opt-in live smoke with exact child evidence, concurrency protection, docs, and
an upstream exit criterion.
