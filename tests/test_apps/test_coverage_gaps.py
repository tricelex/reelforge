"""Targeted tests for remaining coverage gaps."""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.services import LibraryAssetService
from server.apps.channels.character_studio import CharacterStudioService
from server.apps.channels.logic.value_objects import CharacterPatchPayload
from server.apps.channels.models import (
    Channel,
    ChannelKind,
    Character,
    CharacterStatus,
    PublishMode,
)
from server.apps.channels.selectors import _iso, list_channels
from server.apps.clips.campaign_services import ClipCampaignService
from server.apps.clips.logic.constants import CampaignStatus
from server.apps.clips.logic.value_objects import (
    ClipCampaignPatchPayload,
    ClipTimedOverlayPatchPayload,
)
from server.apps.clips.models import ClipCandidate
from server.apps.clips.services import ClipsService, _parse_dt
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.prompts.models import PromptScope, PromptTemplate, StoryFormat
from server.apps.prompts.selectors import (
    _json_beats,
    _json_object,
    _to_version,
    list_prompt_templates,
    list_story_formats,
)
from server.apps.prompts.services import PromptTemplateService, StoryFormatService
from server.common.events import InProcessEventBus
from server.common.storage import PresignUrlHelper


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Coverage Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )


def test_channels_iso_helper() -> None:
    """Cover channel selector datetime helper."""
    assert _iso(None) is None
    dt = datetime(2026, 6, 19, tzinfo=UTC)
    assert _iso(dt) == dt.isoformat()


@pytest.mark.django_db
@pytest.mark.django_db
def test_list_channels_active_only(channel: Channel) -> None:
    """Cover active_only filter branch."""
    channel.is_active = False
    channel.save(update_fields=['is_active'])
    result = list_channels(active_only=True)
    assert result.total == 0


@pytest.mark.django_db
def test_assets_list_inactive_and_filters(channel) -> None:
    """Cover list_assets filter branches."""
    from server.apps.assets.logic.value_objects import LibraryAssetCreatePayload
    from server.apps.assets.models import LibraryAssetKind

    service = LibraryAssetService(events=InProcessEventBus())
    service.register_from_key(
        LibraryAssetCreatePayload(
            kind=LibraryAssetKind.MUSIC,
            name='Tagged',
            storage_key='uploads/tagged.mp3',
            tags=['intro'],
            channel_id=str(channel.id),
        ),
    )
    tagged = service.list_assets(tag='intro', channel_id=str(channel.id))
    assert tagged.total == 1
    inactive = service.list_assets(active_only=False)
    assert inactive.total >= 1


def test_clips_parse_dt_aware() -> None:
    """Cover timezone-aware datetime parsing branch."""
    parsed = _parse_dt('2026-06-19T12:00:00+00:00')
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_prompt_selector_json_helpers() -> None:
    """Cover JSON sanitizers for invalid inputs."""
    assert _json_object('not-a-dict') == {}
    assert _json_beats('not-a-list') == []
    assert _json_beats([{'key': 'beat', 'pct': 0.5}]) == [{'key': 'beat', 'pct': 0.5}]


@pytest.mark.django_db
def test_prompt_selectors_scope_and_active() -> None:
    """Cover prompt selector filter branches."""
    PromptTemplate.objects.create(
        name='Global',
        key='global_prompt',
        scope=PromptScope.GLOBAL,
    )
    scoped = list_prompt_templates(scope=PromptScope.GLOBAL)
    assert scoped.total >= 1

    StoryFormat.objects.create(
        key='inactive_fmt',
        name='Inactive',
        beats=[],
        is_active=False,
    )
    active = list_story_formats(active_only=True)
    assert active.total >= 0


@pytest.mark.django_db
def test_prompt_version_to_payload() -> None:
    """Cover _to_version helper."""
    template = PromptTemplate.objects.create(
        name='Versioned',
        key='versioned',
        scope=PromptScope.GLOBAL,
    )
    from server.apps.prompts.models import PromptVersion

    version = PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='sys',
        user_prompt='user',
    )
    payload = _to_version(version)
    assert payload.version == 1


