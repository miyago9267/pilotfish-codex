# PROGRESS — Model Routing Tuning

- Status: Done
- Updated: 2026-08-04

## Phases

- [x] P0. Merge PR #9 and close superseded PR #7/#8. GitHub marked all three
      PRs merged at `8bf61c9073cfb06b346d3b545cdc2641ccc36570`.
- [x] P1. Apply root Luna-medium and Terra/Sol routing decisions.
- [x] P2. Update validators, fixtures, and targeted tests.
- [x] P3. Run verification and report remaining gaps. The 87-test suite,
      validator, Python compilation, Codex config override, changed-file
      Markdown lint, and `git diff --check` pass. Full-repository Markdown lint
      still reports pre-existing `.ai/` violations.
- [x] P4. Run the 36-trial native v6 usage pilot. Luna accepted `12 / 12`; Terra
      accepted `10 / 12`, cost 83.3% more, and had 43.9% higher median wall
      time. Sol accepted `5 / 12` under the artifact contract; this is not an
      intelligence ranking.
- [x] P5. Remove Terra, move outcome verification to Luna/xhigh, and bind the
      existing Nanako risk-triggered Plan review to Sol/high without changing
      its invocation timing.
- [x] P6. Migrate the native routing contract to a `>=0.147.0`
      compatibility floor: use the documented `[agents]` child concurrency
      contract, preserve the Nanako risk trigger, migrate only an exact
      state-owned V2 table, and emit an
      auditable per-path dry-run manifest including transaction artifacts.
- [x] P7. With explicit operator authorization, back up and reconcile the
      stale active install state, then migrate the active Codex home. The
      installer now uses native `[agents]` concurrency, upgrades the canonical security
      reviewer, applies the approved Luna/medium root override, and is
      idempotent on dry-run.
