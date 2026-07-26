"""Tests for the documentary footage review adapter."""

from unittest.mock import MagicMock

import pytest
from django.core.files.base import ContentFile

from server.apps.assets.models import Asset, AssetKind
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.review import documentary


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Create a documentary review channel with final_gate."""
    return Channel.objects.create(
        name='Documentary Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
        default_budget_usd='40.00',
    )


@pytest.fixture
def blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Create a documentary blueprint graph for review stages."""
    return PipelineBlueprint.objects.create(
        name='documentary_footage_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'profile': 'documentary_footage',
            'stages': [
                {'key': 'scene_breakdown', 'depends_on': []},
                {'key': 'footage_queries', 'depends_on': ['scene_breakdown']},
                {'key': 'footage_search', 'depends_on': ['footage_queries']},
                {'key': 'footage_prep', 'depends_on': ['footage_search']},
                {
                    'key': 'final_gate',
                    'depends_on': ['footage_prep'],
                    'gate': True,
                },
                {'key': 'publish', 'depends_on': ['final_gate']},
            ],
        },
    )


@pytest.fixture
def run(channel: Channel, blueprint: PipelineBlueprint) -> PipelineRun:
    """Create a documentary run awaiting review."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Documentary topic',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='3.20',
    )


@pytest.fixture
def scene_breakdown_stage(run: PipelineRun) -> StageExecution:
    """Seed succeeded scene_breakdown output with two scenes."""
    return StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scenes': [
                {
                    'idx': 0,
                    'narration_text': 'The city fell silent.',
                    'visual_concept': 'empty streets at dawn',
                    'est_seconds': 6.0,
                },
                {
                    'idx': 1,
                    'narration_text': 'A single light remained.',
                    'visual_concept': 'lit window at night',
                    'est_seconds': 4.5,
                },
                {
                    'idx': 2,
                    'narration_text': 'No footage was ever found.',
                    'visual_concept': 'lost archive',
                    'est_seconds': 5.0,
                },
            ],
        },
    )


@pytest.fixture
def footage_search_parent(run: PipelineRun) -> StageExecution:
    """Seed parent footage_search execution."""
    return StageExecution.objects.create(
        run=run,
        stage_key='footage_search',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
    )


@pytest.fixture
def provider_scene_asset(run: PipelineRun) -> Asset:
    """Create a stored provider-sourced footage asset for scene 0."""
    return Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'\x00\x01', name='scene0.mp4'),
        mime='video/mp4',
        checksum='scene0abc',
        run=run,
    )


@pytest.fixture
def provider_footage_child(
    run: PipelineRun,
    footage_search_parent: StageExecution,
    provider_scene_asset: Asset,
) -> StageExecution:
    """Seed a provider-sourced footage_search child for scene 0."""
    return StageExecution.objects.create(
        run=run,
        stage_key='footage_search',
        parent=footage_search_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scene_idx': 0,
            'asset_id': str(provider_scene_asset.id),
            'media_type': 'video',
            'source': 'pexels',
            'license': 'Pexels License',
            'license_url': 'https://www.pexels.com/license/',
            'attribution_required': False,
            'attribution': 'Jane Doe',
            'source_url': 'https://pexels.com/video/123',
            'rerank_score': 0.87,
            'candidates': [
                {
                    'external_id': 'ext-1',
                    'provider': 'pexels',
                    'thumb_url': 'https://pexels.com/thumb/1',
                    'preview_url': 'https://pexels.com/preview/1',
                    'width': 1920,
                    'height': 1080,
                    'duration_s': 12.5,
                    'license': 'Pexels License',
                    'author': 'Jane Doe',
                    'source_url': 'https://pexels.com/video/123',
                },
                {
                    'external_id': 'ext-2',
                    'provider': 'pixabay',
                    'thumb_url': 'https://pixabay.com/thumb/2',
                    'preview_url': 'https://pixabay.com/preview/2',
                    'width': 1280,
                    'height': 720,
                    'duration_s': None,
                    'license': 'Pixabay License',
                    'author': 'John Roe',
                    'source_url': 'https://pixabay.com/video/456',
                },
            ],
        },
    )


@pytest.fixture
def ai_fallback_footage_child(
    run: PipelineRun,
    footage_search_parent: StageExecution,
) -> StageExecution:
    """Seed an ai_flux-sourced footage_search child for scene 1."""
    return StageExecution.objects.create(
        run=run,
        stage_key='footage_search',
        parent=footage_search_parent,
        shard_index=1,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scene_idx': 1,
            'asset_id': None,
            'media_type': 'image',
            'source': 'ai_flux',
            'license': '',
            'license_url': '',
            'attribution_required': False,
            'attribution': '',
            'source_url': '',
            'rerank_score': None,
            'candidates': [],
        },
    )


@pytest.mark.django_db
def test_provider_scene_exposes_license_and_candidates(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    provider_footage_child: StageExecution,
) -> None:
    """A provider-sourced scene reports its licence, source, and candidates."""
    presign = MagicMock()
    presign.presign_get.return_value = 'https://storage.example/scene0.mp4'

    board = documentary.get_storyboard(str(run.id), presign)

    row = next(row for row in board.scenes if row.idx == 0)
    assert row.source == 'pexels'
    assert row.license == 'Pexels License'
    assert row.asset_url == 'https://storage.example/scene0.mp4'
    assert row.status == StageStatus.SUCCEEDED
    assert len(row.candidates) == 2
    assert row.candidates[0].external_id == 'ext-1'
    assert row.candidates[1].duration_s is None


@pytest.mark.django_db
def test_ai_fallback_scene_has_no_candidates_and_counts_toward_fallback(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    ai_fallback_footage_child: StageExecution,
) -> None:
    """An ai_flux scene reports empty candidates and increments the count."""
    presign = MagicMock()

    board = documentary.get_storyboard(str(run.id), presign)

    row = next(row for row in board.scenes if row.idx == 1)
    assert row.source == 'ai_flux'
    assert row.candidates == []
    assert row.asset_url is None
    assert board.ai_fallback_count == 1


@pytest.mark.django_db
def test_scene_without_footage_shard_is_pending_with_no_asset(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
) -> None:
    """A scene lacking any footage_search shard is pending with no asset."""
    presign = MagicMock()

    board = documentary.get_storyboard(str(run.id), presign)

    row = next(row for row in board.scenes if row.idx == 2)
    assert row.asset_url is None
    assert row.status == StageStatus.PENDING
    assert row.candidates == []


@pytest.mark.django_db
def test_apply_scene_edit_returns_footage_queries(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
) -> None:
    """Applying a scene edit stales footage_queries, not visual_prompts."""
    stale_from = documentary.apply_scene_edit(
        str(run.id),
        0,
        {'narration_text': 'Updated narration for scene zero'},
    )

    assert stale_from == 'footage_queries'
    scene_breakdown_stage.refresh_from_db()
    scene = scene_breakdown_stage.output['scenes'][0]
    assert scene['narration_text'] == 'Updated narration for scene zero'


@pytest.mark.django_db
def test_apply_scene_edit_without_breakdown_still_returns_footage_queries(
    run: PipelineRun,
) -> None:
    """Applying an edit with no scene_breakdown output is a safe no-op."""
    stale_from = documentary.apply_scene_edit(
        str(run.id),
        0,
        {'narration_text': 'No breakdown yet'},
    )

    assert stale_from == 'footage_queries'


@pytest.mark.django_db
def test_apply_scene_edit_skips_non_dict_scene_entries(
    run: PipelineRun,
) -> None:
    """Non-dict entries in scene_breakdown output are skipped, not edited."""
    row = StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scenes': [
                'not-a-scene-dict',
                {'idx': 0, 'narration_text': 'Original narration'},
            ],
        },
    )

    stale_from = documentary.apply_scene_edit(
        str(run.id),
        0,
        {'narration_text': 'Edited narration'},
    )

    assert stale_from == 'footage_queries'
    row.refresh_from_db()
    assert row.output['scenes'][0] == 'not-a-scene-dict'
    assert row.output['scenes'][1]['narration_text'] == 'Edited narration'


@pytest.mark.django_db
def test_footage_state_skips_children_missing_scene_idx(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    footage_search_parent: StageExecution,
) -> None:
    """A footage_search child with no scene_idx is skipped, not mapped."""
    StageExecution.objects.create(
        run=run,
        stage_key='footage_search',
        parent=footage_search_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'asset_id': None},
    )
    presign = MagicMock()

    board = documentary.get_storyboard(str(run.id), presign)

    row = next(row for row in board.scenes if row.idx == 0)
    assert row.status == StageStatus.PENDING
    assert row.asset_url is None


@pytest.mark.django_db
def test_presign_asset_returns_none_when_asset_missing(
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    footage_search_parent: StageExecution,
) -> None:
    """A scene referencing a deleted/missing asset has no asset_url."""
    StageExecution.objects.create(
        run=run,
        stage_key='footage_search',
        parent=footage_search_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scene_idx': 0,
            'asset_id': '00000000-0000-0000-0000-000000000099',
            'media_type': 'video',
            'source': 'pexels',
        },
    )
    presign = MagicMock()

    board = documentary.get_storyboard(str(run.id), presign)

    row = next(row for row in board.scenes if row.idx == 0)
    assert row.asset_url is None
    presign.presign_get.assert_not_called()
