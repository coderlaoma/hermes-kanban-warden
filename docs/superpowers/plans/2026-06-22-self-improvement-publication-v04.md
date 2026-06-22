# Self-Improvement Publication v0.4 Implementation Plan

**Goal:** Add the next safe E3 slice: record externally produced branch and PR publication metadata after human review approval, without creating branches, opening PRs, pushing, deploying, or mutating source files.

**Architecture:** Extend `SelfImprovementEngine` with publication recording. The method accepts branch and PR links created elsewhere, validates the branch name against the prepared package, requires an approved human review, and writes immutable `branch_pushed` and `mr_created` audit events.

**Tech Stack:** Python 3.10+, SQLite-backed state store, pytest, ruff, mypy.

---

### Task 1: Publication Audit

**Files:**
- Modify: `src/kanban_warden/self_improvement.py`
- Test: `tests/test_self_improvement.py`

- [x] Write RED test that publication records `branch_pushed` and `mr_created`.
- [x] Implement `record_code_change_publication()` as audit-only metadata.
- [x] Preserve publication links without creating external resources.

### Task 2: Publication Guardrails

**Files:**
- Modify: `src/kanban_warden/self_improvement.py`
- Test: `tests/test_self_improvement.py`

- [x] Write RED test that publication requires approved human review.
- [x] Write RED test that branch name must match the prepared package.
- [x] Write RED test that pull request URL is required.

### Task 3: Verification and PR

- [x] Run `uv run ruff check .`.
- [x] Run `uv run mypy src`.
- [x] Run `uv run pytest`.
- [x] Run `git diff --check`.
- [x] Commit, push, open PR, and merge if checks allow.
