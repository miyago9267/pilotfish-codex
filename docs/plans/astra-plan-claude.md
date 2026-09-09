---
id: plan-astra-claude
title: GPT-6 Astra 導入 Pilotfish Claude Role 企劃
status: draft
created: 2026-09-08
updated: 2026-09-08
author: Miyago
approved_by:
tags: [pilotfish, astra, claude-code, role-routing, benchmark]
priority: high
---

<!-- markdownlint-disable MD013 MD025 MD029 -->

# GPT-6 Astra 導入 Pilotfish Claude Role 企劃

## Goal

驗證 GPT-6 Astra 是否能改善 Claude Code / Pilotfish 在高不確定性、高風險與長流程任務中的判斷品質，並以 provider-neutral evidence 決定是否調整 Claude role routing。

這是一份 Claude adapter 對照企劃。Astra 先作為可替換的 model candidate，不直接新增 role、不取代 approval boundary，也不把 Claude 的 hooks、agents 或 permission semantics 假裝成 Codex 的 TOML contract。

## Current Baseline

Pilotfish 的共通 role 語意為：`scout`、`plan-verifier`、`executor`、`mech-executor`、`security-reviewer`、`security-executor`、`verifier`。

Codex 版本目前以 TOML manifest、typed dispatch、fresh-context verification 與 Waza evidence 驗證這些語意。Claude adapter 應分別映射到 `CLAUDE.md`、Claude agents、hooks、permission settings 與 Claude event/session receipt；兩者共享語意與 schema，保留 runtime-specific implementation。

## Astra Capability Hypothesis

以下均為待驗證假設：

| 能力 | 對 Claude/Pilotfish 的可能價值 | 必須觀察的證據 |
| --- | --- | --- |
| 長 context 與長流程 coherence | 維持跨 repo、長 acceptance flow 與多次 checkpoint 的一致性 | scope drift、遺失 constraint、checkpoint continuation |
| 複雜 reasoning 與 browser/tool use | 改善 architecture、dependency、rollback 與外部工具判斷 | tool trace、Plan quality、reproducible outcome |
| 更強的 intent/scope adherence | 降低不必要的修改、越權與錯誤 delegation | negative cases、permission boundary |
| mid-turn steering 與 dynamic reasoning effort | 需求變更時保留已驗證工作並調整 effort | correction recovery、duplicate action rate |
| 高階 security capability | 增加 threat modeling、prompt injection 與 abuse-case 覆蓋 | read-only findings、security regression |

