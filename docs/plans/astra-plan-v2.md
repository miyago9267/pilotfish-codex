---
id: plan-astra-v2
title: GPT-6 Astra 導入評估 v2 — 證據、成本模型與 Role 適配
status: draft
created: 2026-09-08
updated: 2026-09-09
author: Miyago
approved_by:
supersedes: [plan-astra-codex, plan-astra-claude, plan-astra-merged]
tags: [pilotfish-codex, astra, role-routing, benchmark, cost-model, security]
priority: high
---

<!-- markdownlint-disable MD013 MD025 MD029 -->

# GPT-6 Astra 導入評估 v2 — 證據、成本模型與 Role 適配

> 本文件整合三份前置企劃（`astra-plan-codex`、`astra-plan-claude`、
> `astra-plan-merged`）、線上 benchmark 與實戰回報，以及本 repo 的靜態查證結果。
> 每個數字皆標註來源。未經驗證的廠商宣稱一律標記 `unverified`，不作為決策依據。

## 結論摘要

1. **`security-reviewer` 換 Astra，effort 用 `high`。** 但**理由要換**：
   ExploitBench 100% 在公開版 API 取不到（見 §E1）。可取得的證據是
   cross-file code review +20%、SRE-Bench 88.0% vs 55.9%。
2. **`verifier` 是被低估的第二順位。** Astra 的 scope violation 0%
   （Sol 48%）、honeypot cheating 0%（Sol 48.2%）、hallucination 4.2%
   （Sol 12.2%）——「不作弊的獨立驗證」正是這個 role 的存在理由。
3. **`plan-verifier` 確定不換。** 純推理場景性價比 0.57，且被 completed spec
   硬綁 Sol（§F1）。
4. **四個 Luna role 全部不動。** 即使計入 token 效率，Astra 仍是 Luna 的
   ~14x 成本，無任何 benchmark 支撐這個倍數。
5. **`security-executor` 暫緩。** 公開版拒絕 PoC exploit 生成，abuse-case
   regression 的核心工作被前置 classifier 攔截（§E1）。

---

## Part A — Benchmark Matrix

全部為 GPT-6 Astra vs GPT-5.6 Sol，除非另註。

### A1. 資安與維運

| Benchmark | Astra | Sol | 其他 | 倍數 |
| --- | --- | --- | --- | --- |
| V8 Zero-Day Port（arbitrary code exec）| 39.0% | 5.5% | — | **7.09x** |
| SRE-Bench（single attempt）| 88.0% | 55.9% | — | **1.57x** |
| ExploitGym | 42.4% | 30.3% | — | 1.40x |
| ExploitBench | 100% | 78.5% | Fable 5.1 70% | 1.27x |

**警告：** ExploitBench / ExploitGym / V8 Zero-Day 三項所測的能力在公開版 API
被前置 classifier 攔截，非 API-accessible。詳見 §E1。

### A2. Agentic / 工具操作

| Benchmark | Astra | Sol | 其他 | 倍數 |
| --- | --- | --- | --- | --- |
| AutomationBench | 41.4% | 18.1% | Fable 5.1 31.4% | **2.29x** |
| Terminal-Bench 4.0 | 57.7–57.9% | 37.3% | Fable 5.1 55.8% | 1.55x |
| Internal DB Migration | 63.9% | 42.7% | — | 1.50x |
| ScreenSpot-Pro | 92.7% | 76.9% | — | 1.21x |
| OSWorld 2.0 | 72.6% | 65.7% | — | 1.11x |
| Agents' Last Exam | 59.3 | 53.6 | — | 1.11x |
| BrowseComp | 91.5% | 90.4% | — | 1.01x |
| Terminal-Bench Science | 64.6% | — | Fable 5.1 52.6%、Opus 5 30% | — |

OSWorld 同任務**快 47%**（40 分鐘 vs 75 分鐘）；Mind2Web 快 **1.9x**。
對 agentic role，wall-clock 常是實際瓶頸而非準確率。

### A3. 程式開發

| Benchmark | Astra | Sol | 其他 | 判讀 |
| --- | --- | --- | --- | --- |
| CodeRabbit cross-file review | 57.1% | 47.6% | — | **+20% 相對** |
| CodeRabbit 整體 bug coverage | 61.3% | 59.0% | — | +4% 相對 |
| DeepSWE v1.1 | 74.1% | 72.7% | Opus 5 73.7%、Muse Spark 1.3 75.4% | 幾乎打平 |
| FrontierCode Extended | 64.5% | — | Fable 5 64.9% | 落後 |
| AA Coding Agent Index | 67 | — | Fable 5.1 70、Opus 5 領先 | 落後 |

**判讀：** 一般 SWE 修補打平；價值集中在**跨檔案、證據分散**的任務。
CodeRabbit 原文建議：targeting「difficult task with scattered evidence」。

### A4. 長 context 與可信度

| 指標 | Astra | Sol | 意義 |
| --- | --- | --- | --- |
| MRCR v2 256K–512K | 100% | 91.5% | 長 context 檢索 |
| MRCR v2 512K–1M | **96.3%** | 73.8% | 1.30x |
| Scope violation（授權外行動）| **0%** | 48% | 見下 |
| Honeypot cheating | **0%** | 48.2% | 見下 |
| Circumvention attempts | 0.00% | 0.29% | — |
| Hallucination rate | 4.2% | 12.2% | 2.9x 少 |
| Misaligned outcome rate | 3.4% | — | — |

