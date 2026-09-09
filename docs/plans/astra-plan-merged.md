---
id: plan-astra-merged
title: GPT-6 Astra 導入 Pilotfish Role Routing 統整企劃
status: draft
created: 2026-09-08
updated: 2026-09-08
author: Miyago
approved_by:
supersedes: [plan-astra-codex, plan-astra-claude]
tags: [pilotfish-codex, astra, role-routing, benchmark, cross-runtime]
priority: high
---

<!-- markdownlint-disable MD013 MD025 MD029 -->

# GPT-6 Astra 導入 Pilotfish Role Routing 統整企劃

> 合併 `astra-plan-codex.md`（Codex runtime）與 `astra-plan-claude.md`
> （Claude adapter）。方法論採 Codex 版的 contract-first 與 matched cohort，
> 證據與成本模型採 Claude 版並補齊，另加入三項本次查證 repo 才發現、兩份原
> 企劃皆未涵蓋的阻擋事項（B1–B3）。

## Goal

以 provider-neutral evidence 判斷 GPT-6 Astra 是否值得進入 Pilotfish 的 role
routing，並在不破壞既有 approval boundary、fail-closed dispatch 驗證與成本模型
的前提下完成導入或否決。

Astra 先作為既有 role 的 **selective model candidate**，不新增 role、不
unconditional 取代 Luna 或 Sol。

## Verified Repo Facts

以下為本次直接查證的 repo 狀態，是全部決策的事實基礎。

| 事實 | 證據 |
| --- | --- |
| 七 role 現行綁定為 Luna×4 / Sol×3 | `install/benchmark_role_fitness.py:29-35` |
| `plan-verifier` 被 completed spec 硬綁 `gpt-5.6-sol@high`，wrong-binding **fail closed** | `docs/specs/automatic-sol-escalation/SPEC.md:20-27` |
| dispatch 驗證以 `RoleBinding` 斷言該綁定 | `tests/test_verify_dispatch.py:508,536,955,998` |
| role manifest validator 的 effort 白名單已排除 `none` | `install/validate_agents.py:25` |
| 成本模型的價格表三個條目全部過期 | `install/benchmark_routing.py:115-119` |

### 現行 role 綁定

| Role | model | effort | sandbox |
| --- | --- | --- | --- |
| `scout` | luna | low | read-only |
| `mech-executor` | luna | medium | — |
| `executor` | luna | max | — |
| `verifier` | luna | xhigh | workspace-write |
| `plan-verifier` | sol | high | read-only（**hook-enforced**）|
| `security-reviewer` | sol | high | read-only, web_search live |
| `security-executor` | sol | high | — |

### 價格：repo 內建模型 vs 實際

| Model | repo `MODEL_PRICES` (in/out) | 實際 (in/out) | 偏差 |
| --- | --- | --- | --- |
| `gpt-5.6-luna` | 1.0 / 6.0 | **0.20 / 1.20** | 高估 5.0x |
| `gpt-5.6-terra` | 2.5 / 15.0 | **2.00 / 12.0** | 高估 1.25x |
| `gpt-5.6-sol` | 5.0 / 30.0 | **4.00 / 20.0** | 高估 1.25x / 1.5x |
| `gpt-6-astra` | 未收錄 | **10.0 / 50.0**（cached in 1.0）| — |

**這不是小數點問題。** repo 目前認為 sol/luna 的 input 價格比是 5:1，實際是
20:1；output 比是 5:1，實際是 16.7:1。也就是說現行成本模型**系統性低估了 Luna
的成本優勢**，所有既有的 quality-adjusted cost 結論都偏向較貴的模型。在修正前
把 Astra 加進同一張表，只會把偏差放大。

### Astra 規格

| 項目 | 值 |
| --- | --- |
| context / max output | 1.05M / 128K |
| reasoning effort | low → max（不支援 `none`）|
| 價格 in / out / cached in | $10 / $50 / $1 |
| 已驗證能力數據 | ExploitBench 100%（Sol 78.5%）、ExploitGym 42.4%（Sol 30.3%）|
| 廠商宣稱（**未驗證**）| 更少 output token 達成更好結果、computer use、long-horizon coherence |

