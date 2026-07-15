# SPEC — Port Hardening: Security Boundaries & Test Robustness

- Slug: `port-hardening`
- Status: Draft
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

The port's **design and routing are accepted as-is** (owner defers to the
upstream author). This spec scopes only the adjustments the owner wants before
or around merge, in priority order:

1. **Security boundaries** — make the capability boundaries the port relies on
   (read-only reviewers, write-capable executors, leaf-only delegation)
   *asserted and validated*, not merely stated in prose.
2. **Boundary / test robustness** — replace prose-coupled assertions with
   contract assertions, and add the agent-TOML validation the installer claims
   but does not currently perform.
3. **Installer slimming** — secondary. Reduce the 277-line runbook to a fresh
   install plus a simple stamped upgrade, gating the elaborate v1.0.x migration
   behind actual legacy detection.

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

## Goals

- G1 (P1) Every role's declared capability boundary is enforced by a test:
  read-only for `scout` / `plan-verifier` / `security-reviewer`, explicit
  `workspace-write` for `verifier`, and no `sandbox_mode` override for
  `executor` / `mech-executor` / `security-executor` so they inherit the parent
  session rather than claiming an independent write guarantee.
- G2 (P1) A real agent-TOML validator: parse each of the seven files, allow only
  known Codex agent-schema keys, and validate enum-typed values
  (`sandbox_mode`, `web_search`, `model_reasoning_effort`). Close the installer's
  validation gap and document that `strict-config` does not cover agent files.
- G3 (P1) The leaf-only property (`max_depth = 1` plus "cannot delegate" in every
  role) is asserted structurally.
- G4 (P1) Template tests assert the security / routing **contract**, not exact
  README / installer prose. Remove brittle sentence-level `assertRegex`.
- G5 (P2) Installer reduced to fresh-install + stamped upgrade; v1.0.x migration
  runs only when a legacy stamp or retired asset is actually detected.

## Non-Goals (defer to upstream author)

- The seven-role structure, phase-aware lifecycle, and approval gates.
- The Remora model/effort map, including `executor` on `gpt-5.6-luna` `max`.
- Retiring `explore`; the SHA-256-pinned retired assets stay (that pinning is an
  integrity control worth keeping, not slimming away).
- Runtime dispatch proof and enforcement hooks — owned by `dispatch-verification`
  (Gap B). This spec only adds the static/boundary layer beneath it.

## ADR

- **ADR-1 — Accept the port, scope to hardening.** The design review concluded
  the port is correct; changing routing or structure would fork from upstream
  for no security benefit. Adjustments are limited to security assertions, test
  robustness, and installer weight.
- **ADR-2 — Agent TOMLs get their own validator.** Because `codex --strict-config`
  covers only `config.toml`, agent-file validity must be proven by an explicit
  parser + key allowlist + enum check. The installer text must stop implying
  `doctor` validates agent files.
- **ADR-3 — Tests assert contract, not prose.** Static tests verify role set,
  model/effort/sandbox map, marker count, version stamp, and capability
  boundaries. They must not pin exact README / installer sentences, which change
  freely and add no safety.
