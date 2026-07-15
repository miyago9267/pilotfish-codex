# TESTS — Port Hardening

All retained acceptance criteria are satisfied by Nanako's existing template
tests or the static validator added in `48e291f`.

## Security boundaries

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

## Validator self-guard

- **AC-B2**: The agent-TOML validator shall reject an unknown key, an invalid
  `sandbox_mode`, an invalid `web_search`, an invalid
  `model_reasoning_effort`, a missing required key, and blank developer
  instructions.

## Runtime boundary

Runtime dispatch and e2e acceptance remain in the related
`dispatch-verification` spec.
