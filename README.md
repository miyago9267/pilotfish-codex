# pilotfish-codex

> Codex-native multi-model orchestration, inspired by
> [pilotfish](https://github.com/Nanako0129/pilotfish).

**pilotfish-codex** is an independent Codex CLI adaptation and maintenance line
for Pilotfish orchestration, maintained by Miyago. It preserves Pilotfish's
separation between machine configuration, role bindings, and model-free policy
while translating the lifecycle and capability boundaries to native Codex
agents. Quality comes from explicit approval gates and fresh-context
verification rather than using the strongest model for every step.

The project now evolves on its own release line. Upstream improvements are
reviewed and selectively adapted when they fit Codex CLI; Codex-specific needs
take priority over source parity. Everything installs globally: one setup for
every project.

Primary credit for the original architecture, research, and design rationale
goes to [@Nanako0129](https://github.com/Nanako0129). This project keeps that
attribution and maintains the Codex-specific adaptation: TOML role agents, an
`AGENTS.md` orchestration policy, and an installer for `~/.codex/`. See the
[Codex design mapping](./docs/design.md) for the adaptation boundary.

v1.1.0 ports Pilotfish v1.2's phase-aware orchestration. Remora 0.1.10 is the
reference only for the GPT-5.6 model and reasoning-effort bindings shared by
the seven Codex roles.

> **Codex-specific boundary:** The Claude-only `Explore` override is
> intentionally not installed. Pilotfish uses that exact name to shadow Claude
> Code's built-in agent; Codex needs no such compatibility shim, and `scout`
> already owns both broad and focused read-only discovery.

## How it works

Three layers, all under `~/.codex/`:

| Layer | File(s) | Job |
|---|---|---|
| **Model default** | `config.toml` | Sets the main-session model to `gpt-5.6-sol`; main-session effort remains user-controlled |
| **Role agents** | `agents/*.toml` | Seven TOML files, each owning one role contract, model, and reasoning level |
| **Delegation policy** | `AGENTS.md` | Tells the orchestrator when to delegate and to whom |

### The seven Codex roles

| Role | Model | Reasoning | When |
|---|---|---|---|
| `scout` | gpt-5.6-luna | low | Broad or focused read-only discovery |
| `plan-verifier` | gpt-5.6-sol | medium | Read-only Plan readiness challenge before approval |
| `security-reviewer` | gpt-5.6-sol | high | Read-only security evidence before approval |
| `mech-executor` | gpt-5.6-luna | medium | Mechanical edits, tests, and docs from a complete spec |
| `executor` | gpt-5.6-luna | max | Features, bug fixes, and refactors needing judgment |
| `verifier` | gpt-5.6-sol | high | Adversarial completed-work verification |
| `security-executor` | gpt-5.6-sol | max | Approved security-sensitive implementation |

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

> Requires Codex CLI 0.144.1 or newer.

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
| `~/.codex/config.toml` | Optionally set `model` to `gpt-5.6-sol`, enable multi-agent support, cap concurrency at three leaf threads, and cap nesting at one leaf generation |
| `~/.codex/agents/` | Seven TOML agent files |
| Active `~/.codex/AGENTS.override.md` or `~/.codex/AGENTS.md` | One `### Orchestration` section between `<!-- pilotfish-codex:begin -->` and `<!-- pilotfish-codex:end -->` markers |

Fresh installs touch only `~/.codex/`. During a v1.0.x upgrade, the installer
may also remove an obsolete marked Pilotfish block from the current project-root
`AGENTS.md`, but only after showing that exact migration, receiving approval,
and backing up the file. Content outside the markers is preserved.

## Updating

Re-run the install prompt. The installer detects the version stamp in the
active global instruction file, shows the changelog delta, and applies changes
idempotently — unchanged files are skipped and the policy block is replaced in
place. Retired discovery files are handled separately: a released v1.0.x
lowercase `explore.toml` is removed only when unmodified or explicitly
approved, while an uppercase `Explore.toml` from a pre-release v1.1 draft always
requires explicit deletion approval. The installer checks this drift even when
the installed version stamp already equals the current version. v1.0.x upgrades
also reuse the original `config.toml.pilotfish-*` pristine backup, surface the
legacy `model_reasoning_effort = "medium"` pin for an explicit migration choice,
and move stale marked policy blocks from inactive global or project-root files
into the active global instruction file without touching surrounding content.

## Versioning

pilotfish-codex uses its own semantic versioning. Upstream pilotfish versions
are recorded as source attribution or compatibility notes, but they do not
determine the pilotfish-codex version number.

## Model Mapping

| Role | Upstream pilotfish tier | pilotfish-codex default |
|---|---|---|
| `scout` | Haiku | gpt-5.6-luna, low |
| `plan-verifier` | Opus | gpt-5.6-sol, medium |
| `security-reviewer` | Opus | gpt-5.6-sol, high |
| `mech-executor` | Sonnet | gpt-5.6-luna, medium |
| `executor` | Opus | gpt-5.6-luna, max |
| `verifier` | Opus | gpt-5.6-sol, high |
| `security-executor` | Opus (high effort) | gpt-5.6-sol, max |

Swap model names in the TOML files to match your available models —
pilotfish-codex is just config, not runtime code.

## Tuning

**Change a role's model:** Edit the `model` field in
`~/.codex/agents/<role>.toml`, then start a fresh Codex session so the agent
definitions are scanned again.

**Disable a role:** Delete or rename the `.toml` file. The orchestrator falls
back to doing the work itself.

**Adjust reasoning:** Each TOML has `model_reasoning_effort`. Available levels
depend on the model (luna supports up to `max`, sol supports up to `ultra`).

## Development

Install the pinned tooling and run the same Markdown check used by CI:

```bash
bun install --frozen-lockfile
bun run lint:md
```

Policy regression tests use the Python standard library:

```bash
python3 -m unittest discover -s tests -v
```

> **Read-only boundary:** `scout`, `plan-verifier`, and `security-reviewer`
> default to `sandbox_mode = "read-only"`. A live
> parent-session permission override can supersede a custom agent's default, so
> choose the parent permission mode before delegating pre-approval review.

## Uninstall

1. Delete the seven `.toml` files from `~/.codex/agents/`
2. Remove the `<!-- pilotfish-codex:begin -->` through
   `<!-- pilotfish-codex:end -->` block from the active global instruction file
3. Restore only the installed `config.toml` keys from the oldest pre-install
   backup

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
