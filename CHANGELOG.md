# Changelog

All notable changes to pilotfish-codex. The installed version is stamped inside the policy block in `AGENTS.md` (`<!-- pilotfish-codex vX.Y.Z -->`).

## v1.0.0 — 2026-07-10

Initial release: Codex CLI adaptation of [pilotfish](https://github.com/Nanako0129/pilotfish) (Claude Code multi-model orchestration).

- Six role agents as TOML definitions (`~/.codex/agents/*.toml`) with GPT-5.6 model tiering: luna (recon), terra (execution), sol (security)
- Orchestration policy block for `AGENTS.md` with delegation rules and model-reasoning table
- Agent-guided installer (`install/AGENT-INSTALL.md`) with approval gate, backup, and idempotent upgrades
- Subagent anti-recursion rule: role agents never spawn further subagents
- Long-process discipline: executor/mech-executor detach and yield instead of polling

Based on the architecture and research from [pilotfish v1.1.1](https://github.com/Nanako0129/pilotfish) by [@Nanako0129](https://github.com/Nanako0129).
