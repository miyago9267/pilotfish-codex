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
| Plan | The main session synthesizes one Plan. Large work uses a program envelope plus independent slices with stable IDs, outcome, scope, non-goals, owners, prerequisites, acceptance that proves the slice outcome, rollback, slice-local budget, and stop conditions. | A fresh `plan-verifier` reviews the envelope first, then only the next executable slice; main session owns revisions and final synthesis. |
| Approval | Present the Plan and wait for explicit user approval when the work is large, architectural, risky, or explicitly plan-first. | Read-only clarification only; do not send an implementation brief or edit source before required approval. |
| Execution | The authorized contract has stable scope, exclusive ownership, constraints, done criteria, integration, and verification. | `mech-executor`, `executor`, or `security-executor`, chosen by the contract and trust boundary. |
| Verification | The integrated result is concrete enough to refute as a completed-work claim. | A fresh `verifier` returns only `CONFIRMED` or `REFUTED`. |

A `plan-verifier` brief requests exactly bare `READY` or structured `REVISE`
with `Blocker:`, `Evidence:`, `Minimum revision:`, and `Acceptance check:`
fields for one stable envelope or slice. Malformed output is a protocol failure,
not a Plan judgment.

Review the envelope before its slices. By default, review only the next
executable slice and seek approval as soon as both are `READY`; unrelated
downstream slices do not block it. Shared blockers and unmet prerequisites
still gate dependent work.

For one readiness unit, materially revise after each valid `REVISE` and use a
fresh `plan-verifier`. After two automatic `REVISE` verdicts for the same unit,
stop resubmitting it and surface the blockers and options to the user; the cap
is not `READY`, cosmetic splitting cannot reset it, and user-directed
continuation remains allowed. Do not resubmit a substantially unchanged Plan.

`READY` is readiness only, never user approval or write authorization.

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
the first readiness review for an affected unit, finish `security-reviewer` and
carry its findings and dispositions into the Plan; do not run the two reviews
concurrently. After approval, give the stable implementation contract to
`security-executor`.

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
Neither role writes the Plan or fixes findings. After a concrete `REFUTED`,
materially fix the same claim before using a fresh verifier. After two
consecutive `REFUTED` verdicts for that claim, stop automatic fix-and-reverify
cycling and surface the failures and options to the user; the cap is not
`CONFIRMED`, and user-directed continuation remains allowed. Do not reverify a
substantially unchanged implementation. Final judgment remains in the main
session.
<!-- pilotfish-codex:end -->
