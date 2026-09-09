# Usage-routing benchmark v1

`manifest.json` is the versioned, offline corpus for the usage-first routing
pilot. It contains six `routine` cases routed to `mech-executor` and six
`judgment` cases routed to `executor`; every case and fixture is hash-bound.

The harness is offline by default:

```sh
python3 install/benchmark_routing.py --dry-run
```

Live execution requires both `--yes` and `--benchmark-yes`; it is refused in CI.
An explicit owner-only `--auth-source` is required. The default is a six-trial
matched smoke cohort: one `routine` case and one `judgment` case, each run with
Luna, Terra, and Sol. Larger runs must use one of these balanced sizes:
`6, 12, 18, 24, 30, 36`; 36 remains the full evidence cohort and the maximum. A
`--max-cost-usd` cap defaults to `$1.00`: the harness estimates parent-plus-child
spend before starting and stops after a completed trial if observed native cost
crosses the cap. This is a local circuit breaker, not a provider billing limit.
Content-bearing benchmark children use a 120-second wait only in the isolated
native-v2 compatibility home. The generic dispatch verifier keeps its 30-second
contract; the longer value is passed explicitly by the benchmark path.
Sparse smoke reports are not eligible for `ingest_review_report`, which still
requires all 36 verdict packets. Raw Codex stdout, stderr, and session JSONL
are never benchmark artifacts. The primary metric is priced from the exact
native parent and child rollout ledgers after auth is removed; CodexBar is an
optional cross-check in a separate credential-free analysis home. A
force-killed process may leave operating-system residuals until the next
known-run cleanup; no credentials are intentionally retained.

This v1 runner deliberately remains the Luna/Terra/Sol baseline. Astra role
candidate cohorts are still offline-only until platform eligibility and the
matched Phase 2 protocol are separately approved.
Production `scout` and `mech-executor` are baseline-only Luna roles. Work that
exceeds either role's boundary must move to `executor` or `verifier`; it must not
upgrade the mechanical child in place.

## Pilot result

The completed v6 cohort has 36 trials. Its post-hoc recommendation is `L→S`
without a Terra tier: Luna passed all 12 deterministic artifact contracts,
whereas Terra passed 10 and Sol passed 5. The candidate aggregates were:

| Candidate | Equivalent cost / 12 | Median wall time |
| --- | ---: | ---: |
| Luna | `$0.743874` | `28.55s` |
| Terra | `$1.363531` | `41.09s` |
| Sol | `$2.931608` | `40.76s` |

The metric is a native-rollout proxy for a versioned artifact task, not a
general intelligence measurement. It supports Luna as default and Sol only for
the existing risk-triggered Plan-review boundary.

### Bar charts

![Weighted token usage per 12-trial cohort](../../assets/v6-weighted-tokens.svg)

![Equivalent cost per 12-trial cohort](../../assets/v6-equivalent-cost.svg)

![Median wall time per candidate](../../assets/v6-median-wall-time.svg)

The charts are generated from the checked-in aggregate summary with Rough.js:

```bash
bun run charts:usage-routing
```

Rough.js is used at generation time only. README pages consume static SVG
assets and do not need a browser-side chart runtime.

The chart-safe aggregate data is checked in as
[`live-v6-summary.json`](./live-v6-summary.json). It deliberately excludes raw
rollouts, prompts, session IDs, and credentials.
