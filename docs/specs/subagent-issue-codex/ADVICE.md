# ADVICE — Claude review of `subagent-issue-codex`

- Reviewer: Claude
- Date: 2026-07-15
- Verdict: **Adopt as the implementation source**, with the amendments below.
  This spec is stronger than `subagent-issue-claude` on engineering
  discipline; the Claude spec should be downgraded to a supplement (see
  Reconciliation).

## What this spec gets right (adopt as-is)

- Explicit `max_concurrent_threads_per_session = 4` with the verified
  root-inclusive semantics — a cost bound the Claude spec lacked.
- ADR-3 fail-closed: never retry a rejected named role as an untyped spawn
  that would silently inherit Sol.
- Smoke anti-forgery design: child thread ID resolved from the spawn result
  instead of filename/timestamp guessing (strictly better than the mtime-based
  rollout lookup used in the 2026-07-15 Claude probe), plus install-vs-template
  drift preflight before spending quota.
- ADR-5 separation of static packaging proof from live runtime proof.
- AC-E1 excluding pricing/benchmark figures not backed by primary sources.
- The new-session requirement (config changes do not affect a running root
  session still holding the reserved schema) — a real footgun worth D1.

## Amendments requested

### A1 — Relax the exact-4 concurrency validation (C4, AC-C5)

`max_concurrent_threads_per_session` is a tunable, not an invariant.
Hard-coding "reject anything other than four" turns a legitimate user choice
(3, or 6) into a validation failure. Amend to: the key MUST be present and a
positive integer `<= 8` (the bound the CLI's own warning string uses); any
non-default value warns rather than fails.

### A2 — Evidence or downgrade the `enabled` conflict claim (SPEC.md L32-34)

"explicitly enabling V2 conflicts with the existing `[agents].max_threads`
fallback" is asserted in the Outcome section but never appears in Verified
evidence. Omitting `enabled` is the right call regardless (Sol's V2 selection
is server-side), but AC-C2's fail condition currently rests on an unverified
premise. Either verify the conflict on 0.144.4 or mark the rationale
unverified and re-justify AC-C2 solely as "avoid forcing V2 where the server
already decides".

### A3 — Record the Sol-parent evidence so the Terra smoke is sufficient

The regression trigger is Sol being server-selected into MAv2; a Terra/low
parent green-light strictly proves only the Terra path. The Sol path was
verified once on 2026-07-15: an exec probe with a `gpt-5.6-sol`/xhigh parent
(session `019f6631-5b42-73e3-a936-d5fa353d4656`) spawned
`agent_type='scout'`, `fork_turns='none'`, and the child rollout
`turn_context` recorded `"model":"gpt-5.6-luna"`. Add this to Verified
evidence so the cheap Terra-parent smoke stands on a recorded Sol-path
baseline instead of an unstated assumption.

### A4 — Reconciliation with `subagent-issue-claude` (X1)

Both specs' Phase 1/2 write the same four files
(`templates/config.snippet.toml`, `install/AGENT-INSTALL.md`,
`templates/agents-md.orchestration.md`, static validation). Disposition:

- Implementation proceeds from THIS spec only; Claude spec tasks T1–T5 are
  superseded.
- Two tasks this spec deliberately excludes (X2, AC-U4) survive in the Claude
  spec as separate work: T7 — reconcile `dispatch-verification` (Gap A
  superseded under MAv2; Gap B gains the rollout `turn_context.model` proof
  method) — and T8 — upstream exit tracking detail. Someone must own that
  gap; it should not fall between the two specs.

### A5 — Version control

This spec directory sat untracked while its status said "Ready for approval";
repo rules require `docs/specs/` changes to be committed. Commit the draft
(approval or not) so the decision trail survives.

## Minor notes (no action required)

- "commit #32751" is labeled like a PR but links a raw commit; harmless.
- Smoke's `multi_agent_version = "v2"` requirement should map a V1-active
  turn to SKIPPED ("adapter not exercised"), which the SKIPPED contract in
  AC-R4 already permits — just make the reason string explicit in R5.
