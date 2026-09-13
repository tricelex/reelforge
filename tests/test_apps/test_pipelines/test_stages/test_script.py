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
                    'target_seconds': 2,
                    'device': 'open_loop',
                },
            ],
            'total_target_seconds': 2,
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


def test_script_run_retries_when_chapters_collapse_to_one() -> None:
    """A script that collapses outline chapters into one is retried."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    ctx = _make_ctx()
    ctx.upstream['outline']['chapters'] = [
        {'idx': 0, 'title': 'Intro', 'target_seconds': 2},
        {'idx': 1, 'title': 'Middle', 'target_seconds': 2},
    ]
    ctx.upstream['outline']['total_target_seconds'] = 4
    ctx.run.asave = AsyncMock()

    collapsed = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Whole episode',
                text='A short synopsis of the whole thing.',
                word_count=7,
                closing_line='The end.',
                commentary='This is a real editorial stance on the piece.',
            ),
        ],
        total_word_count=7,
    )
    fixed = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Intro',
                text='Rome was great.',
                word_count=3,
                closing_line='But it fell.',
                commentary='I think this was avoidable.',
            ),
            ScriptChapter(
                idx=1,
                title='Middle',
                text='Then it declined.',
                word_count=3,
                closing_line='Slowly at first.',
                commentary='The decline was not inevitable, in my view.',
            ),
        ],
        total_word_count=6,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(side_effect=[collapsed, fixed]),
            ) as mock_run_agent,
            patch(
                'server.apps.pipelines.stages.script.embed_text',
                new=AsyncMock(return_value=[1.0, 0.0]),
            ),
            patch(
                'server.apps.pipelines.stages.script._recent_script_embeddings',
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await ScriptStage().run(ctx)
            assert mock_run_agent.await_count == 2
            return result

    result = asyncio.run(_inner())
    assert len(result['chapters']) == 2


def test_script_run_raises_fatal_error_after_exhausting_coverage_retries() -> (
    None
):
    """A script that never covers the outline fails loudly, not silently."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput
    from server.common.exceptions import FatalProviderError

    ctx = _make_ctx()
    ctx.upstream['outline']['chapters'] = [
        {'idx': 0, 'title': 'Intro', 'target_seconds': 2},
        {'idx': 1, 'title': 'Middle', 'target_seconds': 2},
    ]
    ctx.run.asave = AsyncMock()

    always_collapsed = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Whole episode',
                text='A short synopsis of the whole thing.',
                word_count=7,
                closing_line='The end.',
                commentary='This is a real editorial stance on the piece.',
            ),
        ],
        total_word_count=7,
    )

    async def _inner() -> None:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=always_collapsed),
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
            await ScriptStage().run(ctx)

    with pytest.raises(FatalProviderError):
        asyncio.run(_inner())


def test_expected_word_count_sums_chapter_target_seconds() -> None:
    """_expected_word_count converts total outline seconds to words at wpm."""
    from server.apps.pipelines.stages.script import _expected_word_count

    chapters = [{'target_seconds': 30}, {'target_seconds': 30}]
    assert _expected_word_count(chapters, wpm=120) == 120


def test_expected_word_count_defaults_missing_target_seconds_to_zero() -> None:
    """A chapter without target_seconds contributes zero, not an error."""
    from server.apps.pipelines.stages.script import _expected_word_count

    assert _expected_word_count([{'title': 'No timing'}], wpm=158) == 0


def test_coverage_note_empty_when_no_outline_chapters() -> None:
    """With no outline to compare against, any script is accepted."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput
    from server.apps.pipelines.stages.script import _coverage_note

    output = ScriptOutput(
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
    assert _coverage_note(output, [], expected_words=0) == ''


def test_coverage_note_flags_chapter_count_mismatch() -> None:
    """A script with fewer chapters than the outline is flagged first."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput
    from server.apps.pipelines.stages.script import _coverage_note

    output = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Whole episode',
                text='A short synopsis of the whole thing.',
                word_count=7,
                closing_line='The end.',
                commentary='A real stance on the material.',
            ),
        ],
        total_word_count=7,
    )
    outline_chapters = [{'idx': 0}, {'idx': 1}]
    note = _coverage_note(output, outline_chapters, expected_words=100)
    assert 'wrote 1 chapters but the outline has 2' in note


def test_coverage_note_flags_word_count_far_below_expected() -> None:
    """A script far short on words, despite matching chapter count, is flagged."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput
    from server.apps.pipelines.stages.script import _coverage_note

    output = ScriptOutput(
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
    outline_chapters = [{'idx': 0}]
    note = _coverage_note(output, outline_chapters, expected_words=100)
    assert 'wrote 3 words total but the outline calls for roughly 100' in note


def test_coverage_note_empty_when_words_within_band() -> None:
    """A script within the coverage ratio band is accepted."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput
    from server.apps.pipelines.stages.script import _coverage_note

    output = ScriptOutput(
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
    outline_chapters = [{'idx': 0}]
    assert _coverage_note(output, outline_chapters, expected_words=2) == ''


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
