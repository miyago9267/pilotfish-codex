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

- [x] `ADAPTER_OK` on 2026-07-16: Terra parent
      `019f66b4-20c3-7930-8263-102ad9b09b8f` spawned Luna child
      `019f66b4-3437-7642-aa8e-f11311e53187` through `scout`.
- [x] Adapter-free probe safely returned
      `SKIPPED: native_schema_introspection_unavailable` before quota or
      spawning on Codex `0.144.4`.

## Deferred

- [ ] Task-class role-selection evaluation
- [ ] Stable pre-execution mismatch enforcement hook
