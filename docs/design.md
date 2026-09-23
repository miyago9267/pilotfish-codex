# Pilotfish-Codex design rationale

Pilotfish-Codex preserves Pilotfish's role routing, approval boundaries, leaf
workers, and fresh-context verification while using Codex-native TOML roles and
global `AGENTS.md` policy. Claude-specific worktrees, task dashboards, agent
IDs, resume commands, and `Explore` shadowing are not Codex runtime claims.

## Native Multi-Agent boundary

The active target is the native Codex contract, with `0.147.0` as the minimum
compatibility floor; later releases are accepted after parsing and native
contract validation. Child concurrency is an `[agents]` setting:

```toml
[agents]
max_concurrent_threads_per_session = 3

[features]
default_mode_request_user_input = true
```

The value is child concurrency, so three permits the root plus three children.
The native decision-card feature is enabled so Default mode can expose the
same bounded `request_user_input` interaction used by Plan mode.
The root model, reasoning effort, and Plan-mode effort are user preferences:
Pilotfish defaults them for a fresh install but does not claim ownership, so a
user may temporarily switch the main session to another compatible model.
Role TOMLs retain model and reasoning-effort precedence. The retired V2 feature
table is migratable only with exact installer provenance; the active contract
does not rely on an adapter namespace, metadata visibility override, or an
undocumented rollout marker.

Migration provenance is an exact committed sidecar schema: `config.toml`, the
seven canonical role paths, and the currently selected policy must be the only
entries in both target maps, with matching SHA-256 fingerprints and original
byte evidence. Missing, stale, extra, or malformed state, an unowned V2 key,
or a conflicting `[agents]` concurrency value aborts before writes. Dry-run
reports only primary paths and the pending/committed sidecars plus backups for
replaced targets; it creates none.

An explicit Astra main session is a zero-write, session-only preference. The
user starts it with `gpt-6-astra`, `high` main and Plan effort, and one optional
child; the default root config is GPT-6 Luna/max with Plan xhigh. Without a
root override, automatic routing uses the installed Astra `executor` and
`verifier` roles for design, tool use, interpretation, and judgment, while
routine and mechanical work stays on the installed Luna roles. The
prompt's `max_tool_calls=12` and `max_wall_seconds=300` values are advisory
usage guards, not provider quota enforcement. Invalid or unavailable Astra
activation fails closed before task work; a separately started no-flags session
returns to the normal root Luna/Sol policy. `plan-verifier` uses GPT-6 Sol/high;
all approval, security, release, and fresh-verifier boundaries remain intact.
This slice adds no main-session typed-dispatch receipt field; existing child
receipt schemas remain unchanged.

The role manifest is seven recursively discovered TOMLs. Pilotfish validates a
single approved staged manifest and rejects duplicate names, filename/name
mismatches, extra roles, path escape, and role drift. Only release-pinned prior
canonical bytes may upgrade automatically; customized same-name roles still
fail closed. This local validation does not claim to duplicate Codex's layered
loader, which may merge role data across layers. The native smoke instead
requires a one-user-layer staged home.

## Policy and evidence

Policy constructs typed named-role requests with a non-empty message, installed
`agent_type`, lowercase schema-safe task name, and `fork_turns = "none"` or
`"1"` through `"3"`. It forbids full history for named roles, untyped retries,
and child model, reasoning-effort, service-tier, and context overrides.

### Plan readiness

Large work keeps shared constraints in a program envelope and splits only
independent execution slices. Concrete security, irreversible or external,
data, release, or cross-component acceptance risk triggers a fresh
`plan-verifier`; file count or “non-trivial” alone does not. `REVISE` returns
all known P0-P2 blockers in one pass; P3/P4 and adjacent hardening do not block.

After two automatic revisions for one unit, the main session stops resubmitting,
dispositions every blocker as `FIX`, `DEFER`, or `REJECT`, and narrows, splits,
or continues independent slices. User input is reserved for unresolved P0/P1,
product or authority choices, or an original scope that can no longer be met.

