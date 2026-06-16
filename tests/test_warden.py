from __future__ import annotations

from kanban_warden import _transform_tool_result
from kanban_warden.warden import build_warning_text, default_scanner

FAKE_GITHUB_TOKEN = "ghp_" + "a" * 30
FAKE_OPENAI_KEY = "sk-" + "b" * 30


def test_scanner_detects_and_redacts_secret_assignments() -> None:
    findings = default_scanner().scan(f"token = {FAKE_GITHUB_TOKEN}")

    assert findings
    assert findings[0].rule_id == "github-token"
    assert FAKE_GITHUB_TOKEN not in findings[0].snippet
    assert "[REDACTED]" in findings[0].snippet


def test_scanner_ignores_redacted_values() -> None:
    findings = default_scanner().scan("password=[REDACTED]\nurl=https://example.com/path")

    assert findings == []


def test_database_url_with_credentials_is_detected() -> None:
    findings = default_scanner().scan("postgres://user:***@example.internal:5432/app")

    assert [finding.rule_id for finding in findings] == ["database-url"]


def test_warning_text_contains_no_raw_secret() -> None:
    findings = default_scanner().scan(f"OPENAI_API_KEY={FAKE_OPENAI_KEY}")
    warning = build_warning_text(findings, task_id="t_123", tool_name="kanban_complete")

    assert "t_123" in warning
    assert "kanban_complete" in warning
    assert FAKE_OPENAI_KEY not in warning
    assert "[REDACTED]" in warning


def test_transform_tool_result_appends_warning_for_kanban_tools() -> None:
    fake_password = "fake-long-password-value"
    result = _transform_tool_result(
        "kanban_comment",
        {"body": f"temporary password = {fake_password}"},
        "ok",
        task_id="t_123",
    )

    assert result.startswith("ok")
    assert "[kanban-warden] WARNING" in result
    assert fake_password not in result


def test_transform_tool_result_ignores_non_kanban_tools() -> None:
    result = _transform_tool_result(
        "terminal",
        {"command": f"echo GH_TOKEN={FAKE_GITHUB_TOKEN}"},
        "ok",
    )

    assert result == "ok"
