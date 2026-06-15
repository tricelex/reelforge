import asyncio

import pytest

from server.apps.pipelines.stages.review_gate import ReviewGateStage


def test_review_gate_key():
    assert ReviewGateStage.key == 'review_gate'
    assert ReviewGateStage.max_retries == 0


def test_review_gate_fan_out_none():
    from unittest.mock import MagicMock

    assert ReviewGateStage().fan_out(MagicMock()) is None


def test_review_gate_run_raises():
    """run() should never be called directly — gates are handled by the orchestrator."""
    from unittest.mock import MagicMock

    async def _inner():
        await ReviewGateStage().run(MagicMock())

    with pytest.raises(RuntimeError, match='handled by the orchestrator'):
        asyncio.run(_inner())
