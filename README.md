# pilotfish-codex

> Codex-native multi-model orchestration, inspired by
> [pilotfish](https://github.com/Nanako0129/pilotfish).

**pilotfish-codex** is an independent Codex CLI adaptation and maintenance line
for pilotfish-style orchestration. The main session owns planning, architecture,
and final review while role-based subagents handle bounded volume work. Quality
comes from clear task contracts and fresh-context verification rather than using
the strongest model for every step.

The project now evolves on its own release line. Upstream improvements are
reviewed and selectively adapted when they fit Codex CLI; Codex-specific needs
take priority over source parity. Everything installs globally: one setup for
every project.

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

### Dispatch principles

- Keep planning, architecture, ambiguity resolution, and final judgment in the
  main session.
- Delegate only when the saved execution or context cost exceeds the briefing
  and review cost.
- Use one read-only scout for bounded reconnaissance; use bounded parallelism
  only for independent, low-overlap workstreams.
- Give each worker a complete contract: goal, constraints, done criteria,
  relevant paths, output shape, and verification expectation.
- Treat delegated results as evidence to integrate, not conclusions to accept
  blindly. Non-trivial changes receive a fresh-context verifier pass.

## Install

Paste this into a Codex CLI session:

```text
Read https://raw.githubusercontent.com/miyago9267/pilotfish-codex/main/install/AGENT-INSTALL.md and follow it to install pilotfish-codex into my global Codex configuration.
```

The agent will read the runbook, show you a plan of every change, and wait for
your approval before writing anything. The whole process takes about a minute.

To pin to a specific version (recommended for teams):

```text
Read https://raw.githubusercontent.com/miyago9267/pilotfish-codex/<commit-sha>/install/AGENT-INSTALL.md and follow it to install pilotfish-codex into my global Codex configuration.
```

## What gets installed

| Target | Change |
|---|---|
| `~/.codex/config.toml` | Optionally set `model` to `gpt-5.6-terra` (asks first if different) |
| `~/.codex/agents/` | Six TOML agent files |
| `AGENTS.md` | One `### Orchestration` section between `<!-- pilotfish-codex:begin -->` and `<!-- pilotfish-codex:end -->` markers |

Nothing outside `~/.codex/` and your `AGENTS.md` is touched. Backups are created
before any modification.

## Updating

Re-run the install prompt. The installer detects the version stamp in your
`AGENTS.md` markers, shows the changelog delta, and applies changes idempotently
— unchanged files are skipped, the policy block is replaced in place.

## Versioning

pilotfish-codex uses its own semantic versioning. Upstream pilotfish versions
are recorded as source attribution or compatibility notes, but they do not
determine the pilotfish-codex version number.

## Model Mapping

| Role | Upstream pilotfish tier | pilotfish-codex default |
|---|---|---|
| scout / explore | Haiku | gpt-5.6-luna |
| mech-executor | Sonnet | gpt-5.6-terra |
| executor / verifier | Opus | gpt-5.6-terra |
| security-executor | Opus (high effort) | gpt-5.6-sol (high reasoning) |

Swap model names in the TOML files to match your available models —
pilotfish-codex is just config, not runtime code.

## Tuning

**Change a role's model:** Edit the `model` field in
`~/.codex/agents/<role>.toml`, then start a new Codex session so the agent
definitions are scanned again.

**Disable a role:** Delete or rename the `.toml` file. The orchestrator falls
back to doing the work itself.

**Adjust reasoning:** Each TOML has `model_reasoning_effort`. Available levels
depend on the model (luna supports up to `max`, sol supports up to `ultra`).

## Uninstall

1. Delete the six `.toml` files from `~/.codex/agents/`
2. Remove the `<!-- pilotfish-codex:begin -->` through
   `<!-- pilotfish-codex:end -->` block from `AGENTS.md`
3. Restore `config.toml` model setting from backup if desired

## Attribution and contributors

pilotfish-codex began as a Codex CLI adaptation of
[Nanako0129/pilotfish](https://github.com/Nanako0129/pilotfish). The original
architecture, research, and design rationale are credited to
[@Nanako0129](https://github.com/Nanako0129); upstream-derived material remains
identified in the documentation and changelog.

- **Miyago**: Codex adaptation, project direction, and maintenance.
- **OpenAI Codex and ChatGPT**: implementation, review, documentation, and
  orchestration-design assistance under Miyago's direction.
- **pilotfish contributors**: upstream fixes and ideas that are selectively
  adapted with source attribution.

## License

MIT. The original pilotfish copyright and permission notice are retained, and
the Codex-specific adaptation copyright is recorded in [LICENSE](./LICENSE).