## Blockers

三項皆須在 Phase 0 結束前處理，B1 與 B2 阻擋任何 live cohort。

### B1 — `plan-verifier` 不能作為第一個 Astra 目標（P0）

兩份原企劃都把 `plan-verifier` 列為 Strong 第一順位。但
`docs/specs/automatic-sol-escalation/SPEC.md` 是 **completed** 狀態的 spec，
其 requirement 2 要求「observable `plan-verifier` child evidence bound to
`gpt-5.6-sol` at `high`」，requirement 4 明文「a missing, wrong-role, or
wrong-binding child **fails the live verifier**」，並由
`tests/test_verify_dispatch.py` 的 `RoleBinding` 斷言與 `UserPromptSubmit` /
`Stop` hook 實際執行。

把 `plan-verifier` 換成 Astra 會讓既有 escalation gate fail closed，這不是
routing 調整，是要改一份已完成的 spec 加上 hook 與 test。

**處置：** `plan-verifier` 移出 Phase 2，改列 Open Decision D1。

### B2 — 成本模型過期（P1）

`install/benchmark_routing.py:115-119` 的三個價格條目全部過期（見上表）。在
修正前產出的任何 Astra cost efficiency 數字都不可採信。

**處置：** Phase 0 先修正三個既有條目並加入 `gpt-6-astra`，且必須**單獨 commit**，
讓價格修正對既有 baseline 的影響可獨立觀察——否則會和 Astra 的影響混在一起。

### B3 — benchmark 綁定與 TOML 分離（P1，採自 Codex 版）

`install/benchmark_role_fitness.py:29-35` 硬編碼 role→(model, effort) 對照表。
只改 `templates/agents/*.toml` 不會改變 benchmark 認定的綁定，會造成「宣稱已換
但量到的是舊綁定」。

**處置：** Phase 0 的 receipt schema 必須讓 model candidate 成為顯式輸入，而非
兩處各自硬編碼。

### 已排除

`none` reasoning effort 不是問題。`install/validate_agents.py:25` 的
`REASONING_EFFORTS` 白名單本來就只收 `low/medium/high/xhigh/max`，全 repo 零個
`none` effort 路徑。

## Role Strategy

依「證據強度」而非「直覺價值」排序。

### Tier 1 — 有硬數據，優先驗證

**`security-reviewer`**

唯一具備可比較 benchmark 數字的升級點（ExploitBench 100% vs Sol 78.5%，
ExploitGym 42.4% vs 30.3%）。read-only、觸發稀疏、單次 token 量小，2.5x 單價
（相對 Sol）可吸收。維持 read-only、credential isolation、外部 action gate。

### Tier 2 — 條件式，需 cohort 決定

**`verifier`**

現為 luna@xhigh。跨 repo、browser、deployment、外部 evidence 或長 acceptance
flow 走 Astra；routine outcome verification 維持 Luna。注意實際單價差為
**50x input / 41.7x output**（非修正前價格表暗示的 10x），無條件切換會直接破壞
成本模型。

**`executor`**

現為 luna@max。僅 architecture fork、cross-module migration 或需持續工具協作時
升級。一般 feature / bug fix / 局部 refactor 不升級。

**semantic adjudication（採自 Codex 版）**

兩份 verdict 出現 fingerprinted disagreement 時，呼叫一次 Astra 作 adjudicator。
這是成本控制最有效的形態：Astra 只在系統已知自己不確定時才付費。

### Tier 3 — 維持不變

`scout`、`mech-executor` 維持 Luna。兩者價值在低成本、可重複、明確 stop
condition，對模型能力上限不敏感。Astra 的長 context 不代表應把 full history 傳
給這兩個 role。

### 待裁決

`plan-verifier`（B1）、`security-executor`（D2）。

## Open Decisions

### D1 — `plan-verifier` 是否值得改動已完成的 escalation gate

Codex 版與 Claude 版都列為第一順位；但 B1 顯示成本是「修改 completed spec +
hook + test」，而非改一個欄位。另一方面 Plan review 的工作型態是對短文件做結構
化推理，Astra 的三項優勢（security / computer use / long-horizon）在此皆無明顯
著力點。

