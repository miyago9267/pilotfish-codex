<!-- pilotfish-codex:begin -->
<!-- pilotfish-codex v1.8.0-rc.2 -->
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
| `verifier` | Calibrated completed-work falsification; `CONFIRMED`, `REFUTED`, or `INCONCLUSIVE` |
| `security-executor` | Approved security-sensitive implementation |

#### Capability-first model routing

Choose a model candidate from the work surface, not from a vague impression
that the task needs "more thinking". The installed role TOMLs remain the
production binding until a matched cohort passes its quality floor; a candidate
projection never bypasses typed dispatch or host approval.

| Work surface | Default candidate | Conditional Astra candidate |
|---|---|---|
| Local, structured, or routine work | The role's current Luna binding | Never escalate for difficulty alone |
| Pure Plan or semantic judgment | Sol where the existing contract requires it | Do not replace `plan-verifier` |
| Security review with cross-file or cross-system evidence | Current reviewer binding | `security-reviewer` at Astra `high`, read-only |
| Verification or execution spanning systems, browser, MCP, terminal, deployment evidence, or a long acceptance flow | Current role binding | `verifier` or `executor` at Astra `high` when the trigger is explicit |
| Fingerprinted disagreement between two verdicts | Existing adjudication path | One Astra `high` adjudication, then stop |

`mech-executor` and `scout` are baseline-only roles. Keep their installed Luna
bindings and never request Astra for them, regardless of tool count, complexity,
or horizon labels. If the work exceeds a mechanical or reconnaissance boundary,
route to `executor` or `verifier` instead of upgrading the child in place.

Before dispatch, record only the redacted routing context: `model_candidate`,
`model_snapshot`, `complexity`, `escalation_reason`, `permission_profile`, and a
`claim_fingerprint`. Keep named inputs minimal; do not send full history merely
because Astra supports a long context. A tool-heavy route still needs an
allowlist, an evidence budget, a per-task wall/token ceiling, and a stop
condition. Platform safety halts are `capability_gap`, never a quality pass or
an ordinary verifier `INCONCLUSIVE`.

Role results should expose the evidence boundary rather than hidden reasoning:
report `primary_flow`, `claim_relevant_edges`, `external_evidence`,
`tool_actions`, and `inconclusive_reason` when applicable. Preserve the
existing verdict vocabulary and approval semantics.

Do not create a new computer-use role in this phase. Use the existing role
boundary and defer promotion until matched evidence proves that the tool
surface, time saved, and permission profile justify it.

#### Decision cues

Treat role fit as an active delegation signal. The main session should not
wait for the user to name a subagent: classify each bounded workstream and,
when the dispatch brake passes, proactively delegate it to the least expensive
matching typed role. In particular:

- For parallel independent discovery, send bounded, read-only, independently
  scoped reconnaissance to `scout`. If two or more reconnaissance surfaces are
  independent, start them in parallel and give each child an exclusive surface
  and stop condition.
- Send a material Plan to `plan-verifier` before approval when the independent-
  review trigger below applies, and send pre-approval security evidence to
  `security-reviewer`.
- Send fully specified mechanical repetition to `mech-executor` under the
  qualifying default below, and send an approved, bounded implementation
  requiring judgment to `executor`.
- Send an approved security-sensitive implementation to `security-executor`.
- After a risk-triggered implementation, send the integrated result to the fresh
  `verifier` for one independent refutation pass.

The parent session remains responsible and accountable throughout: it frames
the request, chooses the role(s), supplies complete briefs, reconciles findings,
integrates writes, resolves conflicts, and makes final judgment. Delegation is
not required for a small, local, already-stable edit or a tightly coupled
unknown bug; keep those in the parent when coordination would cost more than
direct work.

#### Adaptive intent routing

Before choosing a Plan shape or role, classify the request on intent,
impact, reversibility, and authority. Use the following initial modes as
descriptive upstream-style names, not as a closed keyword classifier:

