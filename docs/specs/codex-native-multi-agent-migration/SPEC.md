# SPEC — Codex native Multi-Agent V2 migration

- Slug: `codex-native-multi-agent-migration`
- Status: Implementation complete; live gate pending
- Owner: Miyago
- Created: 2026-07-22
- Updated: 2026-07-23
- Related specs: `subagent-issue`, `dispatch-verification`,
  `subagent-service-tier-guard`
- Upstream: [Codex `rust-v0.145.0` release](
  https://github.com/openai/codex/releases/tag/rust-v0.145.0)
- Pilotfish baseline: upstream `v1.3.0`, checked against
  `main@4d65cc94b59acec2debec37983ad0a021440d643` on 2026-07-22

## Outcome

Pilotfish shall target the pinned Codex `rust-v0.145.0` release with native
typed named-role Multi-Agent V2. The migration removes the pre-stable transport
workarounds while retaining role routing, delegation policy, redaction, and
fresh-context verification. Later releases are outside this spec; a future
version requires a separate revalidation decision and an updated version pin
before the same evidence contract can be applied.

The native target has one authoritative configuration shape:

```toml
[features.multi_agent_v2]
enabled = true
max_concurrent_threads_per_session = 4
```

The configured V2 value is a total-thread limit including the root. Four slots
therefore permit the root plus three concurrent children. The legacy
`[agents]` concurrency input is not emitted in the native template; upstream
only uses it as a compatibility fallback and converts its child value to a V2
total by adding one.

The current live native verifier result remains
`SKIPPED: native_schema_introspection_unavailable`. Source evidence establishes
the implementation target; only a later explicit live smoke may produce
`NATIVE_OK`.

Codex versions below `0.145.0` are outside this migration target. The
installer shall not auto-select the old adapter. Existing adapter material may
remain as a manual rollback artifact during implementation, but it is not an
active supported route after migration.

## Problem

The current template was designed around a pre-stable V2 adapter:

```toml
[features]
multi_agent = true

[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
max_concurrent_threads_per_session = 4

[agents]
max_threads = 3
max_depth = 1
```

That patch solved two local problems: typed role dispatch was not reliably
available, and child routing metadata was hidden from the parent. Codex
`rust-v0.145.0` now contains stable opt-in V2 role application, native model
and reasoning fields, role loading, and V2 concurrency handling.

The old configuration therefore carries unnecessary transport assumptions:

1. forced namespace and metadata visibility;
2. duplicated concurrency settings with different units; and
3. adapter wording that treats a backend workaround as the role contract.

## Pinned upstream evidence

The following source evidence is pinned to the `rust-v0.145.0` tag. It proves
the source-level target, not a live account or rollout. The live boundary is
tracked separately in `docs/specs/dispatch-verification/REPORT.md`.

- `codex-rs/features/src/feature_configs.rs:34-39` defines
  `MultiAgentV2ConfigToml.enabled` and
  `max_concurrent_threads_per_session`.
- `codex-rs/features/src/lib.rs:642-648` maps
  `features.multi_agent_v2` to `FeatureToml<MultiAgentV2ConfigToml>`.
- `codex-rs/features/src/lib.rs:763-774` confirms that a feature accepts either
  a scalar boolean or a configuration table; this migration uses the table.
- `codex-rs/features/src/lib.rs:1053-1059` marks V2 stable with default disabled.
- `codex-rs/core/src/config/mod.rs:1199-1202` gives native defaults for
  namespace, metadata hiding, and model/reasoning override exposure.
- `codex-rs/core/src/config/mod.rs:1433-1475` selects V2 from the explicit
  feature and subtracts the root from the V2 total for child capacity.
- `codex-rs/core/src/config/mod.rs:2534-2545` shows that an `[agents]`
  child limit is used only when the V2 feature table omits its value; the
  materializer adds one to obtain a V2 total, after which
  `effective_agent_max_threads` subtracts the root again. The relevant source
  shape is:

  ```rust
  base.max_concurrent_threads_per_session
      .or_else(|| agents.max_concurrent_threads_per_session.map(|n| n + 1))
  // V2 effective child limit: v2_total.saturating_sub(1)
  ```

  A feature-table value therefore remains authoritative when both are present.
- `codex-rs/config/src/config_toml.rs:680-712` defines `[agents]`, its
  concurrency alias, V1-only `max_depth`, and flattened role declarations.
- `codex-rs/core/src/config/agent_roles.rs:19-115` merges role declarations
  across config layers. Same-layer duplicate declarations are warned and
  skipped; same-name roles from different layers can be merged by filling
  missing fields.
- `codex-rs/core/src/config/agent_roles.rs:474-553` recursively discovers
  `.toml` files under each config layer's `agents/` directory, derives role
  identity from file content, sorts paths, and warns/skips duplicate identities
  discovered in one layer.
- `codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs` requires
  `task_name`, accepts `agent_type`, rejects full-history forks with a role,
  and applies the role through `apply_spawn_agent_role`. Its parser accepts
  `none`, `all`, and any positive integer; Pilotfish's narrower `1..3` bound is
  local request-construction policy. The handler also requires `message` and
  rejects `fork_context`; optional model, reasoning, and service-tier fields
  are policy-forbidden here.

The previous local spec recorded the reserved schema state as of 2026-07-16.
The v0.145 source now supplies the implementation evidence that was missing at
that date. A live `NATIVE_OK` is still a separate acceptance requirement.

## Goals

1. Adopt the exact native V2 configuration shape without changing the existing
   Codex role manifest or role semantics.
2. Remove forced namespace, metadata visibility, duplicate legacy concurrency,
   and adapter-specific transport wording.
3. Keep role files as the source for model, reasoning, sandbox, and developer
   instructions when the role layer explicitly sets them. Accept only observed
   child model/reasoning, record sandbox when stably exposed, and do not claim
   developer-instruction application from config or a receipt; unspecified
   fields may retain upstream caller/default values.
4. Preserve typed role, task-name, bounded-fork, no-untyped-retry, and
   service-tier policy requirements.
5. Make the installer atomic and idempotent, with
   `install/AGENT-INSTALL.md` as the authoritative runbook.
6. Keep ordinary verification offline and make one explicit native smoke the
   only quota-gated acceptance step.
7. Preserve separate read-only plan verification and fresh outcome verification.

## Non-goals

- Supporting Codex versions below `0.145.0` in this migration.
- Adding a permanent native/adapter capability selector.
- Changing the seven-role Codex manifest or its model distribution.
- Adding role declarations when native recursive discovery already loads the
  role files.
- Hard-coding one provider's namespace into backend-neutral policy.
- Treating `max_depth` as V2 runtime enforcement of the leaf boundary.
- Removing the local `service_tier` policy guard.
- Claiming that source inspection is a live `NATIVE_OK` result.
- Porting Claude Code's `.claude/agents`, background task dashboard, worktree
  manager, Agent View, agent IDs, or resume commands into Codex runtime.
- Running live model probes in ordinary CI.

## Scope

### Configuration and templates

Update `templates/config.snippet.toml` to emit exactly the native table shown
in Outcome. It shall not emit:

- `features.multi_agent = true` as a V2 prerequisite;
- `hide_spawn_agent_metadata = false`;
- `tool_namespace = "agents"`;
- `[agents].max_threads` or
  `[agents].max_concurrent_threads_per_session` in the native template; or
- V2 `max_depth` settings.

The native defaults for namespace, metadata hiding, and model/reasoning
exposure remain upstream defaults. The template does not duplicate role model
names in the root config.

### Role discovery and manifest

Keep `~/.codex/agents/` as the installed role source. Native Codex discovery
walks the configured layer's `agents/` directory recursively and loads `.toml`
files. Role identity comes from the role file's `name`, not its filename.

The Codex migration manifest is exactly:

```text
executor
mech-executor
plan-verifier
scout
security-executor
security-reviewer
verifier
```

The repository source for this manifest is `templates/agents/*.toml`. The
validator shall compare the staged target manifest with these seven names,
require the existing role fields, reject duplicate names, and reject files
outside the approved Codex home. Active extra roles are migration candidates,
not part of the target: a byte-identical verified retired `explore.toml` may be
removed under the home-write approval after backup. The only trusted retired
assets are `install/retired/v1.0.0/explore.toml` with SHA-256
`9bfdcbc3c032c084dcc0ee77e4fa74de3b30f0e1dfd1e87e180545052a85b59b` and
`install/retired/v1.0.1/explore.toml` with SHA-256
`d90b4735917afe9d5525c2f0429406c6bffa8d539d664b27760ed4680449a9a4`.
An unknown or customized extra role is preserved and blocks the native gate
with `role_manifest_extra`.
Filename/name mismatch is a local Pilotfish
validator rule; Codex runtime discovery uses the TOML `name` field. Each of the
seven same-name role files must match the packaged canonical TOML bytes
exactly before staging. The installer may replace only exact release-pinned
prior canonical bytes; a customized same-name role returns
`installed_role_drift` and requires explicit replacement approval before the
staged target can pass. The runbook-owned `install/stage_smoke_home.py` staging
step shall accept
`ACTIVE_CODEX_HOME` as its source and an absolute `STAGED_CODEX_HOME`
destination that does not yet exist. Before creating any temporary directory,
it shall canonicalize both homes and reject equal or nested canonical paths
with `stage_materialization_failed`. It shall copy only the approved hashed
inputs plus `auth.json` into a sibling temporary directory and publish that
directory with an exclusive, atomic
no-replace commit; a plain overwriting `rename` is forbidden. The commit must
fail closed if the platform cannot provide no-replace publication. An existing
active home is a source namespace, not a staged-layout allowlist. The helper
reads `config.toml` through the confined required-input path, verifies the
native V2 table, and emits only the canonical `enabled = true` and total
concurrency `4` table. It also projects both policy candidates needed to prove
exactly one effective policy, `agents/`, and `auth.json`.
It must not recursively enumerate, stat, open, copy, or hash any other
active-root entry. This exclusion includes `.DS_Store`,
`.app-server-state-reconciled-v1`, `.codex-global-state.json`,
`.codex-global-state.json.bak`, `..codex-global-state.json.tmp-*`, rollback
backups, existing SQLite state, sessions, logs, temporary files, and future
runtime metadata regardless of file type. Required projected inputs still
fail closed on symlinks, special or unreadable files, containment
escapes, source replacement, metadata mutation, or TOCTOU. The staged
destination remains an exact allowlist and rejects every unknown entry,
including those ignored at the active root. An existing
destination is rejected rather than deleted or reused, including when another
process creates it after the initial absence check. Copy, permission,
existing-destination, race, unsupported-primitive, or finalization failure is
reported by this staging step as out-of-band `stage_materialization_failed`,
with no verifier/Codex launch or canonical receipt. Every failed staging
attempt must remove its sibling temporary directory and any copied
`auth.json` before returning; cleanup failure is itself fatal and
must not continue to verifier launch. The verifier receives this
newly materialized staged home, validates its layout, and freezes its private
immutable snapshot; it does not silently rebuild the staged home from the
active target. Every copied source path, including `auth.json`, must resolve
inside the canonical active home before it is read; a
source symlink escape or source path resolving into the staged destination is
`stage_materialization_failed` before any destination publication. The helper
must copy from the same confined, no-follow file handles used for containment
validation (or an equivalent directory-fd confinement primitive), and reject a
source replacement, symlink swap, or metadata change between validation and
read as `stage_materialization_failed`. Before
child creation, active and staged config/manifest hashes must be equal; a
mismatch fails closed. The staged home contains this manifest and no
unreviewed higher/lower config layer or
`[agents.<role>]` declaration. If a real installation contains role
declarations outside the staged manifest, preflight shall fail closed with
`role_layer_unapproved`; extra recursive roles
return `role_manifest_extra`; higher/lower layers return
`role_layer_unapproved`; and project-local config in `SMOKE_DIR` returns
`smoke_cwd_untrusted`. The verifier shall never guess the effective merge.
The native fixture shall also cover two config layers: upstream warns/skips
same-layer duplicates and merges same-name roles across layers. Pilotfish
rejects duplicates in its single approved staged target. It shall not render
`[agents.<role>]`
`config_file` declarations; upstream supports declarations, but recursive file
discovery already supplies this project's role source.

### Pinned effective-input boundary

Codex `rust-v0.145.0` can load more than the staged user layer. The pinned
loader evidence is:

- `codex-rs/config/src/config_layer_source.rs:6-47` names MDM, system,
  enterprise-managed, user/profile, project, session-flag, and legacy managed
  layers, with their precedence order;
- `codex-rs/config/src/loader/mod.rs:80-107` lists the Unix system paths,
  enterprise bundle, `${CODEX_HOME}/config.toml`, selected profile files,
  `${PWD}/config.toml`, ancestor and repository `.codex/config.toml` files,
  and runtime overrides;
- `codex-rs/config/src/loader/layer_io.rs:19-20,61-91,171-182` identifies
  `/etc/codex/managed_config.toml` and macOS managed preferences as additional
  managed sources; and
- `codex-rs/login/src/auth/storage.rs:38-216` identifies `auth.json` as the
  file-backed CLI credential store. The keyring path is external to
  `CODEX_HOME`; and
- `codex-rs/codex-home/src/instructions/mod.rs:9-27` loads only the global
  `AGENTS.override.md` or `AGENTS.md` from `CODEX_HOME`, while
  `codex-rs/core/src/agents_md.rs:1-17,153-236` discovers project
  `AGENTS.override.md` and `AGENTS.md` files from project root through `cwd`;
  and
- `codex-rs/config/src/project_root_markers.rs:5-49` defines the default
  marker as `.git` and permits an explicit `project_root_markers` array,
  including an empty array that disables root detection.

The approved smoke target contains one user layer only. It must not contain a
selected profile, project or repository `.codex` layer, system or managed
config, cloud or MDM input, session config override, config-lock replay file,
or legacy `managed_config.toml`. `SMOKE_DIR` and every ancestor used for
project discovery must also be free of `AGENTS.md`, `AGENTS.override.md`,
project-local `.codex` files, and every configured project-root marker. When
`project_root_markers` is absent, the verifier checks the pinned default `.git`;
when present, it checks the exact configured string array. The intentionally
non-repository cwd is launched with `--skip-git-repo-check`; this does not
relax the preceding clean-cwd validation. The verifier must
inspect effective layer metadata or the pinned source paths before the child is
created; if any non-user layer is present or its absence is unobservable, it
returns `stage_layout_untrusted` or `smoke_cwd_untrusted` and does not claim
native proof.

The active config remains byte-for-byte untouched, but the staged config is a
canonical required-input projection. Unrelated keys are neither copied nor
executed during the smoke. The known resource-bearing inventory includes
top-level `notify`, `mcp_servers`, `plugins`,
`skills`, `marketplace`/`marketplaces`, `model_providers`, `projects`,
`project_root_markers`, `experimental_compact_prompt_file`, `log_dir`,
`sqlite_home`, and `debug.config_lockfile`, plus path-bearing fields inside
role TOML. These active config values are outside the projection. If any such
value appears in a caller-supplied staged config, it is
`external_input_unowned` and blocks the smoke. Unknown staged path-bearing keys
are also `external_input_unowned`. Matching is ASCII case-insensitive on each
dotted key segment: a segment in `path`, `file`, `dir`, `directory`, `command`,
`executable`, `cwd`, or `*_path` is path-bearing. A string is path-bearing when
it begins with `/`, `~/`, `./`, `../`, `${HOME}`, `${CODEX_HOME}`, a Windows
drive or UNC prefix, or an ASCII scheme followed by `://`; any non-empty value
under a `command` or `executable` segment is also path-bearing. Unknown nested
tables or arrays are rejected if any descendant matches these rules. The
installer must not silently delete such unrelated settings; the operator may
classify or separate them before the native gate.

### Installer, runbook, and validator

Update `install/install.py`, `install/AGENT-INSTALL.md`, and
`install/validate_agents.py` for one native target:

- require exactly Codex `0.145.0`; reject lower or higher versions before
  writes;
- render and merge the exact native feature table;
- normalize the managed V2 total to `4`; reject values outside the local
  `1..8` policy range before writes;
- remove active adapter-owned keys from the target config;
- preserve unrelated TOML, atomic writes, backups, symlink safety, and
  abort-before-write behavior;
- make repeated installation idempotent; and
- fail closed for unsupported versions, malformed manifests, unsafe paths, or
  invalid concurrency values.

The feature-table value is authoritative. The installer first normalizes any
existing feature value in the managed `1..8` domain to total `4`. If both the
feature value and an `[agents].max_concurrent_threads_per_session` fallback are
present, it then requires the fallback child value to be `3` (the equivalent of
total `4`), rejects a conflicting or malformed fallback before writes, and
removes a matching fallback only when its per-key provenance is proven
Pilotfish-managed.
An unknown-provenance fallback is preserved with a warning, because unrelated
TOML must remain intact. Existing managed V2 values in the `1..8` range are
normalized to the target `4`, not preserved as a second policy.

Existing scalar `features.multi_agent_v2 = true` is converted to the explicit
table while preserving the opt-in; scalar `false` and table `enabled = false`
are explicit user opt-outs and abort before writes. Inline or dotted forms that
cannot be rewritten without collateral changes also abort before writes. A
missing `enabled` field may be set to `true` in an otherwise safe native table.
The same rules apply to equivalent parsed TOML forms, and tests must cover each
form separately.

The installer owns static/version preflight. Native typed-surface availability
is proved by the separate quota-gated smoke after installation; it is not an
installer routing mode. A `SKIPPED` or `FAILED` smoke cannot be reported as a
successful native migration and must leave the operator with the backup for
manual rollback.

`verify_dispatch.py` shall accept a separate `--codex-cwd` input for the child
working directory while retaining `--repository-root` for Pilotfish templates
and fixtures. Native smoke preflight must assert that `--codex-cwd` is clean and
that the child command receives it; changing the shell's current directory alone
is insufficient.

The active post-migration configuration shall not contain these known
Pilotfish-owned adapter paths when their provenance is proven:

- `features.multi_agent` as the adapter's V2 prerequisite;
- `features.multi_agent_v2.tool_namespace`;
- `features.multi_agent_v2.hide_spawn_agent_metadata`;
- `[agents].max_threads`; and
- the adapter transport block in `templates/agents-md.orchestration.md`.

Provenance is proven per key and per file, not by value equality alone. The
complete adapter fingerprint is only a candidate-integrity check. Ownership
requires either (a) the earliest valid Pilotfish pristine backup showing the
pre-install bytes and the installer-owned delta, or (b) a recorded install
state created before the write that records the key/file path, original
presence, and original bytes. A matching fingerprint without one of those
records is unknown provenance and must not be deleted. The install state is a
pending transaction until every target write succeeds and the post-write
fingerprint matches; an aborted write deletes or invalidates that pending
record. A stale record cannot prove ownership when target bytes do not match
its committed post-write fingerprint. The authoritative sidecar is the sibling
`<CODEX_HOME>.pilotfish-install-state.json`, mode `0600`; its pending sibling
uses `.pending` and is never accepted as ownership proof. The sidecar is
installer metadata, not a Codex input, is excluded from the staged snapshot and
receipt hashes, and is atomically committed only after all target writes and
post-write checks succeed. On a later run, a pending sidecar is treated as an
aborted transaction: the installer takes no cleanup action, preserves the
backup and current bytes, and requires an operator resolution before writing.
A committed sidecar whose target fingerprint no longer matches is stale and
returns `legacy_key_unowned`; it is never silently applied as a rollback.

The effective instruction file is `~/.codex/AGENTS.override.md` when present,
otherwise `~/.codex/AGENTS.md`; conflicting candidate files fail closed. There
is no implicit install marker. A partial or unknown legacy key/block is
preserved and emits `legacy_key_unowned`; it is never deleted by key name alone,
and it blocks the native smoke and `NATIVE_OK` until an operator physically
removes it from active effective inputs.
`expose_spawn_agent_model_overrides` is an upstream native default and is not
removed merely because it exists. The installer shall not add
`[agents].max_depth`; an existing user value may be preserved as unrelated V1
compatibility state and is ignored by V2. Rollback artifacts are backups or an
explicit reverted commit, not a second active configuration state.

### Orchestration policy

Update `templates/agents-md.orchestration.md` to describe a backend-neutral
native typed spawn surface. The policy shall require:

- a known `agent_type` from the installed manifest;
- a schema-safe lowercase task name;
- `fork_turns = "none"` by default;
- only positive integer strings `"1"` through `"3"` for recent-turn forks;
- no full-history fork with a named role;
- no child model, reasoning-effort, or service-tier override; and
- no untyped retry when typed dispatch is unavailable.

These are Pilotfish policy requirements. The current verifier validates
resulting evidence after dispatch; it is not a reliable pre-execution hard
block. The policy and verifier must say so explicitly rather than overclaim
runtime enforcement. `max_depth` remains a V1 compatibility setting and a
policy/documentation boundary only.

### Dispatch verification

Update `install/verify_dispatch.py` and fixtures to verify one native typed
route. The active CLI shall be native-only: remove `--mode` and
`--all-roles` from the live parser, invoke the native route unconditionally,
and reject those retired options with out-of-band `cli_input_invalid` rather
than selecting an adapter path. This rejection occurs before authentication,
quota use, or child creation and produces no canonical receipt. Historical
adapter behavior may remain only in explicitly labeled offline fixtures that
do not invoke the active CLI. The Gate 3 command therefore does not pass
`--mode native`.

It shall require an absolute `--active-codex-home` distinct from the staged
`--codex-home`. Resolve both paths canonically with existing-directory and
readability checks before hashing. Missing, unreadable, non-absolute, equal
canonical paths (including symlink aliases), or nested canonical homes return
out-of-band `home_input_invalid` before hashing or child creation. For every
mandatory hashed input, its resolved path must remain inside its own canonical
home and must not resolve into the other home; an active/staged cross-home
symlink or an escape outside its home is `home_input_invalid`, not a hash
mismatch. A valid, distinct home pair whose mandatory hashed input is missing
or unreadable returns out-of-band `hash_input_unavailable`; neither diagnostic
creates a canonical receipt or fabricates hashes.

Its preflight shall compare `codex --version` to exactly `0.145.0`
before authentication or quota use; every other version returns
`FAILED: version_not_pinned` and creates no child. V2 selection is proven only
by at least one observed parent rollout field `multi_agent_version`. All
observed values must normalize to the same `"v2"` value; multiple consistent
observations are allowed. A missing field returns
`SKIPPED: native_v2_selection_unobservable`, and any conflicting or non-`v2`
completed observation returns `FAILED: native_v2_selection_mismatch`. A
successful spawn alone cannot infer V2.

A native typed spawn is identified by a function call whose name is
`spawn_agent`, whose arguments contain `message`, `agent_type`, `task_name`,
and `fork_turns`, and whose `call_id` correlates to the parent
`sub_agent_activity`. Namespace absence or an upstream namespace value is not a
pass/fail predicate; adapter-owned config/prose is checked separately.
`NATIVE_OK` additionally requires exactly one spawn attempt with only
`message`, `agent_type`, `task_name`, and `fork_turns`; it must use `none` or
`1..3`, omit `model`, `reasoning_effort`, `service_tier`, and `fork_context`,
and have no untyped fallback or second attempt. A violation returns
`FAILED: policy_violation`. The evidence contract is:

| Evidence | Source | Required for `NATIVE_OK` |
| --- | --- | --- |
| V2 selection | parent rollout version/feature event | Yes |
| native typed spawn | exact parent spawn activity/tool event | Yes |
| role and task | spawn arguments and installed manifest | Yes |
| fork mode | exact spawn arguments; child fork metadata is optional | Yes |
| parent/child link | `sub_agent_activity` and child parent metadata | Yes |
| child model/reasoning | raw `turn_context.model` and `turn_context.effort` | Yes |
| verifier launch binding | parent command capture of the two homes and `--codex-cwd` | Yes |
| sandbox | stable child rollout field, if exposed | No; record only |

Model and reasoning are mandatory core evidence for `NATIVE_OK`. Missing
child context produces `SKIPPED: child_evidence_missing`; a present child
context without model or reasoning produces `SKIPPED:
child_binding_unobservable`. Sandbox is optional because the active backend may
hide it. Developer instruction application is outside the receipt contract and
shall not be inferred from role configuration. An observed model or effort
value that disagrees with the role uses its specific mismatch reason; absence
is never treated as a mismatch.

The parent receipt has this positive allowlist:

```text
status, reason_code, phase, child_created, codex_version,
active_config_sha256, active_role_manifest_sha256, active_policy_sha256,
target_config_sha256, target_role_manifest_sha256, target_policy_sha256, role,
task_name, fork_turns, parent_ref, child_ref, model, reasoning_effort, sandbox
```

`codex_version` comes only from the preflight `codex --version` result.
`phase` is one of `preflight`, `dispatch`, `execution-pre-child`, or
`post-spawn`; `child_created` is one of `no`, `yes`, or `unknown`. The latter is
recorded as `unknown` whenever bounded evidence cannot establish creation and
never satisfies `NATIVE_OK`. The same operator receipt records the active and
target config, role-manifest, and policy hashes calculated before the child is
created. `parent_ref` and
`child_ref` are the first 16 lowercase hex characters of a SHA-256 digest over
the corresponding runtime ID; raw IDs, absolute paths,
secrets, hidden metadata, and unapproved keys are forbidden. `model` is the
observed child `turn_context.model`, and normalized `reasoning_effort` is the
observed child `turn_context.effort`. `sandbox` is omitted when unobservable.
The receipt is verdict data, not a session transcript. Its canonical reason,
status, and execution-phase matrix is:

| Phase | Reason code | Status | Child created |
| --- | --- | --- | --- |
| preflight | `live_flag_required` | `SKIPPED` | No |
| preflight | `operator_opt_in_required` | `SKIPPED` | No |
| preflight | `native_schema_introspection_unavailable` | `SKIPPED` | No |
| preflight | `version_not_pinned` | `FAILED` | No |
| preflight | `version_parse_failed` | `SKIPPED` | No |
| preflight | `auth_unavailable` | `SKIPPED` | No |
| preflight | `smoke_cwd_untrusted` | `FAILED` | No |
| preflight | `stage_layout_untrusted` | `FAILED` | No |
| preflight | `external_input_unowned` | `FAILED` | No |
| preflight | `role_layer_unapproved` | `FAILED` | No |
| preflight | `role_manifest_extra` | `FAILED` | No |
| preflight | `legacy_key_unowned` | `FAILED` | No |
| preflight | `target_hash_mismatch` | `FAILED` | No |
| preflight | `snapshot_mutated` | `FAILED` | No |
| preflight | `role_preflight_failed` | `FAILED` | No |
| preflight | `installed_role_drift` | `FAILED` | No |
| preflight | `parent_model_not_distinct` | `FAILED` | No |
| preflight | `environment_propagation_failed` | `FAILED` | No |
| preflight | `environment_binding_unobservable` | `SKIPPED` | No |
| execution-pre-child | `snapshot_mutated` | `FAILED` | No/Unknown |
| execution-pre-child | `parent_model_unavailable` | `SKIPPED` | No/Unknown |
| execution-pre-child | `codex_exec_failed` | `FAILED` | No/Unknown |
| post-spawn | `parent_model_unavailable_after_spawn` | `SKIPPED` | Yes/Unknown |
| post-spawn | `snapshot_mutated` | `FAILED` | Yes/Unknown |
| post-spawn | `codex_exec_failed_after_spawn` | `FAILED` | Yes/Unknown |
| preflight | `environment_binding_mismatch` | `FAILED` | No |
| post-spawn | `native_v2_selection_unobservable` | `SKIPPED` | Yes/Unknown |
| post-spawn | `native_v2_selection_mismatch` | `FAILED` | Yes/Unknown |
| post-spawn | `native_spawn_evidence_missing` | `SKIPPED` | Yes/Unknown |
| post-spawn | `untyped_fallback_detected` | `FAILED` | Yes/Unknown |
| dispatch | `policy_violation` | `FAILED` | Yes/Unknown |
| dispatch | `service_tier_override_forbidden` | `FAILED` | Yes/Unknown |
| post-spawn | `parent_child_mismatch` | `FAILED` | Yes |
| post-spawn | `child_evidence_missing` | `SKIPPED` | Yes/Unknown |
| post-spawn | `child_binding_unobservable` | `SKIPPED` | Yes |
| post-spawn | `child_binding_mismatch` | `FAILED` | Yes |
| post-spawn | `child_model_mismatch` | `FAILED` | Yes |
| post-spawn | `child_effort_mismatch` | `FAILED` | Yes |
| post-spawn | `inherited_parent_model` | `FAILED` | Yes |
| post-spawn | `native_verified` | `NATIVE_OK` | Yes |

For rows showing `Yes/Unknown`, the verifier records `yes` when bounded
`sub_agent_activity` or child rollout evidence proves creation and `unknown`
otherwise; it never infers `no` from missing evidence. An observed child with
missing typed spawn evidence uses `native_spawn_evidence_missing` with `yes`;
without child evidence it uses the same reason with `unknown`. The matrix
describes the classification rule
without claiming that a post-hoc verifier can observe an unavailable child.

`snapshot_mutated` is emitted when a readable hashed input differs from the
captured pre-child snapshot or from the final recheck. The phase discriminator
is observable launch state, not timing guessed from the mutation: `preflight`
means the mismatch is found before the parent command launches;
`execution-pre-child` means the command launched but no spawn-attempt,
`sub_agent_activity`, or child-rollout event was observed; `post-spawn` means
a spawn-attempt or child-rollout boundary was observed. Within
`execution-pre-child`, clean evidence of no spawn records `child_created = no`
and an incomplete process/trace records `unknown`. Within `post-spawn`,
creation evidence records `yes`, while a reached post-spawn boundary without
creation proof records `unknown`. A mandatory input that cannot be read is
`hash_input_unavailable` instead. When both a snapshot mutation and an
execution failure are observed, the mutation wins deterministically in the
phase selected above; only an unchanged snapshot permits `codex_exec_failed`
or `codex_exec_failed_after_spawn`.

Pre-child `SKIPPED` or `FAILED` (including `execution-pre-child`)
requires `status`, `reason_code`, `codex_version`, and all six hashes. It
requires `phase` and `child_created = no` or `unknown`,
and forbids role, task, fork, refs, model, effort, and sandbox keys. Post-spawn
`SKIPPED` or `FAILED` keeps those keys and
may add only observed role, task, fork, refs, model, effort, and sandbox. It
requires `child_created = yes` when child evidence exists, or `unknown` for an
unobservable post-spawn result; it forbids inferred model/effort and unobserved
sandbox. `NATIVE_OK` requires `phase = post-spawn`,
`child_created = yes`, and all core keys, including observed role/task/fork/refs,
model, and effort; only
observed sandbox is optional. An execution failure is classified as
`codex_exec_failed` while the verifier remains in `execution-pre-child`, with
`child_created = no|unknown`; after a
post-spawn boundary it uses `codex_exec_failed_after_spawn`, with
`child_created = yes|unknown`. A parent model failure follows the same phase
rule, using `parent_model_unavailable_after_spawn` after that boundary and
`parent_model_unavailable` before it. Neither outcome can satisfy `NATIVE_OK`
without the required child proof.
Receipt destination, serialization, and mandatory-input hash failures are
transport/pre-receipt errors, not canonical receipt verdicts: the verifier
returns a nonzero process result and `home_input_invalid`,
`receipt_destination_invalid`, `receipt_write_failed`, or
`hash_input_unavailable` on stderr, with no `NATIVE_OK` or partial receipt.
`stage_materialization_failed` belongs exclusively to the preceding
`install/stage_smoke_home.py` staging step and is emitted before the verifier is
invoked.
A missing or unreadable `config.toml`, effective policy file, role manifest, or
other mandatory hashed input never fabricates six hashes.
`environment_propagation_failed` is preflight/No for a missing command
environment; unavailable launch capture uses `environment_binding_unobservable`
and a wrong launch binding uses `environment_binding_mismatch`. The launch
capture records only the two approved home values and `--codex-cwd`, never
secrets or the full process environment.

Status always uses `reason_code` and `codex_version`; no aliases such as
`reason` or `version` are accepted. Classification is ordered: an observed
`service_tier` uses `service_tier_override_forbidden`; any other forbidden
argument or second spawn uses `policy_violation`, and an untyped fallback uses
`untyped_fallback_detected`, before checking correlation. Only then does absent
typed spawn/correlation use
`native_spawn_evidence_missing`, even if unrelated child context exists; a
valid typed spawn/correlation without child context uses
`child_evidence_missing`; present child context without required model or
effort uses `child_binding_unobservable`; parent/child identity errors use
`parent_child_mismatch`; role/task/fork binding errors use
`child_binding_mismatch`; and model or effort value errors use their specific
`child_model_mismatch` or `child_effort_mismatch` reason. Hashes are the six
keys
`active_config_sha256`, `active_role_manifest_sha256`, `active_policy_sha256`,
`target_config_sha256`, `target_role_manifest_sha256`, and `target_policy_sha256`.
The live probe calls `wait_agent` once after the sole typed spawn so the child
can finish writing its context before `codex exec` exits; this wait is not a
second dispatch.
`codex_version` is the normalized token, or `unknown` when the command fails or
contains no parseable token. Unknown reason codes or phase/status combinations
are invalid.

Before child creation, the verifier reads and projects the post-install active
target from `--active-codex-home`, then validates and freezes a private
immutable snapshot of the already supplied `--codex-home` staged inputs. It
does not materialize or rebuild the staged home. `active_config_sha256` must
equal `target_config_sha256`, `active_role_manifest_sha256` must equal
`target_role_manifest_sha256`, and `active_policy_sha256` must equal
`target_policy_sha256`; any mismatch fails before child creation. Both the
parent verifier and child Codex process use that staged snapshot via
`CODEX_HOME="$STAGED_CODEX_HOME"`; writable session state and receipts are
outside the hashed input files. The verifier checks those required projections
and input bytes again before accepting the child result.

`active_config_sha256` is SHA-256 over the canonical native-V2 config
projection; unrelated active config keys do not affect it.
`active_role_manifest_sha256` uses the canonical role stream over the active
target. `active_policy_sha256` covers the exact effective
`AGENTS.override.md` or `AGENTS.md` bytes selected by precedence. The staged
`target_config_sha256` uses the same canonical projection, while
`target_role_manifest_sha256` and `target_policy_sha256` cover the corresponding
staged bytes. `target_role_manifest_sha256` is SHA-256 over a length-prefixed
canonical stream for
each discovered role in lexical path order: big-endian `u64` path-byte length,
UTF-8 relative POSIX path bytes, big-endian `u64` TOML-byte length, then raw TOML
bytes. The receipt reuses those captured values and never recomputes them after
the child runs.

The pre-launch staged-home layout is an exact allowlist:

- read-only hashed inputs are the canonical native-V2 `config.toml`, exactly
  one effective global
  instruction file (`AGENTS.override.md` or `AGENTS.md`), and recursive
  `agents/**/*.toml`;
- `auth.json` is the only allowed file-backed CLI credential entry;
  keyring-backed CLI auth is external to the home, and `.credentials.json` is
  allowed only for an explicitly exercised MCP OAuth file-store path;
- no active runtime state is materialized. After preflight, Codex may create
  the five SQLite files
  `state_5.sqlite`, `logs_2.sqlite`, `goals_1.sqlite`, `memories_1.sqlite`,
  and `thread_history_1.sqlite`, each with its `-wal`, `-shm`, or transient
  `-journal` sidecar when SQLite creates one, plus `log/**`, `sessions/**`,
  `shell_snapshots/**`, `tmp/**`, `history.jsonl`, `models_cache.json`, and
  `version.json`; verifier receipts are limited to `dispatch-receipts/**`; and
- no profile `*.config.toml`, role declaration, system or managed config,
  cloud or MDM input, config-lock replay file, extra role file, or project
  config is allowed. Symlinks, special files, and unreadable entries are
  rejected. Unknown entries fail with `stage_layout_untrusted`.

The five SQLite filenames are pinned to `codex-rs/state/src/lib.rs:92-99`.
The v0.145 runtime write-path audit also covers `models_cache.json`,
`shell_snapshots/**`, `history.jsonl`, `version.json`, and `tmp/**`; the offline
fixture must prove that each representative active runtime entry is excluded
without inspection. The exact source allowlist applies through preflight;
runtime outputs created afterward are never promoted to required inputs. The
verifier must set or verify `CODEX_SQLITE_HOME` resolves to this staged home.
The launch wrapper must pass the exact `CODEX_HOME`, `CODEX_SQLITE_HOME`, and
`--codex-cwd` to the parent command and capture only those bindings. The plan
claims this launch contract, not hidden child-process environment inspection;
child inheritance is required by command construction but remains
runtime-unobservable. If any non-user layer listed in the pinned loader
inventory is present or unobservable, preflight fails closed.

Any extra effective input, missing launch binding, or input mutation returns a
named failure before `NATIVE_OK`. Offline tests exercise this layout without
credentials.

### Portable Pilotfish semantics

Upstream Pilotfish `v1.3.0` and `main@4d65cc9` provide these portable policy
semantics:

- role names and role contracts are separate from model routing;
- delegation briefs contain goal, constraints, done criteria, relevant paths,
  rationale, output format, budget, and verification expectation;
- independent work may run in parallel only when dependency and ownership
  allow it;
- writing work has exclusive ownership or an equivalent isolation boundary;
- the main session owns framing, plan synthesis, ambiguity resolution,
  integration, and final judgment;
- plan verification is read-only and pre-approval, while outcome verification
  is fresh-context and post-implementation; and
- discovery findings are inputs, not completed verification.

Claude Code mechanics remain adapter-specific: Markdown/YAML frontmatter,
`.claude/agents` scope resolution, `run_in_background`,
`isolation: worktree`, Agent View, `/tasks`, `SendMessage`, agent IDs,
Claude session resume, and `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION`. Codex
shall preserve the policy semantics without claiming those mechanics.

## Architecture decisions

### ADR-1 — Explicit native V2 table

Use `[features.multi_agent_v2]` with `enabled = true` and an explicit total
concurrency value. The scalar boolean form is accepted by upstream's untagged
`FeatureToml`, but the table is required here because the migration configures
additional V2 fields.

**Why:** this is the exact typed configuration shape in the v0.145 source and
makes opt-in explicit without relying on the legacy V1 feature.

### ADR-2 — Native defaults, no transport forcing

Omit namespace, metadata, and model-override visibility settings from the
native template. Codex v0.145 supplies documented defaults; portable policy
must not require a namespace string.

**Why:** forced adapter keys were the workaround, not Pilotfish role policy.

### ADR-3 — Feature-level total concurrency

Set `features.multi_agent_v2.max_concurrent_threads_per_session = 4`. This
means four total slots including root and three concurrent children. Do not
also emit the `[agents]` child-capacity fallback or legacy `max_threads`.

**Why:** V2 uses the feature value as the authoritative total. Upstream only
converts an `[agents]` value by adding one when the feature value is absent.

### ADR-4 — Native recursive role discovery

Keep role files and exact local manifest validation. Do not add per-role
`config_file` declarations to the generated native config.

**Why:** the tagged source recursively discovers `.toml` role files and derives
identity from their content. Declarations are an optional upstream surface,
not a required Pilotfish registration layer.

### ADR-5 — Policy-owned fork and leaf boundaries

Keep `fork_turns`, no-untyped-retry, tool boundaries, and role contracts as
local policy. Treat `max_depth` as V1-only and do not claim V2 enforcement.

**Why:** source-level V2 fork behavior and local governance are distinct; the
current verifier cannot cancel an invalid spawn before execution.

### ADR-6 — Evidence over schema claims

A config snapshot or source listing cannot produce `NATIVE_OK`. Exact native
child evidence is mandatory for the live gate, and current
`SKIPPED: native_schema_introspection_unavailable` remains an incomplete result.

**Why:** the prior dispatch report proves that parser fixtures and source
presence are not live runtime proof.

### ADR-7 — Local service-tier guard remains

Reject child-provided `service_tier` in named-role policy even if upstream
accepts the field. The stable verifier result is
`FAILED: service_tier_override_forbidden`; generic `policy_violation` is
reserved for other policy failures.

**Why:** backend capability and organization-level cost policy are separate
controls.

### ADR-8 — Fresh verification boundary

Use a read-only `plan-verifier` before approval and a fresh executable
`verifier` after implementation. Neither role may substitute for the other.

**Why:** this Pilotfish governance boundary is portable and independent of
Claude-specific task or worktree mechanics.

## Document authority and migration scope

After Gate 1 approval, this spec supersedes the active adapter contract in
`docs/specs/subagent-issue/SPEC.md` and `PROGRESS.md`, plus the active routing
claims in `docs/specs/dispatch-verification/SPEC.md`,
`TASKS.md`, `TESTS.md`, `PROGRESS.md`, and `REPORT.md`. Those files retain their
historical evidence, but their headers and links must identify the adapter
baseline and current `SKIPPED` native boundary rather than prescribe the active
route. Adapter assertions in the dispatch-verification spec/tests are excluded
from the native acceptance gate.

The implementation/documentation batch must update these active paths:

- `README.md` Multi-Agent V2 version and support claims;
- `CHANGELOG.md` migration entry and current native gate;

- `install/AGENT-INSTALL.md` preflight, merge, verify, staging, and smoke
  instructions;
- `install/stage_smoke_home.py` for atomic staged-home materialization and its
  out-of-band failure diagnostics;
- `docs/design.md` adapter/native architecture claims;
- `docs/specs/subagent-service-tier-guard/SPEC.md`, retaining its local
  service-tier and parent-tier rules while marking namespace examples as
  historical or backend-neutral;
- `templates/config.snippet.toml` and
  `templates/agents-md.orchestration.md`; and
- `tests/test_install.py`, `tests/test_templates.py`,
  `tests/test_policy.py`, and `tests/test_verify_dispatch.py`.

Only deliberately named historical adapter fixtures may retain old keys or
`ADAPTER_OK` expectations. They must be labeled as historical and excluded
from the active native acceptance suite.

## Approval gates

The work has four separate approvals and must not collapse them into one:

1. **Spec approval:** Miyago approves the native-only implementation plan and
   the exact-only `0.145.0` version boundary.
2. **Home-write approval:** the operator authorizes backup and writes to a real
   Codex home, the sibling install-state sidecar and its transactional pending
   file, any explicitly approved customized same-name role replacement, and any
   verified-retired role cleanup; offline fixtures use a staged temporary home.
   General home-write approval does not authorize replacement of a customized
   role.
3. **Quota approval:** set absolute, distinct `REPO_ROOT`, `SMOKE_DIR`,
   `ACTIVE_CODEX_HOME`, and `STAGED_CODEX_HOME`; `SMOKE_DIR` must be outside
   `REPO_ROOT`, and the two homes must not be equal. It must contain no
   project-local Codex config in itself or any ancestor, and pass the clean-CWD
   preflight. The runbook/operator must first atomically materialize
   `STAGED_CODEX_HOME` from the post-install active target using only approved
   inputs; a staging failure stops before verifier launch. From that clean
   directory, export `LAUNCH_CAPTURE="$SMOKE_DIR/pilotfish-launch-capture.json"`
   and write JSON with the exact `CODEX_HOME`, `CODEX_SQLITE_HOME`, and
   `codex_cwd` launch bindings to that path. The operator then explicitly authorizes
   `CODEX_HOME="$STAGED_CODEX_HOME" CODEX_SQLITE_HOME="$STAGED_CODEX_HOME"
   python3 "$REPO_ROOT/install/verify_dispatch.py" --live
   --role scout --yes --codex-home "$STAGED_CODEX_HOME"
   --active-codex-home "$ACTIVE_CODEX_HOME" --repository-root "$REPO_ROOT"
   --codex-cwd "$SMOKE_DIR" --launch-capture "$LAUNCH_CAPTURE"` in a fresh
   authenticated session after installation. The launch wrapper must pass the
   approved homes and `SMOKE_DIR` to the parent command; the active native
   route must not use `--ignore-user-config`. Hidden child-process inheritance
   is required by
   command construction but is not claimed as independently observable.
4. **Residual cleanup approval:** after the active target is already
   adapter-free, the operator authorizes deletion of leftover adapter files or
   temporary receipts only after `NATIVE_OK`; `SKIPPED` or `FAILED` keeps those
   rollback artifacts.

The pinned source proves `rust-v0.145.0` only. The version matrix is exact:

| Codex version | Preflight behavior |
| --- | --- |
| below `0.145.0` | fail before writes |
| exactly `0.145.0` | eligible for the native smoke |
| above `0.145.0` | fail closed as `version_not_pinned` until separately revalidated |

The native smoke records `codex_version` from `codex --version` in the
operator receipt. The parser requires exit code zero and exactly one standalone
generic `X.Y.Z` semver token with no suffix in stdout/stderr; prefixes such as
the `codex` prefix is allowed. Multiple tokens, suffixes, parse failures, and
missing
tokens return `version_parse_failed`. A single parsed token other than
`0.145.0` returns `version_not_pinned`; the receipt stores the normalized
parsed token. No later-version compatibility is implied.

## Compatibility and rollback

This proposal has one supported runtime target: Codex `0.145.0` with the native
V2 table enabled. Approval includes rejecting an automatic pre-0.145 adapter
route and rejecting unverified later versions. Unsupported versions fail
before writes.

During implementation, the old adapter may remain only in backups or an
explicitly reverted commit. It is not an active installed route, and the
installer shall not select it from a capability state. If a supported
pre-0.145 route is needed later, it requires a separate compatibility spec.

## Risks and rabbit holes

- Source support does not guarantee that the authenticated account exposes the
  native schema; the live smoke remains quota-gated and may be skipped.
- Hidden metadata defaults mean receipts must not depend on fields invisible to
  the parent.
- Config layers can merge role declarations and discovered files; fixtures must
  test duplicate identity and exact layer boundaries.
- A native `agent_type` field alone does not prove effective role model,
  reasoning, sandbox, or developer-instruction application.
- Claude background, worktree, resume, and spawn-budget behavior must not be
  reinterpreted as Codex runtime evidence.
- A successful native route must not weaken the old local policy contract.

## Acceptance

The migration is complete only when all normative cases in `TESTS.md` pass,
static verification remains offline-safe, and one explicit authenticated
`rust-v0.145.0` smoke returns `NATIVE_OK` with every mandatory core field,
using a staged home whose config, role-manifest, and policy hashes each equal
the post-install active target. `SKIPPED` never satisfies the final native gate.
Adapter-only active
config and policy paths must be absent before the smoke; residual artifacts may
be deleted only after the gate passes. Later releases are not accepted by this
spec; a separate spec or approved pin revision must revalidate the evidence
contract before they can be considered.
