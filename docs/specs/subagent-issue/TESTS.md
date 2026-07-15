# TESTS — subagent-issue

## Config and installation

- **AC-C1**: When the packaged config is inspected, it shall contain
  `hide_spawn_agent_metadata = false`, `tool_namespace = "agents"`, and an
  explicit concurrency value in `[features.multi_agent_v2]`.
- **AC-C2**: When the packaged config is inspected, it shall not force
  `multi_agent_v2.enabled`; the default concurrency shall be 4.
- **AC-C3**: When metadata exposure is present without the `agents` namespace,
  validation shall fail with the reserved-schema reason.
- **AC-C4**: When concurrency is absent, non-integer, below 1, or above 8,
  validation shall fail. A valid value other than 4 shall warn and pass.
- **AC-C5**: When concurrency is 1, validation shall warn that child delegation
  is disabled. When it exceeds 4, validation shall warn about added cost.
- **AC-C6**: When the install merge is applied, unrelated feature keys and
  legacy `[agents]` settings shall remain unchanged.

## Orchestration policy

- **AC-P1**: When the affected adapter is active, a delegation shall call
  `agents.spawn_agent` with `agent_type`, `task_name`, and `fork_turns`.
- **AC-P2**: When no recent context is required, the call shall use
  `fork_turns = "none"` and a self-contained brief.
- **AC-P3**: When recent context is required, `fork_turns` shall be a bounded
  positive integer string. Omitted, `all`, and implicit full-history forks
  shall fail policy validation.
- **AC-P4**: When `agent_type` or the typed spawn surface is unavailable, the
  orchestrator shall stop delegation for that task and shall not retry an
  untyped child.
- **AC-P5**: When policy is rendered, model and effort identifiers shall remain
  in role TOMLs and shall not be duplicated in spawn instructions.
- **AC-P6**: When transport changes from adapter to native, only the isolated
  transport section and compatibility fixtures shall require namespace edits.

## Static proof

- **AC-S1**: When repository roles, config, and policy are valid, static
  validation shall pass without auth, runtime sessions, or model calls.
- **AC-S2**: When an installed role differs from its repository template, the
  smoke preflight shall report drift before spending quota.
- **AC-S3**: When normal tests run, they shall use bounded fixtures and shall
  not scan the user's Codex session store.

## Runtime proof

- **AC-R1**: When adapter smoke succeeds, the parent rollout shall report V2
  and an `agents.spawn_agent` call with `agent_type = "scout"` and
  `fork_turns = "none"`.
- **AC-R2**: When the child starts, its thread ID shall be taken from the parent
  `sub_agent_activity` event correlated to the spawn call and canonical path.
- **AC-R3**: When child correlation completes, its session shall name the exact
  parent ID and its model and effort shall match installed scout routing.
- **AC-R4**: When adapter routing is proven, the command shall report
  `ADAPTER_OK`; when adapter-free native routing is proven, it shall report
  `NATIVE_OK`.
- **AC-R5**: When V1 is active, the command shall report
  `SKIPPED: adapter_not_exercised`. Other unavailable prerequisites shall use
  explicit `SKIPPED` reason codes and shall not claim routing was verified.
- **AC-R6**: When namespace, role, correlation, model, effort, or schema differs
  from expectation, the command shall report `FAILED` and a cost-safety warning.
- **AC-R7**: When the smoke starts, it shall warn that it spends quota and shall
  inspect only sessions created by that invocation.

## Upgrade and migration

- **AC-U1**: When Codex is upgraded, config validation and the appropriate live
  capability probe shall rerun before routing is declared supported.
- **AC-U2**: When a stable release appears native-ready, version or feature-list
  output alone shall not remove the adapter.
- **AC-U3**: When adapter-free smoke returns `NATIVE_OK`, removal shall preserve
  role TOMLs, bounded context, typed-role semantics, and fail-closed behavior.
- **AC-U4**: When the new release changes concurrency support, migration shall
  make a separate evidence-backed decision for the concurrency key.
- **AC-U5**: When neither route succeeds, Pilotfish shall report `unsupported`
  and shall not substitute an untyped inherited-model spawn.

## Documentation and evidence

- **AC-D1**: When `dispatch-verification` is reconciled, it shall acknowledge
  proven headless V2 spawning and retain the unresolved runtime-enforcement gap.
- **AC-D2**: When docs describe install or migration, they shall require a new
  root session after config changes.
- **AC-E1**: Pricing, automatic decomposition counts, and benchmark figures not
  established by cited primary evidence shall not be acceptance inputs.
