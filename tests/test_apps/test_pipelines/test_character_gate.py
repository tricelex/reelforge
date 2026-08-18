"""Tests for character_gate skip / auto / park behavior."""

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    CharacterDesignMode,
)
from server.apps.pipelines.models import (
    CastDesignStatus,
    CastImportance,
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunCast,
    RunStatus,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.services.orchestrator import advance_pipeline_impl

pytestmark = pytest.mark.django_db(transaction=True)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close_connections() -> None:
        from django.db import connections

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close_connections()

    return asyncio.run(_wrapped())


def _graph_with_character_gate() -> dict[str, object]:
    return {
        'stages': [
            {
                'key': 'cast_proposal',
                'depends_on': [],
                'queue': 'api',
            },
            {
                'key': 'character_gate',
                'depends_on': ['cast_proposal'],
                'gate': True,
                'queue': 'api',
            },
            {
                'key': 'visual_prompts',
                'depends_on': ['character_gate'],
                'queue': 'api',
            },
        ],
    }


def _make_run(
    *,
    mode: str,
    gates: list[str],
    requires_design: bool,
) -> PipelineRun:
    channel = Channel.objects.create(
        name='Char Gate Channel',
        kind=ChannelKind.LONGFORM,
        gates=gates,
        character_design_mode=mode,
    )
    bp = PipelineBlueprint.objects.create(
        name='char_gate_test_v1',
        kind=PipelineKind.LONGFORM,
        graph=_graph_with_character_gate(),
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='character gate test',
    )
    StageExecution.objects.create(
        run=run,
        stage_key='cast_proposal',
        status=StageStatus.SUCCEEDED,
        input_hash='',
        output={
            'cast': [],
            'requires_character_design': requires_design,
            'reason': 'test',
        },
        finished_at=None,
    )
    return run


def test_character_gate_skips_when_no_design_needed() -> None:
    run = _make_run(
        mode=CharacterDesignMode.INTERACTIVE,
        gates=['character_gate'],
        requires_design=False,
    )
    with (
        patch(
            'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
            new=AsyncMock(),
        ),
        patch(
            'server.apps.pipelines.services.orchestrator.publish_sse',
            new=AsyncMock(),
        ),
    ):
        _run(advance_pipeline_impl(str(run.id)))

    gate = StageExecution.objects.get(run=run, stage_key='character_gate')
    assert gate.status == StageStatus.SUCCEEDED
    assert gate.output.get('skipped_reason') == 'no_characters'
    run.refresh_from_db()
    assert run.status != RunStatus.AWAITING_REVIEW


def test_character_gate_skips_when_mode_none() -> None:
    run = _make_run(
        mode=CharacterDesignMode.NONE,
        gates=['character_gate'],
        requires_design=True,
    )
    with (
        patch(
            'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
            new=AsyncMock(),
        ),
        patch(
            'server.apps.pipelines.services.orchestrator.publish_sse',
            new=AsyncMock(),
        ),
    ):
        _run(advance_pipeline_impl(str(run.id)))

    gate = StageExecution.objects.get(run=run, stage_key='character_gate')
    assert gate.status == StageStatus.SUCCEEDED
    assert gate.output.get('skipped_reason') == 'mode_none'


def test_character_gate_parks_when_interactive_and_armed() -> None:
    run = _make_run(
        mode=CharacterDesignMode.INTERACTIVE,
        gates=['character_gate'],
        requires_design=True,
    )
    with (
        patch(
            'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
            new=AsyncMock(),
        ),
        patch(
            'server.apps.pipelines.services.orchestrator.publish_sse',
            new=AsyncMock(),
        ),
    ):
        _run(advance_pipeline_impl(str(run.id)))

    run.refresh_from_db()
    assert run.status == RunStatus.AWAITING_REVIEW
    gate = StageExecution.objects.get(run=run, stage_key='character_gate')
    assert gate.status == StageStatus.NEEDS_INPUT


def test_character_gate_auto_mode_runs_studio() -> None:
    run = _make_run(
        mode=CharacterDesignMode.AUTO,
        gates=[],
        requires_design=True,
    )
    fake_output = {
        'auto_designed': True,
        'designed': [],
        'approved_cast_ids': [],
    }
    with (
        patch(
            'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
            new=AsyncMock(),
        ),
        patch(
            'server.apps.pipelines.services.orchestrator.publish_sse',
            new=AsyncMock(),
        ),
        patch(
            'server.apps.pipelines.services.auto_character_design.'
            'run_auto_character_design',
            return_value=fake_output,
        ) as auto_mock,
    ):
        _run(advance_pipeline_impl(str(run.id)))

    auto_mock.assert_called_once()
    gate = StageExecution.objects.get(run=run, stage_key='character_gate')
    assert gate.status == StageStatus.SUCCEEDED
    assert gate.output.get('auto_designed') is True
    run.refresh_from_db()
    assert run.status != RunStatus.AWAITING_REVIEW


def test_run_auto_character_design_does_not_crash_on_cast_ordering() -> None:
    """Regression: RunCast has no created_at column.

    run_auto_character_design used to order RunCast rows by 'created_at',
    which RunCast does not have (it only extends UUIDModel), raising
    FieldError on every invocation. It must now query and design cast
    members without crashing.
    """
    from server.apps.channels.logic.value_objects import (
        CharacterRoundResultPayload,
        CharacterSessionPayload,
    )
    from server.apps.channels.models import (
        Character,
        CharacterOrigin,
        CharacterStatus,
    )
    from server.apps.pipelines.services.auto_character_design import (
        run_auto_character_design,
    )

    channel = Channel.objects.create(
        name='Auto Design Channel',
        kind=ChannelKind.LONGFORM,
        character_design_mode=CharacterDesignMode.AUTO,
    )
    bp = PipelineBlueprint.objects.create(
        name='auto_design_test_v1',
        kind=PipelineKind.LONGFORM,
        graph=_graph_with_character_gate(),
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='auto character design test',
    )
    character = Character.objects.create(
        name='Hero',
        channel=channel,
        appearance_prompt='A brave hero',
        status=CharacterStatus.DRAFT,
        origin=CharacterOrigin.RUN,
        source_run=run,
    )
    run_cast = RunCast.objects.create(
        run=run,
        character=character,
        role='protagonist',
        importance=CastImportance.MAIN,
        design_status=CastDesignStatus.PROPOSED,
    )

    session_payload = CharacterSessionPayload(
        id='11111111-1111-1111-1111-111111111111',
        character_id=str(character.id),
        rounds=[],
        created_at='2026-01-01T00:00:00Z',
    )
    round_payload = CharacterRoundResultPayload(
        session_id=session_payload.id,
        candidate_asset_ids=['aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'],
        cost_usd='0.10',
    )

    with (
        patch(
            'server.apps.pipelines.services.auto_character_design.'
            'CharacterStudioService.start_session',
            return_value=session_payload,
        ),
        patch(
            'server.apps.pipelines.services.auto_character_design.'
            'CharacterStudioService.generate_round',
            return_value=round_payload,
        ),
        patch(
            'server.apps.pipelines.services.auto_character_design.'
            'CharacterStudioService.approve',
            return_value=MagicMock(),
        ),
    ):
        output = run_auto_character_design(run)

    assert output['auto_designed'] is True
    assert len(output['designed']) == 1
    assert output['designed'][0]['winning_asset_id'] == (
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    )
    assert output['approved_cast_ids'] == [str(run_cast.id)]
    run_cast.refresh_from_db()
    assert run_cast.design_status == CastDesignStatus.APPROVED


def test_cast_proposal_empty_cast_sets_requires_false() -> None:
    from server.apps.pipelines.stages.base import StageContext
    from server.apps.pipelines.stages.cast_proposal import CastProposalStage

    channel = Channel.objects.create(
        name='Empty Cast',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='cast_prop_empty',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='no people',
    )
    exec_ = StageExecution.objects.create(
        run=run,
        stage_key='cast_proposal',
        status=StageStatus.RUNNING,
        input_hash='',
    )
    ctx = MagicMock(spec=StageContext)
    ctx.run = run
    ctx.channel = channel
    ctx.execution = exec_
    ctx.upstream = {
        'scene_breakdown': {'scenes': [], 'cast': []},
    }
    result = asyncio.run(CastProposalStage().run(ctx))
    assert result['requires_character_design'] is False
    assert RunCast.objects.filter(run=run).count() == 0


def test_cast_proposal_creates_runcast_for_mains() -> None:
    from server.apps.pipelines.stages.base import StageContext
    from server.apps.pipelines.stages.cast_proposal import CastProposalStage

    channel = Channel.objects.create(
        name='Fantasy Cast',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='cast_prop_main',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='hero story',
    )
    exec_ = StageExecution.objects.create(
        run=run,
        stage_key='cast_proposal',
        status=StageStatus.RUNNING,
        input_hash='',
    )
    ctx = MagicMock(spec=StageContext)
    ctx.run = run
    ctx.channel = channel
    ctx.execution = exec_
    ctx.upstream = {
        'scene_breakdown': {
            'scenes': [],
            'cast': [
                {
                    'name': 'Aria',
                    'role': 'protagonist',
                    'importance': 'main',
                    'appearance_brief': 'scarred mercenary',
                },
            ],
        },
    }
    result = asyncio.run(CastProposalStage().run(ctx))
    assert result['requires_character_design'] is True
    row = RunCast.objects.get(run=run)
    assert row.importance == CastImportance.MAIN
    assert row.design_status == CastDesignStatus.PROPOSED
    assert 'scarred' in row.draft_prompt


def test_cast_proposal_explicit_empty_cast_ignores_foreground() -> None:
    """An empty cast list must not harvest scene foreground names."""
    from server.apps.pipelines.stages.base import StageContext
    from server.apps.pipelines.stages.cast_proposal import CastProposalStage

    channel = Channel.objects.create(
        name='Zero Cast Niche',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='cast_prop_zero',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='geography explainer',
    )
    exec_ = StageExecution.objects.create(
        run=run,
        stage_key='cast_proposal',
        status=StageStatus.RUNNING,
        input_hash='',
    )
    ctx = MagicMock(spec=StageContext)
    ctx.run = run
    ctx.channel = channel
    ctx.execution = exec_
    ctx.upstream = {
        'scene_breakdown': {
            'cast': [],
            'scenes': [
                {
                    'idx': 0,
                    'foreground_cast': ['Caesar'],
                },
            ],
        },
    }
    result = asyncio.run(CastProposalStage().run(ctx))
    assert result['requires_character_design'] is False
    assert result['cast'] == []
    assert RunCast.objects.filter(run=run).count() == 0
