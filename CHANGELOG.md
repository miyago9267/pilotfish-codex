# Changelog

All notable changes to pilotfish-codex. The installed version is stamped inside the policy block in `AGENTS.md` (`<!-- pilotfish-codex vX.Y.Z -->`). pilotfish-codex uses its own semantic versioning; upstream pilotfish versions are noted only as source references.

## v1.0.1 — 2026-07-10

- Fix Codex 0.144.1 compatibility: use `sandbox_mode = "read-only"` for `scout` and `explore` instead of the unsupported `locked-network` value.
- Fix install URLs to point at `miyago9267/pilotfish-codex` rather than the non-Codex fork path.

## v1.0.0 — 2026-07-10

Initial release of pilotfish-codex: a Codex CLI adaptation of [pilotfish](https://github.com/Nanako0129/pilotfish)'s multi-model orchestration pattern.

- Six role agents as TOML definitions (`~/.codex/agents/*.toml`) with GPT-5.6 model tiering: luna (recon), terra (execution), sol (security)
- Orchestration policy block for `AGENTS.md` with delegation rules and model-reasoning table
- Agent-guided installer (`install/AGENT-INSTALL.md`) with approval gate, backup, and idempotent upgrades
- Subagent anti-recursion rule: role agents never spawn further subagents
- Long-process discipline: executor/mech-executor detach and yield instead of polling

Primary architecture and research credit: [pilotfish v1.1.1](https://github.com/Nanako0129/pilotfish) by [@Nanako0129](https://github.com/Nanako0129). Codex-specific adaptation and maintenance: Miyago.
