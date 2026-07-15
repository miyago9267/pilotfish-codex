# TESTS — subagent-issue-codex (EARS acceptance)

## Config and installation

- **AC-C1**: When the config snippet is validated, it shall contain
  `hide_spawn_agent_metadata = false`, `tool_namespace = "agents"`, and
  `max_concurrent_threads_per_session = 4` in
  `[features.multi_agent_v2]`.
- **AC-C2**: When the V2 table contains `enabled = true`, validation shall fail
  because the project retains the legacy `[agents]` fallback.
- **AC-C3**: When metadata exposure is present without the `agents` namespace,
  validation shall fail with the reserved-schema reason.
- **AC-C4**: When the installer merge is applied to a config with unrelated
  feature keys, those keys shall remain unchanged.
- **AC-C5**: When the configured concurrency is inspected, it shall cap active
  threads at four including root.

## Role-routing policy

- **AC-P1**: When the orchestrator delegates to a named role, it shall call
  `agents.spawn_agent` with `agent_type` and shall not duplicate the role's
  model or effort in policy.
- **AC-P2**: When no recent context is required, the spawn shall use
  `fork_turns = "none"` and a self-contained brief.
- **AC-P3**: When recent context is required, `fork_turns` shall be a bounded
  positive integer string; implicit or full-history forks shall not be used.
- **AC-P4**: When `agent_type` or the `agents` namespace is unavailable, the
  orchestrator shall stop native delegation for that task and shall not retry
  with an untyped child.
- **AC-P5**: When `task_name` is generated, it shall match `[a-z0-9_]+`.

## Static validation

- **AC-S1**: When repository role templates are valid, static validation shall
  pass without accessing user auth or runtime sessions.
- **AC-S2**: When an installed role differs from its repository template, the
  smoke preflight shall report drift before launching a model call.
- **AC-S3**: When normal tests run, no test shall spend model quota or scan the
  user's entire Codex session store.

## Runtime smoke

- **AC-R1**: When the optional smoke runs successfully, the parent rollout shall
  report MultiAgentV2 and an `agents.spawn_agent` call with
  `agent_type = "scout"` and `fork_turns = "none"`.
- **AC-R2**: When the spawn succeeds, the child thread ID shall come from the
  spawn result rather than filename or timestamp guessing.
- **AC-R3**: When the child completes, its rollout model and effort shall match
  the installed and repository scout bindings.
- **AC-R4**: When auth, Terra, Luna, or V2 tooling is unavailable, the command
  shall report `SKIPPED` with the exact reason and shall not claim routing was
  verified.
- **AC-R5**: When namespace, role, model, effort, or concurrency mismatches, the
  command shall report `FAILED` and a cost-safety warning.
- **AC-R6**: When the smoke starts, it shall warn that it spends real quota and
  shall inspect only the parent and child sessions created by that invocation.

## Upgrade and regression

- **AC-U1**: When Codex is upgraded, the documented process shall rerun config
  validation and the optional live smoke before declaring routing supported.
- **AC-U2**: When a stable release exposes a supported named-role selector, the
  adapter shall be tested removed before any template change is accepted.
- **AC-U3**: Existing policy, template, and validator tests shall continue to
  pass after the implementation.
- **AC-U4**: Claude's spec and `dispatch-verification` shall remain unchanged by
  the Codex planning deliverable.

## Evidence exclusions

- **AC-E1**: Pricing, automatic decomposition counts, and benchmark claims not
  backed by the cited primary sources shall not be used as acceptance evidence.
