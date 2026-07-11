"""Tests for TTS shard loading from child StageExecution rows."""

import asyncio

import pytest

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.services.tts_shards import load_tts_chapter_shards


def _run_async(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_load_tts_chapter_shards_reads_child_output() -> None:
    """Child rows supply chapter_idx and asset_id even when parent shards are bare."""
    channel = Channel.objects.create(
        name='TTS Shard Loader',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='tts_shard_loader_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'tts', 'depends_on': [], 'queue': 'api'}]},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )
    parent = StageExecution.objects.create(
        run=run,
        stage_key='tts',
        status=StageStatus.SUCCEEDED,
        output={'shards': [{'shard_index': 0, 'status': StageStatus.SUCCEEDED}]},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        output={'chapter_idx': 0, 'asset_id': 'audio-ch0', 'char_count': 100},
    )

    result = _run_async(load_tts_chapter_shards(run))
    assert result == [{'chapter_idx': 0, 'asset_id': 'audio-ch0'}]


@pytest.mark.django_db(transaction=True)
def test_load_tts_chapter_shards_latest_attempt_wins() -> None:
    """The highest attempt per shard_index is used when merging child output."""
    channel = Channel.objects.create(
        name='TTS Shard Retry',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='tts_shard_retry_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'tts', 'depends_on': [], 'queue': 'api'}]},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )
    parent = StageExecution.objects.create(
        run=run,
        stage_key='tts',
        status=StageStatus.SUCCEEDED,
        output={},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=0,
        attempt=0,
        status=StageStatus.SUCCEEDED,
        output={'chapter_idx': 0, 'asset_id': 'audio-old'},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=0,
        attempt=1,
        status=StageStatus.SUCCEEDED,
        output={'chapter_idx': 0, 'asset_id': 'audio-new'},
    )

    result = _run_async(load_tts_chapter_shards(run))
    assert result == [{'chapter_idx': 0, 'asset_id': 'audio-new'}]


@pytest.mark.django_db(transaction=True)
def test_load_tts_chapter_shards_falls_back_to_shard_index() -> None:
    """chapter_idx defaults to shard_index when absent from child output."""
    channel = Channel.objects.create(
        name='TTS Shard Fallback',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='tts_shard_fallback_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'tts', 'depends_on': [], 'queue': 'api'}]},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )
    parent = StageExecution.objects.create(
        run=run,
        stage_key='tts',
        status=StageStatus.SUCCEEDED,
        output={},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=2,
        status=StageStatus.SUCCEEDED,
        output={'asset_id': 'audio-ch2'},
    )

    result = _run_async(load_tts_chapter_shards(run))
    assert result == [{'chapter_idx': 2, 'asset_id': 'audio-ch2'}]


@pytest.mark.django_db(transaction=True)
def test_load_tts_chapter_shards_skips_children_without_asset_id() -> None:
    """Children missing asset_id are ignored even when chapter_idx is present."""
    channel = Channel.objects.create(
        name='TTS Shard Skip',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='tts_shard_skip_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'tts', 'depends_on': [], 'queue': 'api'}]},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )
    parent = StageExecution.objects.create(
        run=run,
        stage_key='tts',
        status=StageStatus.SUCCEEDED,
        output={},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        output={'chapter_idx': 0},
    )

    result = _run_async(load_tts_chapter_shards(run))
    assert result == []
