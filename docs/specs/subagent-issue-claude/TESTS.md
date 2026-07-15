# TESTS — subagent-issue-claude (EARS acceptance)

## G1 — config block shipped

- **AC-1**: When a user merges `templates/config.snippet.toml` into
  `~/.codex/config.toml`, the result shall contain
  `[features.multi_agent_v2]` with `hide_spawn_agent_metadata = false` and
  `tool_namespace = "agents"`.
- **AC-2**: When static validation runs, it shall fail if either key is
  missing from the snippet or carries a different value.

## G2 — call-shape contract

- **AC-3**: When a reader consults the orchestration policy, it shall state
  that role spawns pass `agent_type` and `fork_turns='none'`, that omitted
  `fork_turns` forks full history and rejects overrides, and that `task_name`
  is limited to lowercase letters, digits, and underscores.

## G3 — runtime smoke proof

- **AC-4**: When the smoke test runs with spawn tooling available, it shall
  spawn `scout` headless and assert the child rollout `turn_context.model` is
  `gpt-5.6-luna`.
- **AC-5**: When spawn tooling or auth is unavailable, the smoke test shall
  report SKIPPED with the reason and shall not fail.

## G4 — spec reconciliation

- **AC-6**: When a reader consults `dispatch-verification/SPEC.md`, Gap A
  shall be marked superseded under MAv2 with the 2026-07-15 evidence, and
  Gap B shall reference the rollout-based proof method.

## G5 — upstream exit

- **AC-7**: When a stable Codex release exposes `agent_type` in the
  spawn-agent schema by default, the workaround shall be re-tested removed and
  the decision recorded in this spec.
