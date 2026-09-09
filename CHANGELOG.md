# Changelog

All notable changes to pilotfish-codex. The installed version is stamped inside
the policy block in `AGENTS.md` (`<!-- pilotfish-codex vX.Y.Z -->`).
pilotfish-codex uses its own semantic versioning; upstream pilotfish versions
are noted only as source references.

## Unreleased

- Add the `pilotfish-decision-checkpoint-v1` contract with bounded options,
  conservative confirmation/rejection handling, and an explicit resume record.

## v1.8.0-rc.2

- Preserve exact rollback bytes on Windows by opening rollback sources and
  backups in binary mode; this keeps CRLF policy files and race checks intact.
- Publish the corrected release candidate from the post-CI-fix mainline while
  leaving the existing `v1.8.0-rc.1` tag immutable.

## v1.8.0-rc.1

- Establish capability-first routing: Astra is reserved for tool-heavy, MCP,
  computer-use, and cross-system execution or verification paths; Luna remains
  the mechanical/scout baseline and Sol remains the cost-conscious reasoning
  route.
- Correct the routing benchmark price baseline and keep benchmark-only cost and
  wait evidence out of runtime dispatch.
- Add current-preserving installer reconciliation with state-v4 provenance,
  symlink identity and TOCTOU checks, exact rollback manifests, and plugin
  mutation/downgrade guards.
- Record the 6-trial Luna/Terra/Sol paid baseline smoke (`$0.59352` observed,
  2/6 accepted) as directional evidence; defer the Astra promotion cohort and
  its 36-verdict gate.

## v1.6.3

- Add the Hybrid runtime: a minimal always-on root bootstrap plus the
  `pilotfish-orchestration` Skill packaged in a Codex local marketplace Plugin.
- Integrate the bootstrap into the active policy while preserving user bytes,
  and record Plugin name, version, source digest, and availability in state v3.
- Preserve valid extra roles and keep customized same-name role replacement
  explicit; unavailable Plugin installation retains the native fallback.

## v1.7.0

- Add a native PowerShell installer wrapper and Windows CI entrypoint; the
  wrapper delegates to the same Python installer and supports local or pinned
  remote sources like the POSIX shell path.
- Add official Codex marketplace layout, legacy state migration, policy symlink
  opt-in, and post-marketplace config fingerprint verification.

## v1.6.2

- Fix Windows hook marker handling without requiring POSIX file-mode semantics.
- Add a Windows path-based session scanner for environments without Unix
  `dir_fd` APIs while retaining bounded, fail-closed transcript validation.
- Warn about preserved command hooks that lack `commandWindows` and keep the
  native Windows hook launch path explicit.
- Expand Python CI validation to Ubuntu, macOS, and Windows runners.

## v1.6.1

- Add a review-service circuit breaker so missing reviewer or verifier receipts
  receive one bounded retry and then enter an explicit waiting state.
- Clarify that review-service loss is not a user decision and does not permit
  readiness, verification, credential, or external-write claims.
- Improve installer recovery for explicitly approved upstream role replacement,
  with per-role and all-role options, backups, and retained fingerprint checks.
- Make the Stop hook expose the read-only boundary while an independent review
  is pending.

## v1.6.0

- Add turn-scoped `review_intent` routing for explicit fast, default, and
  strict requests without weakening mandatory gates.
- Keep Pilotfish as an advisory signal producer while optional review
  scheduling remains owned by the auto-review consumer.
- Add a 60-case offline intent Matrix and quality-adjusted cost efficiency:
  quality points divided by equivalent cost, credited only above the baseline
  quality floor with a non-negative paired confidence bound.
- Preserve the Codex compatibility floor `>=0.146.0`; later releases remain
  accepted and are evaluated by runtime evidence.

## v1.5.1

- Stop hard-pinning the installer to one Codex release; require only the
  minimum compatible version `>=0.146.0`, accept later releases, and let the
  native contract and receipt evidence decide compatibility.
- Keep Luna as the default route and make high-reasoning escalation selective:
  clean work stays on Luna, risk-bearing disagreement can request one Sol
  second opinion, and the route records an auditable reason.
- Add role-fitness benchmark tooling, matched scorecards, adjudicator Matrix
  reports, native typed dispatch evidence, and regression coverage.
- Document the measured result honestly: native Sol transport is available and
  stable, but its switching quality/cost score remains `5/10`; direct Sol is
  retained only as a high-risk fallback with positive quality evidence.

## v1.5.0

- Add adaptive intent routing for clear execution, broad changes, and open-ended
  discovery, with grounding floors, stopping ceilings, and explicit
  `direction_checkpoint` decisions.
