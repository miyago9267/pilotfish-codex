# TESTS — Codex native Multi-Agent V2 migration

## Static configuration

### NATIVE-CONFIG-001

Given the pinned Codex `rust-v0.145.0` target, when the template is rendered,
then it shall contain:

```toml
[features.multi_agent_v2]
enabled = true
max_concurrent_threads_per_session = 4
```

The parser shall accept the table form, and V2 selection shall not depend on
legacy `features.multi_agent` or `[agents].enabled` settings.

### NATIVE-CONFIG-002

Given the native target, when the validator evaluates transport settings, then
it shall reject forced `tool_namespace`, forced
`hide_spawn_agent_metadata = false`, forced model-override exposure, and
legacy `[agents].max_threads` or `[agents].max_concurrent_threads_per_session`
from the rendered native template. Upstream defaults shall remain implicit.

### NATIVE-CONFIG-003

Given the staged Codex home, when the validator runs, then recursive discovery
under the configured `agents/` directory shall produce exactly these seven role
names:

```text
executor, mech-executor, plan-verifier, scout,
security-executor, security-reviewer, verifier
```

Role identity shall come from each TOML `name`; the local Pilotfish validator
shall reject duplicate names, malformed required fields, filename/name
mismatches, and files outside the approved home. Filename matching and local
duplicate rejection are Pilotfish rules, not claims about Codex's layered
loader. Separate parser fixtures shall cover (a) duplicate declarations in one
layer, and (b) duplicate discovered files in one layer; each warns and skips
the later entry. A parser-only layer-merge fixture models a low-precedence
`scout` role with `description = "low"` and `config_file = "low.toml"`, plus a
high-precedence role with `description = "high"` and no config file; the
expected merged result is description `"high"` with `config_file = "low.toml"`.
None of these mixed-layer fixtures is an approved staged target. The validator
shall not require `[agents.<role>] config_file` declarations. A same-name
role whose TOML bytes match a release-pinned prior canonical payload upgrades
to the packaged template. Any other differing same-name role returns
`FAILED: installed_role_drift` and cannot be native proof until explicit
customized-role replacement approval; general home-write approval alone is
insufficient.

### NATIVE-CONFIG-004

Given a configured V2 total of four, when the validator evaluates concurrency,
then it shall report four total slots, one root slot, and capacity for three
concurrent children. The managed native input domain is `1..8`; any existing
feature value in that range is normalized to `4` before fallback validation,
while zero, values above eight, and malformed values abort before writes.
Given only `[agents].max_concurrent_threads_per_session = 3`, the parser
fixture shall record the upstream fallback materialization but the generated
native template shall omit that key. An unknown-provenance fallback may remain
in an existing user config and block the native gate. Given both settings,
every raw feature value in `1..8` is accepted only after normalization to `4`,
and the fallback must parse as child capacity `3`; any malformed or other
fallback value is a conflict and aborts. The generated native target still
omits the fallback key.

## Installer and policy

### INSTALL-001

Given an existing config with unrelated keys, when the native installer runs,
then unrelated keys shall remain byte-for-byte unchanged, the target write shall
be atomic, and a backup shall exist before replacement.

### INSTALL-002

Given a native install followed by a second identical install, when both
manifests are compared, then the result shall be idempotent and shall not add
adapter blocks, duplicate role declarations, or duplicate concurrency keys.

### INSTALL-003

Given a Codex version below or above the pinned `rust-v0.145.0`, malformed role
manifest, unsafe symlink, conflicting path, invalid concurrency value, explicit
native opt-out, or an unrewritable inline/dotted feature form, when the
installer plans the migration, then it shall abort before writing any target
file and shall not select an adapter route. Scalar `true` is converted to the
explicit native table; scalar `false` and table `enabled = false` remain an
operator decision and abort. The version parser shall require exit code
zero and exactly one standalone generic `X.Y.Z` semver token with no suffix;
prefixes are allowed. Multiple
tokens, suffixes, parse failures, and missing tokens are rejected as
`version_parse_failed`; a single parsed version other than `0.145.0` is
`version_not_pinned`. Raw command output is diagnostic-only; the normalized
parsed token is stored.
Typed-surface availability is tested separately by the live smoke, not by
installer mode selection.

