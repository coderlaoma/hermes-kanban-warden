"""Kanban Warden Hermes plugin.

The plugin registers lightweight guard hooks around Kanban coordination tools.
It never blocks writes: it appends actionable warnings to tool results so the
agent can correct leaked values before the task state becomes durable.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from .warden import ScanFinding, build_warning_text, default_scanner

LOGGER = logging.getLogger(__name__)
_KANBAN_TOOLS = {"kanban_comment", "kanban_complete", "kanban_block"}
_TEXT_FIELDS = ("body", "summary", "result", "reason")


def _extract_text(args: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    for field in _TEXT_FIELDS:
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            chunks.append(f"{field}: {value}")
    metadata = args.get("metadata")
    if metadata is not None:
        try:
            chunks.append("metadata: " + json.dumps(metadata, ensure_ascii=False, sort_keys=True))
        except TypeError:
            chunks.append(f"metadata: {metadata!r}")
    return "\n".join(chunks)


def _scan_tool_call(tool_name: str, args: Mapping[str, Any]) -> list[ScanFinding]:
    if tool_name not in _KANBAN_TOOLS:
        return []
    text = _extract_text(args)
    if not text:
        return []
    return default_scanner().scan(text)


def _pre_tool_call(
    tool_name: str,
    args: dict[str, Any],
    task_id: str | None = None,
    **_: Any,
) -> None:
    """Log findings before durable Kanban output is written.

    Hermes pre_tool_call hooks are observers. We log only redacted snippets here;
    the transform hook appends the user-facing warning to the result afterwards.
    """
    findings = _scan_tool_call(tool_name, args or {})
    if findings:
        LOGGER.warning(
            "kanban-warden detected %d finding(s) before %s for task %s: %s",
            len(findings),
            tool_name,
            task_id or "unknown",
            ", ".join(f.rule_id for f in findings),
        )


def _transform_tool_result(
    tool_name: str,
    args: dict[str, Any],
    result: str,
    task_id: str | None = None,
    **_: Any,
) -> str:
    """Append a warning to Kanban tool results when unsafe text is detected."""
    findings = _scan_tool_call(tool_name, args or {})
    if not findings:
        return result
    warning = build_warning_text(findings, task_id=task_id, tool_name=tool_name)
    return f"{result}\n\n{warning}" if result else warning


def register(ctx: Any) -> None:
    """Register Kanban safety hooks with Hermes."""
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("transform_tool_result", _transform_tool_result)
