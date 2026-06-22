# Self-Improvement Review v0.4 Implementation Plan

**Goal:** Add the next safe E3 slice: prepare a human review packet after verification passes, without creating branches, opening PRs, pushing, deploying, or mutating source files.

**Architecture:** Extend `SelfImprovementEngine` with review-packet preparation. The packet combines proposal summary, evidence, package metadata, verification output, approval context, empty external links, and rollback plan. It writes a `human_review_requested` audit record and remains inert planning/review data.

**Tech Stack:** Python 3.10+, SQLite-backed state store, pytest, ruff, mypy.

---

### Task 1: Human Review Packet

**Files:**
- Modify: `src/kanban_warden/self_improvement.py`
- Test: `tests/test_self_improvement.py`

- [x] Write RED test that a passed verification produces a complete human review packet.
- [x] Write RED test that review packet preparation requires passed verification.
- [x] Implement `prepare_human_review_packet()` from existing proposal, signal, approval, package, and verification records.

### Task 2: Review Audit

**Files:**
- Modify: `src/kanban_warden/self_improvement.py`
- Test: `tests/test_self_improvement.py`

- [x] Write `human_review_requested` audit metadata when a packet is prepared.
- [x] Keep review preparation side-effect-free except for audit persistence.
- [x] Leave branch and PR links empty because this slice does not create external resources.

### Task 3: Verification and PR

- [x] Run `uv run ruff check .`.
- [x] Run `uv run mypy src`.
- [x] Run `uv run pytest`.
- [x] Run `git diff --check`.
- [x] Commit, push, open PR, and merge if checks allow.