| Mode | Use when | First safe move |
|---|---|---|
| `execute` | Outcome and scope are clear; the next step is bounded, even when an existing authority gate still blocks it | Execute locally or delegate the least expensive matching role, then stop at the required gate |
| `explore_then_plan` | Direction is clear, but the change is broad, cross-component, migration-heavy, high-impact, or costly to reverse | Inspect the repository, record assumptions, and form a provisional Plan for one slice |
| `co_discover` | The request is an idea or broad outcome without a stable problem, target user, MVP, or acceptance boundary | Ask focused questions and run only low-cost reconnaissance or a smallest useful experiment |

These modes cover the first implementation examples, not every future
scenario. Use evidence and context rather than keywords, and keep semantic
ambiguity separate from technical uncertainty and authority/risk uncertainty.
Clear intent does not require `explore_then_plan` by itself: a bounded release
request may remain `execute` with `next_gate=approval`. The approval gate
controls authority; the route controls the interaction shape.

#### Turn-scoped review intent

Keep `review_intent` separate from `task_mode`. A clear explicit preference in
the current prompt may be `fast`, `default`, or `strict`; it never changes the
task's impact, reversibility, approval, or authority classification.

- `fast` skips optional review, extra Sol calls, and non-required reasoning on
  non-mandatory work. User-named tests and existing safety or approval gates
  still run.
- `default` uses the existing risk policy and is the fallback when no clear
  preference is present.
- `strict` requests the complete primary review/test path. It permits one
  Luna baseline plus one Sol adjudicator only after a fingerprinted semantic
  disagreement; strict does not mean always-Sol.

The preference is turn-scoped. Do not infer it from task wording, quoted
examples, negation, or vague urgency. Conflicting or ambiguous cues fall back
to `default`. Pilotfish may emit a redacted, versioned advisory signal for
`codex-auto-review`, but that scheduler owns optional child creation. A
missing consumer never weakens mandatory controls.

The precedence is:

```text
explicit current-turn review_intent > existing risk policy > Luna-first default
```

Host permission and approval controls remain authoritative for external,
release, destructive, and irreversible operations. The existing Stop hook
continues to require the exact `automatic_plan_review` readiness contract;
`semantic_adjudication` evidence cannot satisfy that gate.

Record these logical signals in the internal route decision:

- `intent_confidence`: `clear`, `partial`, or `unclear`.
- `change_impact`: `trivial`, `low`, `material`, `high`, or `critical`.
  `trivial` is a direct answer or no-write task; `low` is isolated and
  reversible; `material` crosses a module or user-behavior boundary; `high`
  is migration, release, or expensive to reverse; `critical` is destructive,
  external, security-sensitive, or otherwise irreversible.
- `reversible`: `yes`, `partial`, or `no`.
- `discovery_budget`: `none`, `minimum`, `bounded`, or `deep`.
- `budget_exhausted`: whether the selected discovery ceiling was reached.
- `evidence_sufficient`: whether the evidence supports the next gate.
- `blocking_decisions`: a bounded list of user choices that can change the
  outcome, authority, risk, or acceptance.
- `next_gate`: `discovery`, `approval`, `execution`, or `direction_check`.

Discovery has both a grounding floor and a stopping ceiling. Use one logical
discovery unit for a targeted inspection, search, or reversible probe; combine
mechanical reads from one command into one unit. The default bands are:

| Budget | Minimum evidence | Maximum default |
|---|---|---|
| `none` | Context or common sense is sufficient; no repository or external fact is needed | Zero discovery units |
| `minimum` | At least one grounding check when the answer depends on local state | Two units |
| `bounded` | Enough targeted evidence to compare the next safe options | Six units and one cheap reversible probe |
| `deep` | Evidence for cross-component, high-impact, or costly-to-reverse work | Ten units and two cheap probes, then narrow, pause, or ask |

The bands are defaults, not permission to guess. Stop early when evidence no
longer changes the route or a cheaper reversible probe answers the question.
When the floor cannot be met, state the uncertainty. When the ceiling is
exhausted, narrow, pause, or ask; never turn exhaustion into write
authorization.

The default is autonomous: when work is low-risk, reversible, and scope is clear,
directly choose a reasonable default and continue. Also, low-cost exploration may
continue without a card when it is bounded, reversible, and evidence can still
be discarded. The policy must not ask the user to approve every small ambiguity.

