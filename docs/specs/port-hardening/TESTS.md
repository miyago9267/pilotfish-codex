# TESTS — Port Hardening

EARS acceptance criteria. Priority 1 = security + boundary; Priority 2 =
installer slimming. Static unless marked runtime.

## P1 — Security boundaries

- **AC-S1**: For each read-only role (`scout`, `plan-verifier`,
  `security-reviewer`), the template test shall assert
  `sandbox_mode = "read-only"`.
- **AC-S2**: For each writer role, the test shall assert the sandbox contract:
  `verifier` explicitly declares `workspace-write`; `executor`,
  `mech-executor`, and `security-executor` omit `sandbox_mode` entirely and
  inherit the parent session. This criterion does not claim they are always
  writable.
- **AC-S3**: For every agent TOML, the validator shall accept only keys in the
  known Codex agent-schema allowlist (`name`, `description`, `model`,
  `model_reasoning_effort`, `sandbox_mode`, `web_search`, `developer_instructions`,
  `nickname_candidates`). An unknown key shall fail.
- **AC-S4**: Where an agent declares `web_search`, its value shall be a member of
  the Codex `WebSearchMode` enum (`disabled`, `cached`, `indexed`, `live`,
  `custom`). `security-reviewer` shall be `live`.
- **AC-S5**: Every agent's `model_reasoning_effort` shall be one of
  `low`, `medium`, `high`, `max`. (Static string check; actual acceptance is
  model-catalog-dependent at runtime — noted, not asserted here.)
- **AC-S6**: The leaf-only property shall be asserted structurally:
  `config.snippet.toml` sets `agents.max_depth = 1`, and every role's
  `developer_instructions` states it cannot delegate / spawn further subagents.

## P1 — Boundary test robustness

- **AC-B1**: Template tests shall assert the structural contract only — role set
  equals the seven names, each role's model/effort/sandbox equals the routing
  map, the policy block has exactly one marker pair, and the version stamp is
  present. They shall not assert exact README or installer sentences.
- **AC-B2**: The agent-TOML validator shall be self-guarded by four independent
  failing fixtures: an unknown key, an invalid `sandbox_mode`, an invalid
  `web_search`, and an invalid `model_reasoning_effort`. This proves the key
  allowlist and every declared enum check can actually fail.
- **AC-B3**: Removing a brittle prose assertion shall not reduce contract
  coverage — every routing and boundary fact previously implied by prose is
  covered by an explicit structural assertion.

## P2 — Installer slimming

- **AC-I1**: Given an isolated `CODEX_HOME` with no prior Pilotfish install, a
  fresh install shall touch only `config.toml`, the seven declared files under
  `agents/`, and exactly one active policy file. A fixture without an existing
  policy shall create `AGENTS.md`; a fixture with a pre-existing
  `AGENTS.override.md` shall update only its owned block and shall not create
  `AGENTS.md`. A before/after filesystem snapshot shall fail on any other
  created or modified path.
- **AC-I2**: The v1.0.x migration path (pristine-backup selection, legacy effort
  pin, stale policy-block relocation) shall execute only when a legacy version
  stamp or a retired `explore.toml` / `Explore.toml` is actually detected; a
  clean fresh install shall not enter it.
- **AC-I3**: The installer text shall not claim `codex --strict-config doctor`
  validates agent files; agent validity shall be attributed to the explicit
  validator from AC-S3.

## Regression

- **AC-R-REG**: Existing `tests/test_policy.py` and the surviving
  `tests/test_templates.py` contract assertions shall continue to pass.
