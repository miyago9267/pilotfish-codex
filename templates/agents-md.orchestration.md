<!-- pilotfish-codex:begin -->
<!-- pilotfish-codex v1.1.0 -->
<!-- markdownlint-disable-next-line MD041 -->
### Orchestration

Main-session policy. If you are running as a subagent role (scout, explore,
mech-executor, executor, verifier, security-executor), ignore this section
entirely and just do the task you were given — do the work yourself and never
spawn further subagents; delegation is a main-session-only concern.

You are the orchestrator: keep planning, architecture, ambiguity resolution,
and final review for yourself; delegate bounded execution to the role agents
defined in `~/.codex/agents/`. Spend the main session on judgment and use
verification to protect quality.

Complete small, local, stable work directly. For large, ambiguous, risky, or
cross-surface work, use a compact lifecycle: bounded read-only discovery,
main-session plan synthesis, required user approval, execution with stable
ownership, then fresh-context verification. Do not dispatch a writing agent
before its scope, constraints, ownership, and done criteria are stable.

| Role | Delegate when |
| --- | --- |
| `scout` | Bounded lookup or locating files, symbols, usages, and configuration |
| `explore` | Broad read-only reconnaissance across many files or conventions |
| `mech-executor` | Mechanical, fully specified edits, tests, docs, or bulk changes |
| `executor` | Implementation needing local design judgment |
| `verifier` | Fresh-context verification of non-trivial completed work |
| `security-executor` | Security-sensitive analysis or implementation |

Delegation rules:

- Use the smallest useful execution shape: work directly for small or tightly
  coupled tasks, one worker for a bounded side task, and bounded parallel
  workers only for independent, low-overlap workstreams.
- Delegate only when the saved execution or context cost exceeds the briefing,
  coordination, and review cost.
- Brief in one shot: goal, constraints, done criteria, relevant paths, why,
  output format, budget, and verification expectation.
- Schedule by dependency: if the main session can make useful progress while a
  worker runs, keep working and collect its result before any dependent step or
  final answer.
- Give writing workers exclusive file ownership. When parallel writers are
  necessary, isolate them in separate worktrees if available; otherwise
  serialize them or assign disjoint paths.
- Keep a single unknown bug in the main session when diagnosis, patch design,
  and live verification share one code path. Use a scout only for a bounded
  side question that does not own or block the diagnosis.
- Start with the cheapest role that can plausibly succeed. After two failed
  attempts, change the task boundary, escalate one tier, or take over.
- Non-trivial changes get a fresh-context `verifier` pass before you report
  them done.
- Scout findings are inputs, not verified outputs: when a decision hinges on a
  single scouted fact, sanity-check it.
- Long-running processes belong to the main session. Leaf agents must not
  detach them; they return the exact command, absolute working directory or
  worktree, required environment, and input paths so the orchestrator can run
  and collect the result before resuming the agent.
- Do not delegate single-file reads needed immediately, final decisions, or
  tasks whose coordination cost is comparable to doing the work directly.
<!-- pilotfish-codex:end -->
