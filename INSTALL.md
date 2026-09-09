# Pilotfish-Codex installation playbook

This playbook is for an AI agent installing the native Pilotfish-Codex target.
Read it completely before running an installation command. The detailed
ownership and migration rules are in
[`install/AGENT-INSTALL.md`](install/AGENT-INSTALL.md); this playbook does not
replace that runbook.

## Scope and prerequisites

The installer changes one Codex home. The default is `~/.codex`; set the
`CODEX_HOME` environment variable or pass `--codex-home` to select another
home. It installs the
native Pilotfish roles, the active bootstrap block in the selected root
`AGENTS.md`, the `pilotfish-codex` Plugin/Skill through Codex's local
marketplace contract, native config, and the Pilotfish hook registration and
script. It does not install an
adapter, change shell startup files, manage credentials, or use `sudo`.

Before any run, confirm all of the following:

- Codex CLI is `>=0.147.0` (one bare version token; a suffix or an ambiguous
  `--version` result is not accepted).
- Python is `3.11` or newer.
- A local POSIX checkout has Bash and Python; a native Windows checkout has
  PowerShell and Python. No network tools are needed for the local path.
- A remote POSIX path additionally needs `curl`, `tar`, `mktemp`, and network
  access to `github.com`; a remote PowerShell path uses
  `Invoke-WebRequest` and `tar`. The remote archive is selected by a visible
  ref.
- The POSIX entrypoint is `install/install.sh`; the native Windows entrypoint is
  `install/install.ps1`; the actual installer remains `install/install.py`.
  `--ref` belongs to either wrapper and must not be passed to `install.py`.

Do not print or copy `auth.json`, tokens, API keys, or other credentials while
inspecting the home.

## Confirmation boundary

The agent may fetch this playbook, inspect source, check versions, read the
documented configuration files, and run `--help` or `--dry-run` without
approval. A remote dry-run downloads a pinned archive into the installer's
private temporary directory; it does not write the Codex home.

Stop immediately after the dry-run and before any real install command that
targets the selected home. Show the user:

- the absolute Codex home path;
- the selected source and ref;
- every `would change primary:` path;
- the policy and hook changes;
- existing files that will receive a timestamped
  `*.pilotfish-codex-<timestamp>` backup; and
- any role drift, extra role, pending transaction, or unresolved hook
  registration ownership that caused an abort.

Ask for explicit approval to back up and write that home. Approval must name
the path and does not authorize replacing customized same-name roles,
deleting residual roles, changing credentials, or using elevated privileges.
If the user does not approve, stop with no install command.

## Inspect before execution

From a checkout, inspect both the thin shell wrapper and the detailed runbook
before invoking the wrapper:

```bash
sed -n '1,220p' install/install.sh
sed -n '1,260p' install/AGENT-INSTALL.md
bash install/install.sh --help
```

For a remote-only run, fetch `INSTALL.md` and the shell entrypoint from the
same pinned ref, then inspect the unpacked `install/AGENT-INSTALL.md` and
`install/install.sh` before proceeding. Do not silently substitute `main` for a
requested pinned ref.

Check the prerequisites and select the target home without changing it:

```bash
python3 --version
codex --version
PILOTFISH_TARGET_HOME="${CODEX_HOME:-$HOME/.codex}"
printf 'target home=%s\n' "$PILOTFISH_TARGET_HOME"
```

Inspect only the managed inputs. Preserve unrelated config and custom role
files; do not read credentials:

```bash
if [ -f "$PILOTFISH_TARGET_HOME/config.toml" ]; then
  sed -n '1,240p' "$PILOTFISH_TARGET_HOME/config.toml"
fi
for policy in "$PILOTFISH_TARGET_HOME/AGENTS.md" "$PILOTFISH_TARGET_HOME/AGENTS.override.md"; do
  if [ -s "$policy" ]; then
    printf '\n--- %s ---\n' "$policy"
    sed -n '1,260p' "$policy"
  fi
done
if [ -d "$PILOTFISH_TARGET_HOME/agents" ]; then
  find "$PILOTFISH_TARGET_HOME/agents" -maxdepth 1 -type f -name '*.toml' -print
fi
```

If both policy files are non-empty, or if a pending state sidecar exists, stop
for operator resolution before a dry-run. The detailed runbook defines the
legacy migration and ownership evidence that must remain intact.