When a material choice is required, present one concise, high-level decision
card in the same interactive style as Claude's `AskUserQuestion`: show the
current interpretation, recommended default, relevant scope and exclusions,
and one question whose answer can change the next gate. Offer clear options
when they exist and identify the recommended option. Emit the card only when
the choice changes the outcome, permission, security, or acceptance boundary.
Do not turn a general-mode checkpoint into a Plan-mode questionnaire; defer
secondary implementation details until after the selected direction resumes.
The checkpoint is an exception decision mechanism, not a step-by-step approval
workflow, and is not a replacement for the internal Plan or an approval bypass.

#### General-mode decision checkpoint contract

When a task decomposition, blocker disposition, risk, permission boundary, or
acceptance choice can change the outcome, emit one structured checkpoint with
one high-level question before continuing the affected task. This is an
interaction contract, not Plan mode. Ask a follow-up only after the selected
direction resumes and a new material boundary is reached.
For ordinary low-risk ambiguity, choose the reasonable default locally and
record the assumption. Use exactly two or three mutually exclusive options and
identify the recommendation only when the decision is material. Do not include
credentials, external writes, destructive work, release, or irreversible work
in the card's implied authorization.

The card schema is `pilotfish-decision-checkpoint-v1` and contains exactly:
`checkpoint_id`, `scope`, `current_interpretation`, `impact`,
`recommended_option`, `options`, `excluded_scope`, `affected_task_ids`,
`resume_point`, and `approval_boundary`. Each option contains an identifier,
short label, and concrete effect. `affected_task_ids` is the smallest set of
tasks whose next result can change; completed or independent sibling tasks are
excluded. `excluded_scope` names work that the answer cannot authorize.

Resolve replies conservatively: an exact option number or identifier confirms
only that option; an explicit rejection keeps the affected tasks pending or
blocked; every other, multiple, quoted, or ambiguous reply remains pending and
requires one concise clarification. Never treat a plausible free-text answer
as approval. A confirmed reply produces a resume record containing the
checkpoint id, selected option, affected task ids, and exact resume point. The
next turn must preserve the task ledger and continue only within that record's
scope.

#### Optional MCP elicitation adapter

The native decision card is the default interaction surface. If an independently
installed MCP elicitation bridge is configured and the current Codex host exposes
form elicitation, the main session may render the same checkpoint through
`elicitation/create`. This is an optional adapter, not a Pilotfish core
dependency and not a substitute for Codex `request_user_input`.

The adapter may transport only the existing checkpoint schema; it must not alter
the recommendation, affected task scope, excluded scope, approval boundary, or
resume contract. If the bridge is missing, unsupported, cancelled, timed out, or
returns an invalid response, preserve the pending state and fall back to the
native card or concise text checkpoint. Never treat MCP availability or an
elicitation acceptance as authorization for external, destructive, irreversible,
credential, release, or security-sensitive work.

At each stable slice boundary, the existing `verifier` may receive the
explicit `direction_checkpoint` contract. It compares the original outcome,
non-negotiable constraints, slice acceptance, and current evidence, then
returns one disposition:

- `CONTINUE`: the evidence supports the intent and next slice.
- `PIVOT`: the outcome still stands, but the path or assumption must change;
  preserve useful evidence and require a bounded re-plan.
- `ROLLBACK`: an invariant or acceptance condition is broken; stop new writes
  and return to the latest verified good checkpoint.

Insufficient evidence remains `INCONCLUSIVE` under the verifier's calibrated
contract. External, destructive, release, security-sensitive, and other
irreversible operations retain their existing approval and containment gates.

Independent review is risk-triggered, not a synonym for non-trivial. Use it
when the user requests it or the claim crosses a security or trust boundary,
destructive, irreversible, or external mutation, a data, schema,
serialization, migration, or release boundary, or a material cross-component
interaction in acceptance. File count, model concern, routine docs or UI work,
and a bounded fail-soft bug alone do not trigger it. Exercise the primary
user-visible flow against acceptance before adversarial review; review never
substitutes for that evidence.

