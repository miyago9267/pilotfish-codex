# core

host 中立的來源，供 `tools/render.py` 產生各 host 的輸出。

- `roles.toml`：canonical role catalog。每個 role 標 `access`
  （read-only / write / verify）、`tier`（fast / standard / strong /
  frontier）與 `security`。不寫任何 model 名稱。
- tier 到 model / effort 的對應、description、工具限制放在
  `hosts/<host>/binding.toml`。
- host 專屬 role（例如 Claude 的 `Explore`、Codex 的 `sol-executor`）
  放在該 host 的 binding，不進 core。
- `mech-executor` 是 `fast` tier：Codex binding 的 fast 與 standard
  對應不同 model，`mech-executor` 與 `executor` 因此分開；Claude binding
  的 fast 與 standard 對應同一個 model，所以 Claude 的輸出不受影響。
- `security_avoid_frontier` 由各 host binding 自行決定：Claude 設 true
  （frontier model 的分類器會誤拒防禦性資安工作），Codex 設 false。

policy 文字目前還在各 host 底下（例如 `hosts/claude/src/`），不在 core。
原因是 claude 和 codex 的 policy 已經分岔，先搬家並用 golden test
證明行為不變；要到 P5 才合併成 host 中立的 `core/policy/`。

## 各 host 的 role 子集與 effort

- host 沒有的 role 要在 binding 用 `omitted_roles = [...]` 明列
  （例如 opencode 沒有 `mech-executor`、`plan-verifier`）。
  驗證規則：`roles.toml` 的每個 role，binding 要嘛有
  `[roles.<name>]`，要嘛列在 `omitted_roles`；兩者不可同時出現。
- host 不支援 effort 時（agy），binding 設 `supports_effort = false`；
  render 不輸出 effort 欄位，role 也不可設 effort。

## 產出物不做 Markdown lint

`hosts/*/src`、`hosts/*/dist`、`tests/golden` 裡的 Markdown 是從各 host
原始 repo 逐位元組搬來的文字與其 render 產出，必須和來源一致，
因此排除在 `lint:md` 之外；Codex 的 dist（`templates/`）維持原本的 lint。
