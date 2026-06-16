"""Tests for ClipApprovalGateStage."""

import asyncio
from unittest.mock import MagicMock

import pytest

from server.apps.pipelines.stages.clip_approval_gate import ClipApprovalGateStage


def test_clip_approval_gate_attributes() -> None:
    assert ClipApprovalGateStage.key == 'clip_approval_gate'
    assert ClipApprovalGateStage.queue == 'api'
    assert ClipApprovalGateStage.max_retries == 0
    assert ClipApprovalGateStage.timeout_s == 1


def test_clip_approval_gate_fan_out_returns_none() -> None:
    assert ClipApprovalGateStage().fan_out(MagicMock()) is None


def test_clip_approval_gate_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_approval_gate' in STAGE_REGISTRY


def test_clip_approval_gate_run_raises() -> None:
    async def _inner() -> None:
        await ClipApprovalGateStage().run(MagicMock())

    with pytest.raises(RuntimeError, match='handled by the orchestrator'):
        asyncio.run(_inner())