**Scope violation 0% 的來源：** OpenAI 依 Hugging Face 事件建立的新評測，測「模型
面對困難或不可能的任務時是否越出授權範圍」。Sol 在無 production safeguard 下
越界 48%，Astra 0%。

**這組數字對 `verifier` 的意義最大**：一個會在 honeypot 上作弊 48% 的驗證者，
其 `CONFIRMED` 判定不可信。

### A5. 學術與推理

| Benchmark | Astra | 對照 |
| --- | --- | --- |
| FrontierMath Tier 4 v2 | 97.6% | Fable 5.1 87.8%、Opus 5 73.2% |
| ARC-AGI-3 | 99.9% | Opus 5 30.2%、Sol 7.8% |
| GPQA Diamond | 96.0% | Gemini 3.8 Flash 95.3% |
| Humanity's Last Exam | 57.2% | Fable 5.1 65.0%（**落後**）|
| AA Intelligence Index | 61（= Sol 61）| Opus 5 63.0、Fable 5.1 65.6 |

### A6. 科學與健康

| Benchmark | Astra | Sol | 倍數 |
| --- | --- | --- | --- |
| GeneBench Pro | 37.8% | 28.7% | 1.32x |
| BenchCAD | 95.9% | 83.3% | 1.15x |
| HealthBench Professional | 63.4% | 60.5% | 1.05x |
| MedChemBench | 49.3% | 47.4% | 1.04x |
| LifeSciBench | 60.3% | 59.9% | 1.01x |

### A7. 數據不一致（需注意）

- **AA Intelligence Index**：AA 模型頁列 Astra xhigh/max 為 **53**；AA 評測文章
  與多家轉載列 **61 / 61.1 / 61.2**。兩者為不同 index 版本或不同快照，
  **不可混用**。本文件在性價比計算中只使用「Astra 與 Sol 在同一 index 下打平」
  這個相對結論，不採用絕對值。
- **Terminal-Bench 4.0**：57.7% 與 57.9% 兩個數字並存，差異在誤差內。

---

## Part B — 成本模型

### B1. 標價

| Model | input | cached input | output | context / max out |
| --- | --- | --- | --- | --- |
| `gpt-6-astra` | $10.00 | $1.00 | $50.00 | 1.05M / 128K（max input 922K）|
| `gpt-5.6-sol` | $4.00 | $0.40 | $20.00 | 1.05M / 128K |
| `gpt-5.6-terra` | $2.00 | — | $12.00 | 1.05M / 128K |
| `gpt-5.6-luna` | $0.20 | — | $1.20 | 1.05M / 128K |

Astra 標價為 Sol 的 **2.5x**、Luna 的 **50x（input）/ 41.7x（output）**。

超過 272K input tokens 的請求：input / cached input / cache write 以 2x 計價，
output 以 1.5x 計價。cache write 為未快取 input 的 1.25x，快取最短存活 30 分鐘。

### B2. Token 效率 — 決定性因素

| 任務類型 | Astra token 用量 vs Sol | 實際每任務成本 |
| --- | --- | --- |
| Coding / agentic（max effort）| **1/3** | **≈ 1.0x（同價）** |
| Intelligence Index（max effort）| 0.9（-10%）| **1.75x（更貴）** |

Artificial Analysis 原文：coding 在 max effort 下「costs about the same as
GPT-5.6 Sol (max) while scoring 2 points higher」；Intelligence Index 則是
「75% more expensive per task than its predecessor at max effort」。

對 Claude Opus 5 (xhigh)，Astra 在 coding 任務用 **1/5** 的 token。

**這是全篇最重要的一組數字**：Astra 的標價是 2.5x，但在動工具的任務上每任務
成本回到 1.0x。單看標價會做出錯誤決策。

### B3. Reasoning effort 的成本／效益曲線

獨立測試的每任務成本與 index 分數：

| effort | 每任務成本 | index 分數 | 邊際 |
| --- | --- | --- | --- |
| `low` | $0.63 | 49 | — |
| `medium` | $1.16 | 52 | **+3 分 / $0.53（最划算）** |
| `high` | $1.41 | 53 | +1 分 / $0.25 |
| `xhigh` | $1.85 | 54 | +1 分 / $0.44 |
| `max` | $2.57 | 55 | **+1 分 / $0.72（最差）** |

`max` 是 `low` 的 **2.3x 成本**，只換 6 分。

**OpenAI 官方建議：** agentic coding 與 research 用 `medium`；複雜除錯用
`high`；`xhigh` 僅在自有 eval 顯示明確效益時才用。Codex CLI 社群指南建議
`high` 為一般 coding 預設，`xhigh` / `max` 保留給困難架構決策與除錯迴圈。

**遷移建議：** 原本用 `none` 或 `minimal` 的，從 `low` 開始比對；其餘保持
現有 effective effort。

### B4. Codex CLI 額度計費

| 項目 | credit rate |
| --- | --- |
| input | 250 credits / 1M tokens |
| cached input | **25 credits / 1M tokens** |
| output | 1,250 credits / 1M tokens |

- Astra 消耗既有 Work / Codex 額度，**沒有獨立配額**。
- 5 小時視窗的 local message 估計值：Plus / Business Standard 5–45、
  Pro $100 25–225、Pro $200 100–900、Business Premium 無 5 小時限制。
  **週配額未公開。**
- 快取命中僅 input 的 1/10 價，使 `AGENTS.md` 與啟動 prompt 這類重複 boilerplate
  在規模化後接近免費——**對 pilotfish 這種 policy 很長的專案是實質利多**。
