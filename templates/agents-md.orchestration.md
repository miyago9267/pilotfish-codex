<!-- pilotfish-codex:begin -->
<!-- pilotfish-codex v1.3.1 -->
<!-- markdownlint-disable-next-line MD041 -->
### Orchestration

Main-session policy. If you are running as a subagent role (`scout`,
`plan-verifier`, `security-reviewer`, `mech-executor`, `executor`, `verifier`,
or `security-executor`), ignore this section and complete the task yourself
without further delegation.

Use the supplied role agents for bounded discovery, execution, and fresh-context
verification while keeping task framing, Plan synthesis, architecture,
ambiguity resolution, integration, and final judgment in the main session.
Complete small, local, already-stable work directly.

| Role | Boundary |
|---|---|
| `scout` | Broad or focused read-only repository reconnaissance |
| `plan-verifier` | Pre-approval Plan challenge; `READY` or `REVISE` |
| `security-reviewer` | Pre-approval read-only security evidence |
| `mech-executor` | Fully specified mechanical implementation |
| `executor` | Bounded implementation requiring local judgment |
| `verifier` | Completed-work challenge; `CONFIRMED` or `REFUTED` |
| `security-executor` | Approved security-sensitive implementation |

For large, ambiguous, architectural, risky, or explicitly plan-first work, use
this lifecycle:

| Phase | Gate | Eligible delegation |
|---|---|---|
| Discovery | Stabilize the question, allowed scope, evidence format, and stop condition. The final implementation may remain unknown. | Bounded read-only `scout` work on disjoint evidence surfaces. |
| Plan | The main session records a program envelope when needed, then decomposes work into independently approvable slices with stable prerequisites, exclusive ownership, acceptance, rollback, and stop conditions. | A fresh `plan-verifier` challenges exactly one readiness unit at a time—the envelope first, then one slice. The envelope must be `READY` before any child slice readiness review. |
| Approval | Present the Plan and wait for explicit user approval when the work is large, architectural, risky, or explicitly plan-first. | Read-only clarification only; do not send an implementation brief or edit source before required approval. |
| Execution | The authorized contract has stable scope, exclusive ownership, constraints, done criteria, integration, and verification. | `mech-executor`, `executor`, or `security-executor`, chosen by the contract and trust boundary. |
| Verification | The integrated result is concrete enough to refute as a completed-work claim. | A fresh `verifier` returns only `CONFIRMED` or `REFUTED`. |

#### Plan readiness protocol

For long-running or large work, the main session first records a program
envelope: outcome and non-goals, cross-cutting architecture/security/privacy
invariants, the dependency DAG, integration and rollback, global budget, and
stops. An unresolved cross-cutting blocker still prevents writes to dependent
slices. The main session then decomposes that envelope into the smallest
genuinely independently approvable, executable, and verifiable slices. Each
slice has a stable slice ID, exclusive ownership, stable prerequisites,
acceptance checks, and rollback; cosmetic fragmentation cannot bypass a
blocker.

The envelope is its own readiness unit with a stable envelope ID. A fresh
`plan-verifier` reviews that envelope alone; it must return `READY` before the
main session submits any child slice for readiness. Readiness, the Plan epoch,
and the automatic `REVISE` count are tracked per stable readiness-unit ID—the
envelope or one slice—in the Plan ledger. A fresh `plan-verifier` is required
for every unit review; the main session never bundles the envelope with a
slice or reuses a prior verifier result.

After the envelope is `READY`, review only the next executable slice by
default. As soon as that slice is `READY`, stop readiness review and present
the envelope plus that slice for explicit approval. Keep downstream slices in
Plan until their prerequisites make them next. Review more slices before
approval only when the user explicitly requests a batch or those slices must
share one approval and integration boundary.

Fully specify only the next executable slice. Downstream slice entries retain
stable IDs, outcomes, dependency edges, ownership boundaries, acceptance
intent, and rollback/stop summaries, but defer implementation detail until
that slice becomes next. Missing future detail is not a blocker for the
current slice.

The `plan-verifier` response is a strict output protocol:

- `READY` must be the entire response: the bare uppercase word with no
  punctuation, formatting, or explanation. It means only that the Plan is
  ready for the approval gate.
- `REVISE` is never a bare response. For every blocking item, provide
  `Blocker`, `Evidence` (a `file:line` reference when available, otherwise an
  explicit `evidence gap`), `Minimum revision`, and `Acceptance check`.
  Keep `REVISE` as the verdict line and put those four fields under each
  blocker; do not omit a field or replace the evidence gap with a guess.
  The field shape is `Blocker: ...`, `Evidence: <file:line or explicit
  evidence gap: ...>`, `Minimum revision: ...`, and `Acceptance check: ...`.

Any decorated, malformed, or otherwise non-conforming response is a protocol
failure, not a readiness verdict. Do not advance readiness or revise the Plan
from it. Retry the same unchanged readiness unit once per unit epoch with a
fresh `plan-verifier` for format recovery. If that response is also invalid,
pause only that unit and report the contract failure to the user. A
format-recovery retry is separate from the two valid automatic `REVISE` rounds
because it obtained no Plan judgment.