官方資料標示 Astra 支援 1.05M context、128K max output、`low` 至 `max` reasoning effort，以及 MCP、computer use、hosted shell、apply patch 與 structured outputs。[OpenAI Model 文件](https://developers.openai.com/api/docs/models/gpt-6-astra)

官方也指出 Astra 在長流程、工具協作、instruction following 與 scope adherence 上有所改善；這些是 model-level claims，Claude adapter 仍須用 Pilotfish 的 matched benchmark 驗證。[OpenAI Model Guidance](https://developers.openai.com/api/docs/guides/latest-model)

## Role Strategy

### Strong — 先導入高價值 review seam

1. `plan-verifier`

   讓 Astra 審查 material Plan、跨 agent ownership、dependency、security、rollback 與 acceptance。適合在 Claude primary verdict 與另一份 verdict 出現 fingerprinted disagreement 時，作一次性 semantic adjudicator。

2. `verifier`

   針對跨 repo、browser、deployment、外部 evidence 或長 acceptance flow 使用 Astra；routine outcome verification 維持較低成本 model。

3. `security-reviewer`

   使用 Astra 增加 threat model、prompt-injection 與攻擊路徑分析，但 Claude adapter 仍限制為 read-only，並由 host permission、credential isolation 與外部 action gate 控制權限。

### Worth exploring — 條件式執行

4. `executor`

   只在 cross-module migration、architecture fork 或需要持續工具協作時升級 Astra。清楚且局部的修補留在一般 model。

5. `security-executor`

   只接受 approved、fingerprinted Plan；Astra 可用於複雜修補與 abuse-case regression，但不可自行擴張 scope 或取得新的 credential authority。

### Keep unchanged initially

`scout` 與 `mech-executor` 維持低成本、明確規格優先。Astra 的長 context 不代表應把 full history 傳給這兩個 role。

## Claude Adapter Contract

Claude adapter 不複製 Codex TOML，而是把共通 invocation metadata 放進 provider-neutral receipt：

```yaml
runtime: claude
model_candidate: gpt-6-astra
model_snapshot: recorded-by-adapter
role: plan-verifier
complexity: routine|cross_system|critical
escalation_reason: explicit-risk|disagreement|long-horizon|tool-complexity
permission_profile: read-only|workspace-write|approved-security-write
evidence_budget:
  max_tool_calls: 20
  max_wall_seconds: 600
  context_scope: named-inputs-only
claim_fingerprint: sha256:...
```

Claude adapter 必須保留以下邊界：

- `CLAUDE.md` 負責 runtime instructions，不能授予 host 沒有的權限。
- Claude agent 負責 role behavior，不能自行建立新 delegation policy。
- hooks 只能提供 advisory/event signal，不能偽造 approval 或 verification receipt。
- permission mode、credential access、external action 與 destructive operation 由 host/Orchestrator 維持 authority。
- verifier 必須回傳 `CONFIRMED`、`REFUTED` 或 `INCONCLUSIVE`，不能用較長的模型輸出取代 evidence。

Receipt 需要記錄 `primary_flow`、`claim_relevant_edges`、`external_evidence`、`tool_actions` 與 `inconclusive_reason`。完整 transcript 不作為預設持久化資料。

## Routing Protocol

```text
routine
  -> Claude low-cost role

material risk / long horizon / cross-system
  -> Claude primary role
  -> Astra only when escalation trigger matches

semantic disagreement
  -> fingerprint both verdicts
  -> one Astra adjudicator
  -> deterministic scorer + host disposition

security-sensitive
  -> security-reviewer read-only
  -> human approval
  -> security-executor
  -> fresh verifier
```

Astra 不應成為 unconditional primary。官方安全文件一方面指出 Astra 的安全邊界與 prompt-injection robustness 有改善，另一方面也指出它達到 Critical cybersecurity capability，且部分 adversarial settings 的 monitorability 下降；Claude adapter 因此必須維持 sandbox、permission、multi-layer evidence 與 human gate。[OpenAI Safety Overview](https://openai.com/index/safety-overview-gpt-6-astra/)

## Waza / Cross-Runtime Benchmark

### Cohorts

1. `claude_baseline`：目前 Claude adapter 的既有 model routing。
2. `claude_first_astra_adjudicator`：Claude primary，只有 fingerprinted disagreement 呼叫 Astra。
3. `claude_astra_selective`：只在 cross-system、critical-risk、長流程案例使用 Astra primary。
4. `codex_reference`：使用既有 Codex provider-neutral records 作為語意參照，不要求字面輸出相同。

四組都使用相同 task intent、scope、acceptance、risk category、negative cases 與 deterministic grader。runtime-specific adapter 只負責 invocation、receipt normalization 與 capability gap，不改寫 rubric。

### Acceptance Gates

- 分開報告 route accuracy、Plan quality、mechanical reliability、verification correctness、tool calls、wall time、token usage、task cost 與 `INCONCLUSIVE`。
- 候選先通過 Claude baseline quality floor，再計算 quality-adjusted cost efficiency。
- approval、permission、security、destructive 與 external-action negative cases 的越權行為必須為 `0`。
- Claude event/session receipt 必須能證明正確 role、model、permission profile、claim fingerprint 與 fresh verification。
- provider credential、CLI、MCP 或 hook 不可用時，結果標記 `capability_gap` 或 `inconclusive`，不可計為 parity pass。
- 單次成功案例不改變 routing；需要 matched paired evidence 與可重現的 acceptance result。

## Rollout Phases

### Phase 0 — Adapter contract

- 定義 Claude role-to-agent mapping、hook event mapping、permission profile 與 receipt schema。
- 保持 Codex role manifest 與 Claude runtime 檔案分離。
- 加入 Astra candidate、snapshot、escalation reason 與 capability-gap 狀態。

### Phase 1 — Offline validation

- 驗證 route、role、approval、permission、fresh verification 與 deterministic grader。
- 建立 mock Claude event/session fixture，不把 mock 結果當成真實 model quality。

### Phase 2 — Bounded live cohort

- 執行三個 Claude cohort，並以 Codex reference 做 provider-neutral 對照。
- 優先測試 `plan-verifier`、高風險 `verifier`、`security-reviewer` 與 semantic adjudication。
- 只保存摘要、receipt、artifact reference 與必要 redacted evidence。

### Phase 3 — Promotion decision

- Astra 達到 quality floor 且 task-level cost/time 有優勢，才提出 selective promotion。
- 只改善高複雜案例時，保留 disagreement-gated routing。
- 未達 baseline 時，維持 Claude 現有 routing，不擴大 role scope。

## Risks and Controls

| Risk | Control |
| --- | --- |
| Astra 單價與 Claude tool call 成本失控 | per-task budget、selective trigger、quality-first gate |
| `CLAUDE.md` 或 hook 指令造成 scope 漂移 | instruction audit、named inputs、host permission authority |
| Claude event 與 Codex receipt 語意不一致 | provider-neutral schema、adapter-owned mapping、capability gap |
| 高能力模型執行未核准外部操作 | permission profile、sandbox、human approval、fresh verifier |
| 長 context 帶入不必要的敏感資料 | context digest、redaction、禁止 full history default |
| Astra 產生較完整但不可驗證的答案 | claim fingerprint、deterministic grader、evidence-required verdict |

## Claude Cross-Review Request

Claude 應只審查本企劃，不重新設計整個 Pilotfish。請：

1. 找出最多五個會阻止 Claude adapter 落地的問題。
2. 分開檢查 model claims、role mapping、permission boundary、receipt validity 與 benchmark fairness。
3. 每個問題標記 priority、confidence、evidence、minimum revision 與 acceptance check。
4. 不因 Astra 能力較強而放寬 host approval、sandbox、credential 或 fresh verifier。
5. 只接受可由官方文件、local test、Waza record 或 Claude event evidence 驗證的修改。

回覆格式：

```text
VERDICT: READY|REVISE

Finding:
Evidence:
Minimum revision:
Acceptance check:
```

## Stop Condition

完成 Claude adapter capability check、三個 Claude matched cohorts、provider-neutral receipt 與本文件的 bounded cross-review 後停止。完成前不修改 production routing，也不宣稱 Astra 優於 Claude baseline 或 Luna。

## Related Files

- `docs/plans/astra-plan-codex.md` — Codex 對照版。
- `docs/plans/pilotfish-codex-multi-shell-adapters.md` — 跨 runtime adapter 邊界。
- `templates/agents/*.toml` — Codex 七 role contract；不作為 Claude 檔案格式。
- `install/benchmark_role_fitness.py` — 既有 role-fitness evidence adapter。
- `install/evaluate_dispatch.py` — route、approval、role 與 checkpoint evaluator。
- `docs/specs/role-fitness-benchmark/SPEC.md` — benchmark 原則與 quota。

## Decision Record

- **Decision:** Astra 先作為 Claude adapter 的 selective model candidate，不新增 role。
  - **Reason:** Astra 的預期價值集中在長流程、複雜判斷與 semantic disagreement；routine role 仍以成本與可重複性為主。
- **Decision:** Claude 與 Codex 共享語意與 evidence schema，各自保留 runtime implementation。
  - **Reason:** Claude 的 agents、hooks、permissions 與事件格式不能安全地偽裝成 Codex TOML 或 typed dispatch。
- **Decision:** 本文件維持 `draft`，直到 Claude live evidence 與 bounded cross-review 完成。
  - **Reason:** 目前只有官方能力資料與架構推論，沒有 Astra 在 Claude adapter 上的 direct evidence。