- 已知問題：`openai/codex#43222` 回報 Astra 的週配額消耗與本地 token telemetry
  不成比例。**額度預估不可信，需實測。**

---

## Part C — 性價比計算

性價比 = 效益倍數 ÷ 每任務成本倍數（成本倍數取 §B2：agentic 1.0x、純推理 1.75x）。

| 場景 | 效益 | 成本 | **性價比** | API 可取得 |
| --- | --- | --- | --- | --- |
| Zero-day / exploit 分析 | 7.09x | 1.0x | **7.09** | **否**（§E1）|
| 工作流自動化 | 2.29x | 1.0x | **2.29** | 是 |
| SRE / 事故排查 | 1.57x | 1.0x | **1.57** | 是 |
| CLI agentic | 1.55x | 1.0x | **1.55** | 是 |
| 跨檔案 migration | 1.50x | 1.0x | **1.50** | 是 |
| 長 context 檢索 | 1.30x | 1.0x | **1.30** | 是 |
| 跨檔案 code review | 1.20x | 1.0x | **1.20** | 是 |
| 一般 SWE 修補 | 1.02x | 1.0x | 1.02 | 是 |
| 純推理 / Plan review | 1.00x | **1.75x** | **0.57** | 是 |

**分界線：要動工具的都賺，只動腦的都虧。**

扣除 API 不可取得項後，實際可用的最高性價比是**工作流自動化 2.29** 與
**SRE 排查 1.57**。

### C1. vs Luna 的計算

Luna $0.20/$1.20。即使 Astra 只用 1/3 token：

- input：50x ÷ 3 ≈ **16.7x**
- output：41.7x ÷ 3 ≈ **13.9x**

沒有任何 benchmark 顯示 Astra 比 Luna 好 14 倍。**四個 Luna role 全部維持。**

---

## Part D — 實戰使用回報

### D1. 一致獲得好評的項目

- **工具使用**：production preview 團隊評為「meaningfully surpasses every model
  we have used」，且**所需 scaffolding 大幅減少**——他們刪掉部分 `AGENTS.md`
  指令後結果反而更好。
- **邊界誠實**：「reliably admits it cannot solve something rather than producing
  a confident hallucination」。與 A4 的 hallucination 4.2% 一致。
- **Git 操作**近乎零失誤；程式碼品質評為 best-in-class。
- **長流程持久性**：有 2,000 步的隔夜執行案例；Codex notes 可跨 context window
  rollover 存活。
- **QA 自動化**：可連續數小時點擊 app、發訊息、刷新頁面、檢查 devtools console，
  找出開發者遺漏的問題。

### D2. 已回報的失敗模式

| 失敗模式 | 描述 | 緩解 |
| --- | --- | --- |
| **過度工程** | 預設產出全面解法而非最小修補 | prompt 必須明寫 minimality |
| **過度研究燒 token** | 超出必要地呼叫 web / 驗證工具 | 限制工具 allowlist、evidence budget |
| **過早放棄** | 遇到合理障礙時比競品更早停手 | 視為邊界尊重，但需明確 retry 契約 |
| **寫作品質下降** | 比前代更差的 writer | 文件 / release notes 不要用它 |
| **額度消耗劇烈** | 有回報單一簡單 coding 任務吃掉 30% 週限額 | per-task budget 硬上限 |
| **提升不顯著** | 部分開發者未見相對 Sol 的明顯改善 | 必須自有 eval，不採信廠商數字 |
| **壓縮通訊** | 多 agent 訊息限制下自創縮寫（省冠詞、融合名詞）| monitorability 風險 |

### D3. 對 pilotfish 特別相關的兩點

1. **「刪掉部分 AGENTS.md 後結果更好」** — pilotfish-codex 的 policy 相當長。
   若導入 Astra，應同時測試 policy 精簡版，否則可能付費買到被冗長指令拖累的
   結果。
2. **「對 skills 與 AGENTS.md 中的指令更敏感」** — 官方明說。既有 policy 的
   細微措辭在 Astra 下的效果可能與 Sol / Luna 不同，**不能假設 policy 行為等價**。

---

## Part E — 營運限制與封鎖項

### E1. 資安能力在公開版 API 被攔截（最重要）

- 公開版 Astra **限於 secure code review 與 patching**，拒絕生成 PoC exploit。
- 攔截發生在**推論之前**：API 前的 classifier 直接回 **HTTP 400、零 token 計費**，
  訊息為「This content was flagged for possible cybersecurity risk」。
- **聲明授權無效** — classifier 針對任務**形狀**而非宣稱意圖。
- 解鎖途徑為 **OpenAI Daybreak Red**，需組織層級佐證（SOC 2 Type II / ISO 27001、
  SSO/MFA、事故應變文件）。有申請者等待七週未決。

**實測通過（HTTP 200，無拒絕、無中斷）的任務：**

- 弱點審查（識別 SQL injection CWE-89、說明利用路徑、提供參數化修補）
- 產生 PHPUnit regression test 驗證修補
- 撰寫具 taint-tracking 的 Semgrep 規則
- 產出 CVSS 向量、業務影響評估與修補建議

**對 pilotfish 的意義：**

- `security-reviewer` 的工作內容（read-only 證據、威脅建模、最小修補方向、
  acceptance check）**完全落在允許區**，可以用。
- 但**不能宣稱取得 ExploitBench 100% 的能力**。A1 的四項數字是 model capability，
  不是 API-accessible capability。理由必須改用 CodeRabbit cross-file +20% 與
  SRE-Bench 1.57x。
