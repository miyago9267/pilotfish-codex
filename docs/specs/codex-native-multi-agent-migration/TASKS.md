# TASKS — Codex native Multi-Agent V2 migration

## Batch 0 — Evidence and exact native target

- [x] T0.1 Record the pinned v0.145 source evidence for feature table shape,
  defaults, V2 selection, total-slot concurrency, role discovery, and spawn
  fields.
- [x] T0.2 Capture the current adapter config, seven-role Codex manifest, and
  current live baseline `SKIPPED: native_schema_introspection_unavailable`.
- [x] T0.3 Confirm the staged target uses
  `[features.multi_agent_v2] enabled = true` with total concurrency `4`, and
  does not emit the `[agents]` fallback or legacy adapter keys.
- [x] T0.4 Record the Claude-native Pilotfish comparison boundary: portable
  delegation and verification semantics versus Claude-specific runtime
  mechanics.

## Batch 1 — Native installer, policy, and evidence

- [x] T1.1 Replace indirect V1/adapter enablement with the exact native V2
  feature table in `templates/config.snippet.toml`.
- [x] T1.2 Remove forced namespace, metadata visibility, legacy concurrency, and
  adapter-only transport wording while preserving unrelated config keys.
- [x] T1.3 Update `install/install.py`, `install/validate_agents.py`, and
  `install/AGENT-INSTALL.md` for exact-version (`0.145.0`) preflight, atomic
  idempotent native-only merge behavior, seven-role manifest validation,
  managed concurrency normalization, scalar/table feature-form handling,
  per-key provenance recorded and atomically committed at the sibling install
  state sidecar, verified-retired-role cleanup with explicit approval,
  exact version-token parsing, and static fail-closed preflight.
- [x] T1.4 Update orchestration policy and `tests/test_policy.py` with
  non-empty message, typed role, task-name, fork values `none|1..3`, no
  full-history named-role forks, no child overrides, and no untyped retry.
  State that current validation is post-hoc and remove namespace-specific
  active assertions.
- [x] T1.5 Add `install/stage_smoke_home.py` and update
  `install/verify_dispatch.py`. The staging helper shall atomically materialize
  the approved staged home and classify copy, permission, and finalization
  failures as out-of-band `stage_materialization_failed` before verifier
  launch. The verifier shall enforce exact preflight version `0.145.0` before
  auth/quota, require the native core evidence fields
  including child `turn_context.model` and `.effort` (normalized to receipt
  `reasoning_effort`), distinguish optional rollout fields, audit the pinned
  effective-layer inventory and exact staged-home allowlist, freeze the staged
  snapshot, calculate canonical config/manifest hashes, enforce the receipt
  allowlist/digests and exhaustive reason/status/phase matrix, identify native
  spawn by `spawn_agent` plus typed arguments/correlation rather than
  namespace, add separate `--codex-cwd` propagation and required distinct
  `--active-codex-home` while retaining `--repository-root`, compare all three
  active/staged hash pairs, reject retired `--mode` and `--all-roles` options
  in the native-only active CLI, classify execution failures by observed child
  creation, cover snapshot mutation with deterministic precedence, and
  preserve explicit `SKIPPED` and `FAILED` reasons.

## Batch 2 — Offline verification and native gate

- [x] T2.1 Replace active adapter assertions in `tests/test_install.py` and
  `tests/test_templates.py`; add offline fixtures for exact V2 TOML shape,
  scalar/table feature forms and explicit opt-out, total/root/child
  concurrency, feature/fallback conflicts, role discovery, same-layer
  warning/skip, the explicit low/high-layer `scout` merge result,
  extra-role/layer/declaration rejection, the pinned effective-layer inventory,
  staged-home minimal source projection and environment propagation,
  namespace-independent spawn predicates, receipt reason/status/phase/key sets,
  malformed manifests, extra/retired role handling, per-key provenance, atomic
  merge, idempotency, cleanup, staging canonical equal/nested rejection,
  source-symlink containment, source TOCTOU replacement/swap detection,
  copy/permission/finalization/race failures, temporary auth cleanup,
  no-launch/no-receipt evidence, and unsupported versions.
- [x] T2.2 Replace active adapter assertions in `tests/test_verify_dispatch.py`
  and `tests/test_policy.py`; add policy regressions for namespace-neutral typed
  spawn, fork bounds, forbidden child overrides, post-hoc
  evidence classification, namespace-independent spawn predicates, staged-home
  environment/layout propagation, receipt reason/status/phase/key sets, receipt
  allowlist/digests, `service_tier_override_forbidden`, untyped fallback
  refusal, native-only CLI rejection for retired mode/all-role options,
  canonical active/staged home validation, and snapshot mutation
  no/unknown/yes precedence, plus staging-wrapper no-launch/no-receipt
  integration checks. Keep only explicitly labeled historical adapter
  fixtures.
