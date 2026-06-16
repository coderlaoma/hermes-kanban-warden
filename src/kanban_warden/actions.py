"""Notification and auto-advance state machine for Kanban Warden.

The module intentionally keeps business-code concerns out of the plugin. It only
observes Kanban events, plans bounded orchestration actions, and optionally applies
small Kanban state transitions through SQLite when auto-advance is enabled.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .board import BoardEvent
from .config import KanbanWardenConfig
from .state import WardenStateStore

ActionKind = Literal[
    "notify",
    "create_reviewer",
    "comment",
    "unblock",
    "retry",
    "escalate",
]


@dataclass(frozen=True)
class PlannedAction:
    """A dry-run-safe action emitted by the warden state machine."""

    kind: ActionKind
    board_name: str
    task_id: str | None
    idempotency_key: str
    reason: str
    message: str
    target_task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    attempt: int = 0
    max_attempts: int = 0
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionResult:
    action: PlannedAction
    applied: bool
    skipped: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.action.to_dict()
        data.update({"applied": self.applied, "skipped": self.skipped, "note": self.note})
        return data


class KanbanActionEngine:
    """Plan and optionally apply Kanban notification/auto-advance transitions.

    Idempotency is durable in ``WardenStateStore``. Every external effect receives
    a stable key before it is executed so replayed events and process restarts do
    not duplicate reviewer cards, comments, unblock transitions, or notifications.
    """

    def __init__(self, config: KanbanWardenConfig, state_store: WardenStateStore) -> None:
        self.config = config
        self.state_store = state_store

    def plan_for_events(self, events: list[BoardEvent]) -> list[PlannedAction]:
        actions: list[PlannedAction] = []
        for event in events:
            actions.extend(self._plan_event(event))
        return actions

    def plan_for_health(self, findings: list[dict[str, Any]]) -> list[PlannedAction]:
        actions: list[PlannedAction] = []
        planned_recoveries: set[tuple[str, str, str]] = set()
        for finding in findings:
            task_id = _text(finding.get("task_id"))
            board_name = _text(finding.get("board")) or "default"
            kind = _text(finding.get("kind"))
            if not task_id or not kind:
                continue
            if kind in {"running_without_recent_heartbeat", "running_exceeded_task_timeout"}:
                recovery_key = (board_name, task_id, "stale-running")
                if recovery_key in planned_recoveries:
                    continue
                planned_recoveries.add(recovery_key)
                actions.extend(
                    self._bounded_recovery(
                        board_name=board_name,
                        task_id=task_id,
                        recovery_kind="stale-running",
                        notify_reason="stale running task detected",
                        event_key=f"health:{board_name}:{task_id}:{kind}",
                        payload=finding,
                    )
                )
            elif kind in {"long_term_blocked", "review_approved_but_still_blocked", "root_not_closed_after_children_done"}:
                actions.append(
                    self._notify(
                        board_name,
                        task_id,
                        f"health:{board_name}:{task_id}:{kind}:notify",
                        f"health finding: {kind}",
                        payload=finding,
                    )
                )
        return actions

    def apply(self, db_path: str | Path, actions: list[PlannedAction]) -> list[ActionResult]:
        results: list[ActionResult] = []
        for action in actions:
            if action.dry_run or not self.config.auto_advance.enabled:
                results.append(ActionResult(action, applied=False, note="dry-run"))
                continue
            if not self.state_store.mark_action_started(action.idempotency_key):
                results.append(ActionResult(action, applied=False, skipped=True, note="duplicate"))
                continue
            try:
                note = self._apply_one(Path(db_path), action)
            except Exception as exc:  # pragma: no cover - defensive runtime safety
                self.state_store.mark_action_failed(action.idempotency_key, str(exc))
                raise
            self.state_store.mark_action_done(action.idempotency_key, note)
            results.append(ActionResult(action, applied=True, note=note))
        return results

    def _plan_event(self, event: BoardEvent) -> list[PlannedAction]:
        task_id = event.task_id
        if not task_id:
            return []
        actions: list[PlannedAction] = []
        event_key = event.idempotency_key()
        kind = event.kind
        payload = event.payload or {}
        reason = _text(payload.get("reason"))
        outcome = _text(payload.get("outcome")) or _text(payload.get("verdict"))
        status = event.task_status or ""

        if self._should_notify_event(kind, status, reason, outcome):
            actions.append(
                self._notify(
                    event.board_name,
                    task_id,
                    f"{event_key}:notify:{_slug(kind, status, reason, outcome)}",
                    f"kanban event {kind} status={status or 'unknown'}",
                    payload=event.summary(),
                )
            )

        if _is_review_required(event):
            actions.append(
                PlannedAction(
                    kind="create_reviewer",
                    board_name=event.board_name,
                    task_id=task_id,
                    target_task_id=None,
                    idempotency_key=f"reviewer:{event.board_name}:{task_id}",
                    reason="review-required blocked implementation card",
                    message=f"Create/dispatch reviewer for {task_id}",
                    payload={"source_event": event.summary(), "assignee": self.config.auto_advance.reviewer_assignee},
                    max_attempts=self.config.limits.max_retries,
                    dry_run=self.config.auto_advance.dry_run,
                )
            )

        verdict = _review_verdict(event)
        source_task = _review_source_task(event)
        if verdict == "approve" and source_task:
            actions.append(
                self._comment(event.board_name, source_task, f"review-approve:{event.board_name}:{task_id}:{source_task}", f"[warden-review-approved] reviewer {task_id} approved; unblock downstream work.")
            )
            actions.append(
                self._unblock(event.board_name, source_task, f"review-approve-unblock:{event.board_name}:{task_id}:{source_task}", "review approve")
            )
        elif verdict == "needs-changes" and source_task:
            actions.append(
                self._comment(event.board_name, source_task, f"review-needs-changes:{event.board_name}:{task_id}:{source_task}", f"[warden-review-needs-changes] reviewer {task_id} requested changes; implementation card is unblocked for follow-up.")
            )
            actions.append(
                self._unblock(event.board_name, source_task, f"review-needs-changes-unblock:{event.board_name}:{task_id}:{source_task}", "review needs changes")
            )

        if _is_worker_failure(kind, status, reason, outcome):
            actions.extend(
                self._bounded_recovery(
                    board_name=event.board_name,
                    task_id=task_id,
                    recovery_kind="worker-failure",
                    notify_reason="worker crash/protocol violation/gave_up",
                    event_key=event_key,
                    payload=event.summary(),
                )
            )
        return actions

    def _bounded_recovery(
        self,
        *,
        board_name: str,
        task_id: str,
        recovery_kind: str,
        notify_reason: str,
        event_key: str,
        payload: dict[str, Any],
    ) -> list[PlannedAction]:
        attempt = self.state_store.peek_retry(board_name, task_id, recovery_kind) + 1
        if attempt <= self.config.limits.max_retries:
            return [
                PlannedAction(
                    kind="retry",
                    board_name=board_name,
                    task_id=task_id,
                    target_task_id=task_id,
                    idempotency_key=f"{event_key}:retry:{attempt}",
                    reason=notify_reason,
                    message=f"Recover {task_id} from {recovery_kind} attempt {attempt}/{self.config.limits.max_retries}",
                    payload={**payload, "recovery_kind": recovery_kind},
                    attempt=attempt,
                    max_attempts=self.config.limits.max_retries,
                    dry_run=self.config.auto_advance.dry_run,
                )
            ]
        return [
            PlannedAction(
                kind="escalate",
                board_name=board_name,
                task_id=task_id,
                target_task_id=task_id,
                idempotency_key=f"{event_key}:escalate:{recovery_kind}",
                reason=f"retry exhausted for {recovery_kind}",
                message=f"Escalate {task_id}: retry budget exhausted for {recovery_kind}",
                payload={**payload, "recovery_kind": recovery_kind},
                attempt=attempt,
                max_attempts=self.config.limits.max_retries,
                dry_run=self.config.auto_advance.dry_run,
            )
        ]

    def _notify(self, board_name: str, task_id: str, key: str, reason: str, *, payload: dict[str, Any]) -> PlannedAction:
        return PlannedAction(
            kind="notify",
            board_name=board_name,
            task_id=task_id,
            idempotency_key=key,
            reason=reason,
            message=f"Notify subscribers: {reason} task={task_id}",
            payload={"channels": self.config.notifications.channels, **payload},
            dry_run=self.config.auto_advance.dry_run,
        )

    def _comment(self, board_name: str, task_id: str, key: str, message: str) -> PlannedAction:
        return PlannedAction("comment", board_name, task_id, key, "review follow-up", message, task_id, {}, dry_run=self.config.auto_advance.dry_run)

    def _unblock(self, board_name: str, task_id: str, key: str, reason: str) -> PlannedAction:
        return PlannedAction("unblock", board_name, task_id, key, reason, f"Unblock {task_id}: {reason}", task_id, {}, dry_run=self.config.auto_advance.dry_run)

    def _should_notify_event(self, kind: str, status: str, reason: str, outcome: str) -> bool:
        if not self.config.notifications.enabled:
            return False
        if kind in {"created", "claimed", "spawned", "blocked", "completed", "done", "gave_up"}:
            return True
        if status in {"running", "blocked", "done", "completed"}:
            return True
        if "review-required" in reason or outcome in {"approve", "needs-changes"}:
            return True
        return _is_worker_failure(kind, status, reason, outcome)

    def _apply_one(self, db_path: Path, action: PlannedAction) -> str:
        if action.kind == "notify":
            self.state_store.enqueue_notification(action.idempotency_key, action.to_dict())
            return "queued-notification"
        if action.kind == "create_reviewer":
            return self._create_reviewer(db_path, action)
        if action.kind == "comment":
            return self._insert_comment(db_path, action)
        if action.kind in {"unblock", "retry"}:
            self.state_store.bump_retry(action.board_name, action.target_task_id or action.task_id or "", _text(action.payload.get("recovery_kind")) or action.kind)
            return self._unblock_task(db_path, action)
        if action.kind == "escalate":
            self.state_store.enqueue_notification(action.idempotency_key, action.to_dict())
            return self._insert_comment(db_path, action)
        return "noop"

    def _create_reviewer(self, db_path: Path, action: PlannedAction) -> str:
        source_task = action.task_id
        if not source_task:
            return "missing-source-task"
        review_id = f"review_{source_task}"
        now = int(time.time())
        with sqlite3.connect(db_path) as con:
            _insert_reviewer_task(
                con,
                review_id=review_id,
                source_task=source_task,
                reviewer_assignee=self.config.auto_advance.reviewer_assignee,
                idempotency_key=action.idempotency_key,
                now=now,
            )
            if _table_exists(con, "task_links"):
                con.execute(
                    "insert or ignore into task_links(parent_id, child_id) values (?, ?)",
                    (source_task, review_id),
                )
            _insert_event(con, review_id, "created", {"by": "kanban-warden", "source_task": source_task, "idempotency_key": action.idempotency_key}, now)
        return f"reviewer={review_id}"

    def _insert_comment(self, db_path: Path, action: PlannedAction) -> str:
        task_id = action.target_task_id or action.task_id
        if not task_id:
            return "missing-task"
        now = int(time.time())
        with sqlite3.connect(db_path) as con:
            if not _table_exists(con, "task_comments"):
                return "comments-table-missing"
            existing = con.execute(
                "select 1 from task_comments where task_id = ? and body like ? limit 1",
                (task_id, f"%{action.idempotency_key}%"),
            ).fetchone()
            if existing:
                return "comment-exists"
            body = f"{action.message}\n\nwarden-action: {action.idempotency_key}"
            _insert_comment_row(con, task_id=task_id, body=body, now=now)
            _insert_event(con, task_id, "commented", {"by": "kanban-warden", "idempotency_key": action.idempotency_key}, now)
        return "commented"

    def _unblock_task(self, db_path: Path, action: PlannedAction) -> str:
        task_id = action.target_task_id or action.task_id
        if not task_id:
            return "missing-task"
        now = time.time()
        with sqlite3.connect(db_path) as con:
            row = con.execute("select status from tasks where id = ?", (task_id,)).fetchone()
            if not row:
                return "task-missing"
            if str(row[0]) != "blocked":
                return f"not-blocked:{row[0]}"
            con.execute("update tasks set status = 'ready' where id = ?", (task_id,))
            _insert_event(con, task_id, "unblocked", {"by": "kanban-warden", "reason": action.reason, "idempotency_key": action.idempotency_key}, now)
        return "unblocked"



def _insert_reviewer_task(
    con: sqlite3.Connection,
    *,
    review_id: str,
    source_task: str,
    reviewer_assignee: str,
    idempotency_key: str,
    now: int,
) -> None:
    """Insert a reviewer card using only columns present in the live schema.

    Hermes Kanban schemas evolve. The real schema has NOT NULL columns such as
    ``workspace_kind`` that are absent from older test fixtures, so direct INSERT
    statements must be built from PRAGMA table_info instead of assuming one fixed
    fixture shape.
    """
    values: dict[str, Any] = {
        "id": review_id,
        "title": f"Review {source_task}",
        "body": f"Review implementation card {source_task}.",
        "status": "ready",
        "assignee": reviewer_assignee,
        "priority": 0,
        "created_by": "kanban-warden",
        "created_at": now,
        "workspace_kind": "scratch",
        "idempotency_key": idempotency_key,
        "consecutive_failures": 0,
        "goal_mode": 0,
    }
    _insert_row(con, "tasks", values, conflict="or ignore")


def _insert_comment_row(con: sqlite3.Connection, *, task_id: str, body: str, now: int) -> None:
    values: dict[str, Any] = {
        "task_id": task_id,
        "author": "kanban-warden",
        "body": body,
        "created_at": now,
    }
    _insert_row(con, "task_comments", values)


def _insert_row(
    con: sqlite3.Connection, table: str, values: dict[str, Any], *, conflict: str = ""
) -> None:
    columns = [name for name in values if name in _table_columns(con, table)]
    if not columns:
        return
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    conflict_sql = f" {conflict}" if conflict else ""
    sql = f"insert{conflict_sql} into {table}({column_sql}) values ({placeholders})"
    con.execute(sql, tuple(values[name] for name in columns))


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"pragma table_info({table})")}

def _is_review_required(event: BoardEvent) -> bool:
    payload = event.payload or {}
    reason = _text(payload.get("reason")).lower()
    return event.task_status == "blocked" and ("review-required" in reason or event.relationship.review_required)


def _review_verdict(event: BoardEvent) -> str | None:
    payload = event.payload or {}
    text = " ".join(_text(payload.get(k)).lower() for k in ("verdict", "outcome", "summary", "result", "reason"))
    if "needs-changes" in text or "needs changes" in text:
        return "needs-changes"
    if "approve" in text or "approved" in text:
        return "approve"
    return None


def _review_source_task(event: BoardEvent) -> str | None:
    payload = event.payload or {}
    for key in ("source_task", "source_task_id", "implementation_task", "reviewed_task"):
        value = _text(payload.get(key))
        if value:
            return value
    if event.relationship.parents:
        return event.relationship.parents[0]
    return None


def _is_worker_failure(kind: str, status: str, reason: str, outcome: str) -> bool:
    text = " ".join([kind, status, reason, outcome]).lower()
    return any(token in text for token in ("crash", "protocol violation", "gave_up", "gave up", "timed_out", "timed out"))


def _insert_event(con: sqlite3.Connection, task_id: str, kind: str, payload: dict[str, Any], now: float) -> None:
    if not _table_exists(con, "task_events"):
        return
    con.execute(
        "insert into task_events(task_id, kind, payload, created_at, run_id) values (?, ?, ?, ?, ?)",
        (task_id, kind, json.dumps(payload, sort_keys=True), now, None),
    )


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("select 1 from sqlite_master where type = 'table' and name = ?", (name,)).fetchone() is not None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else "" if value is None else str(value)


def _slug(*parts: str) -> str:
    raw = ":".join(part for part in parts if part)
    return "".join(ch if ch.isalnum() else "-" for ch in raw.lower())[:80] or "event"