- `security-executor` 的 abuse-case regression 若涉及 PoC 形狀，會被攔截。
  這是 D2 暫緩的**新增技術理由**，不只是政策理由。

### E2. Production 安全檢查可中止任務

OpenAI 在 production 執行 misalignment monitoring。額外安全檢查可能減速、暫停
或**停止合法工作，包含防禦性資安**。

- 在 ChatGPT / Codex 中：任務暫停，可能要求人工複核後才續行。
- 在 **API 中：任務直接停止**。

**對 pilotfish 的意義：** 任何自動化 role 都可能中途被停。receipt schema 必須
能區分「模型判定 INCONCLUSIVE」與「被平台安全檢查中止」，後者應映射為
`capability_gap`，不可計為 parity pass 或驗證失敗。

### E3. monitorability 退步

OpenAI 明說 Astra 的書面 reasoning 比 Sol **更難監控**，並因此延後後續 scaling。
內部部署採更嚴格隔離、checkpoint 加密、全 trajectory（含 CoT）監控與 blocking
alignment evaluation。

與 D2 的「壓縮通訊」現象一致。對需要人工審閱模型推理的 role 是負面因素。

### E4. 平台前置條件

| 項目 | 值 | repo 現況 |
| --- | --- | --- |
| Codex CLI 最低版本 | **v0.153.1**（2026-09-03）| repo 未 pin，**待確認** |
| 存取資格 | Trusted Access Programme enrollment | **待確認** |
| 驗證指令 | `codex models` | — |
| 支援工具面 | web search、file search、image gen、code interpreter、hosted shell、apply patch、computer use、MCP、tool search | — |

建議設定：

```toml
model = "gpt-6-astra"
model_provider = "openai"
model_reasoning_effort = "high"

[model_settings]
auto_compact_token_limit = 850000

[tui]
auto_recap = false
```

自動化管線建議 `approval_policy = "untrusted"` 而非 `"never"`，直到累積運作經驗。

---

## Part F — Repo 現況與 Blockers

本次直接查證的 repo 狀態。

### F1. `plan-verifier` 被 completed spec 硬綁 Sol（P0）

`docs/specs/automatic-sol-escalation/SPEC.md` 為 **completed** 狀態：

- requirement 2：必須產生綁定 `gpt-5.6-sol` at `high` 的可觀測 `plan-verifier`
  child evidence。
- requirement 4：missing / wrong-role / **wrong-binding child fails the live
  verifier**。

由 `tests/test_verify_dispatch.py:508,536,955,998` 的 `RoleBinding` 斷言與
`UserPromptSubmit` / `Stop` hook 實際執行。

換掉 `plan-verifier` 的模型會讓既有 escalation gate fail closed。這不是 routing
調整，是改一份已完成的 spec 加 hook 加 test。

**加上 §C 的性價比 0.57，結論是明確不換。**

### F2. 成本模型的價格表全部過期（P1）

`install/benchmark_routing.py:115-119`：

| Model | repo 記的 | 實際 | 偏差 |
| --- | --- | --- | --- |
| `gpt-5.6-luna` | 1.0 / 6.0 | 0.20 / 1.20 | **高估 5.0x** |
| `gpt-5.6-terra` | 2.5 / 15.0 | 2.00 / 12.0 | 高估 1.25x |
| `gpt-5.6-sol` | 5.0 / 30.0 | 4.00 / 20.0 | 高估 1.25x / 1.5x |
| `gpt-6-astra` | 未收錄 | 10.0 / 50.0 | — |

repo 認為 sol:luna 的 input 價格比是 5:1，實際 **20:1**；output 比 5:1，實際
**16.7:1**。現行成本模型**系統性低估 Luna 的成本優勢**，所有既有
quality-adjusted cost 結論都偏向較貴的模型。

此表也缺少 §B1 的超過 272K input 加價規則與 §B2 的 token 效率因子，
無法表達「標價 2.5x 但每任務同價」這件事。

### F3. benchmark 綁定與 TOML 分離（P1）

`install/benchmark_role_fitness.py:29-35` 硬編碼 role→(model, effort) 對照表。
只改 `templates/agents/*.toml` 不會改變 benchmark 認定的綁定。

### F4. 已排除的非問題

`none` reasoning effort 不構成阻擋。`install/validate_agents.py:25` 的
`REASONING_EFFORTS` 白名單本就只收 `low/medium/high/xhigh/max`，全 repo 零個
`none` effort 路徑。（Astra 對 `none` 會回 HTTP 400。）

### F5. 現行 role 綁定

| Role | model | effort | sandbox |
| --- | --- | --- | --- |
| `scout` | luna | low | read-only |
| `mech-executor` | luna | medium | — |
| `executor` | luna | max | — |
| `verifier` | luna | xhigh | workspace-write |
| `plan-verifier` | sol | high | read-only（hook-enforced）|
| `security-reviewer` | sol | high | read-only, web_search live |
| `security-executor` | sol | high | — |

---

## Part G — Role 適配裁決

### Tier 1 — 建議進入 cohort

#### `security-reviewer` → Astra @ `high`

