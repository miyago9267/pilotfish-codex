# PROGRESS — dispatch-verification

## Reconciliation (done)

- [x] Retire the outdated claim that all `codex exec` sessions lack subagents.
- [x] Confirm affected MultiAgentV2 headless sessions can spawn through the
      `agents` compatibility namespace.
- [x] Replace the proposed app-server spike with `codex exec --json` evidence.
- [x] Implement exact parent/spawn/child rollout correlation.
- [x] Add offline fail-closed and path-boundary tests.
- [x] Record explicit-role mechanism proof separately from task-class judgment.
- [x] Move implementation and upstream migration ownership to
      `docs/specs/subagent-issue/`.

## Live result

- [x] `ADAPTER_OK` on 2026-07-15: Terra parent
      `019f6676-164b-7d61-ab96-9e7e3ef316f5` spawned Luna child
      `019f6676-32d0-7742-ae4d-d3b6c14f7c41` through `scout`.
- [x] Adapter-free probe safely returned
      `SKIPPED: native_schema_introspection_unavailable` before quota or
      spawning on Codex `0.144.4`.

## Deferred

- [ ] Task-class role-selection evaluation
- [ ] Stable pre-execution mismatch enforcement hook
