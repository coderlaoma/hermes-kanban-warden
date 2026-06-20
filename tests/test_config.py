from __future__ import annotations

from kanban_warden.config import KanbanWardenConfig


def test_task_filter_and_cleanup_config_parse_from_mapping() -> None:
    config = KanbanWardenConfig.from_mapping(
        {
            "kanban_warden": {
                "task_filter": {
                    "ignore_terminal_tasks": "true",
                    "active_statuses": ["todo", "blocked"],
                },
                "cleanup": {
                    "enabled": "true",
                    "archive_done": "true",
                    "done_retention_days": 3,
                    "purge_archived": "true",
                    "archived_retention_days": 15,
                    "gc_enabled": "true",
                    "gc_retention_days": 15,
                    "min_interval_seconds": 120,
                },
            }
        }
    )

    assert config.task_filter.ignore_terminal_tasks is True
    assert config.task_filter.active_statuses == ["todo", "blocked"]
    assert config.cleanup.enabled is True
    assert config.cleanup.archive_done is True
    assert config.cleanup.done_retention_days == 3
    assert config.cleanup.purge_archived is True
    assert config.cleanup.archived_retention_days == 15
    assert config.cleanup.gc_enabled is True
    assert config.cleanup.gc_retention_days == 15
    assert config.cleanup.min_interval_seconds == 120
