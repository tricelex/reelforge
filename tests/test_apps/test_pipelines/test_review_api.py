"""Tests for longform review DMR API."""

import uuid
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from dmr.test import DMRClient

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


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Create a longform review channel with final_gate."""
    return Channel.objects.create(
        name='Review Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
        default_budget_usd='30.00',
    )


@pytest.fixture
def blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Create a longform blueprint graph for review stages."""
    return PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'scene_breakdown', 'depends_on': []},
                {'key': 'visual_prompts', 'depends_on': ['scene_breakdown']},
                {'key': 'image_gen', 'depends_on': ['visual_prompts']},
                {'key': 'assembly', 'depends_on': ['image_gen']},
                {
                    'key': 'final_gate',
                    'depends_on': ['assembly'],
                    'gate': True,
                },
                {'key': 'publish', 'depends_on': ['final_gate']},
            ],
        },
    )


@pytest.fixture
def run(channel: Channel, blueprint: PipelineBlueprint) -> PipelineRun:
    """Create a run awaiting longform review."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Review topic',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='6.41',
    )


@pytest.fixture
def scene_breakdown_stage(run: PipelineRun) -> StageExecution:
    """Seed succeeded scene_breakdown output."""
    return StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'scenes': [
                {
                    'idx': 0,
                    'chapter_idx': 0,
                    'beat': 'cold_open',
                    'narration_text': 'The lights went dark…',
                    'visual_concept': 'dark street',
                    'shot_type': 'wide',
                    'est_seconds': 8.5,
                    'is_hero': True,
                    'foreground_cast': ['detective_mara'],
                    'word_count': 12,
                },
            ],
        },
    )


@pytest.fixture
def visual_prompts_stage(run: PipelineRun) -> StageExecution:
    """Seed succeeded visual_prompts output."""
    return StageExecution.objects.create(
        run=run,
        stage_key='visual_prompts',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'prompts': [
                {
                    'scene_idx': 0,
                    'prompt': 'noir street at night',
                    'negative_prompt': '',
                },
            ],
        },
    )


@pytest.fixture
def image_gen_parent(run: PipelineRun) -> StageExecution:
    """Seed parent image_gen execution."""
    return StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
    )


@pytest.fixture
def image_gen_child(
    run: PipelineRun,
    image_gen_parent: StageExecution,
) -> StageExecution:
    """Seed child image_gen shard with asset output."""
    asset = Asset.objects.create(
        kind=AssetKind.IMAGE,
        file=ContentFile(b'\x89PNG', name='scene.png'),
        mime='image/png',
        checksum='abc123',
        run=run,
    )
    return StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        parent=image_gen_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        cost_usd='0.06',
        output={
            'scene_idx': 0,
            'asset_id': str(asset.id),
            'seed': 42817,
        },
    )


@pytest.mark.django_db(transaction=True)
def test_storyboard(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
    image_gen_child: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """GET storyboard merges breakdown, prompts, and image_gen state."""
    StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )

    with patch(
        'server.apps.pipelines.storyboard_selectors._presign_asset',
        return_value='https://storage.example/image',
    ):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-storyboard',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['run']['gate'] == 'final_gate'
    assert body['run']['spent_usd'] == '6.4100'
    assert len(body['scenes']) == 1
    assert body['scenes'][0]['idx'] == 0
    assert body['scenes'][0]['image']['seed'] == 42817


@pytest.mark.django_db(transaction=True)
def test_patch_scene(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH scene updates breakdown and stales downstream stages."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={
            'narration_text': 'Updated narration text here now',
            'is_hero': False,
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['is_hero'] is False

    breakdown = StageExecution.objects.get(id=scene_breakdown_stage.id)
    scene = breakdown.output['scenes'][0]
    assert scene['narration_text'].startswith('Updated narration')


@pytest.mark.django_db(transaction=True)
def test_patch_scene_sets_had_manual_edits(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH scene marks the run as having had a manual edit."""
    assert run.had_manual_edits is False

    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'narration_text': 'Updated narration text here now'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    run.refresh_from_db()
    assert run.had_manual_edits is True


