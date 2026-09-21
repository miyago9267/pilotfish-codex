---
id: spec-automatic-model-routing
title: Automatic model routing for atomic and judgment work
status: implemented
created: 2026-09-21
updated: 2026-09-21
owner: Miyago
tags: [codex, routing, models, delegation, anti-tunnel]
priority: high
---

<!-- markdownlint-disable-next-line MD025 -->
# Automatic model routing for atomic and judgment work

## Goal

讓 workflow 依工作需要的判斷成本自動選 model。固定的一個指令一個動作走
cheap Luna；需要設計、選工具、解讀輸出、多步驟整合或 QA 的工作自動升級到
strong typed role。Miyago 不需要在 prompt 中要求「開多 role」。

## Scope

- 在 `UserPromptSubmit` 由 hook 判定啟動時機與實現目的，產生保守、redacted
  的 atomic/judgment route signal。
- route signal 明確帶出 escalation 條件與 dispatch contract，讓 parent 不必
  猜測是否要開 role、使用哪個 task 或 fork 邊界。
- 對非 atomic turn 自動要求 `executor` typed role；該 role 綁定
  `gpt-6-astra@high`。
- 對 atomic turn 保持 parent-local cheap execution，不建立 child。
- 若 judgment turn 結束時沒有對應的 typed `executor` child，透過既有 Stop
  hook 最多自動重試一次。
- 不確定時一律往 strong route 升級；工具輸出異常或 scope 擴大時沿用同一
  個升級規則。
- 保留 security、permission、external、release、destructive 與
  irreversible 的既有 gates。

## Non-goals

- 不在一個 turn 為每個 command 建立 child。
- 不讓 cheap role 選擇下一步、擴大 scope 或沿錯誤輸出重試。
- 不自動改變 root session model；自動升級透過 installed typed role 完成。
- 不以 route signal 取代 approval、security evidence 或 live acceptance。
- 不新增 universal classifier role，也不做付費 live probe 作為本地測試前提。

## Routing contract

### `atomic`

只有在 prompt 明確是單一 command、單一 target、單一可逆動作，且預期輸出與
stop condition 都可直接判斷時成立。parent 使用目前 cheap binding，或把完整
mechanical brief 交給 `mech-executor`。

### `judgment`

以下任一條件成立即自動升級：需要設計或拆解、需要選擇或解讀工具輸出、跨檔案
或跨系統、多步驟、需求含糊、需要修正方向，或 atomic 判定不確定。預設 route
是 `executor`，由 `gpt-6-astra@high` 負責 bounded implementation、工具操作與
局部設計判斷；parent 保留 scope、整合與最終 acceptance。

### Anti-tunnel escalation

cheap action 的工作包固定為 `goal -> target -> exact action -> expected signal
-> stop`。結果不符合預期、出現 error、需要 retry、target 改變或需要下一個
未列出的動作時，停止 cheap path，交回 strong route。hook 只自動重試一次，
避免錯誤路徑造成無限 token 消耗。

## Acceptance

- 明確的單一 command 產生 `atomic` signal，且不要求 child。
- 設計、工具選擇、模糊需求與多步驟 prompt 產生 `judgment` signal，且要求
  `executor`。
- judgment turn 沒有 typed `executor` 時，Stop hook 只重試一次並給出固定 route
  directive；directive 固定 `agent_type=executor`、`task_name=automatic_model_route`
  與 `fork_turns=none`。Codex 已由 Stop hook 續行後，不得再次鎖住同一 session。
- `executor` 與相關 strong route 的實際 role binding 是
  `gpt-6-astra@high`；`mech-executor` 與 `scout` 維持 cheap Luna binding。
- 既有 mandatory security／permission／external／destructive gates 的測試不退化。
- 本地測試能證明 route classification、marker redaction、typed child correlation
  與 prompt-lock mirror consistency；不把 static evidence 宣稱成 live model proof。

## Tasks

- [x] 建立 route signal、atomic 判定與 anti-tunnel regression tests。
- [x] 加入 hook route marker 與一次性 automatic escalation。
- [x] 將 `executor`／`verifier` 的 strong binding 與 policy route 接上。
- [x] 同步 packaged policy、Skill、canonical adapter 與 release metadata。
- [x] 執行 targeted/full local verification，確認 strict config、prompt lock 與
      active install 狀態。

## Stop condition

停止於本地 route/typed-dispatch regression、prompt lock、role validation、full
test、strict config 與 global install 都通過；live automatic task-class selection
仍標記為未驗證，除非另有明確 quota 與 live probe 授權。