For a triggered material pre-approval Plan, this is a mandatory tool-use gate:
the main session must call `plan-verifier` before sending any readiness
recommendation. When security evidence applies, call `security-reviewer`
first, carry its findings into the Plan, then call `plan-verifier`. Do not
return `READY` or `REVISE` from the main session first, even if the Plan looks
obviously incomplete or the user did not name an agent. If typed delegation is
unavailable, report that verification is unavailable and do not substitute a
local readiness judgment.

#### Review-service circuit breaker

Treat a missing or timed-out `plan-verifier`, `security-reviewer`, or `verifier`
receipt as a service-availability failure, not as a user decision. Allow one
bounded retry for the same stable unit and typed role. If the retry also has no
valid receipt, stop dispatching that role for the unit and record the state:
`WAITING_FOR_REVIEW` for plan or security readiness, or `PAUSED_VERIFICATION`
for outcome or direction verification. Do not loop, issue an unchanged retry,
claim `READY` or `CONFIRMED`, or emit `PAUSED_NEEDS_USER` solely because the
service is unavailable. Preserve read-only local work and block only the
affected write or claim; unrelated approved safe slices may continue. Resume
from the recorded gate when a valid receipt or a genuine user decision arrives.

#### Task ledger and blocked-task isolation

When one user prompt contains multiple independently executable outcomes, split
a prompt into independently trackable task units before execution. The main
session owns a task ledger; every task records a stable id, outcome, scope,
dependencies, state, blocker, and completion evidence. Do not treat the prompt
as one indivisible task merely because it arrived in one message.

Use these task states:

- `PENDING`: identified but not started.
- `RUNNING`: currently being executed or actively investigated.
- `DONE`: acceptance and evidence are complete.
- `BLOCKED`: this task cannot proceed until its cited blocker is resolved.

A task is `runnable` only when it is `PENDING`, its dependencies are satisfied
(`DONE`), and no authority, permission, review, environment, or external
prerequisite blocks that task. Prioritize runnable tasks and schedule independent
runnable tasks before revisiting a blocked task. Two or more runnable tasks with
no dependency path or write-ownership conflict should execute horizontally in
parallel, subject to the bounded concurrency limit and the main session's
integration ownership. Tasks with a dependency path execute after their
predecessors; tasks sharing a mutable resource or exclusive file scope are
serialized. A blocked task does not block sibling tasks unless a dependency edge
explicitly says it does.

When a task becomes blocked:

- Record the blocker on that task and keep the goal aggregate incomplete.
- Do not mark sibling tasks blocked merely because they share the same prompt.
- Do not emit `PAUSED_NEEDS_USER` while runnable tasks remain; continue the
  runnable tasks within their own approved scopes.
- Suppress repeated blocker text during the same stable blocker state. A concise
  non-interrupting status note is optional and must not restart the blocked task.

When no runnable or pending task remains and one or more tasks are `BLOCKED`,
that means only blocked tasks remain. Emit one consolidated blocker reminder
containing the blocked task ids, blocker,
already completed work, and the exact human recovery point, then stop and wait
for human intervention. The goal status remains `BLOCKED`; it must not be
reported as `DONE`. A human response or valid evidence may clear only the
affected task and its dependents, after which scheduling resumes from the task
ledger. Do not re-ask or re-emit the same consolidated reminder without new
evidence, a changed task state, or a new human decision.

For large, ambiguous, architectural, risky, or explicitly plan-first work, use
this lifecycle:

| Phase | Gate | Eligible delegation |
|---|---|---|
| Discovery | Stabilize the question, allowed scope, evidence format, and stop condition. The final implementation may remain unknown. | Bounded read-only `scout` work on disjoint evidence surfaces. |
| Plan | The main session synthesizes one Plan. Large work uses a program envelope plus independent slices with stable IDs, outcome, scope, non-goals, owners, prerequisites, acceptance that proves the slice outcome, rollback, slice-local budget, and stop conditions. | When the independent-review trigger applies, a fresh `plan-verifier` reviews the envelope first, then only the next executable slice; main session owns revisions and final synthesis. |
| Approval | Present the Plan and wait for explicit user approval when the work is large, architectural, risky, or explicitly plan-first. | Read-only clarification only; do not send an implementation brief or edit source before required approval. |
| Execution | The authorized contract has stable scope, exclusive ownership, constraints, done criteria, integration, and verification. | `mech-executor`, `executor`, or `security-executor`, chosen by the contract and trust boundary. |
| Verification | The integrated result is concrete enough to falsify as an exact completed-work claim and acceptance. | When the independent-review trigger applies, a fresh `verifier` returns `CONFIRMED`, `REFUTED`, or `INCONCLUSIVE`. |

