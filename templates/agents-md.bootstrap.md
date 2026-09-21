<!-- pilotfish-codex:begin -->
<!-- pilotfish-codex v1.8.0-rc.6 -->
<!-- markdownlint-disable-next-line MD041 -->
### Pilotfish always-on bootstrap

Pilotfish orchestration is active. Preserve the user's Persona and Agent Rules;
Pilotfish supplements them and does not replace their precedence boundary.

- Apply approval, security, blocked-task isolation, and parent-accountability
  invariants to work in this session.
- Route by capability before the first action: keep one-command/one-action
  work on cheap Luna; automatically use `executor` for design, tool choice,
  interpretation, multi-step, or uncertain work.
- `mech-executor` and `scout` are baseline-only: keep their installed Luna
  bindings, never request Astra, and route to `executor` or `verifier` when
  work exceeds their boundary instead of upgrading the child in place.
- Treat a clear request to fix or complete something as one outcome: continue
  through its necessary commands, phases, and verification until acceptance.
  Phase updates do not require approval; explicit “only this step/slice” wording
  remains a named stop boundary.
- For a clear bounded workstream or mandatory review, proactively dispatch the
  least expensive matching native typed role. Keep one tightly coupled local
  action in the parent; do not create a child for every command or wait for the
  user to name the next phase.
- Use `AUTO`/`ASK` only for explicit unattended continuation. Preserve material
  approval, security, release, destructive, external, and irreversible gates.
- When the user explicitly starts the main session with Astra, use the
  `astra-thinking` contract: keep named inputs, make one sufficient pass, and
  stop when acceptance evidence is sufficient. Delegate mechanical or
  repetitive work to the existing Luna roles.
- The Astra main-session guard is advisory: `max_tool_calls=12` and
  `max_wall_seconds=300` are not provider-enforced quotas. Keep the mode
  session-scoped and never switch the main model because a task is difficult.
- An invalid override or unavailable Astra model is a fail-closed activation
  error before task work. Start a new no-flags session to use the normal
  Luna/Sol policy.
- Keep `plan-verifier` on `gpt-5.6-sol@high`; approval, security, release, and
  fresh-verifier gates remain unchanged.
- Use the `pilotfish-orchestration` Skill for the complete routing, role,
  planning, and verification workflow when it is available.
- If the Skill or Plugin is unavailable, keep these core invariants active and
  use a bounded fail-soft fallback; do not claim full Pilotfish verification.

<!-- pilotfish-codex:end -->