After each `REVISE` for one readiness unit in one epoch, the main session may
materially revise that envelope or slice, or add evidence, and must then
dispatch a fresh `plan-verifier`. A `REVISE` may recommend a genuine slice
split or narrowing; child slices receive their own epoch only when their
dependencies and acceptance are independently meaningful. Record that material
scope change as a new child slice ID; it does not reset the parent's count and
is never a cosmetic fragmentation.
Count automatic `REVISE` verdicts per `(stable readiness-unit ID, Plan epoch)`
pair. After the
second automatic `REVISE`, stop automatic resubmission for that envelope or
slice, pause only that unit, and surface its blockers and available options to
the user for explicit direction. A paused envelope keeps every dependent slice
from readiness review or execution. Never treat this cap as `READY`; never
silently overrule a blocker or reset the count with a superficial rewrite.
Unrelated `READY` slices may proceed after explicit approval while the paused
or later slices remain in planning;
blocked prerequisites and cross-cutting slices still gate their dependents.
User-directed continuation is allowed for a paused readiness unit after
intervention and remains a fresh-verifier review, so the brake is not a
permanent ban. User direction is not a silent count reset; only a materially
new readiness-unit epoch under the rule below starts a new automatic count,
whether the unit is an envelope or a slice.

A readiness unit's Plan epoch changes only when the user materially changes
its outcome, scope, or architecture, or explicitly chooses a materially new
envelope or slice Plan
after intervention. Reformatting, restating, or other superficial rewrites
cannot create a new epoch. Record the stable readiness-unit ID, user-directed
continuation, and any new epoch in the Plan ledger rather than inferring
consent from a verdict.

For a Plan envelope or slice involving authentication, authorization,
credentials, identity, privacy, secrets, crypto/cryptography, validation,
hardening, or vulnerability work, the main session must finish the read-only
`security-reviewer` and carry its findings (or an explicit evidence gap) into
the Plan ledger before the first `plan-verifier` call for that unit. Never
launch those reviews concurrently. Refresh the security evidence before a
later readiness pass only when a revision changes the trust boundary or
invalidates a finding. Security evidence does not authorize writes or replace
either Plan review. The `security-reviewer` and `plan-verifier` remain separate
capability boundaries.

`READY` is readiness only, never user approval. It means only that the slice is
ready for the Approval phase; it never means that the user approved it. It does
not authorize `exit_plan_mode`, execution, or writes: the main session must
wait for explicit user approval before mutating that slice.
A ready slice may execute while unrelated or later slices remain in planning,
but blocked prerequisites and cross-cutting
invariants still gate dependent slices. After Execution, the fresh `verifier`
uses only `CONFIRMED` or `REFUTED`; those outcome verdicts never replace Plan
readiness, and a Plan verifier never issues them.

Before every agent call, identify the phase and apply a dispatch brake. Do not
fan out when workers would repeatedly depend on evolving shared evidence, write
ownership overlaps, no clear synthesis or integration owner exists, or
coordination cost exceeds the likely benefit. Discovery agents report facts;
the main session reconciles contradictions and writes the Plan.

Use the smallest useful execution shape: work directly for small or tightly
coupled tasks, one worker for a bounded side task, and bounded parallel workers
only for independent, low-overlap workstreams. Delegate only when the saved
execution or context cost exceeds the briefing, coordination, and review cost.
A matching role makes work eligible rather than mandatory.

A delegation-planning layer may shape discovery questions, execution topology,
worker count, ownership, sequence, budgets, and stop conditions. This policy
remains authoritative for named role semantics, the leaf-agent boundary, the
approval gate, and verifier contracts; agent TOMLs remain authoritative for
model and reasoning-effort bindings.

Keep a single unknown bug's initial root-cause discovery, trace-driven
debugging, tightly coupled state propagation, and the first minimal fix in the
main session when they share one reasoning chain. Use a scout only for a
bounded side question whose result does not own or block the main diagnosis.

Route security-sensitive work through separate capability boundaries. Before
required approval, use `security-reviewer` for evidence only. After approval,
give the stable implementation contract to `security-executor`.

Model routing is owned by the named agent definitions. Select the named role
without replacing its configured model or reasoning effort. Use an ad-hoc model
override only for a truly ad-hoc agent with no matching role definition.

<!-- pilotfish-codex:spawn-transport:begin -->
#### Spawn transport — temporary MultiAgentV2 adapter

On affected MultiAgentV2 releases, dispatch named roles through
`agents.spawn_agent`. This transport paragraph is the only namespace-specific
part of the policy and can be replaced after adapter-free native role dispatch
is verified.

Every named-role call must supply all three routing fields:

- `agent_type` selects an installed role TOML;
- `task_name` matches `[a-z0-9_]+`; and
- `fork_turns = "none"` is the default.

Use a positive integer string from `"1"` through `"3"` for `fork_turns` only
when the brief depends on recent turns. Never omit the field, exceed that
bound, or request full history. Keep the brief self-contained whenever the
default is sufficient.

If the `agents` namespace, `agent_type`, or installed role is unavailable, fail
closed. Never retry the task with an untyped child because it can inherit the
orchestrator model. Do not pass model or reasoning-effort overrides for an
installed named role; its TOML remains authoritative. Do not pass a
`service_tier` override. Omitting it prevents child-only tier escalation but
does not downgrade a tier deliberately selected for and inherited from the
parent session.
<!-- pilotfish-codex:spawn-transport:end -->

Brief each worker in one shot with the goal, constraints, done criteria,
relevant paths, rationale, output format, budget, and verification expectation.
Start with the cheapest eligible role. After two failed attempts, change the
task boundary, escalate one tier, or take over. Treat scout findings as inputs;
sanity-check any single fact that carries a decision.

Schedule by data dependency. Start independent agents concurrently when useful,
give writing agents exclusive file ownership or isolated worktrees, continue
independent main-session work while they run, and collect every result before
dependent work or the final answer.

Long-running processes belong to the main session. Leaf agents must not detach
them; they return the exact command, absolute working directory or worktree,
required environment, input paths, and completion criterion so the orchestrator
can run and collect the result before resuming the agent.

Never swap `plan-verifier` and `verifier`. The former challenges Plan
readiness; the latter reproduces tests and challenges a completed-work claim.
Neither role writes the Plan or fixes findings. Final judgment remains in the
main session.
<!-- pilotfish-codex:end -->
