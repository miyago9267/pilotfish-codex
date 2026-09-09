---
id: plan-pilotfish-codex-multi-shell-adapters
title: Pilotfish-Codex Multi-Shell Adapter 計劃
status: draft
created: 2026-08-21
updated: 2026-08-21
author: Miyago
approved_by:
tags: [pilotfish-codex, codex, claude-code, remora, adapters]
priority: medium
---

<!-- markdownlint-disable MD013 MD025 MD029 -->

# Pilotfish-Codex Multi-Shell Adapter 計劃

## Goal

讓 `pilotfish-codex` 保留 Codex-native workflow 的完整性，同時把可跨 runtime 的 orchestration semantics 整理成 adapter-friendly contract，支援 Claude Code、remora 與未來其他 shell。

## Scope

- 從目前 `pilotfish-codex` 抽出穩定的跨 runtime semantics 與 schema。
- 定義 Codex adapter、Claude Code adapter、remora session adapter 的責任邊界。
- 將 route/review intent、risk、approval、verification receipt、blocked state、task ledger 等概念映射到不同 shell。
- 保留 Codex 原生的 `AGENTS.md`、hooks、TOML、tool schema 與 state model。
- 讓 Claude/remora adapter 可獨立演進，不要求 Nanako 的 `pilotfish` upstream 接受這些變更。

## Out of Scope

- 不覆蓋或修改 Nanako 的 `pilotfish` upstream。
- 不把 Claude hook payload、remora session flags 或 Codex tool 名稱偽裝成共通格式。
- 不在第一階段抽出第三個 repository。
- 不為了表面格式一致而犧牲各 runtime 的 permission、model routing 或 approval semantics。

## Architecture / Plan

### Decisions

- **Decision:** 共享語意與 schema，各 runtime 以 adapter 實作。
  - **Reason:** Codex、Claude Code 與 remora 的 hook、agent、settings 和 approval surface 不同；共享檔案格式會造成語意漂移或 runtime coupling。
  - **By:** Miyago (2026-08-21)
- **Decision:** `pilotfish-codex` 是行為與 contract 的主要實驗場，Codex adapter 仍是 first-class runtime。
  - **Reason:** 目前較完整的 review gate、route intent、fresh-context verification 與 state handling 已在 Codex 版形成。
  - **By:** Miyago (2026-08-21)
- **Decision:** remora-specific model routing 與 session composition 留在 remora adapter。
  - **Reason:** CLIProxyAPI routing 和 remora 的 `--agents` / `--append-system-prompt` 是 launcher 責任，不應被 Codex policy 直接接管。
  - **By:** Miyago (2026-08-21)

### Shared Contract Candidates

```text
RouteIntent
ReviewIntent
RiskAssessment
ApprovalState
VerificationReceipt
DirectionCheckpoint
BlockedReason
TaskLedger
```

每個 contract 應描述輸入、輸出、狀態轉移、redaction 規則與最低驗證要求；不綁定特定 CLI 的 event payload。

### Adapter Responsibilities

```text
Codex adapter:
  AGENTS.md, Codex hooks, TOML, native tools, Codex state

Claude Code adapter:
  CLAUDE.md, Claude hooks, agents/*.md, Claude event payloads

Remora adapter:
  session overlay, bundle manifest, --agents,
  --append-system-prompt, CLIProxyAPI model routing
```

Claude Code adapter 與 remora adapter 可以同時存在：前者描述 Claude runtime 能理解的行為，後者描述如何把它組合進 remora session。

## Tasks

- [ ] 盤點 `pilotfish-codex` 現有行為，標記 shared semantics、Codex-only implementation 與暫不移植項目。
- [ ] 建立 contract 草稿與 versioning 規則。
- [ ] 將 route/review intent、risk、approval、verification receipt 和 blocked state 寫成 runtime-neutral schema。
- [ ] 為 Claude Code 定義 hook event mapping 與 agent contract mapping。
- [ ] 建立 Claude adapter 的最小 policy、hooks 和 agents fixture。
- [ ] 讓 remora adapter 以外部 bundle 形式提供 Claude adapter，不把 remora logic 混回 Codex core。
- [ ] 建立同一組 scenarios 的 Codex、Claude Code、remora parity tests。
- [ ] 記錄因 runtime 能力差異而無法 1:1 映射的行為。
- [ ] 評估是否有足夠穩定的共通 contract，再決定未來是否抽成獨立 package/repository。

## Verification

- 同一 scenario 在各 adapter 產生可比較的 route/review/approval/verification 結果。
- Codex-native tests 與 hooks 行為維持既有結果。
- Claude adapter 不要求 Claude Code 讀取 `AGENTS.md` 或 Codex TOML。
- remora adapter 不改寫 CLIProxyAPI 的 model routing 責任。
- 每個無法映射的欄位都有明確 `unsupported`、`degraded` 或 `adapter-owned` 定義。
- contract version 升級能檢查 adapter compatibility，而不是靠檔案 diff 猜測。

## Files

- `/Users/miyago/Project/Active/Forks/Fork-Remaster-code/pilotfish-codex` - 現有 Codex fork，第一階段的 contract 與 adapter 實驗位置。
- `/Users/miyago/Project/Active/Forks/Fork-Remaster-code/pilotfish` - 官方 Claude Pilotfish checkout；僅作為相容性參考，不在本計劃中修改 upstream。
- `/Users/miyago/Project/Active/Forks/Fork-Remaster-code/docs/plans/pilotfish-codex-multi-shell-adapters.md` - 本計劃。

## Stop Condition

完成一組最小 shared contract、Codex adapter regression tests、Claude adapter fixture 與 remora bundle smoke test 後停止；只有在跨 runtime contract 已證明穩定時，才評估抽成獨立 package。

## Notes

這條線的目標是兼容多種 shell，不是把所有 shell 壓成相同 runtime。若某個行為依賴 Codex 特有能力，應保留在 Codex adapter，並在其他 adapter 明確標記差異。
