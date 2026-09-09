# Pilotfish-Codex native install runbook

This runbook installs one native Codex Multi-Agent target plus the Hybrid
Pilotfish bootstrap and Plugin/Skill package. It does not support an adapter
fallback.

## Preconditions

- Parse exactly one Codex semantic version from `codex --version`. Version
  numbers are recorded for evidence but are not hard-pinned; native schema,
  role binding, and receipt checks determine compatibility.
- The native configuration is exactly:

```toml
max_concurrent_threads_per_session = 3

[features]
default_mode_request_user_input = true
```

Pilotfish owns the orchestration contract, not the user's main-session model
preference. Fresh homes default to Luna/medium with xhigh Plan reasoning;
existing model and effort choices are preserved and may be changed later.

- The value is child concurrency: one root plus up to three children. Do not
  emit `features.multi_agent_v2`, adapter namespace/metadata keys, or
  `agents.max_threads`.
- The native manifest is exactly `executor`, `mech-executor`,
  `plan-verifier`, `scout`, `security-executor`, `security-reviewer`, and
  `verifier`. Role identity is each TOML `name`; filename equality is a local
  Pilotfish validation rule.

## Preflight and approval

1. Run `codex --version` and stop unless its one standalone version token is
   a single parseable semantic version; do not hard-pin a release in the
   installer.
2. Read the active `config.toml`, effective global policy (`AGENTS.override.md`
   wins over `AGENTS.md`) and recursively discovered role files. The installer
   integrates only the short bootstrap into the selected active root policy
   file while preserving bytes outside its marker block. It installs the full
   workflow through Codex's local marketplace and `codex plugin add` contract.
3. Locate the sibling install state
   `<CODEX_HOME>.pilotfish-install-state.json`. A `.pending` state or stale
   committed fingerprint stops the installation for operator resolution. The
   one explicit reconciliation path is `--reconcile-current`; it accepts only
   current policy/config drift whose Pilotfish routing projection is unchanged
   and publishes state version 4 with preimage, identity, and rollback evidence.
4. Present changed paths, timestamped backups, unowned legacy keys, and
   customized same-name roles. Valid extra user roles are preserved and do not
   block installation. General home-write approval never approves customized
   same-name role replacement.
5. Obtain the separate home-write approval before backing up or writing a real
   Codex home. Offline tests use only temporary homes. An installed plugin newer
   than this checkout stops unless `--allow-plugin-downgrade` is explicitly
   selected.

The installer uses a pending sidecar, stages all target files, writes backups
before replacement, validates the post-write fingerprint, then atomically
commits the mode-`0600` state sidecar. A pending state is never ownership proof.
The sidecar binds Pilotfish to its allowlisted, event-bound complete hook groups
instead of claiming ownership of unrelated groups in `hooks.json`. Repeated
identical installs are idempotent.

A legacy V2 table is migratable only when it is exactly `enabled = true` and
`max_concurrent_threads_per_session = 4`, and the committed sidecar has exactly
`config.toml`, all seven canonical role paths, and the currently selected policy
in both target maps. Every non-config target fingerprint and original-byte
record must match; missing, stale, extra, malformed, or unowned state aborts
before writes. A trusted Codex hook may append `[hooks.state]` to
`config.toml`: that is accepted only when the owned routing projection is
unchanged. Conflicting `[agents]` values and extra V2 keys abort as well.
Unrelated config and custom same-name role bytes remain untouched.

The installer refuses disabled or scalar legacy V2 forms, inline/dotted forms,
and malformed/conflicting `[agents]` values. Fresh homes receive the root
concurrency key and an active managed bootstrap block in `AGENTS.md`; migration
removes only the exact proven old V2 table. Existing user policy bytes outside
the managed block are preserved byte-for-byte.