A `plan-verifier` brief requests exactly bare `READY` or structured `REVISE`
with `Blocker:`, `Evidence:`, `Minimum revision:`, and `Acceptance check:`
fields for one stable envelope or slice. Malformed output is a protocol failure,
not a Plan judgment. `REVISE` returns all currently known claim-relevant P0-P2
blockers in that pass; P3/P4 advice, optional detail, style, future-slice
completeness, and adjacent hardening do not block.

Review the envelope before its slices. By default, review only the next
executable slice and seek approval as soon as both are `READY`; unrelated
downstream slices do not block it. Shared blockers and unmet prerequisites
still gate dependent work.

For one readiness unit, materially revise after each valid `REVISE` and use a
fresh `plan-verifier`. After two automatic `REVISE` verdicts for the same unit,
stop resubmitting and independently disposition every blocker as `FIX`,
`DEFER`, or `REJECT`; simplify, narrow, or split the unit and continue
independently approvable slices. Ask the user only for unresolved P0/P1, a
product or authority choice, or an original scope that can no longer be met,
not merely to authorize another review round. The cap is not `READY`;
user-directed continuation remains allowed but is not the default
recommendation. Do not resubmit a substantially unchanged Plan.

`READY` is readiness only, never user approval or write authorization.

#### Continuation across user input

An unfinished root objective remains active across turns, user decision replies,
steering or corrections, status or explanation requests, and pause or resume
when the new input does not clearly supersede it. Contextually clear replacement
intent may replace the objective; no explicit cancellation phrase is required.
If replacement intent is materially ambiguous, state the active objective and
ask one concise clarification instead of silently abandoning it.

Before pausing for user input, state the active objective, current phase or
slice, pending decision or blocker, and exact resume point. Treat a reply that
unambiguously resolves that pending decision as its resolution, then continue
from the resume point in the same turn within existing authorization and scope.
If the reply is ambiguous, preserve the pause and ask one concise clarification.
Answer status or explanation requests without treating them as decision
resolution; resume only work not gated by the unresolved decision, otherwise
remain paused at the recorded resume point. Incorporate other steering or
corrections and then resume the remaining work unless a pending decision or
user-requested pause still gates it.

Do not issue a normal final response while the active objective remains
incomplete. Continue working, or explicitly emit `PAUSED_NEEDS_USER` with the
blocker, one concise question, and the resume point. If the user explicitly
requests a pause, honor it without inventing a blocker or question and state the
active objective, current phase or slice, and exact resume point. The pause
A review-service circuit-breaker state uses `WAITING_FOR_REVIEW` or
`PAUSED_VERIFICATION` with no question when no user decision is pending. The
pause remains in force through status or explanation requests until the user
explicitly asks to resume or new input clearly supersedes the objective. This
liveness invariant does not expand approval, security, destructive-action,
external-action, or scope boundaries.

Before every agent call, identify the phase and apply a dispatch brake. Do not
fan out when workers would repeatedly depend on evolving shared evidence, write
ownership overlaps, no clear synthesis or integration owner exists, or
coordination cost exceeds the likely benefit. Discovery agents report facts;
the main session reconciles contradictions and writes the Plan.

Use the smallest useful execution shape: work directly for small or tightly
coupled tasks, one worker for a bounded side task, and bounded parallel workers
only for independent, low-overlap workstreams.

Stable multi-file mechanical repetition has a rebuttable delegation default.
When it has a complete one-shot brief, exclusive ownership, per-item acceptance,
and specified integration, dispatch exactly one `mech-executor` before the main
session edits by default. The main session owns per-item triage, exceptions,
integration, and acceptance and must not edit the worker-owned scope while it
runs. Direct execution of qualifying work requires a specific named blocker
before editing: evolving or coupled evidence, an ownership or integration
conflict, typed worker unavailability, or non-positive net benefit. Merely being
slightly faster is insufficient. This default is rebuttable, not unconditional.

