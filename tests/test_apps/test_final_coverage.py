"""Final coverage tests for remaining uncovered lines."""

import asyncio
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.urls import reverse
from dmr.endpoint import Endpoint
from dmr.test import DMRClient

from server.apps.channels.api.character_views import (
    CharacterDetailController,
    CharacterPromoteController,
    CharacterSessionDetailController,
    CharacterSheetExpandController,
)
from server.apps.channels.api.views import (
    YouTubeCallbackController,
    YouTubeConnectController,
)
from server.apps.channels.character_studio import CharacterStudioService
from server.apps.channels.logic.value_objects import CharacterPatchPayload
from server.apps.channels.models import (
    Channel,
    ChannelKind,
    Character,
    CharacterStatus,
    PublishMode,
)
from server.apps.clips.api.campaign_views import (
    CampaignCollectionController,
    CampaignDetailController,
    EarningCollectionController,
)
from server.apps.clips.api.source_views import (
    ClipSourceCollectionController,
    ClipSourceDetailController,
)
from server.apps.clips.models import ClipCampaign, ClipSource
from server.apps.ideas.api.views import (
    ChannelIdeaGenerateController,
    IdeaCollectionController,
)
from server.apps.pipelines.api.cast_views import (
    RunCastApproveController,
    RunCastDetailController,
    RunCastSessionDetailController,
)
from server.apps.pipelines.api.review_views import (
    RunPublishController,
    RunPublishMetadataController,
    RunSceneDetailController,
)
from server.apps.pipelines.api.views import RunCollectionController
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.services.orchestrator import (
    _advance_in_transaction,
    cancel_run_impl,
    pause_run_impl,
    resume_run_impl,
)
from server.apps.pipelines.storyboard_selectors import (
    _image_gen_state,
    get_preview,
)
from server.apps.prompts.api.views import (
    PromptTemplateDetailController,
    PromptVersionActivateController,
    StoryFormatDetailController,
)
from server.common.storage import PresignUrlHelper


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Final Cov Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
    )


@pytest.fixture
def character(channel: Channel) -> Character:
    return Character.objects.create(
        channel=channel,
        name='Final Character',
        appearance_prompt='hero',
    )


@pytest.fixture
def run(channel: Channel) -> PipelineRun:
    bp = PipelineBlueprint.objects.create(
        name='final_cov',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='final',
        status=RunStatus.RUNNING,
    )


def _super_handle_error(controller: object, exc: Exception) -> HttpResponse:
    controller_obj = controller  # type: ignore[assignment]
    endpoint = MagicMock(spec=Endpoint)
    fallback = HttpResponse(status=HTTPStatus.INTERNAL_SERVER_ERROR)
    with patch(
        'dmr.controller.Controller.handle_error',
        return_value=fallback,
    ) as mock_super:
        response = controller_obj.handle_error(  # type: ignore[attr-defined]
            endpoint,
            MagicMock(),
            exc,
        )
    assert response is fallback
    mock_super.assert_called_once()
    return response


