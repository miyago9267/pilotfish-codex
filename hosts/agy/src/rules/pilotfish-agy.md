<!-- pilotfish-agy:begin -->
## Pilotfish orchestration (agy only)

This section applies only to the agy (Antigravity CLI) main session. If you are
not in agy, or `invoke_subagent` and the roles below are unavailable, ignore it.
If you are running as one of these roles, ignore it and do the task yourself
without delegating.

| Role | Boundary |
|---|---|
| `scout` | Read-only reconnaissance; file:line findings |
| `plan-verifier` | Pre-approval Plan challenge; `READY` or `REVISE` |
| `security-reviewer` | Pre-approval read-only security evidence |
| `mech-executor` | Fully specified mechanical implementation |
| `executor` | Bounded implementation requiring local judgment |
| `verifier` | Completed-work challenge; `CONFIRMED`, `REFUTED`, or `INCONCLUSIVE` |
| `security-executor` | Approved security-sensitive implementation |

The main session keeps framing, Plan, architecture, integration, and final
judgment. Do small, local, already-stable work directly.

Before any large, ambiguous, architectural, risky, cross-surface, or
explicitly plan-first task, load the `pilotfish-orchestration` skill and follow
it. For those tasks only (not small, local edits), these gates hold even
without the skill:

- No source writes before Miyago explicitly approves a Plan that a fresh
  `plan-verifier` returned `READY` on. Auto-approved tool permissions are not
  Plan approval.
- Invoke named roles by name only; tier and tools come from their definitions.
- Children never delegate. Never swap `plan-verifier` and `verifier`.
- After integration, a fresh `verifier` checks the exact claim before you
  report `完成`.
<!-- pilotfish-agy:end -->
