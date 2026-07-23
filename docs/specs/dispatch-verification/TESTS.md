# TESTS — dispatch-verification

> Historical adapter acceptance record. These cases are excluded from the
> active native gate in `codex-native-multi-agent-migration`.

## Headless mechanism proof

- **AC-A1**: When the adapter E2E runs, `codex exec --json` shall expose one
  typed `agents.spawn_agent` call for `scout`.
- **AC-A2**: When the spawn starts, the verifier shall correlate its call ID and
  canonical task path to one exact child thread ID.
- **AC-A3**: When the child is inspected, its session shall name the exact
  parent and its model and effort shall match installed scout routing.
- **AC-A4**: When parent and child use the same model, verification shall fail
  with `inherited_parent_model`.

## Failure and boundary behavior

- **AC-B1**: When V1 is active, verification shall report
  `SKIPPED: adapter_not_exercised`.
- **AC-B2**: When safe adapter-free schema introspection is unavailable, the
  native probe shall report
  `SKIPPED: native_schema_introspection_unavailable` before quota or child
  creation.
- **AC-B3**: When namespace, role, context, parent relation, model, or effort
  differs, verification shall report `FAILED` and shall not infer success.
- **AC-B4**: When rollout lookup runs, it shall accept one exact thread-ID
  suffix in bounded day directories and reject fuzzy, duplicate, or out-of-root
  candidates.
- **AC-B5**: When normal tests run, they shall not call Codex, spend model quota,
  or scan the full user session store.

## Evidence expansion

- **AC-C1**: A green explicit-role E2E shall not be described as proof that the
  orchestrator chooses the correct role for every task class.
- **AC-C2**: When an opted-in adapter probe runs, it shall persist a versioned
  redacted JSON receipt without raw prompts, responses, rollout contents,
  developer instructions, absolute paths, or raw process output.
- **AC-C3**: Receipt paths shall be prepared before Codex execution; an
  unavailable or colliding destination shall fail before quota is spent, and a
  final receipt write failure shall never produce `ADAPTER_OK`.
- **AC-C4**: Receipts shall use only the bounded route-observation values
  `not_attempted`, `not_observed`, `requested_role_not_executed`,
  `typed_child_observed`, and `typed_child_verified`.
- **AC-C5**: A structurally valid parent rollout with no expected typed spawn
  shall report `FAILED: requested_role_not_executed`; malformed, missing,
  ambiguous, or unsafe evidence shall retain an evidence-failure result.
- **AC-C6**: `--role` shall accept only the seven packaged role names, and
  `--all-roles --matrix-yes` shall preflight all roles, run sequentially, stop
  on the first failure, and require every role to pass for aggregate success.
- **AC-C7**: Native mode shall still return
  `SKIPPED: native_schema_introspection_unavailable` before Codex, quota, or
  child creation, including when matrix mode is requested.
- **AC-C8**: Terminal proof shall remain disabled until two same-version live
  probes establish stable child terminal, result, error/cancellation, and close
  event semantics. No completion claim may be inferred from timeout or absence.
- **AC-C9**: The task-class evaluator shall validate exact case coverage,
  decision shape, role names, rationale, selection accuracy, and abstention
  accuracy without claiming runtime enforcement.
- **AC-C10**: Quota-spending probes, role matrices, and task evaluators shall
  remain manual-only and shall not run in CI.
