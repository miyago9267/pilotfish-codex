# SPEC — Port Hardening: Security Boundaries & Test Robustness

- Slug: `port-hardening`
- Status: Done
- Owner: Miyago
- Created: 2026-07-15
- Source PR:
  [#1 — port Pilotfish v1.2 orchestration to Codex](https://github.com/miyago9267/pilotfish-codex/pull/1)
  (author @Nanako0129)
- Related spec:
  [`dispatch-verification`](../dispatch-verification/SPEC.md) — this spec
  extends its Gap A / Gap B rather than redefining them.

## Context

PR #1 ports Pilotfish v1.2's phase-aware orchestration to native Codex: seven
roles, Discovery → Plan → Approval → Execution → Verification lifecycle, a
Remora 0.1.10 model/effort map, `multi_agent` config, and a rewritten installer
runbook with v1.0.x migration logic.

The port's design, routing, role structure, and installer are accepted as-is.
Review found one concrete gap: `codex --strict-config doctor` validates
`config.toml`, but not `agents/*.toml`. This completed batch adds that missing
static validation and corrects the installer instructions. Nanako's existing
tests already cover the role sandbox map and leaf-only delegation contract.

## Evidence (live, Codex CLI 0.144.4)

Verified in an isolated `CODEX_HOME`, not assumed:

- `--strict-config` **does** reject unknown keys (bogus key → exit 1), so it is
  a valid gate for `config.toml`.
- `features.multi_agent = true`, `agents.max_threads = 3`, `agents.max_depth = 1`,
  `model = "gpt-5.6-sol"` all load clean under `--strict-config` → **config keys
  legal**.
- `web_search = "live"` is a valid `WebSearchMode` enum value
  (`disabled / cached / indexed / live / custom`) → **`security-reviewer` key
  legal**.
- `sandbox_mode` enum is `read-only / workspace-write / danger-full-access` →
  both values used by the port are valid.
- **Gap:** `codex --strict-config doctor` validates `config.toml` only. There is
  no CLI that statically validates `agents/*.toml`, so unknown keys or bad enum
  values in an agent file are **not** caught by the installer's stated Step 4
  command.
- `model_reasoning_effort = "max"` cannot be validated statically; acceptance is
  model-catalog-dependent and the placeholder `gpt-5.6-*` names are not in any
  local catalog. This is a runtime boundary, not a static one.

## Completed outcomes

- G1 — Satisfied by Nanako's existing routing-map tests: read-only reviewers,
  explicit `workspace-write` for `verifier`, and inherited parent sandbox for
  executors.
- G2 — Satisfied by `install/validate_agents.py`: required keys, known-key
  allowlist, and enum validation for every agent TOML.
- G3 — Satisfied by Nanako's existing tests: `max_depth = 1` and a leaf-only
  contract for every role.

## Non-goals

- The seven-role structure, phase-aware lifecycle, and approval gates.
- The Remora model/effort map, including `executor` on `gpt-5.6-luna` `max`.
- Retiring `explore`; the SHA-256-pinned retired assets stay (that pinning is an
  integrity control worth keeping, not slimming away).
- Runtime dispatch proof and enforcement hooks — owned by `dispatch-verification`
  (Gap B).
- Prose-assertion cleanup and installer slimming; neither is required to close
  the static-validation gap.

## ADR

- **ADR-1 — Accept the port, scope to hardening.** The design review concluded
  the port is correct; changing routing or structure would fork from upstream
  for no security benefit. The only local adjustment is the missing static
  agent-TOML validation and its installer documentation.
- **ADR-2 — Agent TOMLs get their own validator.** Because `codex --strict-config`
  covers only `config.toml`, agent-file validity must be proven by an explicit
  parser + key allowlist + enum check. The installer text must stop implying
  `doctor` validates agent files.