@pytest.mark.django_db
def test_character_detail_patch_api(
    dmr_client: DMRClient,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    """PATCH character via API covers controller patch path."""
    response = dmr_client.patch(
        reverse(
            'api:channels_api:character-detail',
            kwargs={'character_id': character.id},
        ),
        data={'name': 'Renamed Hero'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['name'] == 'Renamed Hero'


@pytest.mark.django_db
def test_character_empty_patch_branches(character: Character) -> None:
    """Patch with no fields still saves character."""
    svc = CharacterStudioService()
    result = svc.patch(str(character.id), CharacterPatchPayload())
    assert result.id == str(character.id)


@pytest.mark.django_db
def test_campaign_get_detail(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """GET campaign detail covers controller get path."""
    campaign = ClipCampaign.objects.create(channel=channel, name='Detail')
    response = dmr_client.get(
        reverse(
            'api:clips:campaign-detail',
            kwargs={'campaign_id': campaign.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['name'] == 'Detail'


def test_character_detail_handle_error_super() -> None:
    """Unknown errors delegate to base handler."""
    _super_handle_error(CharacterDetailController(), RuntimeError('x'))


def test_character_promote_handle_error_super() -> None:
    _super_handle_error(CharacterPromoteController(), RuntimeError('x'))


def test_character_expand_handle_error_super() -> None:
    _super_handle_error(CharacterSheetExpandController(), RuntimeError('x'))


def test_campaign_detail_handle_error_super() -> None:
    _super_handle_error(CampaignDetailController(), RuntimeError('x'))


def test_earning_collection_handle_error_super() -> None:
    _super_handle_error(EarningCollectionController(), RuntimeError('x'))


def test_run_cast_handle_error_super() -> None:
    _super_handle_error(RunCastDetailController(), RuntimeError('x'))


def test_run_cast_approve_handle_error_super() -> None:
    _super_handle_error(RunCastApproveController(), RuntimeError('x'))


def test_scene_patch_handle_error_super() -> None:
    _super_handle_error(RunSceneDetailController(), RuntimeError('x'))


def test_run_collection_handle_error_super() -> None:
    _super_handle_error(RunCollectionController(), RuntimeError('x'))


def test_prompt_template_handle_error_super() -> None:
    _super_handle_error(PromptTemplateDetailController(), RuntimeError('x'))


def test_prompt_version_activate_handle_error_super() -> None:
    _super_handle_error(PromptVersionActivateController(), RuntimeError('x'))


def test_story_format_handle_error_super() -> None:
    _super_handle_error(StoryFormatDetailController(), RuntimeError('x'))


def test_run_publish_handle_error_super() -> None:
    _super_handle_error(RunPublishController(), RuntimeError('x'))


@pytest.mark.django_db(transaction=True)
def test_advance_in_transaction_skips_paused_run(run: PipelineRun) -> None:
    """Paused runs short-circuit before DAG evaluation."""
    run.is_paused = True
    run.save(update_fields=['is_paused'])
    to_enqueue, states = _advance_in_transaction(str(run.id))
    assert to_enqueue == []
    assert states == {}


@pytest.mark.django_db
def test_cancel_pause_resume_impl_publish_sse(run: PipelineRun) -> None:
    """Async lifecycle helpers publish SSE events."""

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.services.orchestrator.publish_sse',
                new=AsyncMock(),
            ) as mock_sse,
            patch(
                'server.apps.pipelines.services.orchestrator'
                '._cancel_run_sync_async',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator'
                '._pause_run_sync_async',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator'
                '._resume_run_sync_async',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.services.orchestrator'
                '.advance_pipeline_impl',
                new=AsyncMock(),
            ),
        ):
            await cancel_run_impl(str(run.id))
            await pause_run_impl(str(run.id))
            await resume_run_impl(str(run.id))
        assert mock_sse.await_count == 2

    asyncio.run(_inner())


@pytest.mark.django_db
def test_cancel_completed_run_noop(run: PipelineRun) -> None:
    """Cancelling a completed run is a no-op."""
    from server.apps.pipelines.services.orchestrator import _cancel_run_sync

    run.status = RunStatus.COMPLETED
    run.save(update_fields=['status'])
    _cancel_run_sync(str(run.id))
    run.refresh_from_db()
    assert run.status == RunStatus.COMPLETED


@pytest.mark.django_db
def test_image_gen_by_scene_skips_duplicate_shards(run: PipelineRun) -> None:
    """Duplicate shard indices are ignored when building scene map."""
    parent = StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'scene_idx': 0},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='image_gen',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        attempt=1,
        output={'scene_idx': 1},
    )
    mapping = _image_gen_state(str(run.id))
    assert 1 in mapping
    assert 0 not in mapping


@pytest.mark.django_db
def test_preview_missing_asset_id(run: PipelineRun) -> None:
    """Preview returns empty payload when assembly has no asset."""
    StageExecution.objects.create(
        run=run,
        stage_key='assembly',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={},
    )
    presign = MagicMock(spec=PresignUrlHelper)
    result = get_preview(str(run.id), presign)
    assert result.url is None


@pytest.mark.django_db
def test_resolve_publish_gate_fallback(
    channel: Channel,
    run: PipelineRun,
) -> None:
    """Publish gate resolution falls back to configured gate keys."""
    from server.apps.pipelines.services.run_review import _resolve_publish_gate

    assert _resolve_publish_gate(run, None) == 'final_gate'


@pytest.mark.django_db
def test_channel_patch_default_budget(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """PATCH channel default_budget_usd."""
    response = dmr_client.patch(
        reverse(
            'api:channels_api:channel-detail',
            kwargs={'channel_id': channel.id},
        ),
        data={'default_budget_usd': '25.50'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['default_budget_usd'] == '25.50'


def test_youtube_connect_handle_error_super() -> None:
    """YouTube connect unknown errors delegate to base handler."""
    _super_handle_error(YouTubeConnectController(), RuntimeError('x'))


def test_youtube_callback_handle_error_super() -> None:
    """YouTube callback unknown errors delegate to base handler."""
    _super_handle_error(YouTubeCallbackController(), RuntimeError('x'))


def test_earning_collection_validation_error() -> None:
    """Earning collection ValidationError returns 422."""
    controller = EarningCollectionController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(spec=Endpoint),
        MagicMock(),
        ValidationError('invalid earning'),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_campaign_list_invalid_limit_parsing() -> None:
    """Campaign list coerces invalid limit query values."""
    controller = CampaignCollectionController()
    controller.request = MagicMock()
    controller.request.GET.get = lambda key, default='20': (
        'bad' if key == 'limit' else default
    )
    controller.resolve = MagicMock(
        return_value=MagicMock(
            list_campaigns=MagicMock(
                return_value=MagicMock(items=[], total=0),
            ),
        ),
    )
    result = controller.get()
    assert result.total == 0


@pytest.mark.django_db
def test_youtube_connect_missing_redirect_uri(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """YouTube connect without redirect_uri returns 400."""
    response = dmr_client.get(
        reverse(
            'api:channels_api:youtube-connect',
            kwargs={'channel_id': channel.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_character_list_status_filter(
    dmr_client: DMRClient,
    channel: Channel,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    """Character list status filter branch."""
    character.status = CharacterStatus.APPROVED
    character.save(update_fields=['status'])
    url = (
        f'{reverse("api:channels_api:character-collection")}'
        f'?channel={channel.id}&status={CharacterStatus.APPROVED}'
    )
    response = dmr_client.get(url, headers=auth_headers)
    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 1


def test_clip_source_collection_handle_error_validation() -> None:
    """Clip source create ValidationError returns 422."""
    controller = ClipSourceCollectionController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(spec=Endpoint),
        MagicMock(),
        ValidationError('bad source'),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_clip_source_collection_handle_error_super() -> None:
    """Clip source create unknown errors delegate to base handler."""
    _super_handle_error(ClipSourceCollectionController(), RuntimeError('x'))


def test_clip_source_detail_handle_error_not_found() -> None:
    """Clip source detail maps DoesNotExist to 404."""
    controller = ClipSourceDetailController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(spec=Endpoint),
        MagicMock(),
        ClipSource.DoesNotExist(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_clip_source_detail_handle_error_validation() -> None:
    """Clip source detail ValidationError returns 422."""
    controller = ClipSourceDetailController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(spec=Endpoint),
        MagicMock(),
        ValidationError('bad source'),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_clip_source_detail_handle_error_super() -> None:
    """Clip source detail unknown errors delegate to base handler."""
    _super_handle_error(ClipSourceDetailController(), RuntimeError('x'))


def test_campaign_detail_handle_error_validation() -> None:
    """Campaign detail ValidationError returns 422."""
    controller = CampaignDetailController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(spec=Endpoint),
        MagicMock(),
        ValidationError('bad campaign'),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_character_session_detail_handle_error_super() -> None:
    """Character session detail unknown errors delegate to base handler."""
    _super_handle_error(
        CharacterSessionDetailController(),
        RuntimeError('x'),
    )


def test_run_cast_session_detail_handle_error_super() -> None:
    """Run cast session detail unknown errors delegate to base handler."""
    _super_handle_error(
        RunCastSessionDetailController(),
        RuntimeError('x'),
    )


def test_publish_metadata_handle_error_super() -> None:
    """Publish metadata unknown errors delegate to base handler."""
    _super_handle_error(RunPublishMetadataController(), RuntimeError('x'))


def test_idea_collection_handle_error_super() -> None:
    """Idea collection unknown errors delegate to base handler."""
    _super_handle_error(IdeaCollectionController(), RuntimeError('x'))


def test_channel_idea_generate_handle_error_validation() -> None:
    """Channel idea generate ValidationError returns 422."""
    controller = ChannelIdeaGenerateController()
    controller.request = MagicMock()
    response = controller.handle_error(
        MagicMock(spec=Endpoint),
        MagicMock(),
        ValidationError('bad channel'),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_channel_idea_generate_handle_error_super() -> None:
    """Channel idea generate unknown errors delegate to base handler."""
    _super_handle_error(ChannelIdeaGenerateController(), RuntimeError('x'))