## Dry-run

Use one of these entrypoints. Local checkout is always the first source choice
when the shell script is executed from a valid checkout.

Local checkout:

```bash
PILOTFISH_TARGET_HOME="${CODEX_HOME:-$HOME/.codex}"
bash install/install.sh --dry-run --codex-home "$PILOTFISH_TARGET_HOME"
```

Native Windows PowerShell:

```powershell
$pilotfishHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
.\install\install.ps1 --dry-run --codex-home $pilotfishHome
```

Pinned remote source (replace the placeholder with an exact published tag or
full commit SHA; do not run the placeholder itself):

```bash
PILOTFISH_TARGET_HOME="${CODEX_HOME:-$HOME/.codex}"
PILOTFISH_REF='<release-tag-or-commit-sha>'
curl -fsSL \
  "https://raw.githubusercontent.com/miyago9267/pilotfish-codex/${PILOTFISH_REF}/install/install.sh" \
  | bash -s -- --ref "$PILOTFISH_REF" --dry-run \
    --codex-home "$PILOTFISH_TARGET_HOME"
```

`--ref=<release-tag-or-commit-sha>` is equivalent to the two-argument form.
Keep the raw script URL ref and the archive ref identical. `PILOTFISH_REF` is
only the wrapper fallback when `--ref` is omitted. The wrapper prints
`selected source:` and `selected ref:` before a remote fetch.

A successful dry-run prints `would change primary:` lines and allowed state,
backup, and pending-artifact names, or says that the target is already up to
date. It must not create those artifacts. A failed dry-run is a stop signal;
resolve its ownership or state error rather than weakening the installer.
When the host Plugin registry is unavailable, the native runtime still installs
but the committed state records Plugin status as `unavailable`; this is a
fallback, not proof that the Skill is active.

## Install after approval

After the user approves the exact home and planned writes, rerun the same
source and ref without `--dry-run`.

Local checkout:

```bash
PILOTFISH_TARGET_HOME="${CODEX_HOME:-$HOME/.codex}"
bash install/install.sh --codex-home "$PILOTFISH_TARGET_HOME"
```

Native Windows PowerShell:

```powershell
$pilotfishHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
.\install\install.ps1 --codex-home $pilotfishHome
```

Pinned remote source:

```bash
PILOTFISH_TARGET_HOME="${CODEX_HOME:-$HOME/.codex}"
PILOTFISH_REF='<release-tag-or-commit-sha>'
curl -fsSL \
  "https://raw.githubusercontent.com/miyago9267/pilotfish-codex/${PILOTFISH_REF}/install/install.sh" \
  | bash -s -- --ref "$PILOTFISH_REF" \
    --codex-home "$PILOTFISH_TARGET_HOME"
```

The wrapper forwards only installer arguments such as `--dry-run` and
`--codex-home`; it consumes `--help` and `--ref`. It validates a remote ref
before constructing the codeload URL, uses no `eval` or `sudo`, and removes
only its own temporary directory.

If the active policy path is a symlink managed by the user's dotfiles, the
installer stops by default. After verifying the target, explicitly authorize
integration with `--follow-policy-symlink --policy-root <contained-root>`; this
preserves the symlink and writes only its regular-file target. A stale committed
policy fingerprint likewise stops by default. Use
`--reconcile-current` only after the dry-run confirms the current policy/config
are the intended source of truth; the resulting state version 4 records the
accepted preimages, target identity, previous sidecar digest, post-merge
fingerprints, and rollback paths. Plugin installation may update only its own
`plugins`/`marketplaces` entries; a foreign config mutation aborts.

## Validate and trust the hook

When a checkout is available, validate the installed config and role manifest:

```bash
python3 install/validate_agents.py \
  --config "$PILOTFISH_TARGET_HOME/config.toml" "$PILOTFISH_TARGET_HOME/agents"
```

The expected result is:
`all native Pilotfish config and agent TOMLs valid`.
Also confirm that these managed hook files exist, without printing secrets:

```bash
test -f "$PILOTFISH_TARGET_HOME/hooks.json"
test -f "$PILOTFISH_TARGET_HOME/hooks/pilotfish_autoroute_gate.py"
grep -F 'Pilotfish automatic typed Plan-review gate.' \
  "$PILOTFISH_TARGET_HOME/hooks.json"
```

