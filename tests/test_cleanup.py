from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kanban_warden.cleanup import (
    CleanupPlan,
    StateCleanupConfig,
    execute_cleanup_plan,
    plan_cleanup,
    prune_state_store,
)


def _init_board(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        create table tasks (
          id text primary key,
          status text not null,
          created_at integer,
          completed_at integer
        );
        """
    )
    con.commit()
    con.close()


def _task(db_path: Path, task_id: str, status: str, created_at: int, completed_at: int | None) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "insert into tasks(id, status, created_at, completed_at) values (?, ?, ?, ?)",
        (task_id, status, created_at, completed_at),
    )
    con.commit()
    con.close()


def test_cleanup_plan_archives_old_done_and_purges_old_archived(tmp_path: Path) -> None:
    db_path = tmp_path / "kanban.db"
    _init_board(db_path)
    now = 2_000_000
    old = now - 16 * 24 * 3600
    recent = now - 2 * 24 * 3600
    _task(db_path, "old_done", "done", old, old)
    _task(db_path, "recent_done", "done", recent, recent)
    _task(db_path, "old_archived", "archived", old, old)
    _task(db_path, "recent_archived", "archived", recent, recent)
    _task(db_path, "active", "blocked", old, None)
    con = sqlite3.connect(db_path)

    plan = plan_cleanup(
        con,
        now=now,
        done_retention_days=7,
        archived_retention_days=15,
        archive_done=True,
        purge_archived=True,
    )

    assert plan.archive_done_ids == ["old_done"]
    assert plan.purge_archived_ids == ["old_archived"]
    assert plan.should_run_gc is True


def test_execute_cleanup_uses_official_cli_with_board_db_env(
    monkeypatch: Any, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(
        cmd: list[str],
        *,
        text: bool,
        capture_output: bool,
        timeout: int,
        env: Mapping[str, str],
    ) -> object:
        calls.append(
            {
                "cmd": cmd,
                "text": text,
                "capture_output": capture_output,
                "timeout": timeout,
                "db": env.get("HERMES_KANBAN_DB"),
            }
        )

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setenv("KANBAN_WARDEN_HERMES_PYTHON", "/opt/hermes/bin/python")
    monkeypatch.setattr("kanban_warden.cleanup.subprocess.run", fake_run)
    db_path = tmp_path / "kanban.db"

    execute_cleanup_plan(
        CleanupPlan(
            archive_done_ids=["done_1"],
            purge_archived_ids=["archived_1"],
            should_run_gc=True,
        ),
        board="default",
        db_path=db_path,
        gc_retention_days=15,
        run_gc=True,
    )

    assert [call["cmd"][3:] for call in calls] == [
        ["kanban", "archive", "done_1"],
        ["kanban", "archive", "--rm", "archived_1"],
        ["kanban", "gc", "--event-retention-days", "15", "--log-retention-days", "15"],
    ]
    assert {call["cmd"][0] for call in calls} == {"/opt/hermes/bin/python"}
    assert {call["db"] for call in calls} == {str(db_path)}



def test_prune_state_store_removes_old_warden_runtime_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        create table processed_keys (key text primary key, created_at real not null);
        create table action_log (
          key text primary key,
          status text not null,
          attempts integer not null default 0,
          note text not null default '',
          created_at real not null,
          updated_at real not null
        );
        create table notification_outbox (
          key text primary key,
          payload_json text not null,
          status text not null default 'queued',
          attempts integer not null default 0,
          last_error text,
          created_at real not null,
          updated_at real not null,
          next_attempt_at real
        );
        create table retry_budgets (
          board_name text not null,
          task_id text not null,
          action text not null,
          attempts integer not null default 0,
          updated_at real not null,
          primary key(board_name, task_id, action)
        );
        create table runtime_metadata (
          key text primary key,
          value_json text not null,
          updated_at real not null
        );
        """
    )
    now = 2_000_000.0
    old = now - 8 * 24 * 3600
    recent = now - 2 * 24 * 3600
    con.executemany(
        "insert into processed_keys(key, created_at) values (?, ?)",
        [("old_processed", old), ("recent_processed", recent)],
    )
    con.executemany(
        "insert into action_log(key, status, attempts, created_at, updated_at) values (?, ?, 1, ?, ?)",
        [
            ("old_done", "done", old, old),
            ("recent_done", "done", recent, recent),
            ("old_started", "started", old, old),
        ],
    )
    con.executemany(
        "insert into notification_outbox(key, payload_json, status, attempts, created_at, updated_at) values (?, '{}', ?, 1, ?, ?)",
        [
            ("old_delivered", "delivered", old, old),
            ("old_exhausted", "exhausted", old, old),
            ("recent_delivered", "delivered", recent, recent),
            ("old_retrying", "retrying", old, old),
        ],
    )
    con.executemany(
        "insert into retry_budgets(board_name, task_id, action, attempts, updated_at) values ('b', ?, 'a', 1, ?)",
        [("old_retry", old), ("recent_retry", recent)],
    )
    con.commit()
    con.close()

    result = prune_state_store(
        db_path,
        now=now,
        config=StateCleanupConfig(retention_days=7, vacuum=False),
    )

    assert result["processed_keys_deleted"] == 1
    assert result["action_log_deleted"] == 1
    assert result["notification_outbox_deleted"] == 2
    assert result["retry_budgets_deleted"] == 1
    con = sqlite3.connect(db_path)
    assert [row[0] for row in con.execute("select key from processed_keys order by key")] == [
        "recent_processed"
    ]
    assert [row[0] for row in con.execute("select key from action_log order by key")] == [
        "old_started",
        "recent_done",
    ]
    assert [row[0] for row in con.execute("select key from notification_outbox order by key")] == [
        "old_retrying",
        "recent_delivered",
    ]
    assert [row[0] for row in con.execute("select task_id from retry_budgets order by task_id")] == [
        "recent_retry"
    ]
    con.close()
