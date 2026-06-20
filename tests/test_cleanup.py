from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kanban_warden.cleanup import CleanupPlan, execute_cleanup_plan, plan_cleanup


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