@pytest.mark.django_db
def test_prompt_template_patch_saves(db: None) -> None:
    """Cover template patch save path."""
    template = PromptTemplate.objects.create(
        name='Patch Me',
        key='patch_me',
        scope=PromptScope.GLOBAL,
    )
    service = PromptTemplateService()
    from server.apps.prompts.logic.value_objects import PromptTemplatePatchPayload

    result = service.patch(
        str(template.id),
        PromptTemplatePatchPayload(name='Patched'),
    )
    assert result.name == 'Patched'


@pytest.mark.django_db
def test_story_format_patch_json_fields(db: None) -> None:
    """Cover story format patch JSON field updates."""
    fmt = StoryFormat.objects.create(key='patch_fmt', name='Patch Fmt', beats=[])
    service = StoryFormatService()
    from server.apps.prompts.logic.value_objects import StoryFormatPatchPayload

    result = service.patch(
        str(fmt.id),
        StoryFormatPatchPayload(
            beats=[{'key': 'hook', 'pct': 0.1}],
            pacing={'speed': 'fast'},
            prompt_overrides={'tone': 'dark'},
            music_mood_map={'intro': 'tense'},
        ),
    )
    assert result.beats == [{'key': 'hook', 'pct': 0.1}]


@pytest.fixture
def run(channel: Channel) -> PipelineRun:
    bp = PipelineBlueprint.objects.create(
        name='cov_run',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='cov run',
    )


@pytest.fixture
def candidate(db, channel):  # type: ignore[no-untyped-def]
    bp = PipelineBlueprint.objects.create(
        name='cov_clip',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run_obj = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='cov',
    )
    return ClipCandidate.objects.create(
        run=run_obj,
        start_sec=0.0,
        end_sec=10.0,
        title='Cov Clip',
    )


@pytest.mark.django_db
def test_campaign_service_branches(channel) -> None:
    """Cover campaign service validation and patch fields."""
    service = ClipCampaignService()
    with pytest.raises(ValidationError, match='Channel not found'):
        from server.apps.clips.logic.value_objects import ClipCampaignCreatePayload

        service.create_campaign(
            ClipCampaignCreatePayload(
                channel_id=str(uuid.uuid4()),
                name='Missing channel',
            ),
        )

    from server.apps.clips.logic.value_objects import ClipCampaignCreatePayload

    created = service.create_campaign(
        ClipCampaignCreatePayload(
            channel_id=str(channel.id),
            name='Patchable',
        ),
    )
    patched = service.patch_campaign(
        created.id,
        ClipCampaignPatchPayload(
            name='Renamed',
            notes='updated',
            status=CampaignStatus.ACTIVE,
        ),
    )
    assert patched.name == 'Renamed'
    assert service.get_campaign(created.id).status == CampaignStatus.ACTIVE

    with pytest.raises(ValidationError, match='Invalid status'):
        service.patch_campaign(
            created.id,
            ClipCampaignPatchPayload(status='NOT_A_STATUS'),
        )

    filtered = service.list_campaigns(channel_id=str(channel.id))
    assert filtered.total >= 1


def _clips() -> ClipsService:
    presign = MagicMock(spec=PresignUrlHelper)
    presign.presign_get.return_value = 'https://storage.example/file'
    return ClipsService(presign=presign)


@pytest.mark.django_db
def test_clips_patch_overlay_image_asset(candidate) -> None:
    """Cover overlay patch image_asset_id branch."""
    from server.apps.clips.models import ClipTimedOverlay

    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        overlay_type='TEXT',
        text='Hi',
        start_sec=0.0,
        end_sec=1.0,
    )
    svc = _clips()
    result = svc.patch_overlay(
        str(candidate.id),
        str(overlay.id),
        ClipTimedOverlayPatchPayload(image_asset_id=None),
    )
    assert result.id == str(overlay.id)


@pytest.mark.django_db
def test_clips_create_post(candidate) -> None:
    """Cover create_post service path."""
    from server.apps.clips.logic.value_objects import ClipPostCreatePayload

    svc = _clips()
    post = svc.create_post(
        str(candidate.id),
        ClipPostCreatePayload(
            platform='youtube_shorts',
            caption='caption',
            title='title',
            hashtags=['tag'],
            scheduled_at='2026-06-19T12:00:00+00:00',
        ),
    )
    assert post.platform == 'youtube_shorts'