The sidecar is state version 3 for ordinary installs and records Plugin name,
version, source digest, and `installed` or `unavailable` status. A reconciled
current policy or an explicitly followed contained policy symlink publishes
state version 4, including the previous sidecar digest, accepted target
preimages/identities, post-merge fingerprints, and root-anchored backup
manifests. An unavailable Plugin does not invalidate the native runtime, but
the installer must not claim that the Skill is active. Plugin installation is
allowed to update only Pilotfish's own `plugins`/`marketplaces` entries; any
other config mutation aborts and remains visible for recovery.

Release-pinned canonical v1.3.0 `plan-verifier` and `security-reviewer` bytes
may upgrade to their packaged v1.3.1 replacements. The released canonical
v1.3.1 `plan-verifier` and `verifier` payloads may likewise upgrade to their
packaged calibrated contracts. The released canonical v1.3.3 payloads for
those roles may upgrade to the latest packaged routing contracts. Any other
same-name role difference remains `installed_role_drift` and requires explicit
operator resolution. When the operator has explicitly chosen the upstream
canonical role, pass `--replace-drifted-roles`; this replaces only drifted
same-name role files and preserves a timestamped backup. The flag does not
authorize credential, external, or unrelated home changes. For a narrower
update, use `--replace-drifted-role <role>` once per approved role. Both forms
retain role validation, transaction fingerprints, and post-write verification.

## Install entrypoints and offline validation

For a local checkout, use the POSIX shell bootstrapper or native Windows
PowerShell wrapper. Both select the checkout, forward options to the one real
installer, and never need a network download:

```bash
bash install/install.sh --dry-run --codex-home "$ACTIVE_CODEX_HOME"
bash install/install.sh --codex-home "$ACTIVE_CODEX_HOME"

# Only after verifying that the active policy is an intended dotfiles-managed target:
bash install/install.sh --dry-run --follow-policy-symlink \
  --policy-root "$HOME/dotfile/config/ai" --reconcile-current \
  --codex-home "$ACTIVE_CODEX_HOME"
bash install/install.sh --follow-policy-symlink \
  --policy-root "$HOME/dotfile/config/ai" --reconcile-current \
  --codex-home "$ACTIVE_CODEX_HOME"
```

```powershell
$activeCodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
.\install\install.ps1 --dry-run --codex-home $activeCodexHome
.\install\install.ps1 --codex-home $activeCodexHome
```

For a remote install, choose a release tag or immutable commit SHA. Pin that
same value in both the raw shell URL and `--ref`; do not install a real home
from the mutable `main` branch:

```bash
REF="<release-tag-or-commit-sha>"
curl -fsSL \
  "https://raw.githubusercontent.com/miyago9267/pilotfish-codex/$REF/install/install.sh" \
  | bash -s -- --ref "$REF" --dry-run --codex-home "$ACTIVE_CODEX_HOME"
```

The shell requires Bash, Python 3.11+, and a parseable Codex CLI version.
Inspect it with `bash install/install.sh --help` before using a remote copy.
The direct Python route is equivalent for a checked-out repository:

```bash
python3 install/install.py --codex-home "$ACTIVE_CODEX_HOME"
python3 install/validate_agents.py \
  --config "$ACTIVE_CODEX_HOME/config.toml" "$ACTIVE_CODEX_HOME/agents"
```

To produce the Hybrid activation report, use a fresh process. The report keeps
bootstrap, Plugin/Skill availability, and behavior verification separate:

```bash
python3 install/probe_hybrid_runtime.py \
  --codex-home "$ACTIVE_CODEX_HOME" \
  --project "$ACTIVE_CODEX_HOME" \
  --persona-token Monika \
  --recap-token recap \
  --run-session
```

Do not add `[agents.<role>] config_file` declarations. Native recursive
role discovery loads the seven TOMLs directly.

Before trusting the hook, prove the registered command can launch at all. A
missing interpreter fails silently and open, so a trusted-but-unlaunchable hook
enforces nothing:

```bash
/usr/bin/env python3 \
  "$ACTIVE_CODEX_HOME/hooks/pilotfish_autoroute_gate.py" --selftest
```

