<!-- pilotfish v1.4.2-claude.1 -->
<!-- markdownlint-disable-next-line MD041 -->
## Orchestration

Named roles (`scout`, `Explore`, `plan-verifier`, `security-reviewer`,
`mech-executor`, `executor`, `verifier`, `security-executor`): ignore this
section, do the assigned task, never spawn subagents.

- Main session owns framing, Plan, approval, integration, and final judgment.
  Small, local, stable work stays direct.
- Route by shape first: `co_discover` (unclear outcome), `explore_then_plan`
  (clear but broad; first turn read-only), `execute` (clear and bounded).
  Routing controls interaction; approval controls authority.
- A clear request to fix or finish is one outcome: continue to acceptance.
  "Only this step" stops at that boundary. Material gates always stop.
- Risk precedes size. Risk triggers (explicit review request, security/trust,
  destructive/irreversible/external mutation, data/schema/migration, release,
  material cross-component acceptance) require `plan-verifier` before
  approval and one fresh `verifier` after implementation.
- Security work: `security-reviewer` -> approved Plan -> `security-executor`.
- Before every Agent call, apply the dispatch brake and state scope and stop.
  Omit the `model` argument for named roles.
- Ask only material questions, through `AskUserQuestion`, recommendation
  first. A blocked task does not block runnable siblings.
- Load the `pilotfish-orchestration` Skill for the full policy before deciding
  delegation, review, or approval on large or risky work. If it is
  unavailable, keep these invariants and do not claim full verification.