@pytest.mark.django_db
def test_publish_metadata_patch_sets_had_manual_edits(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """PATCH publish-metadata marks the run as having had a manual edit."""
    StageExecution.objects.create(
        run=run,
        stage_key='metadata',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'title': 'Original title',
            'description': 'Original description',
            'tags': ['history'],
            'category': 'Education',
        },
    )
    assert run.had_manual_edits is False

    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-publish-metadata',
            kwargs={'run_id': run.id},
        ),
        data={'title': 'Updated title'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    run.refresh_from_db()
    assert run.had_manual_edits is True


@pytest.mark.django_db(transaction=True)
def test_preview(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET preview returns presigned assembly video URL."""
    asset = Asset.objects.create(
        kind=AssetKind.FINAL_VIDEO,
        file=ContentFile(b'video', name='final.mp4'),
        mime='video/mp4',
        checksum='final123',
        run=run,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='assembly',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'asset_id': str(asset.id), 'duration_s': 120.5},
    )

    with patch(
        'server.apps.pipelines.storyboard_selectors._presign_asset',
        return_value='https://storage.example/final.mp4',
    ):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-preview',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['url'] == 'https://storage.example/final.mp4'
    assert body['duration_s'] == pytest.approx(120.5)


@pytest.mark.django_db(transaction=True)
def test_publish_approves_gate(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST publish approves final_gate and resumes the pipeline."""
    StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )

    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(return_value=None),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-publish',
                kwargs={'run_id': run.id},
            ),
            data={
                'thumbnail_asset_id': None,
                'schedule_at': '2026-07-01T18:00:00+00:00',
            },
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['gate_key'] == 'final_gate'

    gate = StageExecution.objects.get(run=run, stage_key='final_gate')
    assert gate.status == StageStatus.SUCCEEDED
    assert gate.output['schedule_at'] == '2026-07-01T18:00:00+00:00'


