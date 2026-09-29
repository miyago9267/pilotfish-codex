---
name: pilotfish-orchestration
description: Full Pilotfish orchestration workflow - interaction-shape routing, Plan and approval gates, dispatch brakes, named-role delegation, security separation, verification, recovery, outcome continuation, review intent, decision checkpoints, and blocked-task isolation. Load before deciding delegation, review, or approval for large, architectural, risky, or cross-surface work.
---
<!-- pilotfish-claude v1.4.2-claude.1 -->

# Pilotfish orchestration

This Skill is the detailed workflow behind the always-on Pilotfish bootstrap.
The bootstrap stays authoritative for its invariants; this Skill supplies the
complete contract.

## First move

1. Classify the interaction shape: `co_discover`, `explore_then_plan`, or
   `execute` (see the policy's routing section).
2. Set `execution_scope`, `review_intent`, and the discovery budget from the
   workflow extensions.
3. Apply risk triggers before size, then the phase gate and dispatch brake
   before every Agent call.

## References

Read only the part needed for the current decision:

- [orchestration-policy.md](references/orchestration-policy.md): routing,
  lifecycle gates, dispatch and ownership, severity, recovery, AUTO/ASK,
  parallel and runtime mechanics.
- [workflow-extensions.md](references/workflow-extensions.md): outcome-level
  continuation, turn-scoped review intent, discovery budget, decision
  checkpoint through `AskUserQuestion`, task ledger and blocked-task
  isolation, continuation across user input, review-service circuit breaker,
  and verifier direction checkpoint.

If a reference is unavailable, keep the bootstrap invariants, work fail-soft,
and do not claim full Pilotfish verification.