### DISPATCH-CLI-001

Given the active verifier CLI, when `--mode`, `--mode native`,
`--mode adapter`, or `--all-roles` is supplied, then argument validation shall
return nonzero `cli_input_invalid` before authentication, quota use, or child
creation, with no canonical receipt. The active parser shall invoke the native
route unconditionally when those retired options are absent. Adapter behavior
may be covered only by explicitly labeled offline historical fixtures that do
not invoke the active parser or count toward the native gate.

### INSTALL-004

Given the current adapter config containing the complete known installer block
(`features.multi_agent`, forced V2 namespace/metadata keys,
`[agents].max_threads`, and the adapter orchestration block), when native
migration is planned, then those proven active adapter paths shall be removed
from the staged target. Provenance requires a matching pristine backup or
recorded pre-write install state for each key/file; a matching value fingerprint
without either source is not ownership proof and must be preserved. An existing
`[agents].max_depth` may remain unchanged as V1 compatibility state but shall
not be added or used by V2. A legacy key with unknown provenance shall remain
and emit `legacy_key_unowned`; the installer shall block the native smoke and
`NATIVE_OK` until an operator explicitly removes or classifies it outside the
active target. Backups may retain original bytes; no proven active adapter route
may remain selectable.

### STAGE-001

Given a completed active install, when the runbook invokes
`install/stage_smoke_home.py` with an absolute destination that does not exist,
then it shall canonicalize the active and staged homes before creating any
temporary directory and reject equal or nested canonical homes as
`stage_materialization_failed`, with no destination write, verifier launch, or
receipt. For a valid home pair, it shall atomically materialize
`STAGED_CODEX_HOME` from the post-install active target before invoking
`verify_dispatch.py`. Every hashed and auth source path shall
resolve inside the canonical active home before reading; a source symlink
escape or source resolving into the staged destination shall return
`stage_materialization_failed` with no destination write, verifier launch, or
receipt. It shall derive the canonical native-V2 config projection and copy
only that projection, the exact hashed policy/role inputs, and `auth.json`
through a sibling temporary directory and an
exclusive atomic
no-replace commit; an overwriting rename is invalid. Copy, permission,
existing-destination, race-injected destination, unsupported publication
primitive, finalization, source replacement, source symlink-swap, and source
metadata-change failures shall each return out-of-band
`stage_materialization_failed`; the fixture shall assert that the existing or
race-created destination is not deleted/reused, no destination is published,
and neither `verify_dispatch.py` nor Codex launches. Every failed case shall
also assert that the sibling temporary directory and any copied `auth.json`
are removed before return, and no canonical receipt is written.
The active-home fixture shall contain `.DS_Store`,
`.app-server-state-reconciled-v1`, `.codex-global-state.json`,
`.codex-global-state.json.bak`, `..codex-global-state.json.tmp-*`, and
future unknown root metadata. The stager and verifier shall project only the
explicit required paths. A guarded fixture shall prove
that unknown root entries are not statted, opened, copied, or hashed, including
unknown or known runtime files, directories, symlinks, and special files;
unique sentinel bytes must not occur anywhere in the staged output. The same
entries in the pre-launch staged home shall return `stage_layout_untrusted`.
Config, the sole effective policy, the exact role manifest, and auth shall
still reject symlinks, special or unreadable files, containment escapes,
copy-time replacement, metadata mutation, and pre-publication TOCTOU.
The verifier shall
validate the supplied staged home and freeze its private snapshot, not rebuild
it implicitly from the active home.

### INSTALL-005

