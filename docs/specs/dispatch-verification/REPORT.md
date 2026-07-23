# Dispatch Verification Gap Assessment

> Historical adapter assessment. The current native boundary is tracked in
> `codex-native-multi-agent-migration` and requires a later `NATIVE_OK` smoke.

- Date: 2026-07-20
- Scope: MultiAgentV2 named-role dispatch evidence
- Related discussion: [#2 — Does role-based model dispatch actually fire?](https://github.com/miyago9267/pilotfish-codex/discussions/2)
- Status: Local evidence-expansion implementation completed; upstream blockers remain

## 1. Executive result

### Current claim

- **Proven:** static role packaging, redacted receipts, and explicit adapter
  binding for all seven packaged roles.
- **Partially proven:** terminal-shaped lifecycle events and task-class scoring
  with synthetic decisions.
- **Not proven:** native adapter-free routing, terminal success/failure
  semantics, runtime hard enforcement, hidden capability application, or live
  task-class behavior.

### Evidence scorecard

| Evidence area | Result | Coverage |
| --- | --- | ---: |
| Offline test suite | Passed | 126/126 (100%) |
| Adapter live binding matrix | Passed | 7/7 roles (100%) |
| Single-role redacted receipt | Passed | 1/1 (`ADAPTER_OK`) |
| Native live proof | Not available | `NATIVE_OK`: 0 |
| Terminal semantic checks | Not enabled | 0/1 (0%); schema gate only |
| Redacted receipt generation | Implemented and observed | 9 live receipts |
| Task-class corpus/scorer | Passed offline | 9/9 cases (100%) |
| Task-class live behavior | Not run | 0 cases |
| Disconnect/restart lifecycle scenarios | Not implemented | 0/2 targeted scenarios |

## 2. Proven evidence

### Fresh live adapter proof — 2026-07-20

```text
ADAPTER_OK reason=verified_distinct_model
parent_thread_id=019f7d50-e3c0-7ee2-bb51-a869bc67ccbe
child_thread_id=019f7d50-ffd8-7b72-87f4-7e79ae1a7f76
parent_model=gpt-5.6-terra
child_model=gpt-5.6-luna
```

The verifier proved this exact chain:

- parent model: `gpt-5.6-terra`;
- typed namespace: `agents.spawn_agent`;
- requested role: `agent_type=scout`;
- bounded fork: `fork_turns=none`;
- one unique spawn `call_id`;
- one correlated `sub_agent_activity.agent_thread_id`;
- child `session_meta.id` matches the correlated child ID;
- child `session_meta.parent_thread_id` matches the parent ID;
- child model: `gpt-5.6-luna`;
- child effort: `low`;
- child model differs from the parent model.

### Seven-role matrix — 2026-07-20

- Command: `python3 install/verify_dispatch.py --live --yes --all-roles
  --matrix-yes`.
- Result: `ADAPTER_OK reason=matrix_verified_all_roles`.
- Roles attempted: `7`.
- Roles passed: `7`.
- Roles skipped after a failure: `0`.
- Per-role receipts: `7`.
- Matrix manifest: `dispatch-receipt-matrix/v1`.
- This proves explicit model/effort binding for each role; it does not prove
  automatic selection or hidden capability application.

### Offline verification

- Full test suite: `126 tests`, `OK`.
- Task-class scorer: `9/9` synthetic cases, role-selection accuracy `1.0`,
  abstention accuracy `1.0`.
- Static validation covers:
  - role TOML schema and required keys;
  - role name and filename consistency;
  - model and reasoning-effort enums;
  - sandbox and web-search enums;
  - seven-role routing map;
  - leaf-role and policy contracts;
  - adapter config and concurrency boundaries.
- Evidence parser tests cover:
  - malformed and non-object events;
  - missing, duplicate, or conflicting evidence;
  - namespace and role mismatches;
  - parent/child relationship mismatches;
  - model, effort, and `service_tier` mismatches;
  - exact rollout lookup and path boundaries;
  - native-probe skip behavior.

### Native boundary

- Live native result: `SKIPPED`.
- Reason: `native_schema_introspection_unavailable`.
- `NATIVE_OK` in offline tests is a synthetic parser fixture.
- No live native child was created or verified.

## 3. What the evidence does not prove

### 3.1 Runtime fallback and hard enforcement — Critical

- The policy requires typed dispatch and fail-closed behavior.
- There is no runtime guard that can reliably block an invalid spawn before
  execution.
- There is no persistent run-state receipt for:
  - delegation capability unavailable;
  - requested role plan not executed;
  - effective executor is the parent;
  - headless or unsupported reason;
  - inherited parent-model fallback prevented.
- Missing spawn evidence can become generic `rollout_evidence_invalid` instead
  of a distinct capability-unavailable result.
- The verifier is post-hoc evidence validation, not a pre-execution blocker.

**Local patch can solve:**

- structured `delegation_unavailable` status;
- `requested_role_not_executed` status;
- `effective_executor=parent` receipt;
- explicit fallback reason codes;
- clearer distinction between unsupported capability and damaged evidence.

**Local patch cannot solve:**

- a reliable pre-execution hard block while the current Codex hook surface
  cannot cancel the spawn call;
- upstream runtime enforcement without a stable dispatch hook.

### 3.2 Native adapter-free routing — Critical / upstream-dependent

- The native command shape is implemented.
- The live native path exits before execution because native schema introspection
  is unavailable.
- `NATIVE_OK` is unreachable from the real native caller today.
- Adapter removal cannot be justified from the current evidence.

**Local patch can solve:**

- native command preparation;
- parser and fixture coverage;
- automatic migration once the required upstream metadata exists.

**Local patch cannot solve:**

- proof that Codex exposes native `agent_type` support;
- proof of the effective native child binding;
- adapter removal before Codex exposes a supported schema and metadata surface.

### 3.3 Complete child execution outcome — High

Current proof checks only routing metadata:

- child identity;
- parent-child relation;
- child model;
- child effort.

Current proof does not check:

- child completion event;
- terminal success or failure;
- child response `READY`;
- child error or cancellation;
- successful child closure;
- parent behavior after child failure.

**Local patch can solve:**

- terminal event parsing;
- required success status;
- expected result validation;
- terminal status and result digest in `Verdict`;
- completion evidence in the receipt.

**Dependency:** rollout events must expose stable lifecycle fields. Otherwise,
this part also needs upstream event support.

### 3.4 Runtime role loading and capability application — High

Static checks prove that the installed `scout.toml` matches the packaged role.
They do not prove that runtime resolution applied:

- sandbox mode;
- developer instructions;
- capability fields;
- authoritative effective role identity.

The child rollout currently exposes model and effort, not a complete resolved
role snapshot.

**Local patch can solve:**

- role/config hashes in the evidence receipt;
- a parameterized probe for each installed role;
- explicit behavioral checks where a capability is externally observable.

**Local patch cannot fully solve:**

- hidden runtime fields without child metadata or observable behavior;
- authoritative effective-role identity without upstream metadata.

### 3.5 Live role coverage — Medium

- Live mechanism proof currently covers `scout` only.
- Live proof coverage is therefore `1/7` roles, or `14.3%`.
- The result must not be generalized to:
  - `plan-verifier`;
  - `security-reviewer`;
  - `mech-executor`;
  - `executor`;
  - `verifier`;
  - `security-executor`.

**Local patch can solve:**

- parameterize the probe by role;
- run a bounded seven-role explicit-dispatch matrix;
- publish per-role verdicts.

**Remaining boundary:** explicit proof for all roles still does not prove that an
orchestrator selects the right role for arbitrary tasks.

### 3.6 Task-class role selection — Medium / claim-dependent

No evaluation currently exists for:

- labeled task corpus;
- expected role per task class;
- selection accuracy;
- delegation abstention accuracy;
- orchestrator selection rationale;
- realistic automatic-selection E2E.

**Local patch can solve:**

- corpus and label format;
- evaluator and scoring;
- rationale receipt;
- selection and abstention reports.

**Boundary:** this evaluates orchestrator behavior; it does not create a hard
runtime guarantee. It is required only if the project claims automatic
 task-class routing correctness.

### 3.7 Lifecycle resilience and portable evidence — Medium

Not covered:

- parent disconnect while child continues;
- restart/resume child identity recovery;
- portable evidence bundle;
- Codex version fingerprint in the CLI verdict;
- role/config hash in the CLI verdict;
- automatic archival of parent and child rollout files;
- terminal status in the persisted receipt.

**Local patch can solve:**

- a receipt containing version, config hash, role hash, timestamps, IDs, event
  references, verdict, and terminal status;
- lifecycle test scenarios when stable lifecycle events are available.

**Upstream dependency:** parent disconnect and resume semantics may require
Codex lifecycle support.

## 4. Patchability summary

| Gap | Local patch | Upstream support | Priority |
| --- | --- | --- | --- |
| Fallback status and receipt | Yes | Hard block still required | P0 |
| Native schema proof | Preparation only | Required for `NATIVE_OK` | P0 |
| Terminal execution outcome | Yes, if events exist | Event fields may be required | P1 |
| Portable evidence bundle | Yes | No | P1 |
| Runtime capability application | Partial | Effective-role metadata | P1 |
| Seven-role explicit matrix | Yes | No | P2 |
| Task-class evaluation | Yes | No | P2 |
| Disconnect/resume proof | Partial | Lifecycle semantics may be required | P2 |

## 5. Recommended implementation order

1. Add explicit capability and fallback receipts.
2. Distinguish unsupported dispatch from damaged rollout evidence.
3. Add terminal child outcome checks.
4. Add portable evidence bundles with version and configuration fingerprints.
5. Parameterize explicit probes across all seven roles if role-wide coverage is
   required.
6. Revisit native proof only after Codex exposes safe adapter-free schema and
   effective child metadata.
7. Build task-class evaluation only if automatic role-selection correctness
   becomes a product claim.

## 6. Discussion reply draft

> Thanks for the detailed review. We can currently prove:
>
> - static role/config packaging;
> - one live adapter-based `scout` dispatch;
> - typed spawn arguments;
> - exact parent/spawn/child correlation;
> - parent-child identity;
> - child model/effort matching the installed binding;
> - fail-closed handling for malformed or mismatched evidence.
>
> We cannot currently prove:
>
> - adapter-free native routing (`NATIVE_OK`);
> - a pre-execution runtime guard or persistent unsupported/headless receipt;
> - the child's complete terminal outcome;
> - full runtime application of every role capability;
> - live binding for all seven roles;
> - task-class role selection.
>
> Local patches can add fallback receipts, terminal-event checks, portable
> evidence bundles, seven-role probes, and a task-class evaluation harness.
> Native schema introspection, authoritative effective-role metadata, and hard
> runtime blocking depend on upstream Codex support. We will keep the claims
> limited to the evidence that is actually available.

## 7. Terminal schema discovery result

Two fresh same-version adapter probes were run on 2026-07-20. Redacted
structural inspection found:

- parent and child each emit `event_msg` with `type=task_started`;
- parent and child each end with `event_msg` with `type=task_complete`;
- final assistant messages are `response_item` with `type=message` and
  `content` containing `output_text`;
- parent spawn correlation remains `call_id` to
  `sub_agent_activity.agent_thread_id`;
- no explicit terminal status enum, cancellation state, or error-state contract
  was exposed in these successful runs.

This is enough to record observed completion-shaped events, but not enough to
claim terminal success/failure semantics. Terminal parsing remains gated until
failure, cancellation, and close behavior are observed with stable fields.

## 8. Selected implementation scope

The approved follow-up includes all locally feasible layers:

- redacted receipts and precise post-hoc observation states;
- explicit seven-role binding matrix;
- terminal proof only after a two-run schema discovery gate;
- task-class selection and abstention evaluation;
- regression tests, documentation, and portable evidence artifacts.

The following remain explicit upstream blockers:

- native adapter-free `NATIVE_OK` proof;
- cancellable pre-execution hard blocking;
- authoritative hidden effective-role and capability metadata;
- lifecycle guarantees not present in stable rollout events.

## 9. Final conclusion

- The adapter explicit `scout` mechanism is proven.
- The broader named-role system is not fully proven.
- The most valuable local work is:
  1. fallback observability;
  2. terminal execution evidence;
  3. portable receipts.
- Native routing and hard enforcement remain upstream-dependent.
- Task-class selection is an optional behavioral evaluation, not a current
  mechanism-proof requirement.
