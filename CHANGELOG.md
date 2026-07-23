# Changelog

All notable changes to pilotfish-codex. The installed version is stamped inside
the policy block in `AGENTS.md` (`<!-- pilotfish-codex vX.Y.Z -->`).
pilotfish-codex uses its own semantic versioning; upstream pilotfish versions
are noted only as source references.

## Unreleased — native Codex `rust-v0.145.0` migration

- Replace the active adapter configuration with the exact native Multi-Agent V2
  table and total concurrency of four.
- Pin installer and live preflight support to exactly `0.145.0`; unsupported,
  ambiguous, or suffixed versions fail closed without an adapter fallback.
- Add transactional install-state provenance, exact seven-role validation,
  native receipt hashes, and a staged-home materialization helper.
- Replace active dispatch mode selection and role matrices with one native-only
  verifier. Historical adapter evidence remains archival and excluded from the
  native gate.

## v1.3.1 — 2026-07-23

- Add program envelopes and independently approvable execution slices; review
  the envelope and next executable slice without blocking on unrelated work.
- Require bare `READY` or structured `REVISE` with blocker evidence, minimum
  revision, and an acceptance check. Stop automatic review after two revisions
  for one unit and return unresolved choices to the user.
- Run read-only security review before readiness for affected units. Apply the
  same two-verdict brake to materially revised completed-work claims after
  consecutive `REFUTED` results.

## v1.3.0 — 2026-07-20

- Add redacted versioned dispatch receipts with atomic writes, path and hash
  boundaries, and explicit post-hoc route observations.
- Parameterize explicit role verification and add a manual sequential matrix for
  all seven installed roles.
- Add a versioned task-class evaluator for delegation selection and abstention;
  this remains a behavioral score, not runtime enforcement.
- Keep terminal proof schema-gated and preserve the native
  `native_schema_introspection_unavailable` safe skip.
- Document upstream blockers for native routing, hard pre-execution blocking,
  hidden effective-role metadata, and unsupported lifecycle guarantees.

## v1.2.1 — 2026-07-16

### English

- Tell named-role subagents not to request their own `service_tier`, and make
  the dispatch verifier reject any recorded child-level override.
- Keep parent Fast-mode inheritance unchanged. Do not install a hook that
  cannot actually stop the spawn call; hard runtime blocking still depends on
  upstream Codex support.

### 中文

- 要求 named-role 子代理不要自行指定 `service_tier`，並讓 dispatch
  verifier 拒絕任何記錄到的 child-level override。
- 保留 parent Fast mode 的既有繼承行為。不安裝無法真正阻止 spawn call
  的 hook；runtime hard block 仍需等待上游 Codex 支援。

## v1.2.0 — 2026-07-15

- Add the three-key MultiAgentV2 compatibility adapter so named roles remain
  selectable outside the reserved collaboration schema.
- Require typed, bounded `agents.spawn_agent` calls and fail closed instead of
  retrying an untyped child that can inherit the parent model.
- Extend static validation to cover adapter shape and concurrency boundaries.
- Add an opt-in live verifier that correlates one exact parent and child
  rollout, then proves the child model differs from the parent and matches the
  installed role TOML.
- Isolate the temporary transport so stable native `agent_type` support can
  replace the adapter without changing role TOMLs or semantic policy.
- Add a scripted install route (`install/install.sh` + `install/install.py`):
  one-line curl install with a byte-preserving config merge, timestamped
  backups, idempotent re-runs, and exit-2 aborts on states that need the
  agent-guided runbook's human decisions.
- Make the scripted route plan and validate every target before writing,
  preserve CRLF and instruction symlinks, use atomic replacements with
  rollback, refuse unapproved role overwrites or duplicate role names, reject
  managed-path aliases and non-file symlink targets, and safely repair an empty
  explicit adapter table.
- Correct pinned bootstrap syntax so the selected ref reaches `bash`, and keep
  dry runs free of target-directory writes.