Given a staged smoke home, when preflight runs, then the only hashed inputs are
the canonical native-V2 `config.toml` projection, exactly one effective global
policy file, and the approved recursive seven-role manifest. The only allowed
credential entry is
`auth.json`; keyring auth is external, and `.credentials.json` requires an
explicit MCP OAuth file-store fixture. Existing active runtime entries,
including SQLite state, logs, sessions, shell snapshots, temporary files,
history, model cache, and version metadata, are excluded without inspection.
The pre-launch staged home rejects every runtime or unknown entry with
`stage_layout_untrusted`; Codex creates its runtime outputs only after
preflight. Profiles, system/managed/cloud/MDM layers remain unowned effective
layers and block preflight.
Unrelated active config from the exact resource inventory
(`notify`, `mcp_servers`, `plugins`, `skills`, `marketplace`/`marketplaces`,
`model_providers`, `projects`, `project_root_markers`, compact-prompt, log,
SQLite, config-lock, or other path-bearing fields) is excluded from the
projection. The same entries in a caller-supplied staged config are rejected
with `external_input_unowned`; unknown staged path-bearing keys are also
rejected. Extra roles or declarations return
`role_manifest_extra` or `role_layer_unapproved`. Matching is ASCII
case-insensitive per dotted segment: `Path`, `file`, `dir`, `directory`,
`command`, `executable`, `cwd`, and every `*_path` segment match. Strings
beginning `/`, `~/`, `./`, `../`, `${HOME}`, `${CODEX_HOME}`, `C:\\` or
`\\\\server\\share`, or an ASCII `scheme://` match; any non-empty
`command`/`executable` value matches. Unknown nested
arrays/tables containing these values return `external_input_unowned`. Plain
values such as `medium`, `true`, and `3` remain unrelated-key safe.
`SMOKE_DIR` must be outside `REPO_ROOT` and all its ancestors must be free of
project-local Codex config, `AGENTS.md`, `AGENTS.override.md`, and every
configured project-root marker. If `project_root_markers` is absent, the
fixture checks `.git`; if present, it checks the exact configured array.
The generated command shall include `--skip-git-repo-check` only after this
clean-cwd validation succeeds.
Its prompt shall issue one `wait_agent` after the sole typed spawn so the child
is not aborted before its rollout context is observable.
Otherwise return `smoke_cwd_untrusted`. The verifier launch capture shall
show only the approved `CODEX_HOME`, `CODEX_SQLITE_HOME`, and `--codex-cwd`
binding; missing capture returns `SKIPPED:
environment_binding_unobservable`, and a wrong launch value returns
`FAILED: environment_binding_mismatch`.

### INSTALL-006

Given a migration with a pre-write provenance record, when any target write
fails or the post-write fingerprint does not match, then the transaction shall
be marked aborted and the record shall not authorize future cleanup. The
authoritative state is sibling `<CODEX_HOME>.pilotfish-install-state.json` with
mode `0600`; its `.pending` sidecar is never proof and is removed or invalidated
on abort. Only a committed record whose target bytes match the recorded
post-write fingerprint may prove ownership. An aborted or stale record returns
`legacy_key_unowned` and keeps the legacy input intact. A simulated process
crash leaving `.pending`, partial target writes, or an old committed state shall
stop the next run before writes; it shall preserve the backup and require an
operator resolution rather than auto-restoring or deleting bytes.

### INSTALL-007

Given an active extra role, the only automatically removable retired asset is
`install/retired/v1.0.0/explore.toml` or
`install/retired/v1.0.1/explore.toml` when the active `explore.toml` is
byte-identical and the source hash matches respectively
`9bfdcbc3c032c084dcc0ee77e4fa74de3b30f0e1dfd1e87e180545052a85b59b` or
`d90b4735917afe9d5525c2f0429406c6bffa8d539d664b27760ed4680449a9a4`.
Gate 2 must cover the deletion. A
customized or unknown `explore.toml`, an uppercase `Explore.toml`, or any other
extra filename is preserved, shown in the plan, and blocks the staged manifest
with `role_manifest_extra` until an explicit operator decision.

### POLICY-001

Given a named-role delegation, when the policy/request fixture is validated,
then a non-empty delegation `message`, known `agent_type`, schema-safe
lowercase task name, and one of `fork_turns = "none"` or positive integer
strings `"1"` through `"3"` shall be present. These bounds are Pilotfish
request-construction policy; Codex itself also accepts `all` and larger
positive integers. Full-history forks and child model, reasoning-effort,
`service_tier`, and `fork_context` overrides shall be rejected.

