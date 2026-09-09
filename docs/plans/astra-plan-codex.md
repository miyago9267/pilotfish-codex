---
id: plan-astra-codex
title: GPT-6 Astra 導入 Pilotfish Role 企劃
status: draft
created: 2026-09-08
updated: 2026-09-08
author: Miyago
approved_by:
tags: [pilotfish-codex, astra, role-routing, benchmark]
priority: high
---

<!-- markdownlint-disable MD013 MD025 MD029 -->

# GPT-6 Astra 導入 Pilotfish Role 企劃

## Goal

驗證 GPT-6 Astra 是否能在 Pilotfish 的高不確定性、高風險與長流程工作中，提供足以抵銷額外成本的品質提升，並以 provider-neutral evidence 決定是否調整 role binding。

第一階段不新增 role 名稱，也不直接取代 Luna。Astra 先作為現有 role 的可替換 model candidate，保留 Pilotfish 的 approval、scope、sandbox、fresh-context verification 與 security separation。

## Current Baseline

目前七個 role 為：`scout`、`plan-verifier`、`executor`、`mech-executor`、`security-reviewer`、`security-executor`、`verifier`。

目前的 routing 原則是 Luna 處理 routine reconnaissance、mechanical work 與一般 verification；Sol 保留給 material Plan review 與 security boundary。role manifest 及 benchmark validator 目前以既定 model/effort binding 驗證，不能只修改 TOML 就宣稱 Astra 相容。

## Astra Capability Hypothesis

以下是待驗證的 hypothesis，不是已接受的 routing 結論：

| 能力 | 對 Pilotfish 的可能價值 | 驗證方式 |
| --- | --- | --- |
| 長 context 與長流程 coherence | 維持跨 repo、長 acceptance flow 與多份 evidence 的一致性 | cross-system task、checkpoint continuation |
| 複雜 reasoning 與 end-to-end tool use | 改善 Plan dependency、rollback 與跨工具執行判斷 | plan review、browser/tool workflow |
| 更強的 scope 與 intent adherence | 降低越權、誤解需求與不必要的 scope expansion | negative cases、approval boundary cases |
| async tool calling、mid-turn steering、dynamic reasoning effort | 讓長任務能在工具等待或需求變更時持續運作 | tool latency、mid-turn correction、effort switch |
| 高階 security capability | 提高 threat modeling 與 abuse-case 覆蓋 | read-only security review、隔離環境 |