- [x] T2.3 Reconcile `README.md`, `docs/design.md`, `CHANGELOG.md`,
  `install/AGENT-INSTALL.md`, `templates/config.snippet.toml`,
  `templates/agents-md.orchestration.md`, and the historical headers/links in
  `docs/specs/subagent-issue/SPEC.md`, `PROGRESS.md`,
  `docs/specs/dispatch-verification/SPEC.md`,
  `docs/specs/dispatch-verification/TASKS.md`,
  `docs/specs/dispatch-verification/TESTS.md`,
  `docs/specs/dispatch-verification/PROGRESS.md`,
  `docs/specs/dispatch-verification/REPORT.md`, and
  `docs/specs/subagent-service-tier-guard/SPEC.md` with the native-only target
  and Claude/Codex boundary. Mark adapter assertions historical and excluded
  from the native gate. Preserve the service-tier guard and parent-tier rules
  while marking namespace examples historical or backend-neutral.
- [x] T2.4 Run the complete offline suite without credentials and without
  mutating the user's real Codex home. The active suite must no longer expect
  adapter keys, `ADAPTER_OK`, or the old 0.144.1 runbook.
- [x] T2.5 After approval and implementation, migrate the active target to the
  adapter-free native config. The runbook/operator shall invoke
  `install/stage_smoke_home.py` with an absolute, distinct, not-yet-existing
  `STAGED_CODEX_HOME`; it shall atomically copy only the canonical native-V2
  config projection, policy/role inputs, and `auth.json` from the
  active target through an exclusive atomic no-replace commit, and reject an
  existing or race-created destination without deleting/reusing it. Any
  staging failure, including an unavailable no-replace primitive, stops before
  verifier launch. Before the command, export
  `LAUNCH_CAPTURE="$SMOKE_DIR/pilotfish-launch-capture.json"` and write JSON
  containing the exact `CODEX_HOME`, `CODEX_SQLITE_HOME`, and `codex_cwd`
  launch bindings to that path. Then run
  `CODEX_HOME="$STAGED_CODEX_HOME" CODEX_SQLITE_HOME="$STAGED_CODEX_HOME"
  python3 "$REPO_ROOT/install/verify_dispatch.py" --live
  --role scout --yes --codex-home "$STAGED_CODEX_HOME"
  --active-codex-home "$ACTIVE_CODEX_HOME" --repository-root "$REPO_ROOT"
  --codex-cwd "$SMOKE_DIR" --launch-capture "$LAUNCH_CAPTURE"` from a clean
  temporary working directory with no project-local config, in a fresh
  authenticated `rust-v0.145.0` session, without `--ignore-user-config`. Require
  active/staged config, role-manifest, and policy hash equality before child
  creation; record all three hash pairs. Require `NATIVE_OK`; `SKIPPED` is
  incomplete and `FAILED` blocks completion.
- [x] T2.6 After `NATIVE_OK` and separate Gate 4 authorization, delete residual
  adapter files or temporary receipts; backups and explicitly reverted commits
  remain the only rollback artifacts.

## Approval and execution gates

1. Miyago approves this native-only `rust-v0.145.0` plan and its exact-only
   version boundary; lower and higher versions fail closed.
2. The operator separately authorizes backup and writes to the real Codex home,
   the sibling install-state sidecar, any explicitly approved same-name role
   replacement, and verified-retired role cleanup; general home-write approval
   does not authorize customized-role replacement. Offline tests use a staged
   temporary home.
3. From a clean temporary working directory with no project-local Codex
   config, with absolute, distinct `REPO_ROOT`, `SMOKE_DIR`,
   `ACTIVE_CODEX_HOME`, and `STAGED_CODEX_HOME`, the operator first invokes
   `install/stage_smoke_home.py` with a not-yet-existing staged destination and
   materializes it atomically from the active target using only approved
   inputs; an existing destination is not deleted/reused, and staging failure
   stops before verifier launch. The operator
   then separately authorizes quota spending with
   `CODEX_HOME="$STAGED_CODEX_HOME" CODEX_SQLITE_HOME="$STAGED_CODEX_HOME"
   python3 "$REPO_ROOT/install/verify_dispatch.py" --live
   --role scout --yes --codex-home "$STAGED_CODEX_HOME"
   --active-codex-home "$ACTIVE_CODEX_HOME" --repository-root "$REPO_ROOT"
   --codex-cwd "$SMOKE_DIR" --launch-capture "$LAUNCH_CAPTURE"` in a fresh
   authenticated session. The launch wrapper must bind both homes and
   `SMOKE_DIR`; the active native route must
   not use `--ignore-user-config`.
4. Adapter cleanup is separately authorized only after `NATIVE_OK`; `SKIPPED`
   or `FAILED` blocks cleanup.

- Do not modify implementation files before Gate 1.
- Do not add a permanent native/adapter capability selector.
- Do not add per-role declarations when native recursive discovery already loads
  the seven role files.
- Keep the role roster unchanged in this migration.
- Keep live model calls out of ordinary tests; the native smoke is explicit and
  operator-authorized.
- Use a fresh read-only `plan-verifier` before Gate 1 and a fresh executable
  `verifier` after the integrated implementation.
