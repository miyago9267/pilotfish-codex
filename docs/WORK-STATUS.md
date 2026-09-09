---
id: pilotfish-work-status
title: Pilotfish Codex work status
status: active
updated: 2026-09-09
owner: Miyago
---

本檔是本專案唯一的 operational todo、handoff 與下一步來源。新 session
必須先讀本檔；prompt 只引用本檔，不另行維護一份清單。各 `SPEC.md` 保留
需求、決策與驗收條件，但不取代本檔的工作狀態。

## Current objective

完成 Hybrid Pilotfish runtime spec：root always-on bootstrap、Codex Plugin／Skill、
native runtime、policy ownership、transaction、migration 與 fresh-session probe。

## Current release candidate — v1.8.0-rc.1

- [x] 以 capability-first policy 將 Astra 限定在 tool-heavy、MCP、computer-use
  與跨系統 execution／verification candidate path；`plan-verifier`、四個 Luna
  baseline role 與既有 Sol gate 不變。
- [x] 修正 routing benchmark 價格基準，並保留低密度 paid baseline smoke 的
  directional-only 限制。
- [x] installer state v4 reconciliation、symlink identity、TOCTOU、rollback
  manifest 與 plugin downgrade guard 通過獨立 verifier。
- [x] repo 版本、manifest、policy marker、changelog 已同步至
  `1.8.0-rc.1`；尚未 push 或建立 tag。
- [x] 依 user approval 將 RC 安裝至全域 `/Users/miyago/.codex`，保留現行
  canonical policy 與 role drift 邊界；state v4 為 `integrated`、Plugin
  `1.8.0-rc.1`，pending sidecar 不存在。

## Completed

- [x] blocker 跨 turn 去重：同一 blocker 只警告一次，避免 Stop loop。
- [x] task-level blocked isolation：blocked task 不鎖定 sibling task。
- [x] runnable-first 規則：可執行 sibling task 優先處理。
- [x] horizontal parallel boundary：無 dependency path／write conflict 的
  runnable tasks 可水平並行；有 dependency 或 resource conflict 時序列化。
- [x] blocker、task isolation、policy phrase regression tests。
- [x] 本地 Python verification：323 tests，1 skipped，全部通過。
- [x] 本地 syntax、shell syntax、agent config validation、Markdown lint。
- [x] Windows 實機驗證：WSL、PowerShell、VS Code task 流程通過。
- [x] GitHub Actions：Ubuntu、macOS、Windows Python tests 與 Markdown lint
  全部通過。
- [x] 版本／Windows CI 修正 commits 已 push：`f169531`、`74ade3e`。
- [x] policy isolation spec：
  `docs/specs/policy-install-isolation/SPEC.md`。
- [x] Hybrid runtime spec 草稿：
  `docs/specs/hybrid-pilotfish-runtime/SPEC.md`。
- [x] Hybrid Plugin／Skill package：local marketplace、Plugin manifest、
  `pilotfish-orchestration` Skill 與 references 已建立並通過 package/skill
  validators。
- [x] Codex local migration：user policy 與 Pilotfish runtime aggregate
  分離；Claude v1.2.1 設定未修改。
- [x] 全新 `codex exec` probe：確認 Miyago、繁體中文與 recap 規則生效。
- [x] Pilotfish hook probe：確認 `UserPromptSubmit`／`Stop` registration 與
  review gate 可運作。
- [x] Hybrid T1/T2：active root 改用 minimal bootstrap；完整 workflow 移入
  `pilotfish-orchestration` Skill，Plugin 透過 local marketplace manifest 封裝。
- [x] Installer state v3：記錄 Plugin name/version/source digest/status、runtime
  outcome 與 exact rollback backup manifest；Codex
  CLI 不可用時保留 native fallback 並標記 `unavailable`。
- [x] Historical targeted/full Python verification：342 tests，1 skipped，全部通過；
  Plugin、Skill validators 與 `git diff --check` 通過。
- [x] Plugin discovery probe：installer 會用 `codex plugin list --json` 驗證
  name、marketplace、version 與 enabled，未通過時不宣稱 Skill active。
- [x] Fresh `codex exec --ephemeral` probe：新 process 讀取 bootstrap、Persona
  token 與 Recap token，並通過 `pilotfish_behavior=verified`；目前 user host 的
  Plugin/Skill 已由實機安裝啟用。
- [x] Hybrid activation report：`probe_hybrid_runtime.py` 已驗證
  `bootstrap=active`、Persona/Recap tokens 與 `pilotfish_behavior=verified`，並
  將目前 host 的 `plugin=installed`、`skill=available` 明確回報。
- [x] Hybrid runtime T1–T9 implementation audit completed；user host 已完成
  Plugin/Skill activation，並通過 fresh-session probe。
- [x] Cross-OS installer path：POSIX `install.sh` 與 Windows PowerShell
  `install.ps1` 共用同一個 `install.py`，Codex command resolution 支援
  `codex`、`codex.exe`、`codex.cmd`。
