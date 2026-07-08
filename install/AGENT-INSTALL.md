# pilotfish — Agent Install Runbook

> This document is written for an AI agent (Claude Code) performing the installation on a user's machine. If you are that agent: follow the steps in order, never skip the approval gate in Step 2, and prefer merging over overwriting at every point. A human can follow the same steps by hand.

## What you are installing

pilotfish is a global multi-model orchestration layer for Claude Code. It touches exactly three places, all under `~/.claude/`:

| Target | Change |
|---|---|
| `~/.claude/settings.json` | Set `model` to `"best"`, add `fallbackModel`, conditionally extend `availableModels` |
| `~/.claude/agents/` | Install six role agent files: `scout.md`, `Explore.md`, `mech-executor.md`, `executor.md`, `verifier.md`, `security-executor.md` |
| `~/.claude/CLAUDE.md` | Insert one `## Orchestration` section between `<!-- pilotfish:begin -->` and `<!-- pilotfish:end -->` markers |

Source of truth for the files: the [templates/](../templates/) directory of this repository. If you are running inside a local clone, use those files directly; otherwise fetch each from `https://raw.githubusercontent.com/Nanako0129/pilotfish/main/templates/...`.

## Step 1 — Preflight (read-only)

Gather the current state before proposing anything:

1. Read `~/.claude/settings.json` (note the current `model`, and whether `fallbackModel` / `availableModels` exist). If the file is missing, you will create a minimal one.
2. Read `~/.claude/CLAUDE.md` if it exists. Check for existing `<!-- pilotfish:begin -->` / `<!-- pilotfish:end -->` markers — their presence means this is an **upgrade**, not a fresh install.
3. List `~/.claude/agents/` and note which of the six pilotfish filenames already exist.
4. Check whether the environment variable `CLAUDE_CODE_SUBAGENT_MODEL` is set (`echo "$CLAUDE_CODE_SUBAGENT_MODEL"`).

> ⚠️ **Warning:** If `CLAUDE_CODE_SUBAGENT_MODEL` is set, it silently overrides every per-agent `model` frontmatter and defeats the entire tiering design. Flag it in your plan and recommend unsetting it. Do not unset it yourself without approval.

## Step 2 — Present the plan and get approval

Show the user a table of every change you intend to make: each file, the exact modification, and whether it is a create / merge / replace-between-markers / skip. Include a backup line (Step 3.1). **Do not write anything until the user approves.**

## Step 3 — Apply

### 3.1 Backup and directories

```bash
mkdir -p ~/.claude/backups ~/.claude/agents
# settings backup: FIRST install only — the pristine pre-pilotfish state must be preserved
ls ~/.claude/backups/settings.json.pilotfish-* >/dev/null 2>&1 || \
  cp ~/.claude/settings.json ~/.claude/backups/settings.json.pilotfish-$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
# CLAUDE.md backup: every run
cp ~/.claude/CLAUDE.md ~/.claude/backups/CLAUDE.md.pilotfish-$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
```

> **Note:** If `~/.claude/settings.json` did not exist before this install (fresh machine), there is no settings backup — record in your final summary that the pre-install state had **no `model` key**, so a future uninstall knows to *remove* the key rather than restore a value.

### 3.2 settings.json — merge, key by key

Never rewrite the whole file; edit only these keys and preserve everything else:

| Key | Rule |
|---|---|
| `model` | If absent → set `"best"`. If present and different → **ask** the user: keep their value, or switch to `"best"` (explain: `best` = Fable 5 when the account has access, otherwise latest Opus — this is the frontier-fallback mechanism). If already `"best"` → no change. |
| `fallbackModel` | If absent → add `["opus", "sonnet"]` (handles overload/unavailability, distinct from the `best` alias which handles access). If present → leave it and note it in the summary. |
| `availableModels` | **Only if the key already exists** (it is an allowlist): ensure it contains `"opus"`, `"sonnet"`, `"haiku"`, and the chosen main-model value — append whatever is missing. If the key is absent → do not add it (absent = unrestricted, which is fine). |

Validate afterwards: `jq empty ~/.claude/settings.json`.

> **Note:** On older Claude Code versions the `best` alias may be rejected at startup. If the user reports that, fall back to `"opus[1m]"` (or `"opus"`), and suggest updating Claude Code. Users who want *guaranteed* 1M context even when `best` resolves to Opus can choose `"opus[1m]"` themselves — the `[1m]` suffix is documented for `sonnet`/`opus`/`opusplan`/full model IDs, not for `best`.

### 3.3 Agent files

For each of the six files in `templates/agents/`, write it to `~/.claude/agents/<same-name>.md`:

| Existing state | Action |
|---|---|
| File doesn't exist | Write it |
| File exists, identical content | Skip (report as up-to-date) |
| File exists, different content | Show the diff, ask: overwrite (upgrade) or keep theirs |

> **Note:** A user-level agent named `Explore` intentionally shadows Claude Code's built-in Explore subagent to pin exploration to Haiku. This is expected, not a conflict.

### 3.4 CLAUDE.md policy section

The canonical section content is [templates/claude-md.orchestration.md](../templates/claude-md.orchestration.md) — it already includes the begin/end markers.

Before writing, count the markers: `grep -c "pilotfish:begin" ~/.claude/CLAUDE.md`. The count must be `0` (fresh) or `1` (upgrade).

| Marker count | Action |
|---|---|
| File missing | Create it with the section as its content |
| `0` | Append the section at the end (or after the first `#` heading if the file has one — either is fine) |
| `1` | Replace exactly that one block, from its `<!-- pilotfish:begin -->` through its matching `<!-- pilotfish:end -->` inclusive (idempotent upgrade) |
| `>1` | **Stop and ask the user** — do not blind-replace; a greedy first-begin-to-last-end replacement could delete user content sitting between two marker pairs |

Do not modify anything outside the markers.

## Step 4 — Verify and hand off

1. `jq empty ~/.claude/settings.json` exits 0.
2. `ls ~/.claude/agents/` shows all six files.
3. The markers appear exactly once in `~/.claude/CLAUDE.md`: `grep -c "pilotfish:begin" ~/.claude/CLAUDE.md` prints `1`.
4. Tell the user to **restart their Claude Code session**: the agents directory is scanned at session start, and the `model` setting applies on restart. After restart, `/agents` should list the six roles and `/model` should show the new default.
5. Summarize what changed, what was skipped, and where the backups are.

## Uninstall

On request, reverse the three targets:

1. Delete the six files from `~/.claude/agents/` (only ones whose content matches pilotfish templates — show a diff first if they were customized).
2. Remove the block from `<!-- pilotfish:begin -->` through `<!-- pilotfish:end -->` (inclusive) in `~/.claude/CLAUDE.md`; delete the file only if that leaves it empty and the user confirms.
3. In `~/.claude/settings.json`: restore `model` from the **oldest** `settings.json.pilotfish-*` backup in `~/.claude/backups/` — that file is the pre-install state (Step 3.1 only ever backs up settings once, on first install). If no such backup exists, or the backup has no `model` key, **remove** the `model` key instead of leaving the pilotfish value. Remove `fallbackModel` if the user doesn't want it. Leave `availableModels` additions in place unless asked — they are harmless.
