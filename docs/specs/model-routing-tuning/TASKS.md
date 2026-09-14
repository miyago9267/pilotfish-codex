# TASKS — Model Routing Tuning

- [x] Merge `miyago9267/pilotfish-codex#9` with its exact current head.
- [x] Close PR #7 and #8 as superseded after #9 is merged. GitHub marked them
      merged because their heads are included in #9.
- [x] Set the root default to Luna/medium and planning escalation to Luna/xhigh.
- [x] Route general plan/outcome review through Terra/xhigh (superseded by the
      live v6 usage result).
- [x] Cap security reviewer/executor effort at Sol/high.
- [x] Preserve mechanical role bindings and Nanako's orchestration policy.
- [x] Add or update focused tests for every changed binding and upgrade path.
- [x] Run the planned verification commands and update `PROGRESS.md`.
- [x] Remove Terra from role bindings; use Luna/xhigh for outcome verification.
- [x] Bind the existing risk-triggered Plan review to Sol/high without changing
      the Nanako-designed escalation timing.
- [x] Establish the approved Codex `>=0.147.0` compatibility floor (later
      releases accepted): update
      the validator, installer, stage helper, verifier, fixtures, and tests.
- [x] Fail closed for stale, malformed, unowned, extra-key, or conflicting V2
      config; make dry-run list every target and transaction-artifact path
      before any home write.
- [x] Update README, the install runbook, and design rationale to make the
      native `[agents]` concurrency contract and `>=0.147.0` compatibility
      floor explicit.
- [x] Run the protected installer against the active Codex home after its
      0.147 dry-run identifies only owned routing changes.
- [x] Resolve the stale active install state with explicit operator approval;
      preserve original-byte evidence and never infer ownership.