- [x] Cross-OS verification：Bash syntax、PowerShell wrapper contract（Windows
  CI）、Python compile、Plugin/Skill validators、Markdown lint 與 full test
  matrix 均已納入或通過。
- [x] General-mode decision checkpoint：schema、確認／拒絕／模糊回覆、resume
  contract tests 與 fresh Codex acceptance smoke 均通過；T9 三平台 hook parity
  仍未完成。

## Open todo

### In progress — P0 policy installation safety

- [x] runtime mode 將 Pilotfish policy 整合到 active root `AGENTS.md`，保留
  marker 外 user bytes，並在 sidecar 記錄 ownership state。
- [x] 合法的 user-owned extra roles 保留；同名 drift role 仍需明確 replacement。

### P0 — policy installation safety

- [x] 定義並實作 user policy／Pilotfish policy ownership state schema。
- [x] installer default policy integration：既有 active `AGENTS.md` 只更新
  Pilotfish marker block，marker 外 bytes 不變。
- [x] 拒絕 symlink、hard link、path alias 與 ambiguous policy target。
- [x] Host Plugin install adapter 使用 `codex plugin marketplace add` 加上
  `codex plugin add`；不自行猜測 arbitrary loader path。
- [x] 將 policy migration 與 roles、hooks、config migration 解耦。
- [x] 補 migration、upgrade、downgrade、rollback、concurrent-edit 測試。
- [x] fresh Codex v0.147.0 session probe：root `AGENTS.md` 會載入；`@...`
  不是 instruction include，不能作為 dedicated policy loader。

### P1 — orchestration follow-up

- [ ] 定義一般模式 decision checkpoint：trigger、option schema、recommendation
  與 resume contract。
- [ ] 補 decision checkpoint 的確認、拒絕、模糊回覆與 session resume tests。
- [ ] 完成三平台 hook launch、marker、path handling 與 review parity validation。
- [x] 更新 CHANGELOG、INSTALL、Hybrid probe 與 policy recovery 文件。

### P2 — local environment follow-up

- [x] 新開全新 Codex session（不要用 `resume`）驗證 Persona 與 recap。
- [ ] 驗證 local `sync_codex_runtime.py` 在 user policy 變更與 Pilotfish
  policy 更新後不會互相覆蓋。
- [ ] 評估是否保留本機 migration helper，或在正式 installer 完成後移除。
- [ ] 不得修改 Claude policy；Claude 目前維持 Pilotfish v1.2.1。

## Known constraints

- Codex `config.toml` 目前沒有已確認的 native instruction include 入口。
- 因此本機目前使用 `AGENTS.runtime.md` aggregate，並由
  `~/.codex/AGENTS.md` symlink 載入。
- `resume` 可能保留舊 session 的 instruction snapshot；runtime probe 必須
  使用全新 `codex` process。
- repository installer 已在目前 user host 完成；後續升級仍應依 INSTALL 的
  dry-run／approval boundary 執行。
- dotfile 與本 repo 仍可能有未 commit 的 local／spec changes；commit 前必須
  重新檢查各自 worktree。

## Canonical paths

- 唯一工作狀態：`docs/WORK-STATUS.md`
- blocker spec：`docs/specs/review-block-deduplication/SPEC.md`
- policy isolation spec：`docs/specs/policy-install-isolation/SPEC.md`
- Hybrid runtime spec：`docs/specs/hybrid-pilotfish-runtime/SPEC.md`
- Codex user policy：`~/dotfile/config/ai/codex/AGENTS.md`
- Codex runtime policy：`~/dotfile/config/ai/codex/AGENTS.runtime.md`
- Codex local sync：`~/.codex/pilotfish/sync_codex_runtime.py`
- Claude policy（唯讀於本任務）：`~/dotfile/config/ai/claude/CLAUDE.md`

## Next smallest action

`v1.8.0-rc.1` 已完成 repo 變更與全域安裝；目前應建立 commit、annotated tag，
推送 `main` 與 RC tag，再建立 GitHub pre-release。付費 Astra cohort、正式
promotion 與 stable release 不在此步驟內。

## Historical release record

以下為 RC 之前的歷史基線，不代表目前 host 狀態：

- `v1.6.3`／`v1.7.0` 已完成 Hybrid runtime、Windows installer 與首次
  marketplace activation，相關 release 已建立並發布。
- 舊版 state v2 的受限相容升級、Codex marketplace layout、post-sidecar
  fingerprint 收斂與 fresh-session probe 已完成。
- 當時的驗證數字為 342 tests passed、1 skipped；目前 RC 的最新驗證為 398
  tests passed、1 skipped。

## Handoff rule

handoff 只需要提供：

```text
讀取 docs/WORK-STATUS.md，從 Next smallest action 繼續。
```

任何進度變更都必須先更新本檔，再回報給使用者。
