# TASKS — dispatch-verification

Implementation ownership moved to `docs/specs/subagent-issue/`.

## Reconciled mechanism proof

- [x] A1. Correct the outdated interactive-only `codex exec` conclusion.
- [x] A2. Document the MultiAgentV2 adapter and headless proof path in README
      and design docs.
- [x] A3. Add explicit static and live verification commands.
- [x] B1. Use `codex exec --json` rather than an app-server spike.
- [x] B2. Implement exact parent/spawn/child rollout correlation.
- [x] B3. Assert installed scout model and effort and require the child model to
      differ from the parent.
- [x] B4. Add offline parser and boundary tests with no model calls.
- [x] B5. Define stable `ADAPTER_OK`, `NATIVE_OK`, `SKIPPED`, and `FAILED`
      verdicts.

## Deferred behavior evaluation

- [ ] C1. Design a task-class evaluation only if Pilotfish later claims that
      every orchestrator judgment is mechanically enforced.
- [ ] C2. Reconsider a hard runtime hook only when Codex exposes a stable event
      containing the effective child role, model, and effort before execution.