### POLICY-002

Given an unavailable native typed spawn surface, when a delegation is
attempted, then the policy shall require a fail-closed result and no untyped
retry. The test shall identify this as a policy/post-hoc boundary, not claim a
pre-execution runtime cancellation hook.

### POLICY-003

Given any explicit `service_tier` key in named-role spawn arguments, when the
verifier classifies the request, then it shall return
`FAILED: service_tier_override_forbidden` in the dispatch phase. A
missing key remains eligible for other native evidence checks, and deliberate
parent-tier inheritance remains allowed.

## Native evidence and gate

### NATIVE-E2E-001

Given a fresh authenticated Codex `rust-v0.145.0` session and explicit operator
opt-in, when the native smoke runs, then its preflight shall compare
`codex --version` to exactly `0.145.0` before authentication or quota use. A
single parsed other version shall return `FAILED: version_not_pinned`; malformed
or ambiguous output shall return `SKIPPED: version_parse_failed`, without
creating a child. The accepted run shall contain at least one parent
`multi_agent_version` field, and every observed value shall normalize to
`"v2"`; multiple consistent observations are valid. Missing selection is
`SKIPPED: native_v2_selection_unobservable`, and any conflicting or non-`v2`
value is `FAILED: native_v2_selection_mismatch`. It shall also prove a
function call
named `spawn_agent` with a non-empty `message`, typed arguments, and exact
spawn/call correlation, without requiring a particular namespace. The accepted
argument set is exactly `message`, `agent_type`, `task_name`, and `fork_turns`.
requested role/task/fork come from spawn arguments, parent identity from
`sub_agent_activity`, and child model/reasoning from `turn_context` matching the
installed role. An adapter namespace alone shall never count as native proof.

### NATIVE-E2E-002

Given a native smoke result, when the verifier classifies evidence, then it
shall accept only the exhaustive reason/status/phase combinations in SPEC.md.
Missing core fields produce `SKIPPED` when unobservable; observed conflicts or
policy violations produce `FAILED`. A pre-child `SKIPPED`/`FAILED` receipt may
contain only `status`, `reason_code`, `phase`, `child_created`,
`codex_version`, and all six hashes
(`active_config_sha256`, `active_role_manifest_sha256`, `active_policy_sha256`,
`target_config_sha256`, `target_role_manifest_sha256`,
`target_policy_sha256`). `codex_version` is the normalized token or `unknown`
when parsing fails. A post-spawn result may add observed role/task/fork and
opaque refs, but model/effort may appear only when read from child
`turn_context`. Missing child context returns
`SKIPPED: child_evidence_missing`; present context without model/effort returns
`SKIPPED: child_binding_unobservable`; wrong model or effort returns the
specific `FAILED: child_model_mismatch` or `FAILED: child_effort_mismatch`;
other role/task/fork binding errors return `FAILED: child_binding_mismatch`.
A fixture with both missing typed spawn and missing child context returns
`SKIPPED: native_spawn_evidence_missing`, not `child_evidence_missing`.
Unknown reason codes and phase/status pairs
are invalid. An observed sandbox may be recorded only when stably exposed;
developer-instruction application is outside the receipt contract and shall
never be inferred from config. `NATIVE_OK`
shall require every mandatory core field and `reason_code = "native_verified"`.
The offline matrix fixture shall cover every reason row, including the
current `native_schema_introspection_unavailable` baseline,
`parent_model_unavailable`, `parent_model_unavailable_after_spawn`,
`codex_exec_failed`, `codex_exec_failed_after_spawn`,
`environment_propagation_failed`,
`environment_binding_unobservable`, `environment_binding_mismatch`,
`external_input_unowned`, `service_tier_override_forbidden`, and the
role/parent/child binding failures. Combination fixtures shall prove
`service_tier` wins over missing correlation, other forbidden arguments and
second spawns return `policy_violation`, and an untyped fallback returns
`untyped_fallback_detected` before `native_spawn_evidence_missing`. Snapshot
fixtures shall cover a readable pre-child mutation classified as
`phase = preflight, child_created = no`, a mutation discovered during
execution with `child_created = no` and `child_created = unknown`, a
post-spawn mutation with `child_created = yes`, and a post-spawn mutation with
`child_created = unknown`. Pair both execution-pre-child cells with
`codex_exec_failed` and both post-spawn cells with
`codex_exec_failed_after_spawn`; a changed digest wins in each pair. An
unreadable mandatory input remains the out-of-band
`hash_input_unavailable` case.

