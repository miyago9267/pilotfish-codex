---
id: spec-jev-role-routing
title: WIP test: optional Jev role classification provider
status: active
created: 2026-09-23
updated: 2026-09-23
owner: Miyago
tags: [codex, jev, routing, plugin, privacy]
priority: medium
---

<!-- markdownlint-disable-next-line MD025 -->
# Optional Jev role classification provider

## Goal

Offer an optional TypeSafe Jev provider that quickly classifies a submitted task
and lets the existing Pilotfish route marker select a matching native role,
without changing the default local route or weakening approval, security, or
anti-tunnel boundaries.

## Scope

- Package Jev questions and a bounded client as an independently installable
  companion plugin.
- Keep the feature fully inactive unless the user explicitly installs/enables
  the companion plugin and selects `shadow` or `active` in
  `$CODEX_HOME/pilotfish-jev/config.json`.
- Call Jev synchronously from the canonical Pilotfish prompt hook so the same
  route decision creates the model-visible signal and the Stop-hook marker.
- Use shadow mode to record compact, prompt-free local route comparisons; active
  mode may use only validated high-confidence classifications.
- Keep deterministic security categories and explicit deep-judgment signals
  above Jev. Abstain on weak, malformed, timed-out, or ambiguous decisions and
  use the existing route.
- Send only bounded, redacted task prose to Jev over HTTPS. Never send tool
  arguments, files, transcripts, or credentials.

## Non-goals

- Do not call Jev in local tests or require a Jev API key to install the plugin.
- Do not let Jev authorize, approve, or execute a tool or external action.
- Do not change the main-session model or any role's installed model binding.
- Do not claim route accuracy from synthetic fixtures; live language coverage
  requires shadow observations and labeled examples.

## Decisions

- The plugin is optional and disabled by default; user-level configuration is
  required before any prompt is sent to TypeSafe.
- Persistent opt-in is a small Codex-home JSON mode file. The hook only loads a
  single enabled, version-matched companion cache; temporary environment
  overrides remain available for CLI testing.
- The canonical hook remains the sole owner of the route marker. A separate
  `UserPromptSubmit` advisory hook is insufficient because it cannot reliably
  replace the role that the existing `Stop` hook enforces.
- `shadow` preserves the existing route and writes only selected label, score
  summary, and disagreement to local state; it never logs prompt text or IDs.
- `active` requires a best score of at least `0.80` and a lead of at least
  `0.20` over the runner-up. Otherwise it abstains to the existing classifier.
- Existing deterministic security screening and explicit deep-judgment signals
  cannot be downgraded by Jev. Jev may select `parent-local`, `mech-executor`,
  `scout`, `sol-executor`, or `executor` only within those constraints.
- Calls have a one-second timeout and fail open to the existing classifier.

## Acceptance

- With no Jev configuration, request handling and output are byte-for-byte
  equivalent to the current route.
- The actual Codex CLI can install the companion into an isolated `CODEX_HOME`,
  and the canonical hook can load that installed cache from a persistent mode
  file without shell environment overrides.
- Shadow mode calls only a local HTTP stub in tests, records no prompt/session
  data, and never changes the route marker.
- Active mode uses one canonical role mapping for both prompt context and the
  Stop-hook marker; uncertain and malformed results fall back locally.
- Security and explicit deep routes are never downgraded; normal role bindings,
  typed dispatch and the existing one-shot anti-loop contract remain valid.
- The plugin marketplace manifest and Codex hook output validate locally.
- Full unit tests, prompt document lock, Markdown lint, and plugin package checks
  pass without a live Jev call.

## Tasks

- [x] Add Jev companion plugin package, questions, redacted API client, and tests.
- [x] Integrate optional shadow/active provider into the canonical route hook.
- [x] Add role-route mapping, marker validation, and regression tests.
- [x] Document privacy, setup, disablement, and the no-key fallback.
- [x] Run offline acceptance checks and install the optional plugin for a
  maintainer-only WIP active pilot; keep stable promotion separate.
- [x] Prove Codex CLI marketplace installation and canonical route selection in
  an isolated temporary `CODEX_HOME`, with HTTP intercepted in tests.

## Stop condition

Stop when the optional plugin and canonical-hook integration pass offline
acceptance. The maintainer-only active pilot is a test; stable promotion still
requires the Stage 2 evidence and separate review of live route quality.
