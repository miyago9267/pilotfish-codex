# PROGRESS — subagent-issue-codex

## Phase 0 — Analysis and planning (done)

- [x] Confirm local Codex `0.144.4`, ChatGPT auth, and active MultiAgentV2 turn.
- [x] Confirm bare metadata exposure conflicts with the reserved collaboration
      schema on affected releases.
- [x] Confirm `tool_namespace = "agents"` exposes named-role routing.
- [x] Prove Terra/low parent to Luna/low scout dispatch using parent and child
      rollout metadata.
- [x] Confirm the upstream `0.145` alpha fix exposes model/effort but does not
      restore `agent_type` by default.
- [x] Confirm the four-thread V2 limit includes root.
- [x] Inspect current template, installer, policy, and static-test exposure.
- [x] Define config, policy, fail-closed, smoke, concurrency, and exit contracts.
- [x] Record the Codex-only plan under `subagent-issue-codex`.

## Phase 1 — Config and install contract

- [ ] C1-C2 config block and rationale
- [ ] C3 installer merge contract
- [ ] C4-C5 validation and fixtures

## Phase 2 — Orchestration policy

- [ ] P1-P3 namespace, role, fork, and fail-closed rules
- [ ] P4 policy regression tests

## Phase 3 — Opt-in runtime proof

- [ ] R1-R5 smoke implementation and verdicts
- [ ] R6 parser and fixture tests

## Phase 4 — Documentation and exit criteria

- [ ] D1-D4 README/design/upgrade contract
- [ ] D5 final targeted verification

## Coordination

- [x] Restore Codex's uncommitted edits to `dispatch-verification` before
      creating this independent spec.
- [x] Leave `subagent-issue-claude` unchanged.
- [ ] Miyago approves this spec or chooses a reconciled implementation source.

## Decisions

- Role TOMLs remain the only model/effort/sandbox/instruction routing source.
- The supported stable adapter uses metadata exposure plus the `agents`
  namespace and an explicit root-inclusive concurrency limit of four.
- Native delegation fails closed when named-role routing cannot be verified.
- Live smoke is manual and quota-spending; normal tests remain offline.
- An external scheduler is deferred while native named-role dispatch works.
