# Model routing tuning

- Slug: `model-routing-tuning`
- Status: Done
- Owner: Miyago
- Created: 2026-08-03

## Goal

Keep PR #9's Nanako-authored orchestration policy, then tune model routing for
lower routine cost without weakening high-judgment work.

## Decisions

- Merge PR #9 first; close PR #7 and #8 as superseded by the integrated branch.
- Main session defaults to `gpt-5.6-luna` at `medium` effort.
- Main-session planning and dispatch reasoning may escalate Luna to `xhigh`,
  with `max` reserved for genuinely difficult orchestration decisions.
- Mechanical Luna roles remain unchanged at their existing low/medium levels.
- Do not install Terra. The v6 usage pilot found it 83.3% more expensive and
  43.9% slower than Luna, with two deterministic artifact failures.
- Use Luna at `xhigh` for Plan-mode reasoning and fresh outcome verification.
- Use Sol at `high` for the existing Nanako risk-triggered deep-Plan review.
  Security review and execution remain Sol/high.
- Keep security review and execution on Sol, capped at `high`.
- Do not rewrite Nanako's continuation, risk-triggered review, or installer
  safety policy unless a routing change requires a contract update.

## Scope

- Root model and effort defaults in the config template and installer.
- Non-security reviewer role bindings and the existing risk-triggered Sol
  escalation contract.
- Security role effort cap and matching historical fixtures/tests.
- Validator, template, installer, and targeted policy tests.

## Non-goals

- Re-designing PR #9's orchestration lifecycle.
- Changing mechanical role behavior or adding unconditional Sol calls.
- Running a paid live Codex behavioral gate.

## Codex native compatibility floor

The active Codex CLI is validated by its documented native root concurrency
contract. The installer requires only the minimum compatible version
`>=0.147.0`; it
records the observed semantic version and accepts later releases without an
exact-version pin.

- Reject an unparseable version or a release below `0.147.0`; do not reject a
  later release merely because it is newer. Native contract evidence remains
  authoritative for behavior compatibility.
- Replace the old `[features.multi_agent_v2]` total of four slots with the
  documented `[agents]` setting `max_concurrent_threads_per_session = 3`.
  This preserves one root plus up to three children.
- Atomically migrate only the prior, installer-owned V2 config. A false,
  malformed, or unowned legacy value remains fail-closed; unrelated config and
  custom role bytes remain untouched.
- Treat the complete old V2 table as owned only when every recorded install
  target still matches its committed fingerprint and the table is exactly
  `enabled = true` with total concurrency `4`. A stale state, extra V2 keys,
  an unowned table, or conflicting root/legacy values aborts before writes.
- Require the committed sidecar to have exactly `config.toml`, the seven
  canonical role paths, and the currently selected active-policy path in both
  target maps. Every entry needs valid fingerprint and original-byte evidence;
  missing, extra, malformed, or mismatched entries abort before migration.
- Make dry-run emit the exact relative path of every planned write. The active
  migration may proceed only when those paths are `config.toml`, the canonical
  role upgrades, and the active Pilotfish policy. It also reports
  only these transaction artifacts: a pending and committed state sidecar plus
  timestamped backups of replaced primary targets. Dry-run creates none.
- Keep role-file discovery, role model precedence, typed dispatch evidence, and
  the existing Nanako risk trigger unchanged. Do not require the undocumented
  `multi_agent_version` rollout marker as a version gate.
- Validate with focused unit tests, a strict-config parse, a temporary-home
  install/stage check, then a real installer dry-run and active installation.
- Update README, the install runbook, and design rationale so no document still
  presents V2, 0.146, or `[agents]` as the active configuration contract.

## Active-install result

The protected 0.147 dry-run against `~/.codex` first stopped on a stale
committed state without writing. With explicit operator authorization, the
affected targets were backed up, the approved packaged Plan and outcome
verifier contracts replaced their stale copies, and the strict sidecar was
rebaselined with validated original-byte evidence. The real installer then
migrated the V2 config, upgraded the canonical security reviewer, and replaced
the active Pilotfish policy atomically. The next dry-run reported that the
installation was already up to date. The approved root override then set the
main session to Luna/medium while retaining Plan-mode `xhigh`; its sidecar
fingerprint was rebaselined with the original-byte evidence unchanged.

## Verification

- Validate the generated config and all role TOMLs.
- Run targeted installer/template/policy tests and the full offline unittest
  suite once after integration.
- Run Python compilation, Markdown lint, and `git diff --check`.
- Confirm the active Codex config accepts Luna/medium and the selected effort
  values before any local config write.