@pytest.mark.django_db(transaction=True)
def test_scene_breakdown(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """GET scene-breakdown returns scene rows."""
    with patch(
        'server.apps.pipelines.storyboard_selectors._presign_asset',
        return_value='https://storage.example/image',
    ):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-scene-breakdown',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['total'] == 1
    assert body['scenes'][0]['narration'].startswith('The lights')


@pytest.mark.django_db(transaction=True)
def test_storyboard_without_breakdown(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Storyboard returns empty scenes when breakdown is missing."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-storyboard',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['scenes'] == []


@pytest.mark.django_db(transaction=True)
def test_storyboard_gate_not_armed(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """Running gate hidden when not listed on channel."""
    StageExecution.objects.create(
        run=run,
        stage_key='unknown_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )

    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-storyboard',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['run']['gate'] is None


@pytest.mark.django_db(transaction=True)
def test_preview_empty_when_no_assembly(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Preview returns nulls when assembly has not succeeded."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-preview',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['url'] is None
    assert body['asset_id'] is None


@pytest.mark.django_db(transaction=True)
def test_patch_scene_validation_errors(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """PATCH scene returns 422 when breakdown is unavailable."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'narration_text': 'No breakdown yet'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_patch_scene_invalid_breakdown_output(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """PATCH scene returns 422 when breakdown scenes is not a list."""
    StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'scenes': 'not-a-list'},
    )

    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'narration_text': 'Bad output'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_patch_scene_not_found(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH missing scene index returns 422."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 99},
        ),
        data={'narration_text': 'Missing scene'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_patch_scene_visual_fields_without_visual_prompts(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH visual fields when visual_prompts stage is absent."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={
            'visual_concept': 'rainy alley',
            'foreground_cast': ['detective_mara', 'informant'],
            'is_hero': True,
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['cast'] == ['detective_mara', 'informant']


@pytest.mark.django_db(transaction=True)
def test_patch_scene_updates_visual_prompts(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH visual_prompt overrides prompt row in visual_prompts output."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'visual_prompt': 'neon alley with fog'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    vp = StageExecution.objects.get(id=visual_prompts_stage.id)
    assert vp.output['prompts'][0]['prompt'] == 'neon alley with fog'


@pytest.mark.django_db(transaction=True)
def test_patch_scene_stales_downstream_terminal_stages(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH scene marks downstream terminal stages stale."""
    image_gen = StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )

    dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'narration_text': 'Stale downstream stages now'},
        headers=auth_headers,
    )

    image_gen.refresh_from_db()
    assert image_gen.status == StageStatus.STALE


@pytest.mark.django_db(transaction=True)
def test_publish_resolves_review_gate(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST publish resolves review_gate from channel config."""
    channel.gates = ['review_gate']
    channel.save(update_fields=['gates'])
    review_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Review gate topic',
        status=RunStatus.AWAITING_REVIEW,
    )
    StageExecution.objects.create(
        run=review_run,
        stage_key='review_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )

    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(return_value=None),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-publish',
                kwargs={'run_id': review_run.id},
            ),
            data={'gate_key': None},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['gate_key'] == 'review_gate'


@pytest.mark.django_db(transaction=True)
def test_publish_no_active_gate(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST publish returns 422 when no gate can be resolved."""
    channel.gates = []
    channel.save(update_fields=['gates'])
    bare_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='No gate topic',
        status=RunStatus.AWAITING_REVIEW,
    )

    response = dmr_client.post(
        reverse(
            'api:pipelines_api:run-publish',
            kwargs={'run_id': bare_run.id},
        ),
        data={},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_publish_metadata_get_and_patch(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET/PATCH publish-metadata reads and updates metadata stage output."""
    StageExecution.objects.create(
        run=run,
        stage_key='metadata',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'title': 'Original title',
            'description': 'Original description',
            'tags': ['history'],
            'category': 'Education',
        },
    )
    get_resp = dmr_client.get(
        reverse(
            'api:pipelines_api:run-publish-metadata',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )
    assert get_resp.status_code == HTTPStatus.OK
    assert get_resp.json()['title'] == 'Original title'

    patch_resp = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-publish-metadata',
            kwargs={'run_id': run.id},
        ),
        data={
            'title': 'Updated title',
            'description': 'Updated description',
            'tags': ['rome', 'empire'],
        },
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    body = patch_resp.json()
    assert body['title'] == 'Updated title'
    assert body['description'] == 'Updated description'
    assert body['tags'] == ['rome', 'empire']


@pytest.mark.django_db
def test_publish_metadata_handle_error_not_found() -> None:
    """Publish metadata controller maps missing run to 404."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.api.review_views import (
        RunPublishMetadataController,
    )

    controller = RunPublishMetadataController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(),
        controller,
        PipelineRun.DoesNotExist(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_publish_metadata_patch_category_and_thumbnail(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """PATCH publish-metadata can update category and thumbnail."""
    StageExecution.objects.create(
        run=run,
        stage_key='metadata',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'title': 'T', 'description': 'D', 'tags': []},
    )
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-publish-metadata',
            kwargs={'run_id': run.id},
        ),
        data={
            'category': 'Entertainment',
            'thumbnail_asset_id': str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['category'] == 'Entertainment'


@pytest.mark.django_db
def test_publish_metadata_get_empty_when_missing_stage(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET publish-metadata returns defaults when metadata stage is absent."""
    get_resp = dmr_client.get(
        reverse(
            'api:pipelines_api:run-publish-metadata',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )
    assert get_resp.status_code == HTTPStatus.OK
    assert get_resp.json()['title'] == ''


@pytest.mark.django_db
def test_publish_metadata_patch_requires_stage(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """PATCH publish-metadata fails when metadata stage output is missing."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-publish-metadata',
            kwargs={'run_id': run.id},
        ),
        data={'title': 'No stage'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_publish_with_metadata_and_thumbnail(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST publish patches metadata and passes thumbnail to gate output."""
    from server.apps.assets.models import Asset, AssetKind
    from server.apps.publishing.models import PublishJob

    StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='metadata',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'title': 'Original title', 'tags': ['old']},
    )
    thumb = Asset.objects.create(
        kind=AssetKind.IMAGE,
        mime='image/png',
        checksum='thumb123',
        run=run,
    )
    PublishJob.objects.create(run=run, channel=run.channel)

    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(return_value=None),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-publish',
                kwargs={'run_id': run.id},
            ),
            data={
                'gate_key': 'final_gate',
                'thumbnail_asset_id': str(thumb.id),
                'metadata_patch': {'title': 'Updated title'},
            },
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['publish_job_id'] is not None

    meta = StageExecution.objects.get(run=run, stage_key='metadata')
    assert meta.output['title'] == 'Updated title'

    gate = StageExecution.objects.get(run=run, stage_key='final_gate')
    assert gate.output['thumbnail_asset_id'] == str(thumb.id)


@pytest.mark.django_db(transaction=True)
def test_publish_run_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST publish for missing run returns client error."""
    missing_id = uuid.uuid4()

    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(return_value=None),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-publish',
                kwargs={'run_id': missing_id},
            ),
            data={'gate_key': 'final_gate'},
            headers=auth_headers,
        )

    assert response.status_code in {
        HTTPStatus.NOT_FOUND,
        HTTPStatus.UNPROCESSABLE_ENTITY,
    }


@pytest.mark.django_db
def test_run_publish_handle_error_not_found() -> None:
    """Publish controller maps missing run to 404."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.api.review_views import RunPublishController
    from server.apps.pipelines.models import PipelineRun

    controller = RunPublishController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(),
        controller,
        PipelineRun.DoesNotExist(),
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db(transaction=True)
def test_storyboard_image_without_asset_file(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    image_gen_parent: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """Storyboard omits URL when asset has no stored file."""
    asset = Asset.objects.create(
        kind=AssetKind.IMAGE,
        mime='image/png',
        checksum='no-file',
        run=run,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        parent=image_gen_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'scene_idx': 0, 'asset_id': str(asset.id)},
    )

    with patch(
        'server.apps.pipelines.storyboard_selectors._presign_asset',
        return_value='',
    ):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-storyboard',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    scene = response.json()['scenes'][0]
    assert scene['image'] is not None
    assert scene['image']['url'] == ''


@pytest.mark.django_db(transaction=True)
def test_publish_uses_running_gate(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST publish prefers the currently running gate execution."""
    StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )

    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(return_value=None),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-publish',
                kwargs={'run_id': run.id},
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['gate_key'] == 'final_gate'


@pytest.mark.django_db(transaction=True)
def test_patch_scene_syncs_visual_concept_to_prompts(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH visual_concept updates prompt when visual_prompt omitted."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'visual_concept': 'misty pier at dawn'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    vp = StageExecution.objects.get(id=visual_prompts_stage.id)
    assert vp.output['prompts'][0]['prompt'] == 'misty pier at dawn'


@pytest.mark.django_db(transaction=True)
def test_patch_scene_when_visual_prompts_not_succeeded(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH skips visual_prompts sync when that stage has not succeeded."""
    StageExecution.objects.create(
        run=run,
        stage_key='visual_prompts',
        status=StageStatus.PENDING,
        attempt=0,
        output={'prompts': []},
    )
    image_gen = StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )

    dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'narration_text': 'Skip visual prompts sync'},
        headers=auth_headers,
    )

    image_gen.refresh_from_db()
    assert image_gen.status == StageStatus.STALE


@pytest.mark.django_db(transaction=True)
def test_storyboard_scene_without_image_asset(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    image_gen_parent: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """Storyboard scene has no image payload when shard lacks asset_id."""
    StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        parent=image_gen_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'scene_idx': 0},
    )

    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-storyboard',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['scenes'][0]['image'] is None


@pytest.mark.django_db(transaction=True)
def test_preview_assembly_not_succeeded(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Preview returns nulls when assembly exists but has not succeeded."""
    StageExecution.objects.create(
        run=run,
        stage_key='assembly',
        status=StageStatus.RUNNING,
        attempt=0,
        output={'asset_id': '00000000-0000-0000-0000-000000000001'},
    )

    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-preview',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['url'] is None


@pytest.mark.django_db(transaction=True)
def test_publish_resolves_storyboard_gate(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST publish resolves storyboard_gate from channel config."""
    channel.gates = ['storyboard_gate']
    channel.save(update_fields=['gates'])
    review_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Storyboard gate topic',
        status=RunStatus.AWAITING_REVIEW,
    )
    StageExecution.objects.create(
        run=review_run,
        stage_key='storyboard_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )

    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(return_value=None),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-publish',
                kwargs={'run_id': review_run.id},
            ),
            data={'gate_key': 'storyboard_gate'},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['gate_key'] == 'storyboard_gate'


@pytest.mark.django_db(transaction=True)
def test_patch_scene_invalid_visual_prompts_output(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH skips visual_prompts sync when prompts is not a list."""
    StageExecution.objects.create(
        run=run,
        stage_key='visual_prompts',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'prompts': 'invalid'},
    )

    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'visual_concept': 'updated concept only'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