Require `pilotfish-autoroute-gate schema=<n> launchable`. On native Windows run
the probe through the `commandWindows` form instead; this uses
`uv run --no-project python` because `python` is often the Store alias stub.
Report the gate as unenforced on any other result rather than reporting a gated
install; see
[the installation playbook](../INSTALL.md#prove-the-hook-can-launch).

After the installer adds the Pilotfish hook group, open an interactive Codex
session and use `/hooks` to inspect and trust the group that runs
`hooks/pilotfish_autoroute_gate.py`. An existing `hooks.json` can retain a
user-owned top-level description, so trust the exact group rather than assuming
one global label. If `/hooks` is unavailable, start a new interactive session
and confirm the launch-time trust prompt. Codex records trust against the hook
definition hash; repeat this one-time step only when that definition changes.
Do not use the bypass flag for normal active-runtime work. Its `[hooks.state]`
entry is expected and does not require reinstalling Pilotfish.

## Update, failure handling, and rollback

Use the same pinned ref for an update. First run its dry-run, inspect the
primary paths and allowed transaction artifacts, then run the identical command
without `--dry-run`. A clean rerun reports `already up to date; nothing to
change`. Trust the hook again only when the prompt identifies a changed hook
definition.

The installer preserves structurally unrelated valid hook groups, but aborts
rather than adopting an unproven current or historical Pilotfish group,
repairing a changed/duplicated/moved Pilotfish group, replacing an unproven hook
script, replacing a customized same-name role, or accepting a stale sidecar. A
script proven by the committed sidecar may upgrade to the selected source. Stop
on other errors. Inspect the current file and its recorded ownership before
taking a separately approved replacement action; do not delete the state
sidecar or rollback backup merely to make an install pass.

On native Windows, the installer also prints a non-blocking compatibility
warning for any preserved command hook that has no `commandWindows` field. The
warning identifies the event and command so its owner can add a Windows form;
Pilotfish does not delete, rewrite, or adopt that unrelated hook.

There is no automatic uninstall or rollback. Each replaced target has a
timestamped sibling backup named `*.pilotfish-codex-<timestamp>`. If recovery
is required, stop the installer, identify the exact affected target and backup,
obtain separate approval, restore only that target, and then rerun the dry-run.
Do not restore a whole Codex home or copy a backup over unrelated runtime state.

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

The helper derives a canonical config containing the installed Luna/medium root
binding, xhigh Plan mode, native Default-mode decision cards, and child
concurrency `3`.
It then copies one effective policy, the seven-role manifest, source-owned
`hooks.json` plus its hook script, and `auth.json`. All other active config
keys remain untouched and are not selected for the smoke.
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
authenticated Codex session. The verifier records the actual CLI version and
lets the native evidence contract decide compatibility:

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
The internal `codex exec` command enables the native `multi_agent_v2` feature
and uses `--skip-git-repo-check` because the
verified clean smoke cwd is intentionally outside every repository.

Generic role probes require one typed `spawn_agent` call with exactly
`message`, `agent_type`, `task_name`, and `fork_turns`, exact correlation to
child activity, and child `turn_context.model` and `turn_context.effort`.

For `--autoroute` only, the verifier also accepts `session_metadata` correlation
when no spawn/activity transport evidence exists. The metadata path requires
exactly one Luna/medium root and one directly linked `plan-verifier` child at
Sol/high; any mixed, orphaned, duplicate, or malformed evidence fails closed.
The probe waits once for that child so `codex exec` does not abort it while
evidence is being written. Receipts normalize effort to `reasoning_effort`,
hash raw runtime IDs, and record `correlation_mode`. Namespace is not native
evidence. `SKIPPED` is incomplete and `FAILED` blocks completion. Only after
`NATIVE_OK` and Gate 4 approval may residual adapter artifacts or temporary
receipts be deleted.
