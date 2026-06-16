from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from kanban_warden.config import KanbanWardenConfig
from kanban_warden.state import WardenStateStore
from kanban_warden.supervisor import WardenSupervisor


def _init_board(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        create table tasks (
          id text primary key,
          title text,
          status text,
          assignee text,
          created_at real,
          started_at real,
          completed_at real,
          current_run_id integer
        );
        create table task_events (
          id integer primary key autoincrement,
          task_id text,
          kind text not null,
          payload text,
          created_at real,
          run_id integer
        );
        create table task_links (parent_id text not null, child_id text not null);
        create table task_comments (id integer primary key autoincrement, task_id text, body text, created_at real);
        create table runs (id integer primary key, task_id text, profile text, status text, started_at real, ended_at real);
        """
    )
    con.commit()
    con.close()


def _event(db_path: Path, task_id: str, kind: str, payload: dict[str, object] | None = None, created_at: int = 100) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "insert into task_events(task_id, kind, payload, created_at, run_id) values (?, ?, ?, ?, ?)",
        (task_id, kind, json.dumps(payload) if payload is not None else None, created_at, None),
    )
    con.commit()
    con.close()


def _config(tmp_path: Path, *, dry_run: bool = True, max_retries: int = 2) -> KanbanWardenConfig:
    return KanbanWardenConfig.from_mapping(
        {
            "enabled": True,
            "hermes_home": str(tmp_path / "home" / ".hermes"),
            "state_db_path": str(tmp_path / "state.db"),
            "leader_lock": {"enabled": False},
            "notifications": {"enabled": True, "channels": ["origin"]},
            "auto_advance": {
                "enabled": True,
                "dry_run": dry_run,
                "review_required": True,
                "stale_claims": True,
                "reviewer_assignee": "reviewer",
            },
            "limits": {"max_retries": max_retries, "stale_claim_seconds": 5, "task_timeout_seconds": 10},
            "loop": {"health_sweep_seconds": 0},
        }
    )


def test_review_required_dry_run_plans_notification_and_reviewer_without_mutating_board(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=True)
    board = Path(config.hermes_home or "") / "kanban.db"
    _init_board(board)
    con = sqlite3.connect(board)
    con.execute("insert into tasks(id, title, status, assignee, created_at) values ('impl', 'Impl', 'blocked', 'hairou', 1)")
    con.commit()
    con.close()
    _event(board, "impl", "blocked", {"reason": "review-required: check diff"}, 2)

    report = WardenSupervisor(config, profile_name="tester").dry_run(now=20)

    kinds = [action["kind"] for action in report["planned_actions"]]
    assert "notify" in kinds
    assert "create_reviewer" in kinds
    assert all(result["applied"] is False and result["note"] == "dry-run" for result in report["action_results"])
    con = sqlite3.connect(board)
    assert con.execute("select count(*) from tasks where id = 'review_impl'").fetchone()[0] == 0


def test_review_required_apply_creates_one_reviewer_with_idempotency(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=False)
    board = Path(config.hermes_home or "") / "kanban.db"
    _init_board(board)
    con = sqlite3.connect(board)
    con.execute("insert into tasks(id, title, status, assignee, created_at) values ('impl', 'Impl', 'blocked', 'hairou', 1)")
    con.commit()
    con.close()
    _event(board, "impl", "blocked", {"reason": "review-required: check diff"}, 2)
    supervisor = WardenSupervisor(config, profile_name="tester")

    first = supervisor.collect(now=20)
    second = supervisor.collect(now=21)

    assert any(result["applied"] and result["kind"] == "create_reviewer" for result in first["action_results"])
    con = sqlite3.connect(board)
    assert con.execute("select count(*) from tasks where id = 'review_impl'").fetchone()[0] == 1
    assert con.execute("select assignee from tasks where id = 'review_impl'").fetchone()[0] == "reviewer"
    assert not any(result["applied"] and result["kind"] == "create_reviewer" for result in second["action_results"])


def test_review_approve_and_needs_changes_comment_and_unblock_source_once(tmp_path: Path) -> None:
    for verdict in ("approve", "needs-changes"):
        config = _config(tmp_path / verdict, dry_run=False)
        board = Path(config.hermes_home or "") / "kanban.db"
        _init_board(board)
        con = sqlite3.connect(board)
        con.execute("insert into tasks(id, title, status, assignee, created_at) values ('impl', 'Impl', 'blocked', 'hairou', 1)")
        con.execute("insert into tasks(id, title, status, assignee, created_at) values ('review_impl', 'Review', 'done', 'reviewer', 2)")
        con.execute("insert into task_links(parent_id, child_id) values ('impl', 'review_impl')")
        con.commit()
        con.close()
        _event(board, "review_impl", "completed", {"verdict": verdict, "source_task": "impl"}, 3)

        WardenSupervisor(config, profile_name="tester").collect(now=20)
        WardenSupervisor(config, profile_name="tester").collect(now=21)

        con = sqlite3.connect(board)
        assert con.execute("select status from tasks where id = 'impl'").fetchone()[0] == "ready"
        assert con.execute("select count(*) from task_comments where task_id = 'impl'").fetchone()[0] == 1


def test_stale_running_retry_budget_escalates_after_retries(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=False, max_retries=1)
    board = Path(config.hermes_home or "") / "kanban.db"
    _init_board(board)
    con = sqlite3.connect(board)
    con.execute("insert into tasks(id, title, status, assignee, created_at, started_at) values ('stale', 'Stale', 'running', 'hairou', 1, 1)")
    con.commit()
    con.close()
    supervisor = WardenSupervisor(config, profile_name="tester")

    first = supervisor.collect(now=20)
    second = supervisor.collect(now=21)

    assert any(action["kind"] == "retry" for action in first["planned_actions"])
    assert any(action["kind"] == "escalate" for action in second["planned_actions"])
    assert WardenStateStore(config.state_db_path or "").peek_retry("default", "stale", "stale-running") == 1