### Outcome verification

A risk-triggered fresh verifier receives the exact completed-work claim and
acceptance after the primary flow has been exercised. It returns `CONFIRMED`,
`REFUTED`, or `INCONCLUSIVE`; P3/P4 advisories do not block confirmation, while
`REFUTED` requires a reproducible P0-P2 blocker. A known blocker takes
precedence over missing evidence for another condition; otherwise any
unevaluated required condition is `INCONCLUSIVE`. The verifier reads and runs
checks but never plans, edits, fixes, delegates, or exposes raw secrets.

Role verdicts are evidence, not implementation or scope authority. The main
session records `FIX`, `DEFER`, or `REJECT` after adjudicating reproducibility,
scope, claim relevance, priority, and confidence. P0 freezes the affected
slice; P1 is fixed or paused for user direction. Regressions caused by the
reviewed implementation remain
claim-relevant even when the brief omitted the affected flow, and an introduced
P2 regression must be fixed or paused rather than hidden by a narrowed claim.
Other bounded in-acceptance P2 is fixed, while lower-priority findings may be
reported with a narrowed claim. An inconclusive gate is retried once only after
its prerequisite materially changes.

### Adaptive intent routing

The orchestration policy now selects among three initial interaction shapes:
`execute` for clear bounded work, `explore_then_plan` for clear but broad or
high-impact work, and `co_discover` for an idea without a stable product
boundary. These are descriptive starting points, not a keyword classifier or
an exhaustive scenario list. Route selection records intent confidence,
five-band change impact, reversibility, discovery budget, blocking decisions,
and the next gate.

Discovery has a grounding floor and a stopping ceiling. The default bands are
`none`, `minimum`, `bounded`, and `deep`, measured in logical inspections,
searches, and reversible probes. A missing floor causes the session to state
uncertainty; an exhausted ceiling causes it to narrow, pause, or ask rather
than silently authorize writes.

Material choices use an AskUserQuestion-style decision card. It is one concise,
high-level user checkpoint containing the current interpretation, recommended
default, relevant scope and exclusions, decision options, and the next
reversible slice. The default remains autonomous: low-risk, reversible,
scope-clear work
and bounded exploratory probes continue with a reasonable local default. The
card appears only when the choice can change the outcome, permission, security,
or acceptance; it does not replace the internal Plan or turn ordinary ambiguity
into a user approval step. Secondary details are deferred until the selected
direction resumes and reaches a new material boundary.

The native card is the default interaction surface. An independently maintained
MCP elicitation bridge may be installed as an optional structured transport for
the same checkpoint when the Codex host exposes form elicitation. It is not a
Pilotfish core dependency, does not replace `request_user_input`, and must
preserve the card schema, affected scope, exclusions, approval boundary, and
resume point. Unsupported, cancelled, timed-out, or invalid MCP responses fall
back to the native card or concise text checkpoint.

### Outcome-level continuation

The unit of execution is the requested user-visible outcome, not one command,
tool call, or checklist item. A clear `execute` request defaults to
`execution_scope=outcome` and `continuation_mode=attended_until_acceptance`.
The main session continues through necessary commands, phases, role handoffs,
and verification; a phase update is progress reporting and does not ask for
approval.

Explicit “only this step”, “只檢查這個檔案”, or “只改這個 module” wording
selects `step` or `slice` and stops at that named boundary. Unclear product
direction uses the smallest reversible slice and stops for a `decision`.
Acceptance stops the requested outcome. Approval, security, release,
destructive, external, and irreversible gates stop at `material_gate` before
acceptance. Work after acceptance is limited to the requested outcome and its
acceptance evidence.

The internal contract records `execution_scope`, `continuation_mode`, and
`stop_condition`. The offline evaluator checks these fields as semantic policy
evidence; it does not prove that every live model or host will comply.

