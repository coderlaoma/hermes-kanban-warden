# Completed Summary Tail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kanban Warden notifications for the omitted tail of long completed task summaries.

**Architecture:** Reuse the existing `blocked_reason_tail` notification flow in `kanban_warden/actions.py` and `kanban_warden/outbox.py`. The action engine detects long completed summaries and queues a durable outbox row; the outbox drainer renders a concise message with only the omitted tail and can fall back to root/parent subscribers when the completed child has no direct subscriber.

**Tech Stack:** Python 3.10+, SQLite state store, pytest, ruff, mypy.

---

### Task 1: Add Completed Summary Tail Planning

**Files:**
- Modify: `tests/test_actions.py`
- Modify: `kanban_warden/actions.py`
- Modify: `kanban_warden/outbox.py`
- Modify: `README.md`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing tests**

Add tests that create a completed event with a long `summary`, assert a `notify` action with key `completed-tail:default:impl:1`, assert only the tail is sent, assert root-only subscriptions receive child completed tails, and assert short summaries do not notify.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_actions.py::test_long_completed_summary_sends_tail_only_to_native_subscriber tests/test_actions.py::test_short_completed_summary_does_not_duplicate_native_notification -q
```

Expected: the long-summary test fails because no `notify` action or delivery exists yet.

- [ ] **Step 3: Implement minimal production code**

Add `_HERMES_NATIVE_COMPLETED_SUMMARY_CHARS`, `_plan_completed_summary_tail`, and a `completed_summary_tail` outbox renderer.

- [ ] **Step 4: Verify GREEN**

Run the focused pytest command again. Expected: both tests pass.

- [ ] **Step 5: Full verification**

Run:

```bash
python -m pytest
python -m ruff check .
python -m mypy kanban_warden
python -m build
```

Expected: all commands exit 0.