| 項目 | 內容 |
| --- | --- |
| 現況 | sol @ high, read-only |
| 支撐證據 | CodeRabbit cross-file review 57.1% vs 47.6%（+20% 相對）；SRE-Bench 88.0% vs 55.9%；hallucination 4.2% vs 12.2% |
| **不可用的證據** | ExploitBench / ExploitGym / V8 Zero-Day——API 攔截（§E1）|
| 成本 | agentic 任務約 1.0x Sol；effort `high` 為 $1.41/task 級距 |
| effort 選擇 | `high`。`xhigh`→`max` 每分要價 $0.44–0.72，不划算 |
| 風險 | 平台安全檢查可能中止任務（§E2）→ 需 `capability_gap` 狀態 |
| 邊界 | 維持 read-only、credential isolation、外部 action gate |

#### `verifier` → 條件式 Astra @ `high`

| 項目 | 內容 |
| --- | --- |
| 現況 | luna @ xhigh, workspace-write |
| 支撐證據 | **scope violation 0% vs Sol 48%**；**honeypot cheating 0% vs Sol 48.2%**；hallucination 4.2%；MRCR 512K–1M 96.3% vs 73.8% |
| 論據 | 這個 role 的存在理由是「不作弊的獨立驗證」，Astra 在此維度有直接數據 |
| 成本 | vs Luna 約 **14x**，無法無條件切換 |
| 觸發條件 | 僅 cross-repo、browser、deployment、外部 evidence、長 acceptance flow，或 `strict` review intent |
| effort 選擇 | `high`（不是現行的 `xhigh`）——邊際效益不足 |
| 待解 | 單一 role 的條件式 model 路由如何實作（§H4）|

#### semantic adjudication → 一次性 Astra @ `high`

兩份 verdict 出現 fingerprinted disagreement 時呼叫一次。Astra 只在系統已知
自己不確定時付費，是成本控制最有效的形態。承自 `astra-plan-codex`。

### Tier 2 — 條件式，需 cohort 決定

#### `executor` → 僅 architecture fork / cross-module migration

| 項目 | 內容 |
| --- | --- |
| 現況 | luna @ max |
| 支撐證據 | Internal DB Migration 63.9% vs 42.7%（1.50x）；cross-file review +20%；Terminal-Bench 1.55x |
| 反證 | DeepSWE 僅 +1.4pt；一般 SWE 修補與 Sol 打平；vs Luna 為 14x 成本 |
| 觸發條件 | architecture fork、cross-module migration、需持續工具協作 |
| 注意 | Astra 有**過度工程**傾向（§D2），prompt 必須明寫 minimality |

### Tier 3 — 維持不變

`scout`、`mech-executor` 維持 Luna。價值在低成本、可重複、明確 stop condition，
對模型能力上限不敏感。Astra 的長 context 不代表應把 full history 傳給這兩個 role。

Bootstrap 與 orchestration policy 另加 baseline-only guard：這兩個 role 不得
要求 Astra；若工作超出其邊界，改路由到 `executor` 或 `verifier`。

### 不換

#### `plan-verifier` → 維持 sol @ high

- 性價比 **0.57**（純推理場景成本 1.75x、Intelligence Index 與 Sol 打平）。
- 被 completed spec + hook + test 硬綁（§F1）。
- 兩份前置企劃都把它列第一順位，本文件推翻該判斷。

#### `security-executor` → 暫緩

- **技術理由（新增）**：公開版拒絕 PoC exploit 形狀的請求（§E1），
  abuse-case regression 的核心工作會被攔截。
- **政策理由**：Critical cybersecurity capability + 寫入權限的組合，與 pilotfish
  刻意分離 reviewer / executor capability boundary 的設計意圖衝突。
- **加重因素**：monitorability 退步（§E3），人工審閱模型推理的成本上升。

---

## Part H — Open Decisions

### H1 — `security-executor` 是否升級

技術面已被 §E1 大幅削弱（PoC 形狀被攔截）。政策面仍需裁決。
**建議：否決本輪，待 Daybreak Red 資格與 §E2 中止行為的實測資料再議。**

### H2 — 是否申請 OpenAI Daybreak Red

解鎖完整 offensive-security 能力的唯一途徑。需 SOC 2 Type II / ISO 27001、
SSO/MFA、事故應變文件等組織層級佐證，且已知有七週未決的案例。
**建議：以 pilotfish 目前的使用情境（防禦性 review + patching），不需要。**

### H3 — computer use 是否值得開新 role

Astra 的 computer use（OSWorld 72.6%、ScreenSpot-Pro 92.7%、可連續數小時做 QA）
讓「實際開瀏覽器跑 flow、截圖、回報」成為可派工角色。
**建議：本輪不做，Phase 3 一併評估。** 前置條件為確認 Codex sandbox 是否放行
computer-use tool 及其 approval 邊界。

### H4 — 單一 role 的條件式 model 路由如何實作

`verifier` 需要依觸發條件在 Luna 與 Astra 之間分流。現行架構是否支援，
或需拆成兩個 agent 定義（`verifier` / `verifier-strict`）。**待確認。**

### H5 — pilotfish policy 是否需要為 Astra 精簡

§D3：production 團隊刪掉部分 `AGENTS.md` 後結果反而更好，且官方說 Astra 對
`AGENTS.md` / skills 的指令**更敏感**。既有 policy 在 Astra 下的行為不能假設
與 Sol / Luna 等價。
**建議：Phase 2 的 Astra cohort 同時跑「完整 policy」與「精簡 policy」兩組。**

---

## Part I — Rollout

每個 slice 可獨立核准與回滾。

### Phase 0 — 修正與前置確認

