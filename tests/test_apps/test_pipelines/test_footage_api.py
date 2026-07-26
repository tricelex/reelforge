"""API tests for documentary review endpoints."""

import uuid
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import Asset, AssetKind, FootageCredit
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)

_RERUN_TARGET = 'server.apps.pipelines.services.run_review.rerun_stage_impl'


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Create a review channel shared by both blueprint profiles."""
    return Channel.objects.create(
        name='Footage Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
        default_budget_usd='25.00',
    )


@pytest.fixture
def ai_visual_blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Create a default blueprint with no ``profile`` key (ai_visual)."""
    return PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'scene_breakdown', 'depends_on': []}]},
    )


@pytest.fixture
def ai_visual_run(
    channel: Channel,
    ai_visual_blueprint: PipelineBlueprint,
) -> PipelineRun:
    """Create an ai_visual-profile run awaiting review."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=ai_visual_blueprint,
        blueprint_snapshot=ai_visual_blueprint.graph,
        topic='AI visual review',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='4.10',
    )


@pytest.fixture
def ai_visual_scene_breakdown_stage(
    ai_visual_run: PipelineRun,
) -> StageExecution:
    """Seed succeeded scene_breakdown output for the ai_visual run."""
    return StageExecution.objects.create(
        run=ai_visual_run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scenes': [
                {
                    'idx': 0,
                    'chapter_idx': 0,
                    'beat': 'cold_open',
                    'narration_text': 'The signal came from nowhere.',
                    'visual_concept': 'radio tower at dusk',
                    'est_seconds': 5.5,
                    'is_hero': True,
                    'foreground_cast': [],
                    'word_count': 6,
                },
            ],
        },
    )


@pytest.fixture
def documentary_blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Create a documentary_footage-profile blueprint graph."""
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
            ],
        },
    )


