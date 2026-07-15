# TASKS — dispatch-verification

Current batch. Check off per step; keep in sync with `PROGRESS.md`.

## Gap A — headless boundary explicit

- [ ] A1. Add a "Delegation is interactive-only" note to `README.md` (state that
      `codex exec` has no `spawn_agent`; delegation runs only in interactive /
      app-server sessions).
- [ ] A2. Record the headless boundary + the forced-flag evidence in
      `docs/design.md` under a "Known boundaries" heading.
- [ ] A3. If a verify/install command surfaces the active surface, emit a
      one-line notice when running headless. (Skip if no such hook exists —
      record the decision.)

## Gap B — runtime proof + optional enforcement

- [ ] B1. Spike: confirm `codex app-server` exposes the multi-agent JSON-RPC
      surface (`spawn_agent` and a way to read the child's effective
      model/effort). Record the exact method names and payload shape found.
- [ ] B2. Write an e2e that spawns one role (`scout`) via app-server and asserts
      its effective model == `gpt-5.6-luna` and effort == `low`. Must SKIP (not
      fail) when app-server / multi-agent is unavailable.
- [ ] B3. Extend the e2e to cover all seven roles' model/effort bindings.
- [ ] B4. Write an optional `SubagentStart` guard script that compares the
      spawned role's model/effort against `~/.codex/agents/<role>.toml` and
      warns/blocks on mismatch. Not part of the default install.
- [ ] B5. Add a policy test asserting the guard flags a deliberately mismatched
      role fixture.
- [ ] B6. Document how to enable the optional guard (README "Tuning" or a new
      "Enforcement" section).

## Wrap-up

- [ ] Update `PROGRESS.md` phase checkboxes.
- [ ] `docs/design.md` "Deliberately left out" row for enforcement hooks updated
      to reference the now-available opt-in guard.
