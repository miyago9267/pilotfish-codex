---
name: pilotfish-orchestration
description: Apply Pilotfish's bounded task routing, Plan and approval gates, typed role delegation, security separation, blocked-task isolation, and fresh-context verification. Use for coding, debugging, refactoring, architecture, security-sensitive work, multi-step repository changes, or any request where execution mode, approval, role selection, or outcome verification matters.
---

# Pilotfish orchestration

Use this Skill as the detailed workflow behind the always-on Pilotfish bootstrap
in the active root `AGENTS.md`. Keep the bootstrap authoritative for safety and
approval invariants; use this Skill for the complete routing and verification
contract.

## First move

Classify the request before acting:

- `execute`: clear, bounded, reversible work; inspect the smallest relevant seam
  and implement directly or use one bounded executor.
- `explore_then_plan`: broad, cross-module, migration-heavy, high-impact, or
  costly-to-reverse work; establish evidence and a provisional Plan first.
- `co_discover`: unclear product intent, target user, MVP, or acceptance; ask only
  the smallest decision-changing question after low-cost reconnaissance.

Keep the task boundary as `goal -> in-scope -> stop condition`. Do not expand
into adjacent cleanup unless correctness or safety requires it.

## Role routing

Use the native Pilotfish roles when the task benefits from independent bounded
work:

- `scout`: read-only repository reconnaissance on an exclusive surface.
- `plan-verifier`: challenge a material Plan before approval.
- `executor`: bounded implementation requiring local judgment.
- `mech-executor`: fully specified mechanical repetition with exclusive ownership.
- `mech-executor` and `scout` are baseline-only Luna roles; never pass an Astra
  override. Route work beyond either boundary to `executor` or `verifier`.
- `security-reviewer`: pre-approval security evidence.
- `security-executor`: approved security-sensitive implementation.
- `verifier`: fresh-context falsification after primary acceptance.

The root session owns scope, Plan synthesis, approval, integration, finding
disposition, and final judgment. Do not delegate the first tightly coupled root
cause of one unknown bug or any work that depends on evolving shared evidence.

## Approval and security

Never treat role approval, hook trust, or Plugin availability as authorization
for policy integration, external mutation, destructive action, release, or
security-sensitive work. Security-sensitive work follows:

```text
security-reviewer -> approved Plan -> security-executor -> verifier
```

For material Plans, independently review the executable envelope before calling
it ready. `READY` is readiness, not user approval. Preserve mandatory permission,
security, and external-operation gates.

## Blocked tasks and parallel work

Track independently runnable tasks separately. A blocked task does not block
sibling tasks; schedule runnable siblings first. Parallelize only when there is
no dependency path, write conflict, or shared mutable resource. When no runnable
task remains, report the exact blocker and resume point once.

## Verification

Exercise the primary user-visible flow first. For risk-triggered work, perform a
fresh-context verifier pass at the smallest coherent integration boundary. Report
`CONFIRMED`, `REFUTED`, or `INCONCLUSIVE`; tests and builds are evidence but do
not replace independent falsification. Recheck the original failure after every
blocking fix and keep claims no broader than the evidence.

Read the detailed contract only when needed:

- [full orchestration policy](references/orchestration-policy.md)
- [role contract](references/role-contract.md)
- [verification contract](references/verification-contract.md)
- [recovery contract](references/recovery-contract.md)
