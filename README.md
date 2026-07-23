# pilotfish-codex

Codex-native role orchestration inspired by
[Pilotfish](https://github.com/Nanako0129/pilotfish). This is an independent
Codex CLI adaptation maintained by Miyago.

## Native target

Pilotfish-Codex targets only Codex `rust-v0.145.0`. The native Multi-Agent V2
configuration is:

```toml
[features.multi_agent_v2]
enabled = true
max_concurrent_threads_per_session = 4
```

Four is a total thread limit: one root and up to three children. The active
native configuration does not emit `features.multi_agent`, a forced spawn
namespace, forced metadata visibility, or an `[agents]` concurrency fallback.
Lower and higher Codex versions fail closed; the installer never selects an
adapter route.

## Roles

The installed manifest is exactly these seven TOML roles:

- `executor`
- `mech-executor`
- `plan-verifier`
- `scout`
- `security-executor`
- `security-reviewer`
- `verifier`

Role TOMLs own their model and reasoning effort. The global policy owns typed
role delegation, approval boundaries, and fresh-context verification. The
Claude-specific `Explore` compatibility override is not installed.

## Install

The scripted route checks the exact CLI version, plans all writes, creates
backups, validates the staged native configuration and manifest, atomically
replaces targets, and commits a mode-`0600` sibling install-state sidecar.
Unknown-provenance legacy adapter settings are preserved and block native
verification rather than being deleted by name.

```bash
python3 install/install.py --codex-home "$ACTIVE_CODEX_HOME"
python3 install/validate_agents.py \
  --config "$ACTIVE_CODEX_HOME/config.toml" "$ACTIVE_CODEX_HOME/agents"
```

See [the install runbook](./install/AGENT-INSTALL.md) before modifying a real
Codex home. The runbook requires a separate home-write approval for backups,
writes, customized same-name role replacement, and retired-role cleanup.

## Native verification

Ordinary tests are offline. One explicit, quota-gated smoke is required to
complete the native migration. First stage an absolute, distinct, not-yet-
existing home:

```bash
python3 install/stage_smoke_home.py \
  --active-codex-home "$ACTIVE_CODEX_HOME" \
  --staged-codex-home "$STAGED_CODEX_HOME"
```

Then, after separate quota approval, launch from a clean `SMOKE_DIR` outside
the repository:

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

The verifier rejects retired `--mode` and `--all-roles` options before
authentication, quota spending, child creation, or receipt writing. It requires
one native typed `spawn_agent` with a non-empty message, known role, safe task
name, bounded fork, correlation to child activity, and observed child
`turn_context.model` plus `turn_context.effort`. Namespace is not native
evidence. `NATIVE_OK` completes the runtime gate; `SKIPPED` is incomplete and
`FAILED` blocks completion.

## Development

```bash
bun install --frozen-lockfile
bun run lint:md
python3 -m unittest discover -s tests -v
python3 -m py_compile install/install.py install/validate_agents.py \
  install/stage_smoke_home.py install/verify_dispatch.py
```

Historical adapter fixtures and specs are retained only as labeled evidence;
they are excluded from the active native acceptance gate.

## License

MIT. The original Pilotfish attribution and permission notice are retained.
