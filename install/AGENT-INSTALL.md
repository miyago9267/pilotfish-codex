# pilotfish-codex — Agent Install Runbook

> This runbook is for a Codex agent installing pilotfish-codex on a user's
> machine. Follow the steps in order, keep the approval gate, and preserve
> unrelated Codex configuration.

## Contents

- [What you are installing](#what-you-are-installing)
- [Updating an existing install](#updating-an-existing-install)
- [Step 1 — Preflight](#step-1--preflight)
- [Step 2 — Present the plan](#step-2--present-the-plan)
- [Step 3 — Apply](#step-3--apply)
- [Step 4 — Verify and hand off](#step-4--verify-and-hand-off)
- [Uninstall](#uninstall)

---

## What you are installing

pilotfish-codex ports Pilotfish v1.2's phase-aware orchestration and capability
boundaries to seven native Codex roles. Remora 0.1.10 supplies the GPT-5.6
model and reasoning-effort reference for those shared roles. The template
recommends Sol for the main session while its reasoning effort stays under the
user's control.

| Target | Change |
|---|---|
| `~/.codex/config.toml` | Offer to set `model = "gpt-5.6-sol"`; enable multi-agent support; set a three-leaf, one-generation limit |
| `~/.codex/agents/` | Install `scout`, `plan-verifier`, `security-reviewer`, `mech-executor`, `executor`, `verifier`, and `security-executor` |
| Active global instruction file | Insert one `### Orchestration` block between `pilotfish-codex:begin` and `pilotfish-codex:end` markers |

The source of truth is the repository's [templates](../templates) directory.
When running inside a local clone, use those files directly. Otherwise fetch
every template from the same Git ref as this runbook. Updates from v1.0.x also
fetch the comparison-only retired Explore templates for
[v1.0.0](./retired/v1.0.0/explore.toml) and
[v1.0.1](./retired/v1.0.1/explore.toml) from that ref so legacy cleanup is
verifiable. Never install either retired asset as an active role.

> **Commit pinning:** If the install prompt names a tag or commit SHA, fetch
> `VERSION`, `CHANGELOG.md`, and every template from that exact ref. Never mix a
> pinned runbook with templates from `main`.

> **Codex permission boundary:** Read-only roles set
> `sandbox_mode = "read-only"`, but a live parent-session permission override
> can supersede a custom agent default. Report the active parent permission
> mode in the plan; do not describe the port as an absolute tool allowlist.

## Updating an existing install

Before the normal preflight, inspect both global instruction candidates and the
current project root used by the legacy v1.0.x installer:

```text
~/.codex/AGENTS.override.md
~/.codex/AGENTS.md
<current-project-root>/AGENTS.md
```

Resolve the current project root with `git rev-parse --show-toplevel` when
available; otherwise use the current working directory. The project-root file
is a legacy migration source only. New policy is always installed in the active
global instruction file.

Search for `pilotfish-codex v` inside the marker block. A stamp such as
`<!-- pilotfish-codex v1.1.0 -->` is the installed version; markers without a
stamp mean a pre-v1.0.0 install. A complete marker pair in an inactive global
or project-root file is migration work, not an automatic error. Unmatched
markers or more than one pair in the same file still require stopping. Fetch
`VERSION` and `CHANGELOG.md` from the same ref as the templates. Even when the
installed version is current, inspect the installed role set for retired
`explore.toml` or `Explore.toml` files before stopping. Stop only when the
version, owned config, sole active policy block, seven active roles, and
retired-role cleanup are all current. Otherwise report the drift, show any
relevant changelog entries, and continue.

An update is idempotent: identical agent files are skipped, the marked policy
block is replaced in place, and only pilotfish-codex-owned config keys are
considered. Show diffs for customized files before replacing them.

## Step 1 — Preflight

Gather the current state without writing:

1. Run `codex --version`. Require Codex CLI 0.144.1 or newer, the verified
   baseline for this template schema, GPT-5.6 `max` effort, and multi-agent
   depth controls. Stop before the write plan if the version is missing, older,
   or unparsable.
2. Read `~/.codex/config.toml`. Record `model`,
   `model_reasoning_effort`, `features.multi_agent`,
   `agents.max_threads`, and `agents.max_depth`. Preserve every unrelated key
   and table. Locate the pristine config backup under both supported names:
   legacy `config.toml.pilotfish-[0-9]*` and current
   `config.toml.pilotfish-codex-*`. Prefer the earliest legacy backup, then the
   earliest current backup, because a legacy backup predates any v1.0.x-owned
   settings.
3. Determine the active global instruction file. A non-empty
   `~/.codex/AGENTS.override.md` wins; otherwise use `~/.codex/AGENTS.md`.
   Resolve symlinks, deduplicate candidates by resolved path, then inspect it,
   the inactive global candidate, and the current project root for marker pairs.
   Record every stale source that must be backed up and cleaned. If the user
   installed v1.0.x from another known project root, ask for that path rather
   than scanning the whole home directory. Stop for unmatched markers or
   multiple pairs within one file; do not stop merely because one valid stale
   pair exists elsewhere.
4. For a v1.0.x upgrade whose current root
   `model_reasoning_effort = "medium"`, parse the pristine backup. If the root
   key was absent there, classify the current value as confirmed legacy-owned
   and offer an explicit remove-or-keep choice. If the backup contained the
   key, preserve it as user-owned. If no pristine backup exists, report the
   value as ambiguous and preserve it unless the user explicitly approves
   removal.
5. Inspect every `~/.codex/agents/*.toml` file and parse its `name` field.
   Record filename collisions and name collisions for all seven installed
   roles. If an existing file differs from the matching template, include its
   diff in the plan. Treat both discovery aliases as retired roles because
   `scout` owns broad and focused discovery in Codex. For a v1.0.x
   `explore.toml` with `name = "explore"`, record whether it matches a released
   v1.0.x template. Treat an uppercase `Explore.toml` as a pre-release v1.1
   artifact; show its full content and require explicit deletion approval.

The expected routing contract is:

| Role | Model | Effort | Sandbox default |
|---|---|---|---|
| `scout` | `gpt-5.6-luna` | `low` | `read-only` |
| `plan-verifier` | `gpt-5.6-sol` | `medium` | `read-only` |
| `security-reviewer` | `gpt-5.6-sol` | `high` | `read-only` |
| `mech-executor` | `gpt-5.6-luna` | `medium` | Parent session |
| `executor` | `gpt-5.6-luna` | `max` | Parent session |
| `verifier` | `gpt-5.6-sol` | `high` | `workspace-write` for test reproduction |
| `security-executor` | `gpt-5.6-sol` | `max` | Parent session |

## Step 2 — Present the plan

Show a table with every target, exact action, and status: create, merge,
replace, overwrite, or skip. Include the backup paths and every customized-file
diff. Include each inactive instruction block that will be removed before the
canonical block is installed globally. For a confirmed or ambiguous legacy
effort pin, show the keep-or-remove choice. State that fresh installs never set
main-session reasoning effort.

Do not write until the user approves the presented plan. Approval may authorize
overwriting colliding role files, but never infer that permission from the
initial request alone.

## Step 3 — Apply

### Backup and directories

Create the directories, preserve the authoritative pre-install config, and back
up every instruction file that the approved migration will modify:

```bash
mkdir -p ~/.codex/backups ~/.codex/agents
LEGACY_CONFIG_BACKUP=$(find ~/.codex/backups -maxdepth 1 -type f \
  -name 'config.toml.pilotfish-[0-9]*' | sort | head -n 1)
CURRENT_CONFIG_BACKUP=$(find ~/.codex/backups -maxdepth 1 -type f \
  -name 'config.toml.pilotfish-codex-*' | sort | head -n 1)
PILOTFISH_PRISTINE_CONFIG=${LEGACY_CONFIG_BACKUP:-$CURRENT_CONFIG_BACKUP}
```

If the selected backup is missing or invalid TOML, stop treating it as a
baseline and report the problem. On a fresh install with an existing config and
no prior backup, create
`config.toml.pilotfish-codex-$(date +%Y%m%d-%H%M%S)` and record it as
`PILOTFISH_PRISTINE_CONFIG`. On an upgrade with no pristine backup, never copy
the already-modified config under either pristine prefix. Instead, preserve a
rollback snapshot as
`config.toml.before-pilotfish-codex-update-$(date +%Y%m%d-%H%M%S)` and report
that the original pre-install state is unknown. If `config.toml` did not exist
on a fresh install, record that fact rather than creating a fake baseline.

Before changing policy, back up the resolved active global instruction file and
every inactive instruction file whose stale marked block will be removed. Use a
separate timestamped filename with a unique location label for each source so a
global `AGENTS.md` and project-root `AGENTS.md` cannot overwrite one another's
backup.

### Merge config.toml

Use [templates/config.snippet.toml](../templates/config.snippet.toml) as the
canonical values. Perform a TOML-aware key merge; do not append root keys after
an existing table and do not rewrite unrelated sections.

| Key | Merge rule |
|---|---|
| `model` | If absent, set `"gpt-5.6-sol"`. If different, apply the user's approved keep-or-replace choice. |
| `model_reasoning_effort` | Never set it on a fresh install. For a v1.0.x upgrade, remove root value `"medium"` only when the pristine backup lacked that root key and the user explicitly approved the legacy-pin migration. Otherwise preserve it. |
| `features.multi_agent` | If absent, set `true`. If `false`, change it only when the approved plan says so. |
| `agents.max_threads` | If absent, set `3`, allowing up to three leaf agent threads. If different, change it only when approved. |
| `agents.max_depth` | If absent, set `1`. If different, change it only when approved; `1` enforces leaf-only delegation. |

### Install agent files

Write the seven files from `templates/agents/` to
`~/.codex/agents/<same-name>.toml`.

For released v1.0.x cleanup, use the retired templates fetched from this same
Git ref. Verify them before comparison:

| Codex release | Historical commit | Retired asset SHA-256 |
|---|---|---|
| v1.0.0 | `305cbdb1d5ca2dda3a1d74bfa6473f46358a18d5` | `9bfdcbc3c032c084dcc0ee77e4fa74de3b30f0e1dfd1e87e180545052a85b59b` |
| v1.0.1 | `139f9dc2eec32e5a5322f9e85cd2808c41f84a1a` | `d90b4735917afe9d5525c2f0429406c6bffa8d539d664b27760ed4680449a9a4` |

Do not use the inherited repository tag named `v1.0.0`; it identifies the
upstream Claude release, not the untagged Codex v1.0.x history.

| Existing state | Action |
|---|---|
| No file and no name collision | Create from the template |
| Matching file is byte-identical | Skip as current |
| Matching file differs | Apply the approved overwrite choice |
| Another filename declares the same `name` | Stop unless the approved plan explicitly resolves the collision |
| Retired v1.0.x `explore.toml` | Delete it automatically only when it is byte-identical to either verified retired asset; otherwise show the diff and preserve it unless the approved plan explicitly allows deletion |
| Retired pre-release `Explore.toml` | Show its full content and delete it only when the approved plan explicitly allows deletion |

### Install the orchestration block

Use
[templates/agents-md.orchestration.md](../templates/agents-md.orchestration.md)
as the canonical marked block.

| Marker state in active global instruction file | Action |
|---|---|
| File missing or empty | Create it with the canonical block |
| No marker pair | Append the block with one separating blank line |
| Exactly one valid pair | Replace that pair and its contents only |
| Valid pair in an inactive global or current project-root file | After its backup and explicit approval, remove exactly that stale block before installing the canonical block in the active global file |
| Valid pairs in multiple candidate files | Treat the active global file as the destination and remove each stale marked block from inactive instruction files after backup and approval |
| Multiple or unmatched pairs within one file | Stop and ask; never use a greedy replacement |

Do not modify content outside the markers. If the user declines removal of a
stale inactive or project-root block, stop the policy migration instead of
creating competing policy blocks. When a stale block differs from the known
v1.0.x policy, show that diff before requesting removal approval. Preserve an
empty file after block removal rather than deleting a possibly versioned
project file.

## Step 4 — Verify and hand off

Run structural and runtime-aware checks:

```bash
codex --strict-config doctor --summary
```

Then parse `~/.codex/config.toml` and all seven agent TOMLs with a TOML parser.
Verify the exact name, model, effort, and sandbox defaults from the routing
table. Confirm `agents.max_threads = 3` and `agents.max_depth = 1`. Confirm the
active global instruction file has exactly one marker pair and no inactive
global or current project-root candidate retains one. Read back the version
stamp. Confirm neither retired discovery filename remains when the approved
outcome is the canonical seven-role roster. If the user chose to preserve
either retired file, report the extra active role and do not claim an exact
seven-role installation. Re-run the same preflight and confirm every policy
action is now `skip`; this is the idempotence check.

Tell the user to start a fresh Codex session. Agent definitions and global
instructions are discovered at session start, so an already-running task does
not prove the new install. Summarize changes, skips, approved overwrites,
permission-mode caveats, and backup locations.

## Uninstall

Delete only installed agent files that still match the templates; show a diff
before deleting customized files. Remove only the marked orchestration block.

For `config.toml`, use the same `PILOTFISH_PRISTINE_CONFIG` selection as the
installer: prefer the earliest valid `config.toml.pilotfish-[0-9]*` legacy
backup, then the earliest valid `config.toml.pilotfish-codex-*` backup. Restore
only the pilotfish-codex-owned keys from that baseline. If no pristine backup
exists, use the recorded install state to remove only keys that did not exist
before installation and preserve everything unrelated. Never restore the whole
backup over a config that may have gained later user changes.
