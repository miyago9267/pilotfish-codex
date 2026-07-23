# PROGRESS — Codex native Multi-Agent V2 migration

## Phase 0 — Evidence reconciliation (done)

- [x] Review the existing adapter, validator, verifier, and migration contract.
- [x] Pin Codex `rust-v0.145.0` source evidence for the V2 feature table,
  defaults, V2 selection, concurrency conversion, role discovery, and spawn
  fields.
- [x] Confirm the exact seven-role Codex manifest under `templates/agents/`.
- [x] Compare Pilotfish upstream `v1.3.0` / `main@4d65cc9` with this Codex
  port.
- [x] Separate portable policy semantics from Claude Code-specific mechanics.
- [x] Record the current live native boundary:
  `SKIPPED: native_schema_introspection_unavailable`; no live native child has
  been verified yet.

## Phase 1 — Specification (approved)

- [x] Resolve the native TOML shape as
  `[features.multi_agent_v2] enabled = true` with a total concurrency value.
- [x] Resolve V2 concurrency as four total slots including root, with three
  child slots; keep `[agents]` conversion as upstream compatibility behavior,
  not a duplicate native template setting.
- [x] Define recursive role discovery root, exact seven-role manifest, and
  duplicate/identity rules.
- [x] Remove forced namespace, metadata visibility, per-role registrations, and
  permanent adapter capability selection from the proposed target.
- [x] Define mandatory versus optional live evidence, receipt redaction, and the
  `NATIVE_OK`/`SKIPPED`/`FAILED` boundary.
- [x] Reword local policy as policy/request construction plus post-hoc evidence;
  do not claim a pre-execution runtime blocker.
- [x] Restore exact named-role fork bounds: `none` or `1..3`; full-history named
  role forks are forbidden by the native spawn contract.
- [x] Add the authoritative `install/AGENT-INSTALL.md` runbook to scope.
- [x] Obtain a fresh `plan-verifier` result after this revision (`READY`).
- [x] Obtain Miyago's approval before implementation.

## Phase 2 — Native configuration and installer (complete)

- [x] Update the config template for the exact native V2 feature table.
- [x] Update installer, validator, and authoritative installation runbook.
- [x] Add offline fixtures for total/root/child concurrency and recursive role
  discovery.

## Phase 3 — Policy and evidence (complete)

- [x] Update orchestration transport wording and V2 depth boundary.
- [x] Update native typed dispatch evidence and redacted receipts.
- [x] Verify mandatory core fields and optional observable rollout fields.

## Phase 4 — Documentation and offline verification (partial)

- [x] Reconcile README, architecture docs, changelog, and related specs.
- [x] Run the complete offline test suite.
- [ ] Run one explicit native live smoke in a fresh `rust-v0.145.0` session;
  later releases are outside this spec until a separate revalidation updates
  the version pin and evidence contract.
- [ ] Remove active adapter paths before the native smoke; delete only residual
  adapter files or receipts after `NATIVE_OK` and Gate 4 authorization.

## Decisions

- Native V2 is explicit opt-in through the typed feature table.
- V2 concurrency is a feature-level total including root; the target is four.
- `[agents]` concurrency is an upstream compatibility fallback, not a second
  native template authority.
- Native role files are recursively discovered; Pilotfish validates the exact
  seven-role manifest rather than rendering role declarations.
- Namespace names are backend transport details, not portable policy.
- `max_depth` is not a V2 runtime leaf guard.
- Local verifier evidence is post-hoc; current native evidence is still skipped.
- Claude-native background, worktree, navigation, and resume mechanics are not
  Codex runtime guarantees.
- Codex versions below `0.145.0` fail closed in this migration; compatibility
  support requires a separate spec.

## Final offline verification

- [x] Fresh `verifier` confirmed the native installer, staging allowlist, and
  receipt contracts after implementation.
- [x] Staging rejects unapproved files at every nested path and excludes
  recognized rollback backups from the published staged home.
- [x] Active-home staging projects only the canonical native-V2 config,
  policy, roles, and auth. Unrelated config, unknown root, and existing runtime
  metadata, including `.DS_Store`,
  `.app-server-state-reconciled-v1`, `.codex-global-state.json`, its backup and
  transient files, is not inspected, copied, or hashed; the staged home rejects
  every such entry.
- [x] Required config, policy, roles, and auth sources retain
  fail-closed symlink, special-file, readability, containment, mutation, and
  pre-publication TOCTOU checks.
- [x] Installer transactions revalidate the active policy through commit;
  late creation of a second non-empty policy file fails closed, rolls back
  managed targets, and records an aborted pending state.
- [x] Complete offline suite passed (76 tests), together with Python
  compilation, role validation, diff checks, and migration Markdown checks.
- [x] Headless live smoke passed on Codex `0.145.0` with
  `NATIVE_OK reason_code=native_verified phase=post-spawn child_created=yes`;
  the observed `scout` child used `gpt-5.6-luna` at `low` effort.
- [x] Gate 4 cleanup removed 10 legacy `ADAPTER_OK` receipts and the now-empty
  active-home receipt directory. Installer rollback backups remain intact.
- [x] Fresh final verifier confirmed the integrated diff and reclassified the
  raw live rollout under the exact one-spawn/one-wait evidence contract.

## Current gate

Gates 1 through 4 are complete. The active target is adapter-free, the
authenticated headless native smoke is `NATIVE_OK`, and authorized adapter
receipt cleanup is complete.
