# Self-Improvement Drafts v0.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first safe v0.4 E3 slice: code-change draft proposals and approval-scope audit records without mutating source code or creating branches.

**Architecture:** Add `src/kanban_warden/self_improvement.py` for E3 proposal drafting. Reuse existing improvement signal/proposal/approval/audit persistence, and store E3 draft metadata inside proposal `patch` as inert planning data, not executable file patches.

**Tech Stack:** Python 3.10+, SQLite-backed state store, pytest, ruff, mypy.

---

### Task 1: Generate E3 Code-Change Drafts

**Files:**
- Create: `src/kanban_warden/self_improvement.py`
- Test: `tests/test_self_improvement.py`

- [x] Write RED test that a `policy_gap` E3 signal creates a `code_change` E3 proposal with affected files, branch name, verification commands, and no source mutation.
- [x] Implement deterministic draft proposal generation from recent improvement signals.
- [x] Record `proposal_created` audit with E3 metadata.

### Task 2: Approval Scope Audit

**Files:**
- Modify: `src/kanban_warden/self_improvement.py`
- Test: `tests/test_self_improvement.py`

- [x] Write RED test that E3 approval records allowed repository, branch prefix, and verification commands in audit payload.
- [x] Implement `record_code_change_approval()` without creating branches or editing files.
- [x] Reject approval for non-E3/non-code-change proposals.

### Task 3: Verification and PR

- [x] Run `uv run ruff check .`.
- [x] Run `uv run mypy src`.
- [x] Run `uv run pytest`.
- [x] Run `git diff --check`.
- [x] Commit, push, open PR, and merge if checks allow.