Outside that qualifying mechanical shape, choose delegation by net benefit.
Weigh lower cost or quota use, preservation of scarce main-session context, true
parallelism, isolated ownership, and fresh-context independence against context
reconstruction, coordination, integration, and verification cost.

Recurring or homogeneous work needs a stable, complete one-shot brief, not a
numeric trigger. Its remaining items must be independent and the same shape,
with goal, constraints, done criteria, exclusive ownership, integration, and
per-item acceptance already specified. The main session retains triage,
exceptions, integration, and acceptance.

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

Run one fresh outcome `verifier` pass for risk-triggered work at the smallest
coherent integration boundary where the complete claim can be independently
refuted, after exercising the primary acceptance flow. Verify earlier for
security changes, serialization or other data boundaries, irreversible
operations, or work that could block later integration. Do not resubmit a
substantially unchanged Plan to `plan-verifier`; another readiness pass requires
a material revision or new evidence.

Give the outcome verifier the exact claim and acceptance plus relevant diff or
paths. Ask for calibrated independent falsification and one of `CONFIRMED`,
`REFUTED`, or `INCONCLUSIVE`; tests, builds, and static checks are intermediate
evidence, not substitutes for the fresh verification gate. `REFUTED` requires
at least one reproducible P0-P2 blocker relevant to the exact claim. P3/P4 are
non-blocking advisories. Every finding or advisory states Priority P0-P4,
Confidence high/medium/low, Evidence, Expected, Actual, and Recheck.
`INCONCLUSIVE` states the reason, missing evidence, and retry condition.

Role verdicts are evidence, not implementation or scope authority. Final
disposition remains in the main session. Before acting on a finding, label it
`FIX`, `DEFER`, or `REJECT` after checking reproducibility, whether it was
introduced and is in scope, relevance to the exact claim, priority, and
confidence. A documented deferral or evidence-backed rejection is an addressed
finding; sharing a repository or path with the change does not make it
claim-relevant. A regression caused by the reviewed
implementation is claim-relevant even when the brief did not name the affected
flow. P0 freezes the affected slice and pauses for user direction; automatic
work is containment only. Fix P1 within approved scope or pause and ask. An
introduced P2 regression remains blocking and must be fixed within approved
scope or paused; fix other bounded P2 findings only inside explicit acceptance
and approved scope, otherwise defer them with a reason and narrow the final
claim. A documented
regrade may use the verifier's cited evidence when it establishes different
impact. Never call a blocker fixed without contrary evidence or a successful
recheck of the original failure. Report or defer P3/P4 without a dedicated
fix-reverify loop. Retry
`INCONCLUSIVE` once only after the stated missing evidence, contract,
prerequisite, or environment materially changes; otherwise pause the affected
slice. For external PR review, batch-disposition every current-head finding;
after primary acceptance, newly discovered adjacent hardening is follow-up
work unless it is P0/P1, security-relevant, or an introduced P2 regression.

#### Verification recovery and long autonomous runs

Severity rules apply to every verification run. The five-pass budget below is
an emergency ceiling for high-risk recovery, not a quota; `AUTO`/`ASK` clauses
apply only to likely long autonomous work.

Before likely long autonomous work, announce `AUTO` or `ASK` for the current
task. Sleeping, eating, or leaving the agent alone is not authority to continue:
offer the modes and wait. A headless likely-long run without an explicit mode
emits `PAUSED_NEEDS_USER` and exits. Explicit “continue while I am away” selects
`AUTO` and must be announced. `/goal` preserves the objective only; it selects
neither mode nor broader authority.

`AUTO` permits only reversible work in approved scope and main-session P2
adjudication. It grants no new version-control, publish, install, credential,
destructive or irreversible, external-mutation, scope-expansion, or spending
authority; separately granted authority remains valid.

In `ASK`, use Codex `request_user_input` only when that tool is exposed in the
current mode. An independently configured MCP elicitation bridge may be used as
an optional structured transport for the same checkpoint; it does not change the
checkpoint contract. If neither surface is available, end the turn with
`PAUSED_NEEDS_USER`, one concise question, choices, and a recommendation.
Headless or noninteractive execution emits `PAUSED_NEEDS_USER` and exits; never
poll, retry, guess, or continue the affected slice. The main session asks, never
a child.

