# SPEC — Dispatch Verification & Enforcement

- Slug: `dispatch-verification`
- Status: Draft
- Owner: Miyago
- Created: 2026-07-15

## Context

pilotfish-codex claims that a main Codex session routes bounded work to six
role-based subagents (`scout`, `explore`, `mech-executor`, `executor`,
`verifier`, `security-executor`), each pinned to a model + reasoning effort via
`~/.codex/agents/*.toml`. A verification pass on Codex CLI `0.144.4` confirmed
the **plumbing is real and the schema matches**, but surfaced two gaps that mean
"effective, role-conforming model dispatch" is currently **not guaranteed and
not provable**.

### What was confirmed (baseline, not in scope to fix)

- `multi_agent` feature flag is `stable = true`.
- The binary ships real subagent tooling: `spawn_agent`, `close_agent`, `wait`,
  `interrupt_agent`, `send_input`, `resume_agent`, plus `SubagentStart` /
  `SubagentStop` hooks.
- `spawn_agent` accepts `agent_type`, `model`, `reasoning_effort`,
  `service_tier` overrides. Default: "Spawned agents inherit your current model
  by default … set `model` only when an explicit override is needed."
- Codex reads the exact TOML keys pilotfish writes: `model`,
  `model_reasoning_effort`, `sandbox_mode`, `developer_instructions`, `name` /
  `nickname_candidates` (binary contains matching keys and the validation string
  `developer_instructions cannot be blank`).
- The six roles, `config.toml` model, and `AGENTS.md` markers are installed.

## The two gaps (in scope)

### Gap A — Headless (`codex exec`) exposes no subagents

`codex exec` provides **no** `spawn_agent` tool. Verified by running `codex exec`
twice, including with `-c features.multi_agent=true -c
features.enable_fanout=true` forced — the model still answered "No" when asked
whether it had `spawn_agent`. Delegation is an **interactive-session-only**
capability. Any workflow driven through `codex exec` (or an equivalent headless
path) gets zero delegation: the main model does everything itself and the entire
role-distribution design is inert.

Impact: silent. Nothing errors. A user automating with `codex exec` believes
pilotfish is routing work when it is not. The README and docs present delegation
as the product without stating this boundary.

### Gap B — No end-to-end proof that dispatch happens, and no enforcement

The repository's only test, `tests/test_policy.py`, checks **template
self-consistency** (filenames match `name`, policy prose contains no model
names, leaf roles say "Never spawn further subagents", version stamp present).
It asserts **nothing** about runtime behavior:

- that Codex actually loads the six roles,
- that a spawned role runs on its bound model / effort,
- that the orchestrator delegates according to `AGENTS.md` on a realistic task.

Role-conforming behavior therefore rests entirely on the main model voluntarily
following `AGENTS.md` prose. `docs/design.md` explicitly records that enforcement
hooks were "Deliberately left out". There is no `SubagentStart` guard that would
catch a role spawned on the wrong model, and no eval that a given task class
triggers the correct role. "Behavior matches role distribution" is currently an
unverified assumption.

## Goals

1. Make Gap A explicit and non-silent: document the headless boundary and, where
   feasible, detect or warn.
2. Provide a runtime proof path for Gap B: an end-to-end check that a spawned
   role actually runs on its bound model/effort, plus a minimal enforcement
   option that catches mismatches.

## Non-goals

- Rewriting the role set, models, or policy prose (baseline is sound).
- Making `codex exec` support subagents (not controllable from this project;
  it is an upstream Codex capability).
- Full behavioral eval of orchestrator judgment quality (a later, larger effort;
  this spec covers only mechanism proof + mismatch enforcement).

## Approaches / ADRs

### ADR-1 — Headless boundary is documented, not worked around

Codex controls whether `exec` exposes subagents; pilotfish cannot add them.
Decision: treat the boundary as a documented product constraint (README +
design.md), and — if an install/verify command exists — emit a one-line notice
when the active surface is headless. Rejected: attempting to shim delegation in
`exec` (out of our control, would be fragile).

### ADR-2 — E2E proof via `codex app-server`, not the TUI

The TUI cannot be driven headlessly for CI. The interactive multi-agent tools
are backed by `codex app-server` (JSON-RPC). Decision: build the runtime proof
against `app-server` so it is scriptable. It spawns each role and asserts the
subagent's effective model/effort equals the TOML binding. Open risk: app-server
JSON-RPC surface is experimental and may change; the test must degrade to
"skipped, unsupported" rather than fail spuriously.

### ADR-3 — Enforcement is an opt-in `SubagentStart` hook, staying policy-first

design.md's "policy-only until discipline slips" stance holds. Decision: ship a
`SubagentStart` guard as an **optional** add-on (not default install) that
rejects or warns when a spawned role's model/effort does not match its TOML.
Keeps the default install policy-only; gives teams who want a hard gate one.

## Acceptance

See `TESTS.md`. Summary: docs state the headless boundary; an app-server-based
e2e proves at least one role binds to its configured model/effort (or cleanly
skips when unsupported); an optional `SubagentStart` guard flags a deliberately
mismatched role.