- Add concise English, Traditional Chinese, and Simplified Chinese entry docs
  covering the routing modes, role paths, installation, and measured evidence.
- Add deterministic Rough.js-generated SVG charts for the usage-routing benchmark
  without adding a browser runtime to the documentation.
- Fix legacy installer-state migration so the exact current hook registration
  remains recognized while unknown fingerprints still fail closed.
- Document a native PowerShell installation path for Windows and keep the
  Windows-specific hook launch behavior explicit.

## v1.4.1

- Fix native installer role-file replacement on Windows by avoiding directory
  file descriptors that Windows cannot open through `os.open`.
- Add platform-independent regression coverage for the Windows replacement
  path.

## v1.4.0

- Retire Terra from the active role bindings. Luna now owns Plan-mode and
  outcome reasoning at `xhigh`.
- Route the existing risk-triggered Plan-review role to Sol `high`; its timing,
  two-`REVISE` budget, and security boundary are unchanged.
- Bound the Plan-review session scan to current evidence: it prunes stale
  dated subtrees, ignores entries that cannot be transcript evidence, and keeps
  ambiguous or unreadable current transcripts fail-closed.
- Add a `--selftest` launch probe for the registered hook command, and document
  the silent native-Windows interpreter failure in both install playbooks.
- Narrow the security trigger so generic Chinese `驗證` no longer buys a Sol
  review; the trigger surface is pinned by a routine/material prompt corpus.
- Print dry-run backup artifacts as Codex-home-relative paths.
- Support coexistence with structurally unrelated native Codex hook groups while
  retaining fail-closed ownership of the complete event-bound Pilotfish groups
  and hook script. Isolated smoke candidates now use the clean Pilotfish
  registration, and transaction rollback preserves concurrent foreign edits.
- Permit a hook-script source upgrade only after its current bytes match the
  committed Pilotfish sidecar; unproven script drift still aborts before writes.
- Accept the runtime's metadata-linked Plan-review child only for `--autoroute`
  when spawn/activity transport is completely absent; generic role probes retain
  strict native spawn/activity correlation and receipts record the evidence mode.
- Run the autoroute smoke through the normally trusted hook path, without a
  hook-trust bypass; directive detection now examines only the submitted smoke
  prompt, not unrelated runtime-injected policy messages.

## v1.3.3

- Route the main session through Luna at `medium`, escalate Plan mode to Luna
  `xhigh`, and use Terra for general plan/outcome reasoning at `xhigh`.
- Cap `security-executor` at Sol `high`, including a fail-closed canonical
  upgrade from the v1.3.2 role payload.
- Permit the exact released v1.3.1 `plan-verifier` payload to upgrade to the
  calibrated contract without weakening custom-role drift checks.

## v1.3.2

- Replace the active adapter configuration with the exact native Multi-Agent V2
  table and total concurrency of four.
- Pin installer and live preflight support to exactly `0.145.0`; unsupported,
  ambiguous, or suffixed versions fail closed without an adapter fallback.
- Add transactional install-state provenance, exact seven-role validation,
  native receipt hashes, and a staged-home materialization helper.
- Replace active dispatch mode selection and role matrices with one native-only
  verifier. Historical adapter evidence remains archival and excluded from the
  native gate.
- Calibrate outcome verification with three verdicts, P0-P4 priority,
  risk-triggered review, main-session `FIX` / `DEFER` / `REJECT` disposition,
  targeted rechecks, a five-pass high-risk emergency ceiling, complete
  candidate/evidence identity, and explicit long-run `AUTO` / `ASK` handling.
- Add offline policy assertions for main-session continuation after decisions,
  steering, status questions, and pauses unless new input clearly supersedes
  the unfinished objective. This is prompt policy, not live runtime proof.

## v1.3.1

- Add program envelopes and independently approvable execution slices; review
  the envelope and next executable slice without blocking on unrelated work.
- Require bare `READY` or structured `REVISE` with blocker evidence, minimum
  revision, and an acceptance check. Stop automatic review after two revisions
  for one unit and return unresolved choices to the user.
- Run read-only security review before readiness for affected units. Apply the
  same two-verdict brake to materially revised completed-work claims after
  consecutive `REFUTED` results.
- Permit exact release-pinned v1.3.0 verifier-role payloads to upgrade while
  preserving fail-closed handling for customized same-name roles.

## v1.3.0

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

## v1.2.1

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

## v1.2.0

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

## v1.1.0

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

## v1.0.1

- Fix Codex 0.144.1 compatibility: use `sandbox_mode = "read-only"` for `scout`
  and `explore` instead of the unsupported `locked-network` value.
- Fix install URLs to point at `miyago9267/pilotfish-codex` rather than the
  non-Codex fork path.

## v1.0.0

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