**建議：** 不在本輪處理。若 semantic adjudication cohort 顯示 Astra 在 Plan 語意
衝突上顯著較佳，再回頭評估。

### D2 — `security-executor` 是否接受 Critical exploit 能力 + 寫入權限

Codex 版列為 conditional 可升，理由是「approval boundary 不變」。但 approval
gate 管的是「能不能動手」，不管「動手時的能力上限」。Codex 版自己在 Routing
Protocol 段引用了 Astra 達 Critical cybersecurity capability 且部分 adversarial
setting 下 monitorability 下降，卻沒把這點回推到唯一具寫入權限的資安 role——
文件內部不一致。

pilotfish 刻意把 `security-reviewer`（read-only）與 `security-executor`
（可寫入）拆成兩個 capability boundary，此決策與該設計意圖直接相關。

**需要 Miyago 明確採納或否決，不留懸置。**

### D3 — computer use 是否值得開新 role

Astra 的 computer use 讓「實際開瀏覽器跑 flow、截圖、回報」成為可派工角色，取代
目前只讀 diff 推測的驗證方式。兩份原企劃都明確排除新增 role（合理，避免第一輪
scope 膨脹）。

**建議：** 本輪不做，但列為 Astra 帶來的最高價值機會，於 Phase 3 決策時一併評估。
前置條件是確認 Codex CLI sandbox 與 Claude permission profile 是否放行
computer-use tool，以及其 approval 邊界如何界定。

### D4 — 未驗證的 model claims

以下宣稱未能在可抓取的官方文件中確認，Claude 版與 Codex 版皆引用：

- 「async tool calling、mid-turn steering、dynamic reasoning effort」
- 引用來源 `openai.com/index/safety-overview-gpt-6-astra/` 抓取回 HTTP 403

**處置：** 在 Capability Hypothesis 表中標記 `unverified`，不作為 routing 依據，
不列入 acceptance gate。

## Contract Additions

不新增第八個 role。在 role invocation 增加 provider-neutral metadata，兩個
runtime 共用 schema、各自實作 adapter（對齊
`docs/plans/pilotfish-codex-multi-shell-adapters.md` 的既有邊界決策）：

```yaml
runtime: codex|claude
role: security-reviewer
model_candidate: gpt-6-astra
model_snapshot: recorded-by-adapter
complexity: routine|cross_system|critical
escalation_reason: explicit-risk|disagreement|long-horizon|tool-complexity
permission_profile: read-only|workspace-write|approved-security-write
evidence_budget:
  max_tool_calls: 20
  max_wall_seconds: 600
  context_scope: named-inputs-only
claim_fingerprint: sha256:...
```

Role output 補足：`primary_flow`、`claim_relevant_edges`、`external_evidence`、
`tool_actions`、`inconclusive_reason`。這些描述可驗證 evidence，不把模型內部
reasoning 當作 authority。完整 transcript 不作為預設持久化資料。

不變的邊界：

- role 不得自行改變 task scope、approval、credential access、sandbox、
  delegation policy 或 verification verdict semantics。
- Codex adapter owns `AGENTS.md` / TOML / typed dispatch；Claude adapter owns
  `CLAUDE.md` / agents / hooks / permission profile。兩者不互相偽裝。
- hooks 只提供 advisory / event signal，不能偽造 approval 或 verification receipt。
- verifier 必須回傳 `CONFIRMED` / `REFUTED` / `INCONCLUSIVE`，不能用較長的模型
  輸出取代 evidence。

## Routing Protocol

```text
routine
  -> 現行低成本綁定（Luna）

material risk / long-horizon / cross-system
  -> 現行綁定為 primary
  -> Astra 僅在 escalation trigger 命中時介入

semantic disagreement
  -> fingerprint 兩份 verdict
  -> 一次性 Astra adjudicator
  -> deterministic scorer + host disposition 不變

security-sensitive
  -> security-reviewer（read-only）
  -> human approval
  -> security-executor
  -> fresh verifier
```

