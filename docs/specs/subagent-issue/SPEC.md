# SPEC — Cost-safe named-role dispatch across MultiAgentV2

> Historical adapter baseline. The active native contract is
> `codex-native-multi-agent-migration`; this document is excluded from its gate.

- Slug: `subagent-issue`
- Status: Complete
- Owner: Miyago
- Created: 2026-07-15
- Updated: 2026-07-16
- Supersedes: `subagent-issue-claude`, `subagent-issue-codex`
- Upstream: [openai/codex#31814](https://github.com/openai/codex/issues/31814),
  [#32031](https://github.com/openai/codex/issues/32031),
  [#31893](https://github.com/openai/codex/issues/31893),
  [PR #32749](https://github.com/openai/codex/pull/32749), and
  [commit 92938d8](https://github.com/openai/codex/commit/92938d880eccbad1242a86a63f819f67780f68c0)

## Outcome

Pilotfish keeps model routing in named agent TOMLs and can safely delegate on
affected MultiAgentV2 releases. The temporary machine adapter is:

```toml
[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
max_concurrent_threads_per_session = 4
```

The adapter restores `agent_type` outside the server-reserved collaboration
namespace. A routed `scout` therefore loads its Luna model, effort, sandbox,
and role instructions instead of silently inheriting a Sol parent.

The implementation also provides a live capability check and an explicit exit
path. When stable Codex exposes native named-role spawning, Pilotfish can remove
the two schema workaround keys without changing the role TOMLs or the semantic
orchestration contract.

## Problem

Pilotfish routes work by role through `~/.codex/agents/<role>.toml`.
MultiAgentV2 currently hides `agent_type`, `model`, `reasoning_effort`, and
`service_tier` from its default `spawn_agent` schema. An untyped child inherits
the parent model. A Sol orchestrator can consequently fan out more Sol workers
while appearing to follow the project's Luna/Terra policy.

The repository packages the roles and validates their TOML, but it does not
currently:

- install the proven MultiAgentV2 adapter;
- require a typed, context-bounded spawn call;
- fail closed when named-role routing is unavailable;
- prove that a live child used the installed role model; or
- distinguish a temporary adapter from stable upstream support.

## Verified evidence

### Affected stable release

- Local Codex `0.144.4` uses ChatGPT auth.
- `codex features list` reported `multi_agent_v2 = false` while a live rollout
  recorded `multi_agent_version = "v2"`. Feature-list output alone cannot
  select the compatibility state.
- Bare `hide_spawn_agent_metadata = false` failed because
  `collaboration.spawn_agent` is server-reserved and its schema must match.
- Adding `tool_namespace = "agents"` exposed the complete client-owned spawn
  schema, including `agent_type` and bounded `fork_turns`.
- Configuration changes did not alter an already-running root session. A new
  Codex session is required after install or migration.

### End-to-end routing

- A Terra/low parent called `agents.spawn_agent` with
  `agent_type = "scout"` and `fork_turns = "none"`; its child rollout recorded
  Luna/low.
- A Sol/xhigh parent, session
  `019f6631-5b42-73e3-a936-d5fa353d4656`, used the same typed call. The exact
  child session `019f6631-9195-7541-a7e8-8d3912499c25` recorded Luna/low.
- The parent rollout's `sub_agent_activity` event carries the child thread ID,
  spawn call ID, and canonical agent path. This gives the smoke test an exact
  parent-to-child correlation without mtime guessing or a full session scan.
- Headless `codex exec` can exercise MultiAgentV2 and produce the rollout
  evidence needed by a manual smoke test.

### Configuration and upstream limits

- Codex `0.144.4` source defaults
  `max_concurrent_threads_per_session` to 4. The value includes root, so the
  default permits at most three concurrent children.
- The same source rejects `agents.max_threads` when locally enabling
  `features.multi_agent_v2`. Pilotfish therefore omits `enabled` and lets the
  active Codex surface decide V1 versus V2.
- That source enforces only a concurrency lower bound of 1. Pilotfish adopts
  `1..8` as its own cost-safety policy, recommends 4, and warns on a non-default
  value instead of treating 4 as an invariant.
- PR #32749 adds direct model and effort overrides in the `0.145` alpha line,
  but does not expose `agent_type` by default. Direct model selection does not
  restore role instructions, sandbox settings, or a complete named-role route.

### Upstream tracking (agent_type native support)

Status as of 2026-07-16; re-check on every Codex CLI upgrade alongside
`verify_dispatch.py --live`.

- Issue openai/codex#31814 (Sol cannot specify subagent models) was closed by
  jif-oai on 2026-07-15. His
  [follow-up comment](https://github.com/openai/codex/issues/31814#issuecomment-4981436324)
  commits to a dedicated sub-agent configuration file in a follow-up PR and
  warns that explicit routing may cost global performance versus letting 5.6
  models self-manage subagents. The comment names no PR, release, or
  `agent_type` schema contract — treat it as an implementation signal, not
  proof of native named-role support.
- PR #32751 (merged 2026-07-13) restricts spawned-agent models to the active
  backend — upstream now owns part of the guard our service-tier hook covers.
- PR #33550 (merged 2026-07-16) unifies multi-agent settings under `[agents]`:
  adds `agents.enabled` as user override, renames the limit key to
  `agents.max_concurrent_threads_per_session` with `agents.max_threads` kept as
  an alias (the 0.144.4 rejection noted above no longer applies there), and adds
  **reserved** subagent model, reasoning-effort, and agent-type settings to the
  config surface, persisted in config locks. Reserved means present in schema
  but not yet an active native named-role selector.
- Migration trigger remains the native migration contract below: act when a
  stable release *activates* the reserved `agents` agent-type settings, not on
  schema presence alone.

## Requirements

1. Fresh installs shall receive the three-key adapter without setting
   `multi_agent_v2.enabled` or overwriting unrelated TOML.
2. `max_concurrent_threads_per_session` shall be an explicit integer from 1 to
   8. The packaged default shall be 4; other valid values shall warn.
3. Named agent TOMLs shall remain the only source for model, effort, sandbox,
   and developer instructions.
4. A delegation shall use the active named-role spawn surface with
   `agent_type`, a valid `task_name`, and explicit bounded `fork_turns`.
5. The affected-release adapter shall use `agents.spawn_agent`. Namespace-
   specific policy shall be isolated so native migration changes one transport
   section rather than the routing architecture.
6. The default fork shall be `"none"`. Only positive integer strings from
   `"1"` through `"3"` are permitted when the brief requires recent turns.
   Implicit, larger, and full-history forks shall not be used for routed
   workers.
7. If the namespace, `agent_type`, role file, or child routing cannot be
   verified, delegation shall fail closed. It shall never retry as an untyped
   child.
8. Static tests shall prove packaging and policy. A manual, quota-spending
   smoke shall separately prove live routing.
9. A stable native named-role surface shall trigger capability-based migration,
   not version-only auto-removal of the adapter.
10. Existing dispatch-verification documentation shall be reconciled with the
    proven headless V2 path and rollout proof method.

## Architecture

### Stable routing core

The architecture has three ownership boundaries:

| Layer | Owns | Must remain stable |
| --- | --- | --- |
| Role TOMLs | model, effort, sandbox, instructions | Yes |
| Orchestration policy | task choice, typed role, context budget, fail-closed rule | Yes |
| Compatibility adapter | active tool namespace and temporary V2 config | No |

The role TOMLs are the deep module. A role name encapsulates all execution
behavior; model identifiers shall not be duplicated in policy or spawn calls.
The adapter is intentionally shallow and replaceable.

### Compatibility states

Runtime support is determined from the live schema and smoke evidence:

| State | Evidence | Action |
| --- | --- | --- |
| `adapter-required` | Native surface lacks `agent_type`; `agents.*` typed spawn passes | Install adapter and report `ADAPTER_OK` |
| `native-ready` | Stable native surface exposes `agent_type`; adapter-free smoke passes | Remove schema workaround and report `NATIVE_OK` |
| `unsupported` | Neither route can prove named-role child routing | Fail closed and report `FAILED` |
| `not-exercised` | V1 is active or auth/model/tooling is unavailable | Report `SKIPPED` with an exact reason |

`codex features list` and version comparison are hints only. They cannot produce
`ADAPTER_OK` or `NATIVE_OK` without matching live evidence.

### Current adapter contract

The current transport section selects `agents.spawn_agent`. Each call must
include `agent_type`, `task_name`, and `fork_turns`. Role TOMLs supply execution
settings. If the schema rejects the typed call, the orchestrator handles tightly
coupled work locally or reports the compatibility failure.

The installer owns the three adapter keys as a TOML-aware merge contract. It
does not force `enabled`, delete legacy `[agents]` fallback settings, or modify
unrelated feature keys. The validator rejects partial or unsafe adapter shapes
and warns when concurrency differs from the recommended value.

### Native migration contract

Adapter removal requires all of the following:

1. A stable Codex release exposes a supported native named-role selector.
2. An isolated adapter-free probe proves the native call includes `agent_type`.
3. The exact child rollout matches the installed role's model and effort.
4. Static and live tests pass after removing `hide_spawn_agent_metadata` and
   `tool_namespace`.
5. The release's concurrency configuration is revalidated before deciding
   whether to retain or replace `max_concurrent_threads_per_session`.

Migration changes only the machine adapter and the isolated transport section.
Role TOMLs, task delegation rules, bounded context, and fail-closed behavior
remain unchanged. The prior adapter remains documented as a rollback for one
supported release cycle.

### External scheduler boundary

An MCP or subprocess scheduler would duplicate Codex authentication, lifecycle,
cancellation, and concurrency behavior. It is a contingency only if both the
client-owned adapter and stable native named-role spawning are unavailable.
This spec does not implement that contingency.

## Runtime smoke contract

The opt-in smoke shall:

1. Preflight Codex version, auth, config state, concurrency, and installed
   `scout.toml`.
2. Compare installed scout routing with `templates/agents/scout.toml` before
   spending quota.
3. Start a low-cost Terra/low parent with a self-contained probe.
4. Assert the active MultiAgent version and the expected spawn namespace,
   `agent_type = "scout"`, `fork_turns = "none"`, and valid task name.
5. Correlate the spawn call to the exact `sub_agent_activity.agent_thread_id`,
   then verify that child's `session_meta.parent_thread_id`.
6. Assert the child `turn_context` model and effort match the installed role.
7. Return `ADAPTER_OK`, `NATIVE_OK`, `SKIPPED`, or `FAILED` with a stable reason
   code. V1 shall return `SKIPPED: adapter_not_exercised`.
8. Warn before spending quota and inspect only the parent and child sessions
   created by the invocation.

Normal tests shall use fixtures and shall never call a model or broadly scan
`~/.codex/sessions`.

## Risks

- `tool_namespace` and spawn metadata exposure are under-development settings
  and can change without a stable compatibility guarantee.
- A valid config does not prove the backend exposed the expected schema.
- Installed role files and account model presets can drift independently of
  repository templates.
- Concurrency values above 4 increase cost exposure; values below 2 prevent a
  child spawn even though they remain syntactically valid.
- Alpha direct-model overrides can create false confidence while bypassing role
  instructions and sandbox settings.

## Non-goals

- Changing the seven-role roster or its model distribution.
- Running a quota-spending smoke automatically in CI.
- Selecting a compatibility state solely from a version string.
- Treating direct model overrides as equivalent to named roles.
- Implementing an external scheduler while the native adapter works.
- Using unverified pricing, fan-out counts, or benchmark claims as acceptance
  evidence.

## Acceptance

`TESTS.md` is the normative acceptance contract. Completion requires the
adapter and installer merge, static validation, transport-isolated typed policy,
fail-closed behavior, exact-child live proof, dispatch-verification
reconciliation, and a tested native migration path.
