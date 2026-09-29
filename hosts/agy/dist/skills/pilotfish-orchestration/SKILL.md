---
name: pilotfish-orchestration
description: Pilotfish orchestration for agy - routing, Plan and approval gate, dispatch to named roles, fresh verification, recovery. Load before deciding delegation, review, or approval on large, ambiguous, architectural, risky, cross-surface, or plan-first work.
---

# Pilotfish orchestration (agy)

Main-session policy. Roles (`scout`, `plan-verifier`, `security-reviewer`,
`mech-executor`, `executor`, `verifier`, `security-executor`) ignore this skill
and do their task without delegating.

## Lifecycle

| Phase | Gate | Delegation |
|---|---|---|
| Discovery | Stabilize the question, allowed scope, evidence format, and stop condition. Read-only. | `scout` on disjoint evidence surfaces |
| Plan | Main session writes one Plan: outcome, non-goals, scope, program envelope, independent slices. | Fresh `plan-verifier` on the envelope, then the next executable slice |
| Approval | `READY` on every required unit, then present the Plan and wait for Miyago's explicit approval. | Read-only clarification only |
| Execution | Approved contract with scope, exclusive ownership, constraints, done criteria, integration, verification. | `mech-executor`, `executor`, or `security-executor` |
| Verification | Integrated result with an exact claim and concrete acceptance. | Fresh `verifier` |

If Miyago has switched agy into `/plan` mode, stay there until approval. If
not, behave as if you were: discovery is read-only and the only thing you write
before approval is the Plan itself (in the reply or a Plan artifact).

## Plan gate

- Brief `plan-verifier` with a `## Target readiness unit` block (`- ID:`,
  `- Kind:` `program envelope` or `execution slice`), the full Plan text, and
  evidence paths.
- `READY` is the bare word. `REVISE` carries one or more blocks with `Blocker:`,
  `Evidence:`, `Minimum revision:`, `Acceptance check:`. Anything else is a
  protocol failure, not a Plan judgment; re-invoke.
- On `REVISE`, materially revise and send the unit to a fresh `plan-verifier`.
  After two automatic `REVISE` on the same unit, pause and ask Miyago.
- Large work: review the envelope, then only the next executable slice. Later
  slices keep stable IDs, outcomes, and prerequisites until they become current.
- No source writes before explicit approval in a later turn. A broad request,
  "just start", or auto-approved permissions do not waive this.

## Security

Keep security basic and proportionate; the goal is to avoid tunnel vision, not
to shrink execution capability.

- For work touching authn/authz, secrets, crypto, input validation at trust
  boundaries, or dependency vulnerabilities, run `security-reviewer` before the
  first `plan-verifier` on the affected unit, and carry its findings and
  dispositions into the Plan. Tell `plan-verifier` you did so.
- Brief `security-reviewer` to look at adjacent entry points and side effects,
  not only the named boundary.
- Implement approved security-sensitive slices through `security-executor`. If
  it fails twice, re-scope or ask Miyago; do not quietly take the slice over.
- Ordinary work that merely sits near a security surface does not need this
  track; use `executor` and have `verifier` probe the obvious abuse case.

## Dispatch

Before each `invoke_subagent`, name the phase and apply a brake: do not fan out
when workers depend on evolving shared evidence, write ownership overlaps, no
integration owner exists, or coordination costs more than it saves.

Use the smallest shape: direct work for small or tightly coupled tasks, one
worker for a bounded side task, parallel workers only for independent,
low-overlap streams. Default routing:

- Unknown file or symbol, or broad cross-file discovery -> `scout`.
- Fully specified multi-file mechanical work -> `mech-executor`.
- Bounded non-security implementation needing judgment -> `executor`.

Keep a single unknown bug's root-cause discovery and first minimal fix in the
main session when they share one reasoning chain.

Brief each worker once with goal, constraints, done criteria, relevant paths,
rationale, output format, and verification expectation. Invoke named roles by
type name only; their tier and tools come from the definitions. Start with the
cheapest eligible role. After two failed attempts, change the task boundary or
move up one role. Sanity-check any single scout fact that carries a decision.

## Parallelism and long work

- `invoke_subagent` accepts several entries to run concurrently. Give writing
  workers exclusive files, or workspace mode `branch` / `share` for isolation;
  read-only workers use `inherit`.
- Collect every worker result before dependent work or the final answer.
  Integrate isolated workspaces before reporting; uncollected branches are lost
  work.
- Long-running commands belong to the main session. Leaves return the exact
  command, working directory, environment, inputs, and completion criterion.

## Verification adjudication

Never swap roles: `plan-verifier` judges Plan readiness (`READY` / `REVISE`);
`verifier` tests a completed claim (`CONFIRMED` / `REFUTED` / `INCONCLUSIVE`).
Neither writes the Plan or fixes findings.

The main session makes the final call. Re-check each finding for
reproducibility, whether this change introduced it, relevance to the exact
claim, priority, and confidence.

- P0 freezes the slice and pauses for Miyago.
- P1, and any P2 regression this change introduced, gets fixed inside approved
  scope or paused.
- Other P2: fix only when bounded and in scope; otherwise defer with a reason
  and narrow the claim.
- P3/P4: report, no dedicated fix loop.
- `INCONCLUSIVE`: one retry only after evidence, environment, or contract
  materially changes.

Blocking P1/P2 recovery shares at most five fix/reverify passes, each with a
material change; never reverify an identical candidate. After five, mark the
slice `PAUSED_VERIFICATION` and continue only unrelated safe slices.

## Long autonomous runs

Before likely long unattended work, announce `AUTO` or `ASK`. `AUTO` covers
approved-scope reversible work only; it grants no commit, push, release,
credential, destructive, external-mutation, or scope-expansion authority. With
`ASK`, or when a Miyago decision is needed, end the turn with
`PAUSED_NEEDS_USER`, one question, choices, and a recommendation. Only the main
session asks.

The final report separates confirmed, fixed, deferred, paused, and unrun
checks, narrowed claims, and external actions not taken.
