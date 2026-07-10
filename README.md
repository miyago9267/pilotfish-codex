# pilotfish-codex

> Codex CLI multi-model orchestration, adapted from [pilotfish](https://github.com/Nanako0129/pilotfish).

**pilotfish-codex** is Miyago's Codex CLI port and ongoing maintenance line for pilotfish-style orchestration: your main session plans and reviews on a strong model, while cheaper models handle the volume work through role-based subagents. Quality is protected by fresh-context verification, not by using the strongest model everywhere. Everything installs globally — one setup, every project.

Primary credit for the original architecture, research, and design rationale goes to [@Nanako0129](https://github.com/Nanako0129). This project keeps that attribution and maintains the Codex-specific adaptation: TOML role agents, `AGENTS.md` orchestration policy, and an installer for `~/.codex/`.

## How it works

Three layers, all under `~/.codex/`:

| Layer | File(s) | Job |
|---|---|---|
| **Model default** | `config.toml` | Sets the main-session model (e.g. `gpt-5.6-terra`) |
| **Role agents** | `agents/*.toml` | Six TOML files, each pinning a role to a model + reasoning level |
| **Delegation policy** | `AGENTS.md` | Tells the orchestrator when to delegate and to whom |

### The six roles

| Role | Model | Reasoning | When |
|---|---|---|---|
| `scout` | gpt-5.6-luna | low | Search, lookup, "where is X" |
| `explore` | gpt-5.6-luna | low | Broad codebase sweeps |
| `mech-executor` | gpt-5.6-terra | low | Mechanical edits, tests, docs |
| `executor` | gpt-5.6-terra | medium | Features, bug fixes, refactors needing judgment |
| `verifier` | gpt-5.6-terra | medium | Adversarial verification — read-and-run only |
| `security-executor` | gpt-5.6-sol | high | Anything security-sensitive |

## Install

Paste this into a Codex CLI session:

```
Read https://raw.githubusercontent.com/miyago9267/pilotfish-codex/main/install/AGENT-INSTALL.md and follow it to install pilotfish-codex into my global Codex configuration.
```

The agent will read the runbook, show you a plan of every change, and wait for your approval before writing anything. The whole process takes about a minute.

To pin to a specific version (recommended for teams):

```
Read https://raw.githubusercontent.com/miyago9267/pilotfish-codex/<commit-sha>/install/AGENT-INSTALL.md and follow it to install pilotfish-codex into my global Codex configuration.
```

## What gets installed

| Target | Change |
|---|---|
| `~/.codex/config.toml` | Optionally set `model` to `gpt-5.6-terra` (asks first if different) |
| `~/.codex/agents/` | Six TOML agent files |
| `AGENTS.md` | One `### Orchestration` section between `<!-- pilotfish-codex:begin -->` and `<!-- pilotfish-codex:end -->` markers |

Nothing outside `~/.codex/` and your `AGENTS.md` is touched. Backups are created before any modification.

## Updating

Re-run the install prompt. The installer detects the version stamp in your `AGENTS.md` markers, shows the changelog delta, and applies changes idempotently — unchanged files are skipped, the policy block is replaced in place.

## Versioning

pilotfish-codex uses its own semantic versioning. Upstream pilotfish versions are recorded as source attribution or compatibility notes, but they do not determine the pilotfish-codex version number.

## Model Mapping

| Role | Upstream pilotfish tier | pilotfish-codex default |
|---|---|---|
| scout / explore | Haiku | gpt-5.6-luna |
| mech-executor | Sonnet | gpt-5.6-terra |
| executor / verifier | Opus | gpt-5.6-terra |
| security-executor | Opus (high effort) | gpt-5.6-sol (high reasoning) |

Swap model names in the TOML files to match your available models — pilotfish-codex is just config, not runtime code.

## Tuning

**Change a role's model:** Edit the `model` field in `~/.codex/agents/<role>.toml`. No restart needed — Codex reads agent definitions per-session.

**Disable a role:** Delete or rename the `.toml` file. The orchestrator falls back to doing the work itself.

**Adjust reasoning:** Each TOML has `model_reasoning_effort`. Available levels depend on the model (luna supports up to `max`, sol supports up to `ultra`).

## Uninstall

1. Delete the six `.toml` files from `~/.codex/agents/`
2. Remove the `<!-- pilotfish-codex:begin -->` through `<!-- pilotfish-codex:end -->` block from `AGENTS.md`
3. Restore `config.toml` model setting from backup if desired

## License

MIT. Original pilotfish copyright is retained; Codex-specific adaptation copyright is added in [LICENSE](./LICENSE).