- Fail closed on non-object rollout payloads, match rollout IDs literally, and
  print a cost-safety warning for every `FAILED` routing verdict. Require
  non-empty correlation IDs and complete, consistent model-context evidence;
  reject malformed evidence events, exec events, and spawn arguments without
  traceback.
- Add Python CI for unit tests, syntax checks, and packaged config validation.

## v1.1.0 — 2026-07-15

- Establish pilotfish-codex as an independent Codex-native project while
  retaining the original pilotfish attribution and MIT notices.
- Credit Miyago, OpenAI Codex, and ChatGPT for the Codex adaptation and ongoing
  collaboration.
- Port Pilotfish v1.2's Discovery → Plan → Approval → Execution → Verification
  lifecycle and dispatch brake to Codex: delegate only for net benefit, keep
  tightly coupled diagnosis in the main session, require stable ownership
  before writes, and retain main-session ownership of synthesis and judgment.
- Remove model names from the installed orchestration policy so routing remains
  owned by the TOML role definitions.
- Replace detached `nohup` execution with exact-context handoff rules across all
  Bash-capable worker roles.
- Add pinned project-local Markdown lint tooling and a GitHub Actions job that
  runs the same `bun run lint:md` command.
- Normalize existing Markdown files to the repository lint rules.
- Add separate `plan-verifier` and `security-reviewer` roles so Plan readiness,
  completed-work verification, pre-approval security evidence, and approved
  security implementation retain distinct capability boundaries.
- Retire the redundant v1.0.x `explore` role. Pilotfish's uppercase `Explore`
  exists to shadow Claude Code's built-in agent; Codex needs no such override,
  and `scout` owns both broad and focused read-only discovery. The installer
  removes an old `explore.toml` only when it is unmodified or deletion is
  explicitly approved; an uppercase `Explore.toml` from a pre-release v1.1
  draft always requires explicit deletion approval. Retired-role drift is
  checked even when the installed version stamp already matches, and the
  released lowercase template is bundled as a checksum-pinned retired asset.
- Use Remora 0.1.10 as the routing reference for the seven shared Codex roles:
  `scout` on Luna low, `plan-verifier` on Sol medium, `security-reviewer` on Sol
  high, `mech-executor` on Luna medium, `executor` on Luna max, `verifier` on
  Sol high, and `security-executor` on Sol max.
- Set the recommended main model to Sol without changing the user's
  main-session reasoning effort.
- Enable native Codex multi-agent support with a three-thread cap and
  `max_depth = 1`, allowing up to three leaf workers while preventing
  recursive agent fan-out.
- Harden installation around active global `AGENTS.override.md` precedence,
  migration of inactive global or project-root policy blocks, legacy-first
  pristine backup selection, explicit removal of the v1.0.x-owned reasoning
  pin, strict config validation, customized-file diffs, and key-level uninstall
  restoration.

## v1.0.1 — 2026-07-10

- Fix Codex 0.144.1 compatibility: use `sandbox_mode = "read-only"` for `scout`
  and `explore` instead of the unsupported `locked-network` value.
- Fix install URLs to point at `miyago9267/pilotfish-codex` rather than the
  non-Codex fork path.

## v1.0.0 — 2026-07-10

Initial release of pilotfish-codex: a Codex CLI adaptation of
[pilotfish](https://github.com/Nanako0129/pilotfish)'s multi-model orchestration
pattern.

- Six role agents as TOML definitions (`~/.codex/agents/*.toml`) with GPT-5.6
  model tiering: luna (recon), terra (execution), sol (security)
- Orchestration policy block for `AGENTS.md` with delegation rules and
  model-reasoning table
- Agent-guided installer (`install/AGENT-INSTALL.md`) with approval gate, backup,
  and idempotent upgrades
- Subagent anti-recursion rule: role agents never spawn further subagents
- Long-process discipline: executor/mech-executor detach and yield instead of polling

Primary architecture and research credit:
[pilotfish v1.1.1](https://github.com/Nanako0129/pilotfish) by
[@Nanako0129](https://github.com/Nanako0129). Codex-specific adaptation and
maintenance: Miyago.