### Prove the hook can launch

Registration and trust do not prove that the registered command runs. A hook
whose interpreter is missing fails silently and open: no enforcement, and no
signal that enforcement is gone. Run the registered command's own launch probe
before trusting the result of any later gate check.

On macOS and Linux:

```bash
/usr/bin/env python3 \
  "$PILOTFISH_TARGET_HOME/hooks/pilotfish_autoroute_gate.py" --selftest
```

On native Windows, `python` is frequently the Microsoft Store alias stub, which
opens the Store instead of running the script. Run the probe through the same
command the `commandWindows` entry uses and require real output:

```powershell
uv run --no-project python -c "import os,runpy; from pathlib import Path; runpy.run_path(str(Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'hooks'/'pilotfish_autoroute_gate.py'), run_name='__main__')" --selftest
```

Both must print `pilotfish-autoroute-gate schema=<n> launchable`. Any other
result — no output, a Store window, `ModuleNotFoundError` — means the gate is
not enforcing anything on this machine. Fix the interpreter or record the gate
as unenforced; do not report the install as gated.

Trust the Pilotfish registration once in an interactive Codex session. Inspect
the group that runs `hooks/pilotfish_autoroute_gate.py`, start Codex, and use
`/hooks` to review and trust it. A pre-existing user-level `hooks.json` can
have its own top-level description, so do not rely on one global description as
the registration identity. Codex records trust against the hook definition
hash; repeat this only when that definition changes. Do not use a bypass flag
for normal active-runtime work.

If the UI exposes trust only as a prompt while a session is starting, close
that session and start a fresh one. Approve the exact hook at session start,
then run `/hooks` in that session (or the next fresh session) to confirm the
trusted state. The resulting `[hooks.state]` entry is expected and does not
require reinstalling Pilotfish.

For a remote-only install with no checkout, validate the same files from a
checkout or source archive at the exact installed ref. Do not fetch an
un-pinned validator or claim validation from a different ref.

## Safe rerun and update

Rerunning the same command at the same ref is intended to be idempotent. It
preserves unrelated config, custom same-name role bytes, user files, and
complete unrelated native hook groups. Pilotfish only owns its exact,
event-bound hook groups and its script. A sidecar-proven Pilotfish script can
upgrade to the selected source; a changed, missing, duplicated, or unproven
Pilotfish group or script stops the update. Run a new dry-run and obtain
approval again before changing to another visible tag or commit. Review every
changed role, policy, hook, and backup path before the real update.

The installer fails closed for customized role drift, malformed or ambiguous
hook registration, an unproven current or historical Pilotfish group, extra
roles, malformed config, or stale transaction evidence. Do not force those
cases by deleting state or passing an unsupported option to `install.py`.

## Recovery and rollback

If an install aborts, stop. Preserve the error output, the pending or aborted
state sidecar, and every `*.pilotfish-codex-<timestamp>` backup. Do not rerun
over a pending transaction, delete unknown roles, or restore the whole home
blindly. After separate operator approval, copy the affected managed files and
state evidence to an explicitly chosen recovery directory; exclude credentials
unless the operator deliberately handles them.

The installer stages writes, creates backups before replacement, verifies
post-write fingerprints, and records committed ownership in a mode-`0600`
sidecar. Its isolated smoke candidate uses the clean Pilotfish registration,
not any unrelated active-home hook group. If a concurrent edit is detected, the
installer preserves that content and leaves an aborted sidecar for operator
resolution. Use those records and
[`install/AGENT-INSTALL.md`](install/AGENT-INSTALL.md) to decide a targeted
restoration. A customized same-name role or an unproven Pilotfish hook group
requires an explicit operator decision; this playbook does not authorize
deletion or an uninstall shortcut.

## Final report

Report all of the following in the agent's completion message:

- selected source, exact ref, and absolute target home;
- dry-run result and real install result, including whether it was already
  up to date;
- validation command and its output;
- changed primary paths and exact backup/state paths, if any;
- hook trust result, including whether a fresh session-start prompt was used;
- preserved or unresolved custom roles, extra files, and pending state; and
- confirmation that no credentials, shell startup files, or elevated
  privileges were used.
