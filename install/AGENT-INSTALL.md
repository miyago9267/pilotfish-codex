# Pilotfish-Codex native install runbook

This runbook installs one native Codex Multi-Agent V2 target. It does not
support an adapter fallback.

## Preconditions

- Require exactly Codex `0.145.0`. Lower, higher, ambiguous, suffixed, or
  nonzero `codex --version` output fails before writes.
- The native configuration is exactly:

```toml
[features.multi_agent_v2]
enabled = true
max_concurrent_threads_per_session = 4
```

- The total of four slots includes the root session and permits three children.
  Do not emit `features.multi_agent`, `tool_namespace`,
  `hide_spawn_agent_metadata`, `agents.max_threads`, or an `[agents]`
  concurrency fallback.
- The native manifest is exactly `executor`, `mech-executor`,
  `plan-verifier`, `scout`, `security-executor`, `security-reviewer`, and
  `verifier`. Role identity is each TOML `name`; filename equality is a local
  Pilotfish validation rule.

## Preflight and approval

1. Run `codex --version` and stop unless its one standalone version token is
   exactly `0.145.0`.
2. Read the active `config.toml`, effective global policy (`AGENTS.override.md`
   wins over `AGENTS.md`), and recursively discovered role files. Preserve all
   unrelated content.
3. Locate the sibling install state
   `<CODEX_HOME>.pilotfish-install-state.json`. A `.pending` state or stale
   committed fingerprint stops the installation for operator resolution.
4. Present changed paths, timestamped backups, unowned legacy keys, customized
   same-name roles, and extra roles. General home-write approval never approves
   customized same-name role replacement.
5. Obtain the separate home-write approval before backing up or writing a real
   Codex home. Offline tests use only temporary homes.

The installer uses a pending sidecar, stages all target files, writes backups
before replacement, validates the post-write fingerprint, then atomically
commits the mode-`0600` state sidecar. A pending state is never ownership proof.
Repeated identical installs are idempotent.

A proven, committed per-key record may remove only these prior adapter-owned
paths: `features.multi_agent`, `features.multi_agent_v2.tool_namespace`,
`features.multi_agent_v2.hide_spawn_agent_metadata`, `agents.max_threads`, and
`agents.max_concurrent_threads_per_session`. Matching bytes alone are not
provenance. Unknown legacy input is preserved as `legacy_key_unowned` and blocks
the native smoke.

The installer refuses scalar `false` or table `enabled = false`. Scalar `true`
is converted to the native table. Inline and dotted V2 forms that cannot be
rewritten without collateral edits abort. Existing V2 totals in `1..8` normalize
to `4`; zero, values above eight, or malformed values abort before writes.

Release-pinned canonical v1.3.0 role bytes may upgrade to their packaged v1.3.1
replacements. Any other same-name role difference remains
`installed_role_drift` and requires explicit operator resolution.

## Install and offline validation

```bash
python3 install/install.py --codex-home "$ACTIVE_CODEX_HOME"
python3 install/validate_agents.py \
  --config "$ACTIVE_CODEX_HOME/config.toml" "$ACTIVE_CODEX_HOME/agents"
```

Do not add `[agents.<role>] config_file` declarations. Native recursive
role discovery loads the seven TOMLs directly.

The only retired role eligible for cleanup is lowercase `explore.toml`, after
separate approval, when its bytes exactly match
`install/retired/v1.0.0/explore.toml` or `install/retired/v1.0.1/explore.toml`
and their recorded SHA-256 values. Customized `explore.toml`, uppercase
`Explore.toml`, and every other extra role remain in place and block the staged
manifest. This runbook does not authorize deleting residual adapter files.

## Explicit staging and smoke

