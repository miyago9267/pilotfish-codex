# Changelog

All notable changes to pilotfish. The installed version is stamped inside the policy block in `~/.claude/CLAUDE.md` (`<!-- pilotfish vX.Y.Z -->`); installs older than v1.1.0 carry no stamp.

## v1.1.0 — 2026-07-09

Security, accuracy, and update-flow release. Re-running the install prompt upgrades in place.

### Security & trust

| Change | Why |
|---|---|
| New **Trust & security** README section, with a tag/SHA-pinned install variant | `main` can change between review and install (TOCTOU); pinning makes what-you-reviewed = what-installs |
| Runbook: templates must be fetched from the same pinned ref as the runbook | Pinning now covers the actual installed bytes, not just the instructions |
| `scout` / `Explore` switched from a `disallowedTools` denylist to a positive `tools: Read, Glob, Grep` allowlist | They previously retained Bash, so "read-only" was prompted, not enforced |
| Runbook detects agent collisions by frontmatter `name:` (not filename) and flags plugin shadowing | Claude Code loads only one definition per name; `executor`/`scout` are common names |

### Behavior & quality

| Change | Why |
|---|---|
| Policy block self-disables for subagent roles | A custom `Explore` loads user memory (the built-in skips it); the policy is main-session-only |
| New policy rule: scout findings are unverified inputs | The verifier gate covers executor output, not reconnaissance |
| `verifier` runs maximum-thoroughness on security-sensitive work | medium-effort verification of high-effort security work was inconsistent |
| Versioning + "Updating an existing install" flow (this release) | Early installs had no way to learn about updates |

### Docs & claim accuracy

| Change | Why |
|---|---|
| Split Anthropic's endorsement (delegation + fresh-context verification) from pilotfish's own cheap-model routing thesis | Attribution honesty |
| 12-worker numbers reframed as an upper-bound, API-dollar experiment, with inline sources | One community experiment ≠ a guarantee; subscription quota ≠ API dollars |
| Explore warning corrected: inherited model is Opus-capped on the Claude API | Precision |
| `best`-alias fallback at the 7/12 boundary restated honestly (documented rule + June outage precedent; boundary UX unpublished; `fallbackModel` never triggers on billing errors) | The boundary hasn't been observed by anyone yet |
| Windows portability note; subscription-vs-API/Bedrock scope note; FAQ rows for spawn overhead, fast off-switch, managed environments, project-CLAUDE.md stacking | Compatibility coverage |

## v1.0.0 — 2026-07-08

Initial public release: three-layer global architecture (settings `best` + `fallbackModel`, six role agents with tiered model/effort bindings, role-based delegation policy), one-prompt agent-guided installer with approval gate and idempotent upgrades, bilingual README, sourced research report and design rationale.