官方資料目前標示 Astra 支援 1.05M context、128K max output、`low` 至 `max` reasoning effort，以及 MCP、hosted shell、apply patch、computer use、structured outputs 等能力；標準價格為 input `$10/MTok`、output `$50/MTok`。[OpenAI Model 文件](https://developers.openai.com/api/docs/models/gpt-6-astra)

官方也指出 Astra 在長流程、工具協作與 scope adherence 上有改善，但這些是 model-level claims，必須以 Pilotfish 自己的 matched benchmark 驗證。[OpenAI Model Guidance](https://developers.openai.com/api/docs/guides/latest-model)

## Role Strategy

### Strong — selective high-value routing

1. `plan-verifier`

   將 Astra 放入 material Plan review 或一次性 `semantic_adjudication` candidate，處理架構 dependency、風險分類、rollback 與兩份 verdict 的語意衝突。

2. `verifier`

   對跨 repo、browser、deployment、外部 evidence 或長 acceptance flow 使用 Astra candidate，要求它針對完整 claim 做反證；一般 routine verification 維持 Luna。

3. `security-reviewer`

   以 Astra 增加 threat modeling、攻擊路徑與 prompt-injection review 的覆蓋，但維持 `read-only`、credential redaction、工具 allowlist 與外部操作 gate。

### Worth exploring — conditional execution

4. `executor`

   只在 architecture fork、跨模組 migration 或需要連續工具協作時使用 Astra；一般 feature、bug fix 與局部 refactor 不升級。

5. `security-executor`

   只接受已核准且 fingerprinted 的 Plan，使用 Astra 處理複雜修補與 abuse-case regression。模型能力提升不能改變 approval boundary。

### Keep unchanged initially

`scout` 與 `mech-executor` 維持 Luna-first。這兩個 role 的主要價值是低成本、可重複與明確 stop condition，Astra 的額外能力未必能轉成可接受的 task-level value。

## Contract Additions

不新增第八個 role；增加 role invocation 的 provider-neutral metadata：

```yaml
model_candidate: gpt-6-astra
model_snapshot: recorded-by-adapter
complexity: routine|cross_system|critical
escalation_reason: explicit-risk|disagreement|long-horizon|tool-complexity
evidence_budget:
  max_tool_calls: 20
  max_wall_seconds: 600
  context_scope: named-inputs-only
claim_fingerprint: sha256:...
```

Role output 應補足：`primary_flow`、`claim_relevant_edges`、`external_evidence`、`tool_actions` 與 `inconclusive_reason`。這些欄位描述可驗證 evidence，不把模型內部 reasoning 當成 authority。

安全約束維持不變：role 不得自行改變 task scope、approval、credential access、sandbox、delegation policy 或 verification verdict semantics。

## Routing Protocol

```text
routine task
  -> Luna role

material risk / long-horizon / cross-system
  -> Luna primary
  -> Astra only when explicit escalation trigger matches

semantic disagreement
  -> fingerprint both verdicts
  -> one Astra adjudicator
  -> unchanged deterministic scorer and host disposition

security-sensitive task
  -> security-reviewer boundary
  -> approval
  -> security-executor
  -> fresh verifier
```

Astra 不應直接成為 unconditional primary。官方安全文件同時指出 Astra 已達 Critical cybersecurity capability，且 monitorability 在部分 adversarial settings 下降；這要求 Pilotfish 保持多層 evidence、sandbox 與 human gate。[OpenAI Safety Overview](https://openai.com/index/safety-overview-gpt-6-astra/)

## Waza Benchmark Plan

### Cohorts

1. `luna_only`：現行 baseline。
2. `luna_first_astra_adjudicator`：Luna primary，只有 fingerprinted disagreement 才呼叫 Astra。
3. `astra_primary_selective`：只在預先定義的 cross-system、critical-risk cases 使用 Astra primary。

沿用既有 role-fitness fixture、typed receipt、fresh-session 與 provider-neutral result；新增 model candidate 與 snapshot，不能改寫原有 rubric 以製造提升。

### Acceptance Gates

- 每個 cohort 分開報告 planning quality、mechanical reliability、verification correctness、usage、wall time、tool calls 與 cost。
- 候選品質先達到 Luna baseline floor，才計算 cost efficiency。
- 高風險 negative cases 的 unauthorized action 必須為 `0`。
- `INCONCLUSIVE` 必須有明確 prerequisite 與 retry condition，不可當成 pass。
- Astra 的品質提升需要 matched paired evidence；單次漂亮案例不升級 routing。
- role binding、dispatch receipt、sandbox 與 approval gate 必須全數通過，才能宣稱 native-compatible。

### Minimum Evidence

至少完成一組包含 routine、architecture、security、cross-repo、browser/tool、disagreement 與 negative-control 的 matched cohort。正式數量沿用現有 role-fitness quota，由 Waza runner 產生 provider-neutral records。

## Risks and Controls

| Risk | Control |
| --- | --- |
| 高單價導致成本失控 | selective trigger、per-task budget、quality-first cost gate |
| 長 context 造成不必要的資料暴露 | named inputs only、context digest、redaction、禁止 full history default |
| 高能力模型越過既有 boundary | host approval、sandbox、typed dispatch、fresh verifier |
| Astra 過度主動，反而造成不必要工作 | role-specific stop condition、禁止自行擴 scope、記錄 escalation reason |
| 安全能力提升帶來更高 misuse 風險 | security roles 分離、read-only review、credential isolation、外部 action gate |
| 供應商 benchmark 與本地結果不一致 | Waza matched cohort 作為唯一 Pilotfish routing evidence |

## Rollout Phases

### Phase 0 — Contract preparation

- 將 model candidate、snapshot、complexity、escalation reason 與 claim fingerprint 加入 benchmark receipt。
- 保持既有七 role 與現行 Luna/Sol binding 不變。
- 建立 Astra adapter capability-gap 與 credential-safe failure state。

### Phase 1 — Offline and mock validation

- 驗證 role manifest、receipt schema、candidate projection、routing matrix 與 deterministic grader。
- 確認 Astra 缺少 provider 或 CLI 時不會被計為 parity pass。

### Phase 2 — Bounded live cohort

- 執行三個 matched cohorts。
- 優先觀察 `plan-verifier`、高風險 `verifier` 與 `semantic_adjudication`。
- 保存完整結果摘要與必要 artifact reference，不保存完整 transcript 作為預設 evidence。

### Phase 3 — Decision

- 若 Astra 達到 quality floor 且 task-level cost/time 值得，才提出 selective promotion。
- 若只改善少數高複雜案例，保留為 disagreement-gated candidate。
- 若未達 quality floor，維持現行 Luna-first，不擴大 role scope。

## Claude Cross-Review Protocol

Claude 的任務是審查企劃書，不是重新設計整個 Pilotfish：

1. 找出最多五個會讓方案無法落地的問題，附文件段落或 repo evidence。
2. 分別檢查 model claims、role boundary、security control、benchmark validity 與 rollout gate。
3. 對每個問題標記 `P0`–`P4`、confidence、minimum revision、acceptance check。
4. 不因 Astra 能力較強就放寬 approval、sandbox、credential 或 fresh verifier。
5. 最終只接受可由 local test、Waza record 或官方文件驗證的修改。

Claude 回覆格式：

```text
VERDICT: READY|REVISE

Finding:
Evidence:
Minimum revision:
Acceptance check:
```

## Stop Condition

完成一組 Astra adapter capability check、三 cohort 的 provider-neutral benchmark record，以及 Claude 對本企劃書的 bounded review 後停止。未完成 matched evidence 前，不修改 production role binding，也不宣稱 Astra 優於 Luna。

## Files

- `docs/plans/astra-plan-codex.md` — 本企劃書。
- `templates/agents/*.toml` — 現有七個 role contract，Phase 0 前保持不變。
- `install/validate_agents.py` — role manifest validator，需在 candidate schema 確定後評估修改。
- `install/benchmark_role_fitness.py` — role-fitness binding 與 evidence adapter。
- `install/evaluate_dispatch.py` — route、approval、role 與 checkpoint evaluator。
- `docs/specs/role-fitness-benchmark/SPEC.md` — 現有 benchmark 原則與 quota。

## Decision Record

- **Decision:** Astra 先作為 selective model candidate，不直接取代 Luna 或新增 role。
  - **Reason:** Astra 的價值集中在高複雜判斷與長流程；routine role 更需要成本、可重複與明確停止。
- **Decision:** Astra 的 promotion 必須通過既有 quality-first、security、dispatch 與 receipt gates。
  - **Reason:** 更強模型不能替代 Pilotfish 的 authority boundary。
- **Decision:** 本文件 status 維持 `draft`，直到 Waza matched cohort 與 Claude cross-review 完成。
  - **Reason:** 目前只有官方能力資料與架構推論，尚無 Astra 在本 repo 的 direct evidence。
