# TESTS — dispatch-verification (EARS acceptance)

## Gap A — headless boundary

- **AC-A1**: When a reader consults `README.md`, the docs shall state that
  delegation works only in interactive / app-server sessions and that
  `codex exec` exposes no `spawn_agent`.
- **AC-A2**: When a reader consults `docs/design.md`, the docs shall record the
  headless boundary as a known constraint, with the evidence that forcing
  `features.multi_agent` and `features.enable_fanout` in `codex exec` still
  yields no `spawn_agent`.

## Gap B — runtime proof

- **AC-B1**: When the e2e runs against a `codex app-server` that supports
  multi-agent, it shall spawn `scout` and assert the child's effective model is
  `gpt-5.6-luna` and effort is `low`.
- **AC-B2**: When app-server or the multi-agent surface is unavailable, the e2e
  shall report SKIPPED with the reason, and shall not fail.
- **AC-B3**: When the full e2e runs, each of the six roles shall be asserted to
  bind to the model and effort declared in its `~/.codex/agents/<role>.toml`.

## Gap B — enforcement

- **AC-B4**: While the optional `SubagentStart` guard is enabled, when a role is
  spawned whose effective model or effort differs from its TOML binding, the
  guard shall emit a mismatch warning (or block, per its configured mode).
- **AC-B5**: While the guard is enabled, when a role is spawned that matches its
  TOML binding, the guard shall stay silent and allow the spawn.
- **AC-B6**: When the guard is not installed, the default pilotfish-codex
  install behavior shall be unchanged (policy-only).

## Regression

- **AC-R1**: Existing `tests/test_policy.py` assertions shall continue to pass
  (template self-consistency is unaffected by this work).