Astra 不作為 unconditional primary。Critical cybersecurity capability 與
adversarial monitorability 下降，要求維持 sandbox、permission、multi-layer
evidence 與 human gate。

## Benchmark Plan

### Cohorts

1. `current_binding_baseline` — 現行 Luna×4 / Sol×3 綁定。
   **不得命名為 `luna_only`**：實際 baseline 是 mixed，三個 Sol role 的數據必須
   與 Luna role 分開列示，否則跨模型差值不可解釋。
2. `astra_adjudicator_gated` — 現行綁定為 primary，僅 fingerprinted
   disagreement 呼叫 Astra。
3. `astra_selective_primary` — 僅在預先定義的 cross-system / critical-risk /
   長流程 case 使用 Astra primary。
4. `cross_runtime_reference` — 以既有 provider-neutral records 作語意參照，
   不要求字面輸出相同。

四組共用相同 task intent、scope、acceptance、risk category、negative cases 與
deterministic grader。adapter 只負責 invocation、receipt normalization 與
capability gap，不改寫 rubric。

### Acceptance Gates

- 分開報告 route accuracy、Plan quality、mechanical reliability、verification
  correctness、tool calls、wall time、token usage、task cost、`INCONCLUSIVE` 率。
- 候選先通過 baseline quality floor，**再**計算 cost efficiency。順序不可顛倒。
- approval / permission / security / destructive / external-action negative
  cases 的越權行為必須為 `0`。
- receipt 必須能證明正確的 role、model、permission profile、claim fingerprint
  與 fresh verification。
- provider credential、CLI、MCP 或 hook 不可用時標記 `capability_gap` 或
  `inconclusive`，不可計為 parity pass。
- 單次成功案例不改變 routing；需 matched paired evidence 與可重現 acceptance。
- 特別驗證「更少 output token」的廠商宣稱在本 repo 任務上是否成立——這是 Astra
  成本論述的全部基礎。

### Benchmark 預算

Astra `$10/$50`，四 cohort × 七類 case（routine / architecture / security /
cross-repo / browser / disagreement / negative-control）。Phase 2 啟動前必須
產出 token 上限與預估金額，並設 per-task budget 硬上限。

## Rollout Phases

每個 Phase 可獨立核准與回滾。

### Phase 0 — 修正與 contract 準備

- **S0.1** 修正 `install/benchmark_routing.py` 三個過期價格條目並加入
  `gpt-6-astra`。單獨 commit。
  - Acceptance：以既有 fixture 重跑，量化價格修正本身對既有結論的影響。
  - Rollback：還原單一 dict。
- **S0.2** 將 model candidate、snapshot、complexity、escalation reason、
  permission profile、claim fingerprint 加入 receipt schema，使綁定成為顯式輸入
  而非 `benchmark_role_fitness.py` 與 TOML 兩處硬編碼（B3）。
  - Acceptance：`install/validate_agents.py` 與既有 dispatch test 全綠。
  - Rollback：schema 欄位為 additive，移除即還原。
- **S0.3** 建立 Astra adapter 的 capability-gap 與 credential-safe failure state。
- 七 role 綁定在本 Phase **完全不變**。

### Phase 1 — Offline 驗證

- 驗證 role manifest、receipt schema、candidate projection、routing matrix、
  deterministic grader、route / approval / permission / fresh verification。
- 確認 Astra 缺少 provider 或 CLI 時不會被計為 parity pass。
- mock fixture 結果不得當成真實 model quality。

### Phase 2 — Bounded live cohort

- 執行四個 matched cohorts。
- 優先順序：`security-reviewer`（Tier 1，有硬數據）→ semantic adjudication →
  高風險 `verifier`。**`plan-verifier` 不在本 Phase**（B1）。
- 只保存摘要、receipt、artifact reference 與必要 redacted evidence。

### Phase 3 — Promotion decision

- 達 quality floor 且 task-level cost/time 有優勢 → 提出 selective promotion。
- 僅改善少數高複雜案例 → 保留為 disagreement-gated candidate。
- 未達 floor → 維持現行綁定，不擴大 role scope。
- 同時裁決 D1（plan-verifier）、D2（security-executor）、D3（computer-use role）。

## Risks and Controls

