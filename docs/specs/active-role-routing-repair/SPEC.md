---
id: spec-active-role-routing-repair
title: Active Codex role routing repair
status: superseded
created: 2026-09-17
updated: 2026-09-17
owner: Miyago
tags: [codex, roles, routing, installer]
priority: high
---

<!-- markdownlint-disable MD025 -->

# Active Codex role routing repair

> Superseded on 2026-09-21 by `docs/specs/automatic-model-routing/SPEC.md` for
> automatic model escalation. This spec remains the historical role-availability
> slice and no longer owns the production model distribution.

## Goal

讓有效的 Codex `CODEX_HOME` 載入 Pilotfish 的七個 native roles，並讓主
session 在有清楚 bounded workstream 或必要 review 時主動使用 typed role，
同時保留小型緊密工作在 parent 內完成。

## Scope

- 提供只處理 `agents/*.toml` 的安全安裝路徑，與 policy、hooks、config、
  Plugin migration 分離。
- 保留既有七個 role、Luna/Sol model binding、approval 與 security gates。
- 更新 Codex canonical adapter 與 root bootstrap 的主動委派提示。
- 以 targeted tests、role validation、fresh session evidence 驗證 active home。

## Decisions

- `roles-only` 不修改 policy、`config.toml`、`hooks.json`、hook script、
  Plugin 或 installer state；每個既有 role replacement 都保留 timestamped
  backup，customized same-name role 仍需明確 approval。
- 不新增 Astra role，也不因任務變難自動切換 root model。`gpt-6-astra` 維持
  explicit main-session／candidate path；既有七個 role 的 production binding
  不變。
- 主 session 只在獨立 bounded workstream 或 mandatory review 適用時主動
  dispatch；單一緊密 local action 不建立 child，也不在同一 outcome 的 phase
  之間等待使用者批准。

## Tasks

- [x] Add isolated role-only installer path and regression coverage.
- [x] Add the bounded proactive-dispatch rule to Codex adapter and bootstrap.
- [x] Deploy roles to the effective Orca Codex home and regenerate the active entry.
- [ ] Validate role loading and named typed dispatch in a fresh session.

## Verification status

- Static role loading, exact payloads, file modes, strict config, prompt lock,
  and the generated active entry are validated.
- The paid live named-role probe is intentionally unrun; automatic task-class
  selection therefore remains unverified and is not claimed as an acceptance
  result.

## Acceptance

- The effective active home contains exactly the seven canonical role files under
  `agents/`, with existing policy, hooks, config, and unrelated files preserved.
- A roles-only dry-run produces no writes and works when policy or hooks are
  symlinks outside the active home.
- The policy text says when to dispatch and when to remain local, without
  requiring every command to create a child or enabling automatic Astra promotion.
- Static tests and native role validation pass; live named-role dispatch is only
  claimed when fresh runtime evidence records the requested role and child model.

## Stop condition

Stop after the active role manifest is installed, the canonical adapter is
regenerated, and the required local and fresh-session checks have a truthful
`CONFIRMED`, `REFUTED`, or `INCONCLUSIVE` result.

## Supersession note

The earlier decision to preserve all Luna/Sol bindings and prohibit automatic
Astra promotion applied to the role-availability repair only. The follow-up
automatic-model-routing spec supersedes that model-distribution decision while
retaining the seven-role manifest, typed dispatch contract, approval boundaries,
and live-evidence limitation.
