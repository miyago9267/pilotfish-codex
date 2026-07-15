# TESTS — dispatch-verification

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

## Evidence boundary

- **AC-C1**: A green explicit-role E2E shall not be described as proof that the
  orchestrator chooses the correct role for every task class.