| Risk | Control |
| --- | --- |
| 過期價格表使成本結論失真 | S0.1 先修正並單獨 commit，量化其獨立影響 |
| 改 TOML 未改 benchmark 綁定，量到舊模型 | S0.2 讓綁定成為顯式 receipt 輸入 |
| 動到 `plan-verifier` 使 escalation gate fail closed | B1，移出本輪，改列 D1 |
| Astra 高單價導致成本失控 | selective trigger、per-task budget、quality-first gate |
| 長 context 造成不必要的資料暴露 | named inputs only、context digest、redaction、禁止 full history default |
| 高能力模型越過既有 boundary | host approval、sandbox、typed dispatch、fresh verifier |
| Critical exploit 能力 + 寫入權限 | D2 明確裁決，未裁決前 `security-executor` 不動 |
| Astra 過度主動造成不必要工作 | role-specific stop condition、禁止自行擴 scope、記錄 escalation reason |
| 廠商 benchmark 與本地結果不一致 | matched cohort 為唯一 routing evidence；未驗證 claim 標記 `unverified` |
| Astra 產生完整但不可驗證的答案 | claim fingerprint、deterministic grader、evidence-required verdict |

## Stop Condition

完成 Phase 0 的價格修正與 receipt schema、Phase 1 offline 驗證、Phase 2 四組
provider-neutral cohort record，並對 D1–D4 產出明確裁決後停止。

在 matched evidence 完成前，不修改 production role binding，也不宣稱 Astra 優於
現行綁定。

## Files

- `docs/plans/astra-plan-merged.md` — 本文件。
- `docs/plans/astra-plan-codex.md`、`docs/plans/astra-plan-claude.md` — 來源企劃。
- `docs/plans/pilotfish-codex-multi-shell-adapters.md` — 跨 runtime adapter 邊界。
- `docs/specs/automatic-sol-escalation/SPEC.md` — **B1 來源**，plan-verifier 硬綁定。
- `docs/specs/role-fitness-benchmark/SPEC.md` — benchmark 原則與 quota。
- `install/benchmark_routing.py` — **B2 來源**，價格表待修正。
- `install/benchmark_role_fitness.py` — **B3 來源**，role 綁定表。
- `install/validate_agents.py` — role manifest validator。
- `install/evaluate_dispatch.py`、`install/verify_dispatch.py` — dispatch evaluator。
- `templates/agents/*.toml` — Codex 七 role contract，Phase 0 前不變。

## Decision Record

- **Decision:** Astra 先作為 selective model candidate，不新增 role、不取代
  現行綁定。
  - **Reason:** 價值集中在高複雜判斷、長流程與資安；routine role 更需成本、
    可重複與明確停止條件。
- **Decision:** `security-reviewer` 為 Tier 1 優先驗證對象，`plan-verifier`
  移出本輪。
  - **Reason:** 前者是唯一有可比較 benchmark 數字的升級點；後者受
    `automatic-sol-escalation` completed spec 的 fail-closed 綁定約束（B1）。
- **Decision:** 價格表修正必須先行且單獨 commit。
  - **Reason:** 現行表把 sol/luna 價格比記為 5:1，實際 20:1，系統性低估 Luna
    的成本優勢；不先修正則 Astra 的 cost 結論不可採信（B2）。
- **Decision:** 本文件維持 `draft`，直到 Phase 2 matched cohort 完成。
  - **Reason:** 目前只有官方能力資料與 repo 靜態證據，沒有 Astra 在本 repo 的
    direct evidence。

## Sources

- [GPT-6 Astra Model | OpenAI API](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Model guidance | OpenAI API](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra)
- [OpenAI announces rollout of GPT-6 Astra (CNBC)](https://www.cnbc.com/2026/09/03/open-ai-astra-gpt-6-cyber.html)
- [OpenAI unveils GPT-6 Astra (Fox Business)](https://www.foxbusiness.com/technology/openai-unveils-gpt-6-astra-major-advances-ai-capabilities)
- [GPT-5.6 Pricing: Sol, Terra, Luna](https://www.layer3labs.io/guides/gpt-5-6-pricing)
