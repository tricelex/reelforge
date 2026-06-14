import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


def test_register_stage_adds_to_registry() -> None:
    from server.apps.pipelines.stages.base import (
        STAGE_REGISTRY,
        Stage,
        register_stage,
    )

    @register_stage
    class _TestStage(Stage):
        key = '_test_register_stage'
        queue = 'api'

        async def run(self, ctx):  # type: ignore[override]
            return {}

    assert '_test_register_stage' in STAGE_REGISTRY
    assert STAGE_REGISTRY['_test_register_stage'] is _TestStage


def test_compute_input_hash_is_deterministic() -> None:
    from server.apps.pipelines.stages.base import compute_input_hash

    h1 = compute_input_hash({'a': 1, 'b': [2, 3]})
    h2 = compute_input_hash({'b': [2, 3], 'a': 1})
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_cost_recorder_accumulates_total() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.pipelines.services.cost_recorder import CostRecorder

    mock_exec = MagicMock()
    mock_exec.id = 'test-id'
    recorder = CostRecorder(mock_exec)

    async def _inner():
        with patch(
            'server.apps.pipelines.models.CostRecord'
        ) as MockCostRecord:
            MockCostRecord.objects.acreate = AsyncMock()
            await recorder.record('fal_flux', 'image_gen', 1, 0.025)
            await recorder.record('fal_flux', 'image_gen', 2, 0.025)

        from decimal import Decimal
        assert recorder.total_usd == Decimal('0.075')

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_dummy_stages_registered() -> None:
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'dummy_a' in STAGE_REGISTRY
    assert 'dummy_b' in STAGE_REGISTRY
    assert 'dummy_c' in STAGE_REGISTRY