- **S0.1（offline 已完成）** 修正 `install/benchmark_routing.py` 的過期價格
  條目，加入 `gpt-6-astra`，並補上 §B1 的 272K 加價規則。變更維持可獨立
  回滾；本輪尚未建立 git commit。
  - Acceptance：既有 fixture 與價格邊界測試全綠，價格修正與 live 執行解耦。
  - Rollback：還原單一 dict。
  - 估時：修改 5 分鐘，重跑與比對 30 分鐘。
- **S0.2** 成本模型加入 **token 效率因子**。現行模型只有單價，無法表達
  「標價 2.5x 但每任務 1.0x」，這是 §B2 的核心。
  - Acceptance：同一任務在 Astra 與 Sol 下的 predicted cost 差距落在實測 ±20%。
- **S0.3** 將 model candidate、snapshot、complexity、escalation reason、
  permission profile、claim fingerprint 加入 receipt schema，使綁定成為顯式輸入
  而非 §F3 的兩處硬編碼。
  - Acceptance：`install/validate_agents.py` 與既有 dispatch test 全綠。
- **S0.4** 確認平台前置條件（§E4）：Codex CLI 版本是否 ≥ v0.153.1、
  Trusted Access 資格、`codex models` 是否列出 `gpt-6-astra`。
- **S0.5** receipt 新增 `platform_halt` 狀態，區分「模型 INCONCLUSIVE」與
  「§E2 平台安全檢查中止」。後者映射為 `capability_gap`。
- 七 role 綁定在本 Phase **完全不變**。

### Phase 1 — Offline 驗證

- 驗證 role manifest、receipt schema、candidate projection、routing matrix、
  deterministic grader、route / approval / permission / fresh verification。
- 確認 Astra 缺少 provider、CLI 或資格時不會被計為 parity pass。
- mock fixture 結果不得當成真實 model quality。

### Phase 2 — Bounded live cohort

Cohorts：

1. `current_binding_baseline` — 現行 Luna×4 / Sol×3。
   **不得命名為 `luna_only`**：實際 baseline 是 mixed，三個 Sol role 的數據
   必須與 Luna role 分開列示。
2. `astra_adjudicator_gated` — 現行綁定為 primary，僅 fingerprinted
   disagreement 呼叫 Astra。
3. `astra_selective_primary` — 僅在 cross-system / critical-risk / 長流程
   case 使用 Astra primary。
4. `astra_slim_policy` — 同 3，但使用精簡版 policy（§H5）。

優先順序：`security-reviewer` → semantic adjudication → 高風險 `verifier`。
**`plan-verifier` 不在本 Phase**（§F1）。

必測項目（來自本次研究）：

- §B2 的「coding 任務 1/3 token」在本 repo 任務上是否成立——**這是整個成本
  論述的基礎**。
- §D2 的過度工程與過度研究燒 token 是否出現，minimality 指令是否有效。
- §E2 的平台中止是否發生，頻率多少。
- §B4 的週配額消耗是否如 `openai/codex#43222` 所述與 telemetry 不符。

### Phase 3 — Promotion decision

- 達 quality floor 且 task-level cost/time 有優勢 → selective promotion。
- 僅改善少數高複雜案例 → 保留為 disagreement-gated candidate。
- 未達 floor → 維持現行綁定。
- 同時裁決 H1–H5。

### Acceptance Gates（全 Phase 適用）

- 分開報告 route accuracy、Plan quality、mechanical reliability、verification
  correctness、tool calls、wall time、token usage、task cost、`INCONCLUSIVE` 率、
  `platform_halt` 率。
- 候選先通過 baseline quality floor，**再**計算 cost efficiency。順序不可顛倒。
- approval / permission / security / destructive / external-action negative
  cases 的越權行為必須為 `0`。
- 單次成功案例不改變 routing；需 matched paired evidence。
- Phase 2 啟動前須產出 token 上限與預估金額，並設 per-task budget 硬上限
  （§D2 有單一任務吃掉 30% 週限額的回報）。

---

## Part J — Risks and Controls

| Risk | 來源 | Control |
| --- | --- | --- |
| 以標價 2.5x 做決策，忽略 token 效率 | §B2 | 成本模型加入 token 效率因子（S0.2）|
| 過期價格表使成本結論失真 | §F2 | S0.1 先修正並單獨 commit |
| 改 TOML 未改 benchmark 綁定 | §F3 | S0.3 讓綁定成為顯式 receipt 輸入 |
| 動 `plan-verifier` 使 escalation gate fail closed | §F1 | 不換，改列 §G「不換」 |
| 以 ExploitBench 100% 為理由，但 API 取不到 | §E1 | 理由改用 cross-file review 與 SRE-Bench |
| 平台安全檢查中止自動化任務 | §E2 | `platform_halt` 狀態（S0.5），映射 `capability_gap` |
| 單一任務燒掉大量週配額 | §B4、§D2 | per-task budget 硬上限、evidence budget |
| 過度工程產出超出 scope 的修改 | §D2 | prompt 明寫 minimality、role stop condition |
| 過度研究燒 token | §D2 | 工具 allowlist、max_tool_calls |
| 既有 policy 在 Astra 下行為改變 | §D3、§H5 | Phase 2 加跑精簡 policy cohort |
| monitorability 退步使人工審閱成本上升 | §E3 | 維持 fresh verifier、deterministic grader |
| Critical exploit 能力 + 寫入權限 | §E1、§E3 | `security-executor` 暫緩（H1）|
| 長 context 帶入不必要的敏感資料 | — | named inputs only、context digest、redaction |
| 廠商 benchmark 與本地結果不一致 | §D2 | matched cohort 為唯一 routing evidence |
| benchmark 數字版本不一致 | §A7 | 只採相對結論，不採絕對 index 值 |

