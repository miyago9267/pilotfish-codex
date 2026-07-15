# SPEC — Dispatch verification and enforcement

- Slug: `dispatch-verification`
- Status: Reconciled
- Owner: Miyago
- Created: 2026-07-15
- Updated: 2026-07-15
- Implementation source: `docs/specs/subagent-issue/`
- Discussion: [#2 — Does role-based model dispatch actually fire?](https://github.com/miyago9267/pilotfish-codex/discussions/2)

## Reconciled outcome

The earlier conclusion that `codex exec` cannot spawn subagents was true for
the probed legacy surface and is false for an affected MultiAgentV2 turn with
the compatibility adapter. `codex exec --json` now provides the scriptable E2E
surface; an app-server spike is unnecessary for mechanism proof.

`install/verify_dispatch.py --live --yes` proves one exact named-role route:

1. a Terra/low parent calls typed `agents.spawn_agent` for `scout`;
2. the parent `sub_agent_activity` event supplies the exact child thread ID;
3. the child session names the exact parent; and
4. the child rollout reports the installed Luna/low binding and differs from
   the parent model.

The proof is manual and quota-spending. Offline fixtures cover parser,
correlation, namespace, role, context, model, effort, and path boundaries.

## Remaining boundary

The E2E proves that explicit named-role routing works. It does not prove that an
orchestrator will choose the correct role for every task class. That behavioral
judgment remains policy-governed and is outside the mechanism verifier.

An optional `SubagentStart` guard is no longer part of this implementation.
Rollout evidence can detect a completed mismatch, while the temporary policy
and runtime verifier fail closed before an untyped fallback. A future hard
runtime guard requires a separate spec if Codex exposes a stable enforcement
hook with the effective child binding.

## Decisions

- Use headless `codex exec --json`, not experimental app-server JSON-RPC.
- Prove the installed `scout` binding first; do not infer all seven roles from
  one child.
- Treat feature-list and version output as hints; rollout evidence is
  authoritative.
- Return `SKIPPED` for an unexercised or unavailable surface and `FAILED` for a
  routing mismatch.
- Keep normal tests offline and bounded to synthetic JSONL evidence.

## Acceptance

`TESTS.md` records the reconciled mechanism-proof contract. Broader task-class
selection evaluation remains a future project.