@pytest.fixture
def run(
    channel: Channel,
    documentary_blueprint: PipelineBlueprint,
) -> PipelineRun:
    """Create a documentary_footage run awaiting review."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=documentary_blueprint,
        blueprint_snapshot=documentary_blueprint.graph,
        topic='Documentary review',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='5.00',
    )


@pytest.fixture
def scene_breakdown_stage(run: PipelineRun) -> StageExecution:
    """Seed succeeded scene_breakdown output with one scene."""
    return StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scenes': [
                {
                    'idx': 0,
                    'narration_text': 'The vault stayed sealed for decades.',
                    'visual_concept': 'rusted vault door',
                    'est_seconds': 6.0,
                },
            ],
        },
    )


@pytest.fixture
def footage_search_parent(run: PipelineRun) -> StageExecution:
    """Seed the parent footage_search execution."""
    return StageExecution.objects.create(
        run=run,
        stage_key='footage_search',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
    )


@pytest.fixture
def footage_search_shard(
    run: PipelineRun,
    footage_search_parent: StageExecution,
) -> StageExecution:
    """Seed a footage_search child shard for scene 0 with two candidates."""
    return StageExecution.objects.create(
        run=run,
        stage_key='footage_search',
        parent=footage_search_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        input_snapshot={
            'scene_idx': 0,
            'primary_query': 'sealed bank vault door',
        },
        output={
            'scene_idx': 0,
            'asset_id': str(uuid.uuid4()),
            'media_type': 'video',
            'source': 'pexels',
            'license': 'Pexels License',
            'license_url': 'https://www.pexels.com/license/',
            'attribution_required': False,
            'attribution': 'Jane Doe',
            'source_url': 'https://pexels.com/video/123',
            'rerank_score': 0.8,
            'candidates': [
                {
                    'external_id': 'ext-1',
                    'provider': 'pexels',
                    'thumb_url': 'https://pexels.com/thumb/1',
                    'preview_url': 'https://pexels.com/preview/1',
                    'width': 1920,
                    'height': 1080,
                    'duration_s': 12.0,
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


@pytest.mark.django_db(transaction=True)
def test_storyboard_returns_profile_for_ai_visual_run(
    dmr_client: DMRClient,
    ai_visual_run: PipelineRun,
    ai_visual_scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """A longform_v1 run's storyboard reports profile == 'ai_visual'."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-storyboard',
            kwargs={'run_id': ai_visual_run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['profile'] == 'ai_visual'
    assert len(body['scenes']) == 1
    assert body['scenes'][0]['idx'] == 0
    assert body['scenes'][0]['narration'].startswith('The signal')


@pytest.mark.django_db(transaction=True)
def test_storyboard_returns_footage_fields_for_documentary_run(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    footage_search_shard: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """Documentary storyboard scenes expose footage-specific fields."""
    response = dmr_client.get(
        reverse('api:pipelines_api:run-storyboard', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['profile'] == 'documentary_footage'
    scene = body['scenes'][0]
    assert scene['media_type'] == 'video'
    assert scene['source'] == 'pexels'
    assert scene['license'] == 'Pexels License'
    assert scene['attribution_required'] is False
    assert len(scene['candidates']) == 2


@pytest.mark.django_db(transaction=True)
def test_select_candidate_requeues_only_that_shard(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    footage_search_shard: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """Selecting a candidate requeues only the footage_prep shard."""
    with patch(_RERUN_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-scene-select-candidate',
                kwargs={'run_id': run.id, 'scene_idx': 0},
            ),
            data={'external_id': 'ext-2'},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    mock_rerun.assert_called_once_with(
        str(run.id),
        'footage_prep',
        shard_indices=[0],
    )
    footage_search_shard.refresh_from_db()
    assert footage_search_shard.output['source'] == 'pixabay'
    assert footage_search_shard.output['selected_external_id'] == 'ext-2'


@pytest.mark.django_db(transaction=True)
def test_select_candidate_rejects_unknown_external_id(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    footage_search_shard: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """An unknown external_id is rejected without enqueuing anything."""
    with patch(_RERUN_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-scene-select-candidate',
                kwargs={'run_id': run.id, 'scene_idx': 0},
            ),
            data={'external_id': 'does-not-exist'},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    mock_rerun.assert_not_called()
    footage_search_shard.refresh_from_db()
    assert footage_search_shard.output['source'] == 'pexels'


@pytest.mark.django_db(transaction=True)
def test_research_footage_requeues_the_search_shard(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    footage_search_shard: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """A new operator query requeues only the footage_search shard."""
    with patch(_RERUN_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-scene-research-footage',
                kwargs={'run_id': run.id, 'scene_idx': 0},
            ),
            data={'query': 'abandoned bank vault door closeup'},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    mock_rerun.assert_called_once_with(
        str(run.id),
        'footage_search',
        shard_indices=[0],
    )
    footage_search_shard.refresh_from_db()
    assert (
        footage_search_shard.input_snapshot['primary_query']
        == 'abandoned bank vault door closeup'
    )


@pytest.mark.django_db(transaction=True)
def test_research_footage_rejects_an_empty_query(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    footage_search_shard: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """A blank query is rejected without enqueuing anything."""
    with patch(_RERUN_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-scene-research-footage',
                kwargs={'run_id': run.id, 'scene_idx': 0},
            ),
            data={'query': '   '},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    mock_rerun.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_research_footage_without_a_shard_still_enqueues(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """No prior footage_search shard exists yet; the query still enqueues."""
    with patch(_RERUN_TARGET) as mock_rerun:
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-scene-research-footage',
                kwargs={'run_id': run.id, 'scene_idx': 0},
            ),
            data={'query': 'bank vault interior night shot'},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    mock_rerun.assert_called_once_with(
        str(run.id),
        'footage_search',
        shard_indices=[0],
    )


@pytest.mark.django_db
def test_credits_endpoint_merges_duplicate_provider_and_source_url(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Two credit rows for the same clip merge into one entry's scene_idxs."""
    for scene_idx in (0, 1):
        asset = Asset.objects.create(
            kind=AssetKind.FOOTAGE,
            mime='video/mp4',
            checksum=f'shared-clip-{scene_idx}',
            run=run,
        )
        FootageCredit.objects.create(
            asset=asset,
            run=run,
            scene_idx=scene_idx,
            provider='pexels',
            license='Pexels License',
            license_url='https://www.pexels.com/license/',
            author='Jane Doe',
            source_url='https://pexels.com/video/reused-clip',
            title='Reused vault footage',
            attribution_required=False,
        )

    response = dmr_client.get(
        reverse('api:pipelines_api:run-credits', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert len(body['entries']) == 1
    assert body['entries'][0]['scene_idxs'] == [0, 1]


@pytest.mark.django_db
def test_credits_endpoint_lists_required_attributions_first(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """A required credit sorts ahead of an optional one."""
    optional_asset = Asset.objects.create(
        kind=AssetKind.FOOTAGE,
        mime='video/mp4',
        checksum='optional-credit',
        run=run,
    )
    FootageCredit.objects.create(
        asset=optional_asset,
        run=run,
        scene_idx=0,
        provider='pexels',
        license='Pexels License',
        license_url='https://www.pexels.com/license/',
        author='Jane Doe',
        source_url='https://pexels.com/video/1',
        title='Vault B-roll',
        attribution_required=False,
    )
    required_asset = Asset.objects.create(
        kind=AssetKind.FOOTAGE,
        mime='video/mp4',
        checksum='required-credit',
        run=run,
    )
    FootageCredit.objects.create(
        asset=required_asset,
        run=run,
        scene_idx=1,
        provider='pixabay',
        license='CC BY',
        license_url='https://pixabay.com/license/',
        author='John Roe',
        source_url='https://pixabay.com/video/2',
        title='Skyline shot',
        attribution_required=True,
    )

    response = dmr_client.get(
        reverse('api:pipelines_api:run-credits', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert len(body['entries']) == 2
    assert body['entries'][0]['attribution_required'] is True
    assert body['entries'][0]['provider'] == 'pixabay'
    assert body['truncated'] is False


@pytest.mark.django_db
def test_credits_endpoint_flags_truncation(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Excess optional credits are truncated; required ones are kept."""
    required_asset = Asset.objects.create(
        kind=AssetKind.FOOTAGE,
        mime='video/mp4',
        checksum='required-credit',
        run=run,
    )
    FootageCredit.objects.create(
        asset=required_asset,
        run=run,
        scene_idx=0,
        provider='aaa-required-provider',
        license='CC BY',
        license_url='https://example.com/license/',
        author='Required Author',
        source_url='https://example.com/required-video',
        title='Required credit that must survive truncation',
        attribution_required=True,
    )
    for i in range(40):
        asset = Asset.objects.create(
            kind=AssetKind.FOOTAGE,
            mime='video/mp4',
            checksum=f'optional-credit-{i}',
            run=run,
        )
        FootageCredit.objects.create(
            asset=asset,
            run=run,
            scene_idx=i + 1,
            provider=f'provider-number-{i}',
            license='Pexels License',
            license_url='https://www.pexels.com/license/',
            author=f'Optional Author Number {i}',
            source_url=(
                f'https://pexels.com/video/optional-clip-number-{i}-'
                'padding-to-make-this-source-url-long-enough'
            ),
            title=f'Optional stock footage clip number {i}',
            attribution_required=False,
        )

    response = dmr_client.get(
        reverse('api:pipelines_api:run-credits', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['truncated'] is True
    assert any(entry['attribution_required'] for entry in body['entries'])
    assert all(
        entry['attribution_required']
        for entry in body['entries']
        if entry['provider'] == 'aaa-required-provider'
    )