### NATIVE-E2E-003

Given an absolute `--active-codex-home` and a distinct staged
`--codex-home`, when native preflight runs, then it shall canonicalize both
existing readable directories before hashing. Missing, unreadable,
non-absolute, equal canonical paths (including symlink aliases), or nested
canonical homes shall return out-of-band `home_input_invalid` before hashing,
authentication, or child creation, with no canonical receipt. Fixtures shall
also cover an active/staged mandatory-input symlink that resolves into the
other home and a symlink escape outside its own home; both are
`home_input_invalid`. Given a valid, distinct, non-nested home pair, a missing
or unreadable mandatory hashed input shall return out-of-band
`hash_input_unavailable` without fabricated hashes. Otherwise it shall require
equal active/staged config, role-manifest, and
policy hashes before child creation; any mismatch shall return canonical
`FAILED: target_hash_mismatch`.
Given any parent receipt, when the verifier serializes the result, then its
keys shall be limited to `status`, `reason_code`, `phase`, `child_created`,
`codex_version`, `active_config_sha256`, `active_role_manifest_sha256`,
`active_policy_sha256`, `target_config_sha256`, `target_role_manifest_sha256`,
`target_policy_sha256`, `role`, `task_name`, `fork_turns`, `parent_ref`,
`child_ref`, `model`, `reasoning_effort`, and the optional `sandbox`.
`codex_version` shall equal the preflight
`codex --version` result; active and target hashes shall be captured and equal
before child creation. The target hashes shall come from an immutable staged
`CODEX_HOME` snapshot; the launch wrapper shall pass both approved homes and
`--codex-cwd` to the parent command. Hidden child-process environment is not
claimed as observable. The verifier shall recheck the hashed inputs before
accepting the result. The config hash shall cover the canonical native-V2
config projection. The manifest hash shall use
a canonical stream for sorted relative POSIX paths: big-endian `u64`
path-byte length, UTF-8 path bytes, big-endian `u64` TOML-byte length, and raw
TOML bytes. The receipt shall reuse those hashes.
`parent_ref` and `child_ref` shall be the first 16 lowercase hex characters of
SHA-256 digests of runtime IDs. The receipt shall reject raw IDs, absolute
paths, raw secrets, hidden metadata, and unapproved keys.

### RECEIPT-TRANSPORT-001

Given an invalid CLI home pair, retired CLI option, invalid receipt
destination, a write failure before or after execution, or a
missing/unreadable mandatory hashed input, then the verifier shall return a
nonzero result with `home_input_invalid`, `cli_input_invalid`,
`receipt_destination_invalid`, `receipt_write_failed`, or
`hash_input_unavailable` on stderr, as applicable. It shall emit no
`NATIVE_OK`, create no child for preflight/CLI failures, and not fabricate a
partial receipt or six hashes. These transport/pre-receipt diagnostics are
outside the canonical receipt key matrix.

### GATE-001

Given the offline suite and one live native smoke, when migration completion is
evaluated, then the active target shall already be free of adapter transport
and adapter-only config paths before the smoke, and the live result shall be
`NATIVE_OK`. `SKIPPED` is incomplete, and `FAILED` blocks completion. After
`NATIVE_OK` plus Gate 4 authorization, residual adapter files or temporary
receipts may be deleted; rollback shall otherwise exist only as backup or an
explicitly reverted commit.

## Offline test boundary

### TEST-BOUNDARY-001

Given the normal test suite, when tests run without credentials, then no test
shall call a model, scan the full Codex session tree, mutate the user's real
Codex home, or require the live native smoke.
