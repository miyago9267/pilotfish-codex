# Pilotfish workflow extensions

Ported from pilotfish-codex 1.8.1 and adapted to Claude Code. These rules
extend [orchestration-policy.md](orchestration-policy.md). When a rule here
conflicts with that policy, the policy wins: report the conflict to the user
instead of choosing silently. None of these rules expands approval, security,
destructive, external, release, or spending authority.

## Outcome-level continuation

The execution unit is the requested user-visible outcome, not one command,
one tool call, or one checklist item. Track three internal route fields:

- `execution_scope`: `step`, `slice`, or `outcome`.
- `continuation_mode`: `attended_until_acceptance` or `explicit_unattended`.
- `stop_condition`: `named_boundary`, `acceptance`, `material_gate`, or
  `decision`.

For a clear `execute` request, default to `execution_scope=outcome` and
`continuation_mode=attended_until_acceptance`. Continue through the necessary
commands, phases, role handoffs, and verification until acceptance evidence is
sufficient. Reporting a phase boundary is progress reporting, not a request
for approval or a reason to pause.

Explicit wording such as "only inspect this file", "先做這一步", or "只改這個
module" selects `step` or `slice` and stops at that named boundary. Wording
such as "finish", "fix", or "complete" selects the requested outcome. If the
product direction is unclear, use the smallest reversible slice and stop at
`decision`.

Material approval, security, release, destructive, external, or irreversible
gates always take precedence and stop at `material_gate`. Acceptance stops the
outcome: do not add cleanup, refactoring, documentation, or adjacent hardening
the user did not request. `AUTO`/`ASK` selection follows the orchestration
policy; outcome continuation by itself never selects `AUTO`.

## Turn-scoped review intent

Keep `review_intent` separate from the task mode. A clear explicit preference
in the current prompt selects `fast`, `default`, or `strict`; it never changes
impact, reversibility, approval, or authority classification.

- `fast` skips optional review and non-required reasoning on non-mandatory
  work. User-named tests and every mandatory gate (independent-review
  triggers, security separation, approval) still run.
- `default` follows the existing risk policy and is the fallback when no clear
  preference is present.
- `strict` requests the complete primary review and test path. It does not
  add a second verifier without new evidence.

The preference is turn-scoped. Do not infer it from task wording, quoted
examples, negation, or vague urgency; conflicting cues fall back to `default`.
Precedence: explicit current-turn `review_intent` > risk policy > default.

## Discovery budget

Discovery has a grounding floor and a stopping ceiling. One discovery unit is
one targeted inspection, search, or reversible probe; mechanical reads in one
command count as one unit.

| Budget | Minimum evidence | Default ceiling |
| --- | --- | --- |
| `none` | Context or common sense is sufficient | Zero units |
| `minimum` | One grounding check when the answer depends on local state | Two units |
| `bounded` | Enough evidence to compare the next safe options | Six units and one cheap probe |
| `deep` | Evidence for cross-component, high-impact, or costly-to-reverse work | Ten units and two cheap probes |

Stop early when evidence no longer changes the route. When the floor cannot be
met, state the uncertainty. When the ceiling is reached, narrow, pause, or
ask; exhaustion never becomes write authorization.

## Decision checkpoint

Low-risk, reversible, clearly scoped work proceeds on a reasonable default and
records the assumption; do not ask the user to approve every small ambiguity.
When a decomposition, blocker disposition, risk, permission boundary, or
acceptance choice can change the outcome, emit one checkpoint through
`AskUserQuestion` before continuing the affected task:

- One high-level question whose answer changes the next gate.
- Two or three mutually exclusive options, recommended option first and
  labelled "(Recommended)".
- Each option states its concrete effect; the question or a preceding line
  states the current interpretation, excluded scope the answer cannot
  authorize, affected tasks, and the resume point.

Resolve replies conservatively: an exact option confirms only that option; a
rejection keeps the affected tasks pending; an ambiguous or multiple reply
stays pending and gets one concise clarification. Never treat a plausible
free-text answer as approval of credentials, external writes, destructive
work, release, or irreversible work. Ask follow-ups only after the selected
direction resumes and a new material boundary appears. If `AskUserQuestion`
is unavailable, end with `PAUSED_NEEDS_USER`, one question, choices, and a
recommendation.

## Task ledger and blocked-task isolation

When one prompt contains multiple independently executable outcomes, split
them into tracked tasks before execution. Use the harness task or todo tool
when available; each task records an outcome, scope, dependencies, state, and
completion evidence. States: `PENDING`, `RUNNING`, `DONE`, `BLOCKED`.

A task is runnable when it is `PENDING`, its dependencies are `DONE`, and no
authority, review, environment, or external prerequisite blocks it. Run
runnable tasks before revisiting blocked ones. A blocked task does not block
siblings unless a dependency edge says so; do not emit `PAUSED_NEEDS_USER`
while runnable tasks remain, and do not repeat unchanged blocker text.

When only blocked tasks remain, emit one consolidated reminder with blocked
task ids, blockers, completed work, and the exact recovery point, then stop.
The goal stays `BLOCKED`, never reported as done. A human response clears only
the affected task and its dependents.

## Continuation across user input

An unfinished objective stays active across decision replies, steering,
corrections, and status or explanation requests unless new input clearly
replaces it. If replacement intent is materially ambiguous, state the active
objective and ask one concise clarification.

Before pausing for input, state the active objective, current phase or slice,
pending decision, and exact resume point. A reply that unambiguously resolves
the pending decision resumes from that point in the same turn within existing
authority. Status or explanation requests do not resolve a decision. Do not
give a normal final response while the objective is incomplete: continue, or
emit `PAUSED_NEEDS_USER` with the blocker, one question, and the resume point.
An explicit user pause is honored without inventing a question.

## Review-service circuit breaker

A missing, failed, or timed-out `plan-verifier`, `security-reviewer`, or
`verifier` result is a service failure, not a user decision and not a
verdict. Allow one bounded retry for the same stable unit and role. If the
retry also returns no valid verdict, stop dispatching that role for the unit
and record `WAITING_FOR_REVIEW` (plan or security readiness) or
`PAUSED_VERIFICATION` (outcome or direction verification). Never claim `READY`
or `CONFIRMED`, never substitute a main-session readiness judgment, and never
loop an unchanged retry. Only the affected write or claim is blocked;
read-only work and unrelated approved slices continue.

## Direction checkpoint

At a stable slice boundary of multi-slice work, the main session may send the
`verifier` a `direction_checkpoint` brief: the original outcome, non-negotiable
constraints, slice acceptance, and current evidence. The verifier returns
`CONTINUE`, `PIVOT` (outcome stands, path or assumption must change; bounded
re-plan), or `ROLLBACK` (an invariant or acceptance condition is broken; stop
new writes and return to the latest verified good checkpoint). Insufficient
evidence stays `INCONCLUSIVE`. Use it only where the slice result can change
the remaining path; it is not a routine extra verification pass.
