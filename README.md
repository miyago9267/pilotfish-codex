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

v1.3.1 bounds Plan and outcome verification loops: large work uses a program
envelope plus independently approvable slices, `REVISE` carries concrete
blockers, and two failed passes return control to the user. Terminal routing
proof remains gated on a stable observed rollout schema. Remora 0.1.10 remains
the reference only for the shared GPT-5.6 role bindings.

> **Codex-specific boundary:** The Claude-only `Explore` override is
> intentionally not installed. Pilotfish uses that exact name to shadow Claude
> Code's built-in agent; Codex needs no such compatibility shim, and `scout`
> already owns both broad and focused read-only discovery.

## How it works

Three layers, all under `~/.codex/`:

| Layer | File(s) | Job |
|---|---|---|
| **Machine adapter** | `config.toml` | Sets the main-session default and exposes typed MultiAgentV2 role dispatch with bounded concurrency |
| **Role agents** | `agents/*.toml` | Seven TOML files, each owning one role contract, model, and reasoning level |
| **Delegation policy** | `AGENTS.md` | Tells the orchestrator when to delegate and to whom |

The main-session effort remains user-controlled.

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

### Plan readiness

Large Plans use one program envelope followed by independently approvable
execution slices. Review the envelope, then only the next executable slice.
`READY` is bare; `REVISE` identifies the blocker, evidence, minimum revision,
and acceptance check. After two automatic revisions for one unit, stop and ask
the user. Security-sensitive units complete read-only security review first,
and `READY` never authorizes writes.