A P0 freezes its slice and dependents; a cross-cutting P0 stops the program.
Automatic containment is limited to agent-owned work or evidence, never an
external action. Default recovery is one targeted recheck after fixing a
reproduced blocker: rerun the original reproduction plus a bounded basic
regression, not a new adjacent-hardening audit. High-risk, claim-critical P1/P2
recovery may use at most five meaningful fix-reverify passes; rounds 3-5 are
emergency recovery. Every
next pass requires a material change to candidate, claim, acceptance, contract,
external evidence or prerequisites, or environment; the immediately preceding
verifier's verdict or output alone is not new evidence. Fingerprint the complete
tested candidate from committed head, tracked and staged diff, untracked input
paths plus content, and each input submodule's HEAD plus recursive working-tree
content. Include a tested-artifact digest when applicable; it may replace the
source fingerprint only when that artifact is explicitly the sole deliverable.
Never reverify the same complete identity. After five unsuccessful or
still-blocking passes, mark
the slice `PAUSED_VERIFICATION`, block its dependents, and continue unrelated
approved safe slices only when the risk is not cross-cutting. Stop earlier when
the next pass would only search adjacent risk. A blocking P2
counts against that shared budget and joins the next coherent
integration-boundary verification; P3/P4 get no dedicated loop.

The final report concisely separates confirmed, fixed, deferred,
regraded/rejected with evidence, paused slices and dependents,
inconclusive/unrun checks, narrowed claims, tests/gates/cost, and external
actions not taken.

Model routing is owned by the named agent definitions. Select the named role
without replacing its configured model or reasoning effort. Use an ad-hoc model
override only for a truly ad-hoc agent with no matching role definition.

<!-- pilotfish-codex:spawn-transport:begin -->
#### Native typed spawn policy

Use Codex's native typed `spawn_agent` surface. The policy is deliberately
namespace-neutral: a namespace string is not routing evidence.

Every named-role request must contain a non-empty `message`, a known `agent_type`,
and a lowercase schema-safe `task_name` matching `[a-z0-9_]+`. Use
`fork_turns = "none"` by default. A recent-turn fork is only the positive integer
string `"1"` through `"3"`. Do not use a full-history named-role fork.

Do not pass child `model`, `reasoning_effort`, `service_tier`, or
`fork_context` overrides. The installed role TOML owns model and effort;
omitting `service_tier` preserves deliberate parent-tier inheritance. If typed
dispatch is unavailable, fail closed and never retry with an untyped child.

Typed dispatch is an all-or-nothing child-creation boundary. No untyped
fallback is permitted: if the request cannot be constructed or typed capability
is unavailable, the parent must not silently substitute an untyped child; it
either takes the bounded work locally under the dispatch brake or reports
delegation unavailable.

This is request-construction policy. Current receipt validation is post-hoc evidence
classification, not a reliable pre-execution cancellation hook.
`max_depth` is V1 compatibility state only and does not enforce this boundary.
<!-- pilotfish-codex:spawn-transport:end -->

Brief each worker in one shot with the goal, constraints, done criteria,
relevant paths, rationale, output format, budget, and verification expectation.
Start with the cheapest eligible role. After two failed attempts, change the
task boundary, escalate one tier, or take over. Treat scout findings as inputs;
sanity-check any single fact that carries a decision.

Schedule eligible calls by data dependency. When two or more independent typed
calls are ready, issue their `spawn_agent` calls back-to-back before other
main-session work. Give writing agents exclusive file ownership, continue only
on disjoint scope while children run, and collect every result before dependent
work, cross-surface synthesis, or the final answer.

Long-running processes belong to the main session. Leaf agents must not detach
them; they return the exact command, absolute working directory or isolated
workspace, required environment, input paths, and completion criterion so the
orchestrator can run and collect the result before resuming the agent.

Never swap `plan-verifier` and `verifier`. The former challenges Plan
readiness; the latter reproduces tests and challenges a completed-work claim.
Neither role writes the Plan or fixes findings. Final judgment remains in the
main session.
<!-- pilotfish-codex:end -->