---

## Stop Condition

完成 Phase 0 的價格修正、token 效率因子、receipt schema 與平台前置確認；
Phase 1 offline 驗證；Phase 2 四組 provider-neutral cohort record；
並對 H1–H5 產出明確裁決後停止。

在 matched evidence 完成前，不修改 production role binding，也不宣稱 Astra
優於現行綁定。

## Implementation status (offline Phase 0/1)

本版已落地不涉及付費或 production binding 的 contract：

- `install/benchmark_routing.py` 使用 Luna/Terra/Sol/Astra 最新標價，實作
  272K input surcharge、分離的 token-efficiency estimate（agentic 1/3、
  reasoning 校準為 Astra/Sol 1.75x），以及
  `security-reviewer`、高風險 `verifier` / `executor` 與 disagreement 的
  Astra candidate projection。
- `install/routing_contract.py` 定義 provider-neutral routing context；dispatch
  與 role-fitness receipt 會記錄 candidate、snapshot、complexity、escalation
  reason、permission profile 與 claim fingerprint，並拒絕和觀測 binding
  不一致的 receipt。
- `platform_halt` 會落在 `capability_gap` failure class，不會被當成品質通過
  或一般 `INCONCLUSIVE`；即使 child 尚未產生，也保留 requested candidate
  與 snapshot。
- `install/benchmark_role_fitness.py` 從 canonical role TOML 讀取 expected
  bindings，避免 benchmark 與 manifest 分離。
- orchestration default prompt 改為 capability-first；`plan-verifier` 的
  completed Sol/high gate、七個 production role binding 與 computer-use 新 role
  均維持不變。

離線測試已覆蓋上述 contract；Phase 2 matched live cohort、平台資格確認與
production promotion 尚未執行。

### Paid pilot density guard

考量 Astra 約為 Luna 20x、Sol 2.5x 的直接成本，Phase 2 的 live runner
改為低密度、可停止的 matched smoke pilot：預設 6 trials，取 routine 與
judgment 各 1 case，兩者都跑 Luna/Terra/Sol。只有 `6/12/18/24/30/36`
這些保持 cohort 平衡的數量可執行；36 仍是完整 evidence cohort，低密度
結果不能送入要求 36 份 verdict 的 review ingestion 或 promotion gate。
這個 guard 先套用既有 v1 baseline runner；Astra candidate cohort 仍須依
Phase 2 的 provider eligibility 與 matched protocol 另行啟動，不會被此路徑
自動帶入。

runner 同時接受 `--max-cost-usd`（預設 `$1.00`），在付費請求前做
parent-plus-child planning estimate，每完成一個 trial 重新累計 native cost，
超過 cap 就寫入安全 checkpoint 並停止。這是本地 circuit breaker，不能取代
provider billing limit。

Benchmark content cases now give the typed child a bounded 120-second wait in the
isolated native-v2 compatibility home. The generic dispatch verifier remains on
its 30-second contract; only the benchmark prompt and evidence parser opt into
the longer window.

### Paid pilot result (2026-09-09)

已完成 `artifacts/usage-routing/live-20260909-v10.json` 的 6-trial matched
smoke（routine-01 與 judgment-01，各跑 Luna/Terra/Sol）。6/6 trial 取得
`NATIVE_OK` typed dispatch evidence，native observed cost 為 `$0.59352`，低於
`$10.00` cap；deterministic artifact acceptance 為 2/6，兩個通過均為 Luna，
Terra 與 Sol 各 0/2。此結果只作 baseline directional signal，不能送入要求
36 份 verdict 的 review ingestion，也不足以支持 Astra role promotion。
本次 global install 僅啟用已驗證的 Pilotfish runtime／policy 更新，不改動
Astra candidate binding、completed 的 `plan-verifier` Sol/high gate 或四個
Luna baseline role。

四筆未通過都落在 `acceptance_command_failed`，且四筆 model wall time 為
42.70–56.91 秒，與原本 30 秒 child wait 上限一致。此 slice 已將等待上限
改為 benchmark-only 120 秒並加入 delayed-child regression；需下一個已授權的
低密度 live cohort 重新確認 artifact acceptance，未重跑前不宣稱已修復 live
品質結果。

---

## Files

- `docs/plans/astra-plan-v2.md` — 本文件。
- `docs/plans/astra-plan-merged.md`、`astra-plan-codex.md`、`astra-plan-claude.md`
  — 前置企劃，由本文件取代。
- `docs/plans/pilotfish-codex-multi-shell-adapters.md` — 跨 runtime adapter 邊界。
- `docs/specs/automatic-sol-escalation/SPEC.md` — §F1 來源。
- `docs/specs/role-fitness-benchmark/SPEC.md` — benchmark 原則與 quota。
- `install/benchmark_routing.py` — §F2，實際價格、272K surcharge 與低密度
  paid-pilot guard。
- `install/benchmark_role_fitness.py:29-35` — §F3，role 綁定表。
- `install/validate_agents.py:25` — effort 白名單。
- `install/evaluate_dispatch.py`、`install/verify_dispatch.py` — dispatch evaluator。
- `templates/agents/*.toml` — 七 role contract，Phase 0 前不變。

## Decision Record

