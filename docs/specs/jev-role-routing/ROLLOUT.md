# Jev Router rollout plan

## Current state

This is a WIP test feature, not a stable or generally promoted routing path.
The maintainer's current Codex home has the optional plugin installed and
enabled with `active` mode; eligible prompts are sent to TypeSafe for
classification. The active-mode quality gate below has not been completed, so
this local pilot is not evidence of stable route quality.

- `pilotfish-jev-router` is listed as an optional WIP test plugin in the repo
  marketplace; it remains disabled unless separately installed and opted in.
- The core Pilotfish plugin remains installed and owns the canonical
  `UserPromptSubmit`/`Stop` route-marker flow.
- The Jev provider is off unless `$CODEX_HOME/pilotfish-jev/config.json` opts in
  with `{"mode":"shadow"}` or `{"mode":"active"}`. Installing the companion
  plugin alone does not activate API calls.
- Codex local plugin installs use a cache path under
  `$CODEX_HOME/plugins/cache/<marketplace>/<plugin>/<version>`; for this local
  marketplace the installed version comes from the plugin manifest (verified
  locally as `0.1.0`), not a hard-coded `local` directory. The hook checks the
  enabled setting and cached manifest before importing the provider. See
  [OpenAI's plugin packaging and marketplace documentation](https://developers.openai.com/plugins/build/plugins).

## Stage 0: offline readiness

Run from the repository root:

```sh
python3 -m unittest discover -s tests
python3 install/validate_prompt_lock.py
bun run lint:md
```

Acceptance: all tests pass; no live Jev request; the normal, unconfigured
Pilotfish route remains unchanged. Current evidence: 466 tests passed (one
platform-specific skip), including the installed-cache-to-canonical-marker
route test with HTTP intercepted locally; Prompt lock and Markdown lint passed.

## Stage 1: install and shadow pilot

Install only the optional package:

```sh
codex plugin add pilotfish-jev-router@pilotfish-codex
codex plugin list
```

Confirm `pilotfish-jev-router@pilotfish-codex` is `installed, enabled`. The real
Codex CLI installed it into
`plugins/cache/pilotfish-codex/pilotfish-jev-router/0.1.0/` under an isolated
temporary `CODEX_HOME`. Configure shadow mode (this file contains no secret):

```sh
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
umask 077
mkdir -p "$CODEX_HOME/pilotfish-jev"
chmod 700 "$CODEX_HOME/pilotfish-jev"
printf '{"mode":"shadow"}\n' > "$CODEX_HOME/pilotfish-jev/config.json"
chmod 600 "$CODEX_HOME/pilotfish-jev/config.json"
```

Restart Codex. The canonical Pilotfish hook discovers the versioned installed
cache, verifies its manifest and enabled state, then reads the mode file. It
adds no second `UserPromptSubmit` hook. Environment variables remain temporary
overrides for controlled CLI testing.

Put the TypeSafe key in `~/.config/typesafe/api_key` with mode `0600`; do not
put it in Codex config, prompt text, or command arguments.
Shadow continues to route through the existing local classifier. It writes
only route labels and bounded scores to
`$CODEX_HOME/pilotfish-jev/shadow-decisions.jsonl`; it does not preserve prompt,
session, or turn content. Because the log intentionally cannot link a decision
to its prompt, use a separate labeled, sanitized evaluation set to judge
classification quality; treat shadow logs as route-distribution and
disagreement evidence only. Do not enable this mode for tasks whose contents
must not be sent to TypeSafe. A one-second timeout and all provider errors fall
back to the existing route.

The Codex-home config path works for both CLI and desktop sessions that share
the same `CODEX_HOME`; no shell variable inheritance is required. Missing or
invalid config, a disabled plugin, or an ambiguous/mismatched cache fails closed
to the existing local route.

## Stage 2: stable-promotion gate

Keep active mode off for general/stable use until all of these checks pass. The
maintainer-only WIP pilot above is an explicitly bounded test, not a waiver of
these requirements:

- Replay at least 50 sanitized, labeled tasks, with at least 10 examples for
  each route class: parent-local, mechanical, exploration, judgment, and deep
  judgment.
- Reach at least 90% exact route agreement overall and at least 85% for each
  class. Ambiguous cases must abstain rather than receive a forced role.
- Get zero security-review or deterministic deep-route downgrades in the
  regression corpus.
- Confirm expected native role bindings, one-shot continuation behavior, and
  unchanged approval/release gates on the installed Codex home.
- Confirm the API call is bounded to one second and all timeout, missing-key,
  malformed-result, and network-error cases preserve local routing.

These are proposed go/no-go thresholds, not measured Jev performance. Synthetic
offline fixtures alone do not prove live language quality.

## Stage 3: bounded activation and rollback

For a controlled WIP pilot, change `{"mode":"shadow"}` to
`{"mode":"active"}` in the mode file and restart Codex. Jev may select an eligible
route only when its top score is at least `0.80` and exceeds the runner-up by
at least `0.20`. Security-sensitive prompts, atomic requests, and locally
classified deep-judgment requests bypass Jev. Approval, security, destructive,
external, and release gates remain authoritative.

Rollback immediately by deleting the Jev mode file and verifying that the
provider makes no request. This does not alter or uninstall the core Pilotfish
plugin. Remove only the optional plugin with
`codex plugin remove pilotfish-jev-router@pilotfish-codex` when package removal
is desired.

## Go-live boundary

The implementation and offline acceptance are complete. The real CLI install
and route test used a temporary `CODEX_HOME`, with HTTP intercepted locally.
The maintainer has since enabled the plugin in the active Codex home for a
bounded WIP test, so eligible prompt text may be sent to TypeSafe. Live
classification quality and the Stage 2 thresholds remain unverified. This
repository update publishes the test feature without changing the existing
plugin version or creating a release tag; it does not promote the plugin to
stable.