Direction checks reuse the existing `verifier` role through an explicit
`direction_checkpoint` contract. `CONTINUE` preserves the path, `PIVOT`
requires a bounded re-plan, and `ROLLBACK` stops new writes and identifies the
latest verified good checkpoint. Missing evidence remains `INCONCLUSIVE`.
External, destructive, release, security-sensitive, and irreversible actions
retain their existing approval and containment gates. The offline route and
checkpoint evaluators are semantic behavior evidence only; they do not prove
live model routing or native dispatch.

### Long autonomous runs

`AUTO`/`ASK` is required for likely long unattended work. An attended task with
clear scope continues through its outcome without selecting a mode merely
because it has many commands or phases. Absence, sleeping, or leaving the
agent alone is not authority; explicit “continue while I am away” selects
`AUTO`. `AUTO` covers approved, reversible scope and P2 adjudication, not new
version-control, publish, install, credential, destructive, external, scope,
or spending authority. `ASK` uses Codex `request_user_input` only when exposed,
may use the optional MCP bridge when configured, and otherwise pauses the turn.

Normal recovery is one targeted recheck of the original reproduction plus a
bounded basic regression. Five materially changed P1/P2 passes remain an
emergency ceiling for high-risk, claim-critical recovery, not a quota.
Verification identity includes the complete tested candidate, claim,
acceptance, contract, external evidence or prerequisites, and environment; a
prior verifier's own output is not a change.
The candidate fingerprint covers committed head, tracked and staged diff,
untracked input paths plus content, and dirty submodule content. Artifact
digests complement source identity unless the artifact is the sole deliverable.
A fifth failure pauses only that slice and its dependents when risk is not
cross-cutting; recovery stops earlier when another pass would only search
adjacent risk.

### Continuation liveness

User input does not necessarily replace the task already in progress. The
main-session policy therefore keeps an unfinished root objective active when a
message answers a pending decision, steers or corrects the work, asks for
status or explanation, or resumes a pause. Contextually clear replacement
intent may supersede it without a literal cancellation phrase.

Before pausing, the main session exposes the objective, current phase or slice,
pending blocker or decision, and exact resume point. A decision response binds
to that point only when it resolves the decision unambiguously; otherwise the
pause remains and the session asks one concise clarification. Status and
explanation requests resume only work not gated by the unresolved decision;
otherwise the session remains paused. An incomplete objective cannot end with a
normal final: the session must continue or return `PAUSED_NEEDS_USER` with the
blocker, question, and resume point. A user-requested pause instead records the
objective, phase, and resume point without inventing a blocker or question. It
remains active through status or explanation requests until the user explicitly
resumes or clearly replaces the objective.

This is a prompt-level liveness contract. It neither persists task state outside
the conversation nor changes Codex App, app-server, approval, security, or
scope behavior. Static assertions prevent accidental policy removal; they are
not behavioral proof that a live model or host always complies.

The verifier is post-hoc evidence classification, not a pre-execution cancel
hook. Native proof requires one `spawn_agent` with exact typed arguments,
call/activity correlation, and child `turn_context.model` and
`turn_context.effort` matching the installed role. It records only redacted,
hashed identifiers and receipt fields. A namespace and an undocumented rollout
marker are neither required nor sufficient evidence.

## Staging boundary

The native smoke first copies the post-install active target into a distinct,
not-yet-existing staged home using canonical containment, confined reads,
TOCTOU checks, cleanup on failure, and exclusive atomic no-replace publication.
Only the canonical native-agent config projection, hashed policy/manifest
input, and `auth.json` are materialized. Unrelated active config and existing runtime
metadata are outside the smoke projection and are not copied or hashed. Before
launch the staged home is an exact minimal allowlist; Codex creates its own
runtime state there only after preflight. The verifier compares active and
staged projected config, policy, and canonical role-manifest hashes before it
can launch Codex. It also rejects project-local configuration and instruction
discovery in the supplied smoke working directory.

`NATIVE_OK` is the only completed native gate. `SKIPPED` remains incomplete and
`FAILED` blocks migration completion. Historical adapter behavior belongs only
to explicitly labeled offline fixtures and archived evidence.