See [Plan readiness](./docs/design.md#plan-readiness) for the design boundary.

## Install

> Requires Codex CLI 0.144.1 or newer and Python 3.11+.

Both routes install the same files and keep timestamped backups of anything
they replace. After either route, start a **new** Codex session — a running
session keeps the old spawn schema.

### Route 1 — one-line script

```bash
curl -fsSL https://raw.githubusercontent.com/miyago9267/pilotfish-codex/main/install/install.sh | bash
```

Non-interactive and idempotent: it merges only the managed keys into
`~/.codex/config.toml` (unrelated keys, comments, and formatting survive byte
for byte), installs the seven role TOMLs, and replaces the marked
orchestration block. Preview with `... | bash -s -- --dry-run`. Anything that
needs a human decision (an explicit `multi_agent = false`, a forced
`multi_agent_v2.enabled = true`, unmatched markers, or a differing existing
role TOML) aborts without writing — use Route 2 for those. Pin a version by
replacing `main` in the URL and setting the same ref on the `bash` process:

```bash
curl -fsSL https://raw.githubusercontent.com/miyago9267/pilotfish-codex/<tag-or-sha>/install/install.sh | PILOTFISH_REF=<tag-or-sha> bash
```

### Route 2 — agent-guided install prompt

Paste this into a Codex CLI session:

```text
Read https://raw.githubusercontent.com/miyago9267/pilotfish-codex/main/install/AGENT-INSTALL.md and follow it to install pilotfish-codex into my global Codex configuration.
```

The agent will read the runbook, show you a plan of every change, and wait for
your approval before writing anything. This route also handles v1.0.x
migrations and any state the script refuses to decide. To pin to a specific
version (recommended for teams), replace `main` with a tag or commit SHA in
the URL.

## What gets installed

| Target | Change |
|---|---|
| `~/.codex/config.toml` | Optionally set `model` to `gpt-5.6-sol`, enable legacy multi-agent fallback, install the MultiAgentV2 compatibility adapter, and bound concurrency |
| `~/.codex/agents/` | Seven TOML agent files |
| Active `~/.codex/AGENTS.override.md` or `~/.codex/AGENTS.md` | One `### Orchestration` section between `<!-- pilotfish-codex:begin -->` and `<!-- pilotfish-codex:end -->` markers |

Fresh installs target only paths under `~/.codex/`. When one of those paths is
an existing symlink to a regular file, the scripted route preserves the
symlink and atomically updates its resolved target; broken or non-file targets
abort before writes. The timestamped backup remains beside the configured
path. During a v1.0.x upgrade, the agent-guided installer may also
remove an obsolete marked Pilotfish block from the current project-root
`AGENTS.md`, but only after showing that exact migration, receiving approval,
and backing up the file. Content outside the markers is preserved.

## MultiAgentV2 compatibility

Affected Codex releases hide `agent_type` from the default MultiAgentV2 spawn
schema. An untyped child inherits the parent model, so a Sol orchestrator can
silently create another Sol worker instead of the Luna or Terra role selected
by Pilotfish.

The temporary machine adapter restores typed role routing outside the reserved
collaboration namespace:

```toml
[features.multi_agent_v2]
hide_spawn_agent_metadata = false
tool_namespace = "agents"
max_concurrent_threads_per_session = 4
```

Do not set `features.multi_agent_v2.enabled`: Codex may select V2 for the live
turn even when the local feature list says otherwise, and locally enabling it
conflicts with the retained legacy `agents.max_threads` fallback on the
verified `0.144.4` release. The packaged concurrency is four active threads
including root. Pilotfish accepts values from 1 through 8, warns outside the
recommended value, and treats 1 as child delegation disabled.

The policy calls `agents.spawn_agent` with `agent_type`, a lowercase task name,
and explicit bounded context, without a child-level `service_tier` override. A
Fast tier deliberately selected for the parent may still be inherited by the
child. If typed role routing is unavailable, the policy must fail closed
instead of retrying an untyped inherited-model child. Start a fresh Codex
session after changing the config or installed roles.

Static validation proves the installed config and role files are internally
consistent:

```bash
python3 install/validate_agents.py \
  --config ~/.codex/config.toml ~/.codex/agents
```

The optional E2E probe spends real quota. It starts a Terra parent, routes one
`scout`, and requires the exact child rollout to report the installed Luna
binding:

```bash
python3 install/verify_dispatch.py --live --yes
```

`ADAPTER_OK` proves the temporary transport. `NATIVE_OK` is reserved for an
adapter-free native probe. `SKIPPED` names an unavailable prerequisite;
`FAILED` means routing evidence was missing or mismatched and prints a
cost-safety warning to stop named-role delegation. An explicit `service_tier`
in the recorded spawn arguments is a failure. This is evidence validation, not
a runtime block: Pilotfish does not install a hook because current
`PreToolUse` hooks cannot cancel the tool call. A future stable Codex release
may retire the schema workaround only after this command with `--mode native`
returns `NATIVE_OK`; role TOMLs and semantic policy remain unchanged. The
current verifier returns
`SKIPPED: native_schema_introspection_unavailable` before quota or spawning,
because Codex `0.144.4` has no safe adapter-free schema introspection surface.

The verifier's evidence-expansion options are manual and quota-gated:

```bash
# One explicit role; scout remains the default.
python3 install/verify_dispatch.py --live --yes \
  --role scout --receipt ~/.codex/dispatch-receipts/scout.json

# Sequential explicit-binding matrix; up to seven parent/child probes.
python3 install/verify_dispatch.py --live --yes \
  --all-roles --matrix-yes --receipt-dir ~/.codex/dispatch-receipts

# Offline behavioral task-class selection evaluation.
python3 install/evaluate_dispatch.py --decisions decisions.json

# Manual live evaluation; case cap and no-tool output are enforced.
python3 install/evaluate_dispatch.py --live --yes --task-eval-yes \
  --case-id independent_read_only_discovery
```

Receipts are versioned, redacted JSON observations. They may contain hashes,
thread IDs, relative rollout references, model/effort fields, and verdicts; they
do not contain prompts, responses, rollout contents, developer instructions,
raw process output, or absolute home paths. A receipt is an evidence artifact,
not a runtime guard. Native routing, hard pre-execution blocking, and hidden
effective-role metadata remain upstream-dependent.

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

Swap model names in the TOML files to match your available models. Production
routing remains config-driven; the verifier only supplies explicit proof.

## Tuning

**Change a role's model:** Edit the `model` field in
`~/.codex/agents/<role>.toml`, then start a fresh Codex session so the agent
definitions are scanned again.

**Disable a role:** Delete or rename the `.toml` file. The orchestrator falls
back to doing the work itself.

**Adjust reasoning:** Each TOML has `model_reasoning_effort`. Available levels
depend on the model (luna supports up to `max`, sol supports up to `ultra`).

## Development

Run the same checks enforced by CI:

```bash
bun install --frozen-lockfile
bun run lint:md
python3 -m unittest discover -s tests -v
python3 -m py_compile install/install.py install/validate_agents.py install/verify_dispatch.py
bash -n install/install.sh
python3 install/validate_agents.py
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
