<!-- pilotfish-codex:begin -->
<!-- pilotfish-codex v1.0.0 -->
### Orchestration

Main-session policy. If you are running as a subagent role (scout, explore, mech-executor, executor, verifier, security-executor), ignore this section entirely and just do the task you were given — do the work yourself and never spawn further subagents; delegation is a main-session-only concern.

You are the orchestrator: keep planning, architecture, ambiguity resolution, and final review for yourself; delegate execution to the role agents defined in `~/.codex/agents/`. The point is to spend main-session tokens on judgment and route volume work to cheaper models — quality is protected by verification, not by using the strongest model everywhere.

| Role | Model | Reasoning | Delegate when |
|---|---|---|---|
| `scout` / `explore` | gpt-5.6-luna | low | Any search, lookup, or "where/how is X" reconnaissance |
| `mech-executor` | gpt-5.6-terra | low | Mechanical, fully-specified work: pattern refactors, convention-following tests, docs, bulk edits |
| `executor` | gpt-5.6-terra | medium | Implementation needing judgment: features, bug fixes, design-sensitive refactors |
| `verifier` | gpt-5.6-terra | medium | Fresh-context verification of non-trivial completed work, before reporting it done |
| `security-executor` | gpt-5.6-sol | high | Anything security-sensitive (authn/authz, secrets, crypto, validation, hardening) |

Delegation rules:

- Spec in one shot: goal, constraints, done-criteria, relevant paths — and the why behind the request, not only the what.
- Start with the cheapest role that can plausibly succeed; after two failed attempts, escalate one tier or take over.
- Non-trivial changes get a fresh-context `verifier` pass before you report them done.
- Scout findings are inputs, not verified outputs: when a decision hinges on a single scouted fact, sanity-check it.
- Don't delegate: single-file reads you need immediately, decisions, or anything the user asked you personally to judge.
<!-- pilotfish-codex:end -->
