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
- [x] Fresh single-role receipt proof on 2026-07-20 with Codex `0.144.6`:
      `ADAPTER_OK`, redacted receipt v1 persisted.
- [x] Seven-role matrix on 2026-07-20: `ADAPTER_OK
      reason=matrix_verified_all_roles`; 7/7 explicit role bindings passed.
- [x] Post-install local smoke on 2026-07-20 with Codex `0.144.6`:
      `ADAPTER_OK`, receipt v1 persisted after replacing the active policy block.
- [x] Adapter-free probe safely returned
      `SKIPPED: native_schema_introspection_unavailable` before quota or
      spawning on Codex `0.144.4`/`0.144.6`.

## Deferred

- [ ] Task-class role-selection evaluation
- [ ] Stable pre-execution mismatch enforcement hook

## Evidence expansion batch

- [x] Receipt schema and redaction contract
- [x] Atomic JSON receipts and valid-no-spawn observation
- [x] Parameterized seven-role explicit binding matrix
- [x] Terminal event discovery gate; parser remains disabled because full
      terminal semantics were not established
- [x] Task-class selection and abstention evaluator
- [x] Documentation, release notes, and regression coverage

## Terminal schema discovery

- [x] Two same-version adapter probes completed on 2026-07-20.
- [x] Both parent and child rollouts expose stable `task_complete` events and
      final `response_item` messages containing `output_text`.
- [ ] Terminal success/failure/cancellation semantics remain unproven: the
      observed event shape has no explicit status enum or cancellation/error
      contract. No terminal parser is enabled from this evidence alone.

## Upstream blockers

- Native adapter-free proof remains
  `SKIPPED: native_schema_introspection_unavailable`.
- Pre-execution hard blocking requires a cancellable Codex dispatch hook.
- Authoritative effective-role and hidden capability metadata require a stable
  upstream runtime surface.
