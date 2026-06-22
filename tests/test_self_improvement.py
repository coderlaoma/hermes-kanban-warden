from __future__ import annotations

from pathlib import Path

import pytest

from kanban_warden.self_improvement import SelfImprovementEngine
from kanban_warden.state import WardenStateStore


def test_self_improvement_creates_e3_code_change_draft_from_policy_gap(
    tmp_path: Path,
) -> None:
    store = WardenStateStore(tmp_path / "state.db")
    signal = store.record_improvement_signal(
        signal_type="policy_gap",
        scope="detector.high_activity_low_progress",
        severity="high",
        supporting_trace_ids=["trace-101", "trace-117", "trace-203"],
        supporting_outcome_ids=["outcome-101", "outcome-117", "outcome-203"],
        summary="Running tasks emit many events without artifacts or state transitions.",
        recommended_level="E3",
        created_at=100.0,
    )

    drafts = SelfImprovementEngine(store).create_code_change_drafts(created_at=101.0)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft["proposal_type"] == "code_change"
    assert draft["level"] == "E3"
    assert draft["signal_id"] == signal["signal_id"]
    assert draft["target"] == "detector.high_activity_low_progress"
    assert draft["suggested_value"] == "draft_code_change_plan"
    assert draft["approval_required"] is True
    assert draft["patch"] == {
        "branch_name": f"warden/improve-{draft['proposal_id'].split(':')[-1]}-high-activity-low-progress",
        "affected_files": [
            "src/kanban_warden/board.py",
            "tests/test_board_events.py",
            "docs/loop-supervisor/v0.4-self-improvement.md",
        ],
        "verification_commands": [
            "uv run pytest tests/test_board_events.py -q",
            "uv run ruff check .",
            "uv run mypy src",
        ],
        "mutates_source": False,
    }
    assert store.recent_improvement_proposals()[0]["patch"] == draft["patch"]
    assert store.recent_improvement_audit()[0]["event_type"] == "proposal_created"


def test_self_improvement_records_e3_approval_scope(tmp_path: Path) -> None:
    store = WardenStateStore(tmp_path / "state.db")
    signal = store.record_improvement_signal(
        signal_type="policy_gap",
        scope="detector.high_activity_low_progress",
        severity="high",
        supporting_trace_ids=["trace-101"],
        supporting_outcome_ids=["outcome-101"],
        summary="Need code detector.",
        recommended_level="E3",
        created_at=100.0,
    )
    draft = SelfImprovementEngine(store).create_code_change_drafts(created_at=101.0)[0]

    approval = SelfImprovementEngine(store).record_code_change_approval(
        proposal_id=draft["proposal_id"],
        actor="hairou",
        allowed_repository="coderlaoma/hermes-kanban-warden",
        allowed_branch_prefix="warden/improve-",
        verification_commands=draft["patch"]["verification_commands"],
        reason="Approved to draft implementation only.",
        created_at=102.0,
    )

    audit = store.recent_improvement_audit()[0]
    assert draft["signal_id"] == signal["signal_id"]
    assert approval["decision"] == "approved"
    assert audit["event_type"] == "human_approved"
    assert audit["payload"] == {
        "approved_level": "E3",
        "allowed_repository": "coderlaoma/hermes-kanban-warden",
        "allowed_branch_prefix": "warden/improve-",
        "verification_commands": draft["patch"]["verification_commands"],
        "reason": "Approved to draft implementation only.",
    }


def test_self_improvement_rejects_non_code_change_approval(tmp_path: Path) -> None:
    store = WardenStateStore(tmp_path / "state.db")
    proposal = store.record_improvement_proposal(
        proposal_type="config_change",
        level="E2",
        signal_id="sig-1",
        title="Raise retry threshold",
        evidence_summary="Retries are exhausted too early.",
        target="limits.max_retries",
        current_value="2",
        suggested_value="3",
        reason="Observed retries were still producing progress.",
        risk="low",
        rollback_value="2",
        approval_required=True,
        patch={"kanban_warden.limits.max_retries": 3},
        created_at=100.0,
    )

    with pytest.raises(ValueError, match="only E3 code-change proposals"):
        SelfImprovementEngine(store).record_code_change_approval(
            proposal_id=proposal["proposal_id"],
            actor="hairou",
            allowed_repository="coderlaoma/hermes-kanban-warden",
            allowed_branch_prefix="warden/improve-",
            verification_commands=["uv run pytest"],
            reason="Wrong level.",
            created_at=101.0,
        )
