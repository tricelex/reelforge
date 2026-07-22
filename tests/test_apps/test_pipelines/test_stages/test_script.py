"""Tests for the script stage."""

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import django.utils.timezone
import pytest

from server.apps.pipelines.stages.script import ScriptStage


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


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.id = 'run-script-1'
    ctx.run.prompt_snapshot = {}
    ctx.channel.id = 'chan-script-1'
    ctx.channel.wpm = 158
    ctx.upstream = {
        'outline': {
            'chapters': [
                {
                    'idx': 0,
                    'title': 'Intro',
                    'thesis': 'Brief intro.',
                    'target_seconds': 60,
                    'device': 'open_loop',
                },
            ],
            'total_target_seconds': 60,
        },
        'research': {
            'brief': {'key_facts': ['Rome fell 476 AD'], 'sources': []},
            'sources': [],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def test_script_stage_key() -> None:
    """ScriptStage has the expected key."""
    assert ScriptStage.key == 'script'
    assert ScriptStage.queue == 'api'


def test_script_fan_out_none() -> None:
    """Script is a single-execution stage."""
    assert ScriptStage().fan_out(MagicMock()) is None


def test_script_run_returns_chapters_and_word_count() -> None:
    """run() returns dict with 'chapters' and 'total_word_count'."""
    from server.apps.pipelines.schemas import (
        ScriptChapter,
        ScriptOutput,
    )

    ctx = _make_ctx()
    ctx.run.asave = AsyncMock()
    fake_output = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Intro',
                text='Rome was great.',
                word_count=3,
                closing_line='But it fell.',
                commentary="I think Rome's fall was avoidable, not inevitable.",
            ),
        ],
        total_word_count=3,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.script.embed_text',
                new=AsyncMock(return_value=[1.0, 0.0]),
            ),
            patch(
                'server.apps.pipelines.stages.script._recent_script_embeddings',
                new=AsyncMock(return_value=[]),
            ),
        ):
            return await ScriptStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'chapters' in result
    assert result['total_word_count'] == 3
    assert result['similarity_flag'] is False


def test_script_run_flags_similarity_and_saves_embedding() -> None:
    """run() computes an embedding, compares to recent runs, and flags similarity."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    ctx = _make_ctx()
    ctx.channel.publish_mode = 'review'
    ctx.run.asave = AsyncMock()

    fake_output = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Intro',
                text='Rome was great.',
                word_count=3,
                closing_line='But it fell.',
                commentary='I think this collapse was avoidable.',
            ),
        ],
        total_word_count=3,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.script.embed_text',
                new=AsyncMock(return_value=[1.0, 0.0]),
            ),
            patch(
                'server.apps.pipelines.stages.script._recent_script_embeddings',
                new=AsyncMock(return_value=[[1.0, 0.0001]]),
            ),
        ):
            return await ScriptStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['similarity_flag'] is True
    ctx.run.asave.assert_awaited_once_with(update_fields=['script_embedding'])
    assert ctx.run.script_embedding == [1.0, 0.0]


def test_script_run_auto_channel_retries_once_on_similarity() -> None:
    """publish_mode=auto triggers exactly one regeneration when too similar."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    ctx = _make_ctx()
    ctx.channel.publish_mode = 'auto'
    ctx.run.asave = AsyncMock()

    first = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Intro',
                text='Rome was great.',
                word_count=3,
                closing_line='But it fell.',
                commentary='I think this was avoidable.',
            ),
        ],
        total_word_count=3,
    )
    second = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Intro',
                text='A different take entirely.',
                word_count=4,
                closing_line='Or was it?',
                commentary='Actually I disagree with the usual take.',
            ),
        ],
        total_word_count=4,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(side_effect=[first, second]),
            ) as mock_run_agent,
            patch(
                'server.apps.pipelines.stages.script.embed_text',
                new=AsyncMock(side_effect=[[1.0, 0.0], [0.0, 1.0]]),
            ),
            patch(
                'server.apps.pipelines.stages.script._recent_script_embeddings',
                new=AsyncMock(return_value=[[1.0, 0.0001]]),
            ),
        ):
            result = await ScriptStage().run(ctx)
            assert mock_run_agent.await_count == 2
            return result

    result = asyncio.run(_inner())
    assert result['similarity_flag'] is False
    assert result['chapters'][0]['text'] == 'A different take entirely.'


@pytest.mark.django_db(transaction=True)
def test_recent_script_embeddings_reads_recent_completed_runs() -> None:
    """_recent_script_embeddings returns embeddings from recent COMPLETED runs."""
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
    )
    from server.apps.pipelines.stages.script import _recent_script_embeddings

    channel = Channel.objects.create(name='Emb Ch', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='emb_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    now = django.utils.timezone.now()
    completed = [
        PipelineRun.objects.create(
            channel=channel,
            blueprint=bp,
            blueprint_snapshot={},
            topic=f'topic {i}',
            status=RunStatus.COMPLETED,
            script_embedding=[float(i), 0.0],
            finished_at=now,
        )
        for i in range(2)
    ]
    PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='no embedding',
        status=RunStatus.COMPLETED,
        script_embedding=None,
        finished_at=now,
    )

    vecs = _run(
        _recent_script_embeddings(str(channel.id), str(completed[0].id)),
    )
    assert vecs == [[1.0, 0.0]]


def test_script_chapter_requires_commentary() -> None:
    """ScriptChapter without commentary fails validation."""
    import pytest
    from pydantic import ValidationError

    from server.apps.pipelines.schemas import ScriptChapter

    with pytest.raises(ValidationError):
        ScriptChapter(
            idx=0,
            title='Intro',
            text='Rome was great.',
            word_count=3,
            closing_line='But it fell.',
            commentary='',
        )


def test_script_output_rejects_filler_commentary() -> None:
    """ScriptOutput construction fails when commentary just echoes narration."""
    import pytest
    from pydantic import ValidationError

    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    with pytest.raises(ValidationError):
        ScriptOutput(
            chapters=[
                ScriptChapter(
                    idx=0,
                    title='Intro',
                    text='Rome was great and powerful for centuries.',
                    word_count=7,
                    closing_line='It fell.',
                    commentary='Rome was great and powerful for centuries.',
                ),
            ],
            total_word_count=7,
        )
