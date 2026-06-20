from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from kanban_warden.board import BoardEventTailer, discover_boards
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
          created_at integer,
          started_at integer,
          completed_at integer,
          current_run_id integer
        );
        create table task_events (
          id integer primary key autoincrement,
          task_id text,
          kind text not null,
          payload text,
          created_at integer,
          run_id integer
        );
        create table task_links (parent_id text not null, child_id text not null);
        create table task_comments (id integer primary key autoincrement, task_id text, body text, created_at integer);
        create table runs (id integer primary key, task_id text, profile text, status text, started_at integer, ended_at integer);
        """
    )
    con.commit()
    con.close()


def _event(
    db_path: Path,
    task_id: str,
    kind: str,
    payload: dict[str, object] | None = None,
    created_at: int = 100,
) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "insert into task_events(task_id, kind, payload, created_at, run_id) values (?, ?, ?, ?, ?)",
        (task_id, kind, json.dumps(payload) if payload is not None else None, created_at, None),
    )
    con.commit()
    con.close()


def test_discover_boards_star_finds_legacy_and_named_boards(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = home / ".hermes" / "kanban.db"
    named = home / ".hermes" / "kanban" / "boards" / "alpha" / "kanban.db"
    _init_board(legacy)
    _init_board(named)

    boards = discover_boards("*", hermes_home=home / ".hermes")

    assert [(board.name, board.db_path) for board in boards] == [
        ("default", legacy),
        ("alpha", named),
    ]

    beta = home / ".hermes" / "kanban" / "boards" / "beta" / "kanban.db"
    _init_board(beta)

    assert [board.name for board in discover_boards("*", hermes_home=home / ".hermes")] == [
        "default",
        "alpha",
        "beta",
    ]


def test_tail_events_keeps_independent_persistent_cursors(tmp_path: Path) -> None:
    first = tmp_path / "default.db"
    second = tmp_path / "alpha.db"
    _init_board(first)
    _init_board(second)
    _event(first, "t_1", "created", {"by": "tester"}, created_at=100)
    _event(second, "t_2", "created", {"by": "tester"}, created_at=101)
    store = WardenStateStore(tmp_path / "state.db")
    tailer = BoardEventTailer(store)

    default_events = tailer.tail("default", first)
    alpha_events = tailer.tail("alpha", second)

    assert [event.task_id for event in default_events] == ["t_1"]
    assert [event.task_id for event in alpha_events] == ["t_2"]
    assert store.get_cursor("default") == 1
    assert store.get_cursor("alpha") == 1
    assert tailer.tail("default", first) == []

    _event(first, "t_3", "claimed", {"run_id": 7}, created_at=102)

    assert [event.task_id for event in tailer.tail("default", first)] == ["t_3"]
    assert store.get_cursor("default") == 2
    assert store.get_cursor("alpha") == 1


def test_tail_events_skips_terminal_tasks_but_advances_cursor(tmp_path: Path) -> None:
    db_path = tmp_path / "kanban.db"
    _init_board(db_path)
    con = sqlite3.connect(db_path)
    con.executemany(
        "insert into tasks(id, title, status, assignee, created_at) values (?, ?, ?, ?, ?)",
        [
            ("active", "Active", "blocked", "planner", 1),
            ("done", "Done", "done", "planner", 1),
            ("archived", "Archived", "archived", "planner", 1),
        ],
    )
    con.commit()
    con.close()
    _event(db_path, "done", "completed", {"result": "ok"}, created_at=2)
    _event(db_path, "archived", "archived", {}, created_at=3)
    _event(db_path, "active", "blocked", {"reason": "waiting"}, created_at=4)
    store = WardenStateStore(tmp_path / "state.db")
    tailer = BoardEventTailer(store)

    events = tailer.tail("default", db_path, active_statuses={"blocked", "running"})

    assert [event.task_id for event in events] == ["active"]
    assert store.get_cursor("default") == 3
    assert tailer.tail("default", db_path, active_statuses={"blocked", "running"}) == []


def test_state_store_tracks_idempotency_retry_budget_and_runtime_metadata(tmp_path: Path) -> None:
    store = WardenStateStore(tmp_path / "state.db")

    assert store.mark_processed("event:default:1") is True
    assert store.mark_processed("event:default:1") is False
    assert store.bump_retry("default", "t_1", "stale-running") == 1
    assert store.bump_retry("default", "t_1", "stale-running") == 2

    store.set_runtime_metadata("last_health_sweep", {"at": 123, "boards": ["default"]})

    assert store.get_runtime_metadata("last_health_sweep") == {"at": 123, "boards": ["default"]}


def test_event_model_enriches_relationships_from_links_comments_and_status(tmp_path: Path) -> None:
    db_path = tmp_path / "kanban.db"
    _init_board(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        "insert into tasks(id, title, status, assignee, created_at) values ('root', 'Root', 'running', 'planner', 1)"
    )
    con.execute(
        "insert into tasks(id, title, status, assignee, created_at) values ('child', 'Review child', 'blocked', 'reviewer', 2)"
    )
    con.execute("insert into task_links(parent_id, child_id) values ('root', 'child')")
    con.execute(
        "insert into task_comments(task_id, body, created_at) values ('child', 'review-required: please approve', 3)"
    )
    con.commit()
    con.close()
    _event(db_path, "child", "blocked", {"reason": "review-required: please approve"}, created_at=4)

    event = BoardEventTailer(WardenStateStore(tmp_path / "state.db")).tail("default", db_path)[0]

    assert event.relationship.parents == ["root"]
    assert event.relationship.root_task_id == "root"
    assert event.relationship.review_required is True
    assert event.task_status == "blocked"


def test_supervisor_dry_run_reports_boards_cursors_events_relationships_and_health(
    tmp_path: Path,
) -> None:
    hermes_home = tmp_path / "home" / ".hermes"
    legacy = hermes_home / "kanban.db"
    _init_board(legacy)
    con = sqlite3.connect(legacy)
    con.execute(
        "insert into tasks(id, title, status, assignee, created_at, started_at) values ('t_old', 'Old', 'running', 'worker', 1, 1)"
    )
    con.commit()
    con.close()
    _event(legacy, "t_old", "created", {"by": "tester"}, created_at=2)
    config = KanbanWardenConfig.from_mapping(
        {
            "enabled": True,
            "leader_lock": {"enabled": False},
            "state_db_path": str(tmp_path / "warden-state.db"),
            "hermes_home": str(hermes_home),
            "limits": {"task_timeout_seconds": 5, "stale_claim_seconds": 5},
            "loop": {"health_sweep_seconds": 0},
        }
    )
    supervisor = WardenSupervisor(config, profile_name="tester")

    report = supervisor.dry_run(now=100)

    assert report["boards"][0]["name"] == "default"
    assert report["boards"][0]["cursor_after"] == 1
    assert report["recent_events"][0]["task_id"] == "t_old"
    assert report["relationships"][0]["root_task_id"] == "t_old"
    assert report["health"][0]["kind"] == "running_without_recent_heartbeat"