The staging and quota gates are separate. Set absolute, distinct values for
`REPO_ROOT`, `ACTIVE_CODEX_HOME`, `STAGED_CODEX_HOME`, and `SMOKE_DIR`.
`SMOKE_DIR` must be outside `REPO_ROOT`, must not exist below a project root,
and its ancestors must contain no project-local Codex configuration,
`AGENTS.md`, `AGENTS.override.md`, or configured root marker.

The staged destination must not exist. Materialize it first:

```bash
python3 "$REPO_ROOT/install/stage_smoke_home.py" \
  --active-codex-home "$ACTIVE_CODEX_HOME" \
  --staged-codex-home "$STAGED_CODEX_HOME"
```

The helper derives a canonical config containing only
`features.multi_agent_v2.enabled = true` and total concurrency `4`, then copies
one effective policy, the seven-role manifest, and `auth.json`. All other
active config keys remain untouched and are not selected for the smoke.
Recognized
`*.pilotfish-codex-*` rollback backups remain in the active home and are not
staged input; they do not require pre-gate cleanup. It canonicalizes
containment, rejects source symlink/TOCTOU changes, cleans temporary copies on
failure, and publishes through an exclusive atomic no-replace operation. Any
`stage_materialization_failed` stops before verifier or Codex launch and creates
no receipt.

The active home is projected from explicit required paths; it is not scanned as
an exact-layout input. Unknown root metadata such as `.DS_Store`,
`.app-server-state-reconciled-v1`, `.codex-global-state.json`,
`.codex-global-state.json.bak`, `..codex-global-state.json.tmp-*`, rollback
backups, existing SQLite state, sessions, logs, temporary files, and future
runtime metadata is not inspected, copied, or hashed. Required config, policy,
role, and auth sources still reject symlinks, special or unreadable files,
containment escapes, and mutation or TOCTOU. Before launch,
`STAGED_CODEX_HOME` remains an exact minimal allowlist; Codex creates its own
runtime state there only after preflight succeeds.

After separate quota approval, run from the clean `SMOKE_DIR` in a fresh,
authenticated `rust-v0.145.0` session:

```bash
cd "$SMOKE_DIR"
LAUNCH_CAPTURE="$SMOKE_DIR/pilotfish-launch-capture.json"
printf '{"CODEX_HOME":"%s","CODEX_SQLITE_HOME":"%s","codex_cwd":"%s"}\n' \
  "$STAGED_CODEX_HOME" "$STAGED_CODEX_HOME" "$SMOKE_DIR" > "$LAUNCH_CAPTURE"
CODEX_HOME="$STAGED_CODEX_HOME" CODEX_SQLITE_HOME="$STAGED_CODEX_HOME" \
  python3 "$REPO_ROOT/install/verify_dispatch.py" --live --yes \
  --role scout --codex-home "$STAGED_CODEX_HOME" \
  --active-codex-home "$ACTIVE_CODEX_HOME" \
  --repository-root "$REPO_ROOT" --codex-cwd "$SMOKE_DIR" \
  --launch-capture "$LAUNCH_CAPTURE"
```

The active verifier has no `--mode` or `--all-roles` route. Supplying either is
`cli_input_invalid` before authentication, quota use, child creation, or
receipt creation. It compares all active/staged config, role-manifest, and
policy hashes before child creation and freezes the staged hash snapshot.
The internal `codex exec` command uses `--skip-git-repo-check` because the
verified clean smoke cwd is intentionally outside every repository.

`NATIVE_OK` requires observed V2 selection, one typed `spawn_agent` call with
exactly `message`, `agent_type`, `task_name`, and `fork_turns`, exact correlation
to child activity, and child `turn_context.model` and `turn_context.effort`.
The probe waits once for that child so `codex exec` does not abort it while
evidence is being written.
Receipts normalize the latter to `reasoning_effort`; raw runtime IDs are hashed.
Namespace is not native evidence. `SKIPPED` is incomplete and `FAILED` blocks
completion. Only after `NATIVE_OK` and Gate 4 approval may residual adapter
artifacts or temporary receipts be deleted.
