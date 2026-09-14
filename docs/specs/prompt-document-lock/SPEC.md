---
title: Prompt and document lock
status: complete
created: 2026-09-14
updated: 2026-09-14
---

<!-- markdownlint-disable MD025 -->

# Prompt and document lock

## Goal

Keep future changes to agent prompts, role descriptions, and orchestration
policy text small, reviewable, and semantically anchored.

## Scope

- Protect the runtime prompt surfaces under `templates/`, `plugin/`, and the
  install prompt.
- Enforce per-surface change budgets against the Git base revision.
- Require stable behavior anchors and exact synchronization of duplicated
  policy files.
- Run the lock in local validation and the Python CI workflow.

General README and historical report prose remains outside the lock.

## Decisions

- The lock is a repository contract, not a runtime permission switch.
- A first lock introduction may establish the baseline while the manifest is
  absent from the base revision; later changes use the declared budgets.
- The lock manifest is immutable during normal changes. Intentional policy
  renewal requires the explicit `--allow-lock-update` validator mode and human
  review.
- Any protected prompt or description change requires a `VERSION` update before
  the global installation is reconciled.
- Budgets measure both changed lines and changed characters. Absolute file-size
  limits and required fragments provide a second boundary when a Git base is
  unavailable.
- `templates/agents-md.orchestration.md` and the packaged policy reference must
  remain byte-identical.

## Contract

The validator must fail when any protected surface is missing, exceeds its
absolute size limit, loses a required fragment, exceeds its base diff budget,
or diverges from its declared mirror. It must report the surface and metric
that caused the failure without printing prompt contents.

## Tasks

- [x] Add the lock manifest and validator.
- [x] Add regression tests for pass, budget failure, manifest drift, and mirror
  drift.
- [x] Add the validator to the Python CI workflow and documentation.
- [x] Verify the complete suite and record the milestone.

## Files

- `docs/specs/prompt-document-lock/LOCK.json`
- `install/validate_prompt_lock.py`
- `tests/test_prompt_document_lock.py`
- `.github/workflows/python-tests.yml`

## Stop condition

The lock is complete when the validator passes for the current rc.4 sources,
rejects an oversized protected-surface diff in tests, and runs in CI for pull
requests and pushes.

## Local verification

```text
python install/validate_prompt_lock.py --base-ref HEAD
python -m unittest tests.test_prompt_document_lock -v
```

The current rc.4 sources pass the lock with 15 protected surfaces. The full
offline suite passes with 424 tests and 1 skipped; Markdown lint, Python syntax,
native agent validation, hook self-test, mirror comparison, and `git diff
--check` also pass.
