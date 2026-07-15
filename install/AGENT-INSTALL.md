# pilotfish-codex — Agent Install Runbook

> This document is written for an AI agent (Codex CLI) performing the
> installation on a user's machine. If you are that agent: follow the steps in
> order, never skip the approval gate in Step 2, and prefer merging over
> overwriting at every point. A human can follow the same steps by hand.

## What you are installing

pilotfish-codex is a global multi-model orchestration layer for Codex CLI. It
touches exactly three places:

| Target | Change |
|---|---|
| `~/.codex/config.toml` | Optionally set `model` to `gpt-5.6-terra`, conditionally adjust `model_reasoning_effort` |
| `~/.codex/agents/` | Install six role agent files: `scout.toml`, `explore.toml`, `mech-executor.toml`, `executor.toml`, `verifier.toml`, `security-executor.toml` |
| `AGENTS.md` | Insert one `### Orchestration` section between `<!-- pilotfish-codex:begin -->` and `<!-- pilotfish-codex:end -->` markers |

Source of truth for the files: the [templates/](../templates/) directory of this
repository. If you are running inside a local clone, use those files directly;
otherwise fetch each from
`https://raw.githubusercontent.com/miyago9267/pilotfish-codex/main/templates/...`.

> **Commit pinning:** If the user's install prompt referenced this runbook at a
> specific commit SHA instead of `main`, fetch **every template from that same
> SHA** — never fall back to `main`.

## Updating an existing install

When the user asks to **update** (rather than fresh-install), run this before
Step 1:

1. Detect the installed version: search the user's `AGENTS.md` for
   `pilotfish-codex v` inside the marker block. A version comment like
   `<!-- pilotfish-codex v1.0.0 -->` gives the installed version; **markers
   present but no version comment means a pre-v1.0.0 install**.
2. Fetch the latest version and changelog from the same ref you were invoked
   from (`VERSION` and `CHANGELOG.md` at the repo root).
3. If already up to date, say so and stop. Otherwise show the user the changelog
   entries between their version and the latest, then proceed with Steps 1–4
   below.
4. If the user customized any agent file, the Step 3.3 diff will surface it —
   never overwrite a customization without showing the diff and asking.

## Step 1 — Preflight (read-only)

Gather the current state before proposing anything:

1. Read `~/.codex/config.toml` (note the current `model` and
   `model_reasoning_effort`). If the file is missing, you will create a minimal
   one.
2. Find the user's `AGENTS.md` — check `~/.codex/AGENTS.md` first (may be a
   symlink), then the project root. Check for existing
   `<!-- pilotfish-codex:begin -->` / `<!-- pilotfish-codex:end -->` markers —
   their presence means this is an **upgrade**, not a fresh install.
3. List `~/.codex/agents/` and note which of the six pilotfish-codex filenames
   already exist. **Also read the `name` field of every existing agent TOML
   file** — Codex resolves collisions by the `name` field, not the filename. If
   any existing agent already declares `name = "scout"`, `"executor"`,
   `"mech-executor"`, `"verifier"`, `"security-executor"`, or `"explore"`, flag
   it as a name collision in the plan and ask the user whether to rename theirs,
   skip that role, or overwrite.

## Step 2 — Present the plan and get approval

Show the user a table of every change you intend to make: each file, the exact
modification, and whether it is a create / merge / replace-between-markers /
skip. Include a backup line (Step 3.1). **Do not write anything until the user
approves.**

## Step 3 — Apply

### 3.1 Backup and directories

```bash
mkdir -p ~/.codex/backups ~/.codex/agents
# config.toml backup: FIRST install only
ls ~/.codex/backups/config.toml.pilotfish-* >/dev/null 2>&1 || \
  cp ~/.codex/config.toml ~/.codex/backups/config.toml.pilotfish-$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
# AGENTS.md backup: every run (resolve symlink first)
AGENTS_REAL=$(readlink -f ~/.codex/AGENTS.md 2>/dev/null || echo ~/.codex/AGENTS.md)
cp "$AGENTS_REAL" ~/.codex/backups/AGENTS.md.pilotfish-$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
```

### 3.2 config.toml — merge, key by key

Never rewrite the whole file; edit only these keys and preserve everything else:

| Key | Rule |
|---|---|
| `model` | If absent → set `"gpt-5.6-terra"`. If present and different → **ask** the user: keep their value, or switch. If already `"gpt-5.6-terra"` → no change. |
| `model_reasoning_effort` | If absent → set `"medium"`. If present → leave it. |

### 3.3 Agent files

For each of the six files in `templates/agents/`, write it to `~/.codex/agents/<same-name>.toml`:

| Existing state | Action |
|---|---|
| File doesn't exist, no `name` collision (Step 1.3) | Write it |
| File exists, identical content | Skip (report as up-to-date) |
| File exists, different content | Show the diff, ask: overwrite (upgrade) or keep theirs |
| A *different* file declares the same `name` | Stop and ask (see Step 1.3) |

### 3.4 AGENTS.md policy section

The canonical section content is
[templates/agents-md.orchestration.md][policy-template] — it already includes
the begin/end markers.

[policy-template]: ../templates/agents-md.orchestration.md

Before writing, count the markers:
`grep -c "pilotfish-codex:begin" <AGENTS.md path>`. The count must be `0` (fresh)
or `1` (upgrade).

| Marker count | Action |
|---|---|
| File missing | Create it with the section as its content |
| `0` | Append the section at the end of the `## Codex Subagent Strategy` section if it exists, otherwise at the end of the file |
| `1` | Replace exactly that one block, from its `<!-- pilotfish-codex:begin -->` through its matching `<!-- pilotfish-codex:end -->` inclusive |
| `>1` | **Stop and ask the user** |

Do not modify anything outside the markers.

## Step 4 — Verify and hand off

1. `ls ~/.codex/agents/` shows all six `.toml` files.
2. The markers appear exactly once in `AGENTS.md`:
   `grep -c "pilotfish-codex:begin" <path>` prints `1`.
3. Tell the user to **restart their Codex session**: agent definitions are
   scanned at session start.
4. Summarize what changed, what was skipped, and where the backups are.

## Uninstall

On request, reverse the three targets:

1. Delete the six files from `~/.codex/agents/` (only ones whose content matches
   pilotfish-codex templates — show a diff first if customized).
2. Remove the block from `<!-- pilotfish-codex:begin -->` through
   `<!-- pilotfish-codex:end -->` (inclusive) in `AGENTS.md`.
3. In `config.toml`: restore `model` from the oldest
   `config.toml.pilotfish-*` backup if desired.
