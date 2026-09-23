# Pilotfish Jev Router

> WIP test feature. It is optional and not promoted as stable. Active mode can
> send eligible, redacted task prose to TypeSafe and affect role routing.

Optional companion plugin that uses Jev System One Noul questions to classify
work scope. Jev only recommends a route; Pilotfish's canonical hook owns role
dispatch and the continuation marker.

## Install and enable

The repo marketplace is `pilotfish-codex`. Add the plugin through the Codex
CLI, then verify it with `codex plugin list`:

```sh
codex plugin add pilotfish-jev-router@pilotfish-codex
codex plugin list
```

The plugin is separate from the already-installed Pilotfish core plugin. After
the CLI reports it as `installed, enabled`, opt in with a Codex-home config file
(the mode file contains no secrets):

```sh
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
umask 077
mkdir -p "$CODEX_HOME/pilotfish-jev"
chmod 700 "$CODEX_HOME/pilotfish-jev"
printf '{"mode":"shadow"}\n' > "$CODEX_HOME/pilotfish-jev/config.json"
chmod 600 "$CODEX_HOME/pilotfish-jev/config.json"
```

Restart the current Codex session. The canonical Pilotfish hook resolves the
enabled companion from `$CODEX_HOME/plugins/cache/pilotfish-codex/pilotfish-jev-router/<version>`;
it does not add a competing prompt hook. If cache identity, enabled state, or
config is missing/ambiguous, routing stays local and Jev is not called.

Store the key in `~/.config/typesafe/api_key` with restrictive file
permissions, or provide `TYPESAFE_API_KEY` through a protected launch
environment. Never put it in the prompt, project config, hook arguments, or
logs. `off` is the default and makes no API call. Shadow mode records only
compact route scores in `$CODEX_HOME/pilotfish-jev/shadow-decisions.jsonl`; it
does not change routing. Keep active mode limited to an explicitly controlled
WIP test until the stable-promotion checks below pass. The maintainer's current
installation is an active WIP pilot; route quality is not established.
To stop sending prompts, delete `pilotfish-jev/config.json` (and unset any
`PILOTFISH_JEV_MODE` environment override), then restart Codex. Uninstall the
optional package with
`codex plugin remove pilotfish-jev-router@pilotfish-codex` if it is no longer
needed.

The hook sends bounded task prose after common credential, email, and URL-query
redaction. Do not enable it for prompts containing sensitive material that must
not leave the machine. Jev errors, missing credentials, ambiguous scores, and
timeouts fall back to Pilotfish's local classifier. Calls use a one-second
timeout. Security-review requirements and deterministic deep-judgment routes
cannot be downgraded.

Routes: parent-local, `mech-executor`, `scout`, `sol-executor`, and `executor`.
Active classification requires a score of at least 0.80 and a lead of at least
0.20 over the next label. The provider never authorizes or executes work.

## Rollout

Use [the rollout plan](../../../docs/specs/jev-role-routing/ROLLOUT.md) before
switching from shadow to active. Configuration takes effect on the next hook
invocation after the file is written; restart Codex to keep the rollout boundary
clear. Treat active mode as a test, not a stable routing guarantee.

Run offline tests with:

```sh
python3 -m unittest tests.test_jev_router tests.test_autoroute_hook
```