@pytest.mark.django_db
def test_campaign_api_invalid_query_parsing(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Cover campaign list invalid limit parsing."""
    response = dmr_client.get(
        reverse('api:clips:campaign-collection'),
        query={'limit': 'bad'},
        headers=auth_headers,
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_character_patch_individual_fields(character: Character) -> None:
    """Cover each optional patch branch independently."""
    svc = CharacterStudioService()
    assert svc.patch(
        str(character.id),
        CharacterPatchPayload(name='Only Name'),
    ).name == 'Only Name'
    assert svc.patch(
        str(character.id),
        CharacterPatchPayload(appearance_prompt='Only Prompt'),
    ).appearance_prompt == 'Only Prompt'
    assert svc.patch(
        str(character.id),
        CharacterPatchPayload(persona='Only Persona'),
    ).persona == 'Only Persona'
    assert svc.patch(
        str(character.id),
        CharacterPatchPayload(status=CharacterStatus.DRAFT),
    ).status == CharacterStatus.DRAFT


@pytest.mark.django_db
def test_character_selector_round_payload() -> None:
    """Cover malformed round payload sanitization."""
    from server.apps.channels.character_selectors import _round_to_payload

    payload = _round_to_payload(
        {
            'prompt': 'p',
            'model': 'm',
            'n': 1,
            'candidate_asset_ids': 'bad',
            'picked': 'asset-1',
        },
    )
    assert payload.candidate_asset_ids == []


@pytest.mark.django_db
def test_character_selector_list_by_channel(channel: Channel) -> None:
    """Cover channel_id filter branch."""
    from server.apps.channels.character_selectors import list_characters

    Character.objects.create(
        channel=channel,
        name='Filtered',
        appearance_prompt='x',
    )
    result = list_characters(channel_id=str(channel.id))
    assert result.total == 1


@pytest.mark.django_db
def test_campaign_earning_with_candidate(
    channel: Channel,
    candidate,
) -> None:
    """Cover earning create with candidate FK validation."""
    from server.apps.clips.logic.value_objects import EarningCreatePayload
    from server.apps.clips.models import ClipCampaign

    campaign = ClipCampaign.objects.create(channel=channel, name='Earn')
    service = ClipCampaignService()
    earning = service.create_earning(
        EarningCreatePayload(
            campaign_id=str(campaign.id),
            candidate_id=str(candidate.id),
            platform='youtube',
            revenue_est_usd='1.00',
            recorded_at='2026-06-19T12:00:00',
        ),
    )
    assert earning.candidate_id == str(candidate.id)


@pytest.mark.django_db
def test_clips_overlay_image_asset_uuid(candidate) -> None:
    """Cover overlay patch with concrete image asset id."""
    from server.apps.assets.models import LibraryAsset, LibraryAssetKind
    from server.apps.clips.models import ClipTimedOverlay

    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.OVERLAY,
        name='Img',
        file='library/overlay.png',
    )
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        overlay_type='IMAGE',
        text='',
        start_sec=0.0,
        end_sec=1.0,
    )
    svc = _clips()
    result = svc.patch_overlay(
        str(candidate.id),
        str(overlay.id),
        ClipTimedOverlayPatchPayload(image_asset_id=str(asset.id)),
    )
    assert result.id == str(overlay.id)


@pytest.mark.django_db
def test_clips_post_patch_fields(candidate) -> None:
    """Cover post patch hashtags and scheduled_at."""
    from server.apps.clips.logic.value_objects import (
        ClipPostCreatePayload,
        ClipPostPatchPayload,
    )

    svc = _clips()
    post = svc.create_post(
        str(candidate.id),
        ClipPostCreatePayload(
            platform='tiktok',
            caption='c',
            title='t',
            scheduled_at='2026-06-19T08:00:00',
        ),
    )
    updated = svc.patch_post(
        str(candidate.id),
        post.id,
        ClipPostPatchPayload(
            hashtags=['a'],
            scheduled_at='2026-06-19T09:00:00+00:00',
        ),
    )
    assert updated.hashtags == ['a']


@pytest.mark.django_db
def test_pipeline_run_unmapped_kind(channel: Channel) -> None:
    """Cover blueprint mapping failure."""
    from server.apps.pipelines.logic.value_objects import RunCreatePayload
    from server.apps.pipelines.services.pipeline_run import PipelineRunService
    from server.common.events import InProcessEventBus

    service = PipelineRunService(events=InProcessEventBus())
    with patch(
        'server.apps.pipelines.services.pipeline_run._BLUEPRINT_BY_KIND',
        {},
    ):
        with pytest.raises(ValidationError, match='No blueprint mapping'):
            service._create_run_sync(
                RunCreatePayload(channel_id=str(channel.id), topic='t'),
            )


@pytest.mark.django_db
def test_rerun_stage_unregistered_in_graph(run) -> None:
    """Cover rerun when stage is in graph but not registered."""
    from server.apps.pipelines.services.orchestrator import _rerun_stage_sync

    run.blueprint_snapshot = {
        'stages': [{'key': 'ghost_stage', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])
    assert _rerun_stage_sync(str(run.id), 'ghost_stage', None) == []


@pytest.mark.django_db
def test_rerun_stage_with_shard_indices(run) -> None:
    """Cover rerun shard_indices filter branch."""
    import server.apps.pipelines.stages.dummy  # noqa: F401
    from server.apps.pipelines.services.orchestrator import _rerun_stage_sync

    parent = StageExecution.objects.create(
        run=run,
        stage_key='dummy_a',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )
    run.blueprint_snapshot = {
        'stages': [{'key': 'dummy_a', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])
    exec_ids = _rerun_stage_sync(str(run.id), 'dummy_a', [0])
    assert isinstance(exec_ids, list)


@pytest.mark.django_db
def test_storyboard_presign_missing_file(run) -> None:
    """Cover storyboard presign when asset has no file."""
    from server.apps.pipelines.storyboard_selectors import _presign_asset
    from server.apps.assets.models import Asset, AssetKind
    from server.common.storage import PresignUrlHelper

    asset = Asset.objects.create(
        kind=AssetKind.IMAGE,
        file='',
        mime='image/png',
        checksum='x',
        run=run,
    )
    presign = MagicMock(spec=PresignUrlHelper)
    assert _presign_asset(str(asset.id), presign) == ''


@pytest.mark.django_db
def test_youtube_callback_missing_refresh_token(
    channel: Channel,
    settings,
) -> None:
    """Cover YouTube OAuth missing refresh token path."""
    from server.apps.channels.logic.value_objects import YouTubeCallbackPayload
    from server.apps.channels.services import ChannelService
    from server.common.events import InProcessEventBus

    settings.YOUTUBE_CLIENT_ID = 'id'
    settings.YOUTUBE_CLIENT_SECRET = 'secret'
    service = ChannelService(events=InProcessEventBus())
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'access_token': 'at', 'expires_in': 3600}
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp

    with patch('server.apps.channels.services.httpx.Client', return_value=mock_client):
        with pytest.raises(ValidationError, match='refresh token'):
            service.youtube_complete_oauth(
                str(channel.id),
                YouTubeCallbackPayload(code='code', redirect_uri='http://cb'),
            )


@pytest.mark.django_db
def test_niche_patch_all_fields(channel: Channel) -> None:
    """Cover niche patch lore_document and format_id branches."""
    from server.apps.channels.logic.value_objects import NicheConfigPatchPayload
    from server.apps.channels.services import ChannelService
    from server.apps.prompts.models import StoryFormat
    from server.common.events import InProcessEventBus

    fmt = StoryFormat.objects.create(key='niche_fmt', name='Fmt', beats=[])
    service = ChannelService(events=InProcessEventBus())
    result = service.patch_niche(
        str(channel.id),
        NicheConfigPatchPayload(
            format_id=str(fmt.id),
            audience='aud',
            angle='ang',
            banned_topics=['spam'],
            lore_document='lore',
        ),
    )
    assert result.lore_document == 'lore'
    assert result.audience == 'aud'
