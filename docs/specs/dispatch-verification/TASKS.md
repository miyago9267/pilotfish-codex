# TASKS — dispatch-verification

> Historical adapter task record. Native implementation is owned by
> `codex-native-multi-agent-migration`.

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

- [x] C1. Add a task-class selection and abstention evaluator while explicitly
      documenting that it measures behavior and does not mechanically enforce
      every orchestrator judgment.
- [ ] C2. Reconsider a hard runtime hook only when Codex exposes a stable event
      containing the effective child role, model, and effort before execution.

## Evidence expansion batch

- [x] D1. Define and document receipt schema v1, redaction rules, bounded
      `route_observation` values, and receipt failure semantics.
- [x] D2. Add atomic redacted JSON receipts and precise valid-no-spawn
      post-hoc classification without claiming fallback executor identity.
- [x] D3. Parameterize explicit probes by packaged role and add the sequential
      seven-role matrix with preflight, per-role receipts, and aggregate result.
- [x] D4. Run two same-version live probes to discover terminal event schema;
      keep terminal proof disabled because explicit status, error/cancellation,
      and close semantics were not established.
- [x] D5. Add the versioned task-class corpus and offline
      selection/abstention evaluator with an opt-in live runner.
- [x] D6. Add synthetic receipt, role-matrix, terminal-gate, and evaluator
      regression tests; update user documentation and release notes.
- [x] D7. Keep native `NATIVE_OK`, pre-execution hard blocking, hidden
      effective-role metadata, and unsupported lifecycle guarantees deferred to
      upstream capability.