- **Decision:** `security-reviewer` 為第一順位，但論據改用 cross-file code
  review 與 SRE-Bench，不使用 ExploitBench。
  - **Reason:** ExploitBench 所測能力在公開版 API 被前置 classifier 攔截（§E1），
    是 model capability 而非 API-accessible capability。
- **Decision:** `verifier` 升為第二順位（原本被兩份前置企劃排在 `plan-verifier`
  之後）。
  - **Reason:** scope violation 0% vs Sol 48%、honeypot cheating 0% vs 48.2%，
    直接對應該 role「不作弊的獨立驗證」的存在理由。
- **Decision:** `plan-verifier` 明確不換，推翻兩份前置企劃的第一順位判斷。
  - **Reason:** 純推理性價比 0.57，且受 completed spec 的 fail-closed 綁定約束。
- **Decision:** `security-executor` 暫緩，新增技術理由。
  - **Reason:** 公開版拒絕 PoC exploit 形狀，abuse-case regression 核心工作
    被攔截（§E1）；加上 monitorability 退步（§E3）。
- **Decision:** 成本模型必須加入 token 效率因子，不只修價格。
  - **Reason:** Astra 標價 2.5x 但 coding 任務每任務成本約 1.0x（§B2）；
    只有單價的模型會做出系統性錯誤的 routing 決策。
- **Decision:** Astra 的 effort 一律建議 `high`，不用 `xhigh` / `max`。
  - **Reason:** §B3 的邊際曲線——`max` 是 `low` 的 2.3x 成本只換 6 分；
    `xhigh`→`max` 每分要價 $0.72。
- **Decision:** 本文件維持 `draft`，直到 Phase 2 matched cohort 完成。

## Sources

### 官方

- [GPT-6 Astra Model | OpenAI API](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Model guidance | OpenAI API](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra)
- [Safety overview: GPT-6 Astra | OpenAI](https://openai.com/index/safety-overview-gpt-6-astra/)
- [GPT-6 Astra System Card | OpenAI Deployment Safety Hub](https://deploymentsafety.openai.com/gpt-6-astra)

### Benchmark 分析

- [Benchmarking GPT-6 Astra | Artificial Analysis](https://artificialanalysis.ai/articles/benchmarking-gpt-6-astra)
- [GPT-6 Astra (xhigh) | Artificial Analysis](https://artificialanalysis.ai/models/gpt-6-astra-xhigh)
- [GPT-6 Astra Benchmarks Explained | Vellum](https://www.vellum.ai/blog/gpt-6-astra-benchmarks-explained)
- [GPT-6 Astra: Features, Benchmarks, and Pricing | DataCamp](https://www.datacamp.com/blog/gpt-6-astra)
- [OpenAI launches GPT-6 Astra | The New Stack](https://thenewstack.io/openai-gpt6-astra-benchmarks/)
- [GPT-6 Astra's Computer Use Skills | MindStudio](https://www.mindstudio.ai/blog/gpt-6-astra-computer-use-agentic)

### 實戰回報

- [GPT-6 Astra: What We Learned Previewing OpenAI's New Model in Production | Kilo](https://blog.kilo.ai/p/gpt-6-astra-what-we-learned-previewing)
- [GPT-6 Astra review: code review gains, privacy, and cost | CodeRabbit](https://www.coderabbit.ai/blog/gpt-6-astra-code-review-evaluation)
- [GPT-6 Astra Review — Hacking Hardware, Building 3D Games | How I AI](https://www.chatprd.ai/how-i-ai/gpt-6-astra-review-hardware-3d-games-and-coding)
- [GPT-6 Astra Burned 30% of My Weekly Limit on One Simple Coding Task](https://bilimgram.medium.com/gpt-6-astra-burned-30-of-my-weekly-limit-on-one-simple-coding-task-e229bec92d08)

### 資安限制

- [GPT-6 Astra Review: We Tested What It Refuses | StationX](https://app.stationx.net/articles/gpt-6-astra-security)
- [GPT-6 Astra Scores 100% on ExploitBench as OpenAI Blocks PoC Exploit Requests | The Hacker News](https://thehackernews.com/2026/09/gpt-6-astra-scores-100-on-exploitbench.html)
- [OpenAI launches GPT-6 Astra, its first model to cross a critical cybersecurity threshold | CSO Online](https://www.csoonline.com/article/4218679/openai-launches-gpt-6-astra-its-first-model-to-cross-a-critical-cybersecurity-threshold.html)

### Effort 與 Codex CLI

- [GPT-6 Astra Reasoning Effort: max Costs 2.3x low for the Same Answers | DEV](https://dev.to/synthorai/gpt-6-astra-reasoning-effort-max-costs-23x-low-for-the-same-answers-5bjh)
- [Moving From GPT-5.6 Sol to GPT-6 Astra: Set It to Medium and Walk Away](https://ilikekillnerds.com/2026/09/06/gpt-5-6-sol-to-gpt-6-astra-reasoning-effort/)
- [GPT-6 Astra Arrives: Configuring OpenAI's Most Capable Model in Codex CLI](https://codex.danielvaughan.com/2026/09/03/gpt-6-astra-codex-cli-configuration-context-notes-safety/)
- [GPT-6 Astra Codex Usage Limits: Quota, Plus vs Pro & Resets](https://www.codexusage.dev/limits/astra)
- [openai/codex#43222 — Astra weekly quota depletion vs local telemetry](https://github.com/openai/codex/issues/43222)

### 定價

- [GPT-5.6 Pricing: Sol, Terra, Luna](https://www.layer3labs.io/guides/gpt-5-6-pricing)
