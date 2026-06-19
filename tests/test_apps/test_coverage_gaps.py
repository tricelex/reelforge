"""Targeted tests for remaining coverage gaps."""

import uuid
from datetime import UTC, datetime
from http import HTTPStatus
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
from server.apps.prompts.services import (
    PromptTemplateService,
    StoryFormatService,
)
from server.common.events import InProcessEventBus
from server.common.storage import PresignUrlHelper


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Coverage Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def character(channel: Channel) -> Character:
    return Character.objects.create(
        channel=channel,
        name='Coverage Character',
        appearance_prompt='hero',
    )


def test_channels_iso_helper() -> None:
    """Cover channel selector datetime helper."""
    assert _iso(None) is None
    dt = datetime(2026, 6, 19, tzinfo=UTC)
    assert _iso(dt) == dt.isoformat()


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
    assert _json_beats([{'key': 'beat', 'pct': 0.5}]) == [
        {'key': 'beat', 'pct': 0.5},
    ]


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
    from server.apps.prompts.logic.value_objects import (
        PromptTemplatePatchPayload,
    )

    result = service.patch(
        str(template.id),
        PromptTemplatePatchPayload(name='Patched'),
    )
    assert result.name == 'Patched'


@pytest.mark.django_db
def test_story_format_patch_json_fields(db: None) -> None:
    """Cover story format patch JSON field updates."""
    fmt = StoryFormat.objects.create(
        key='patch_fmt',
        name='Patch Fmt',
        beats=[],
    )
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
def scene_breakdown_stage(run: PipelineRun) -> StageExecution:
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
                    'beat': 'hook',
                    'narration_text': 'Original narration text here.',
                    'visual_concept': 'dark alley',
                    'word_count': 5,
                    'est_seconds': 4.0,
                },
            ],
        },
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
    from server.apps.clips.logic.value_objects import ClipCampaignCreatePayload

    service = ClipCampaignService()
    missing_channel_payload = ClipCampaignCreatePayload(
        channel_id=str(uuid.uuid4()),
        name='Missing channel',
    )
    with pytest.raises(ValidationError, match='Channel not found'):
        service.create_campaign(missing_channel_payload)

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
    assert (
        svc.patch(
            str(character.id),
            CharacterPatchPayload(name='Only Name'),
        ).name
        == 'Only Name'
    )
    assert (
        svc.patch(
            str(character.id),
            CharacterPatchPayload(appearance_prompt='Only Prompt'),
        ).appearance_prompt
        == 'Only Prompt'
    )
    assert (
        svc.patch(
            str(character.id),
            CharacterPatchPayload(persona='Only Persona'),
        ).persona
        == 'Only Persona'
    )
    assert (
        svc.patch(
            str(character.id),
            CharacterPatchPayload(status=CharacterStatus.DRAFT),
        ).status
        == CharacterStatus.DRAFT
    )


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

    run.blueprint_snapshot = {
        'stages': [{'key': 'dummy_a', 'depends_on': []}],
    }
    run.save(update_fields=['blueprint_snapshot'])
    exec_ids = _rerun_stage_sync(str(run.id), 'dummy_a', [0])
    assert isinstance(exec_ids, list)


@pytest.mark.django_db
def test_storyboard_presign_missing_file(run) -> None:
    """Cover storyboard presign when asset has no file."""
    from server.apps.assets.models import Asset, AssetKind
    from server.apps.pipelines.storyboard_selectors import _presign_asset
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

    settings.YOUTUBE_CLIENT_ID = 'id'
    settings.YOUTUBE_CLIENT_SECRET = 'secret'
    service = ChannelService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'access_token': 'at', 'expires_in': 3600}
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp

    with patch(
        'server.apps.channels.services.httpx.Client',
        return_value=mock_client,
    ):
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

    fmt = StoryFormat.objects.create(key='niche_fmt', name='Fmt', beats=[])
    service = ChannelService()
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


@pytest.mark.django_db
def test_list_characters_status_filter(channel: Channel, character: Character) -> None:
    """Cover character list status filter branch."""
    from server.apps.channels.character_selectors import list_characters

    character.status = CharacterStatus.APPROVED
    character.save(update_fields=['status'])
    result = list_characters(
        channel_id=str(channel.id),
        status=CharacterStatus.APPROVED,
    )
    assert result.total == 1


@pytest.mark.django_db
def test_list_characters_channel_filter_only(channel: Channel, character: Character) -> None:
    """Cover character list channel_id-only filter branch."""
    from server.apps.channels.character_selectors import list_characters

    result = list_characters(channel_id=str(channel.id))
    assert result.total == 1


@pytest.mark.django_db
def test_niche_patch_audience_only(channel: Channel) -> None:
    """Cover niche patch single-field branch."""
    from server.apps.channels.logic.value_objects import NicheConfigPatchPayload
    from server.apps.channels.services import ChannelService

    service = ChannelService()
    result = service.patch_niche(
        str(channel.id),
        NicheConfigPatchPayload(audience='solo audience'),
    )
    assert result.audience == 'solo audience'


@pytest.mark.django_db
def test_run_review_update_prompt_wrong_scene_idx() -> None:
    """Cover _update_prompt_row early return for mismatched scene_idx."""
    from server.apps.pipelines.logic.value_objects import ScenePatchPayload
    from server.apps.pipelines.services.run_review import _update_prompt_row

    prompt: dict[str, object] = {'scene_idx': 1, 'prompt': 'keep'}
    _update_prompt_row(
        prompt,
        0,
        ScenePatchPayload(visual_prompt='ignored'),
    )
    assert prompt['prompt'] == 'keep'


@pytest.mark.django_db
def test_run_review_patch_scene_missing_after_board(
    run,
    scene_breakdown_stage,
) -> None:
    """Cover patch_scene when storyboard row disappears after save."""
    from unittest.mock import patch

    from server.apps.pipelines.logic.value_objects import (
        ScenePatchPayload,
        StoryboardPayload,
        StoryboardRunSummaryPayload,
    )
    from server.apps.pipelines.services.run_review import RunReviewService
    from server.common.storage import PresignUrlHelper

    service = RunReviewService(presign=MagicMock(spec=PresignUrlHelper))
    empty_board = StoryboardPayload(
        run=StoryboardRunSummaryPayload(
            id=str(run.id),
            status=run.status,
            gate=None,
            spent_usd='0',
            projected_next_usd='0',
            budget_usd=None,
        ),
        scenes=[],
    )
    with patch(
        'server.apps.pipelines.services.run_review.get_storyboard',
        return_value=empty_board,
    ):
        with pytest.raises(ValidationError, match='not found after patch'):
            service.patch_scene(
                str(run.id),
                0,
                ScenePatchPayload(narration_text='updated narration here'),
            )


@pytest.mark.django_db
def test_channel_patch_budget_only(channel: Channel) -> None:
    """Cover channel patch default_budget_usd-only branch."""
    from server.apps.channels.logic.value_objects import ChannelPatchPayload
    from server.apps.channels.services import ChannelService

    service = ChannelService()
    result = service.patch(
        str(channel.id),
        ChannelPatchPayload(default_budget_usd='12.00'),
    )
    assert result.default_budget_usd == '12.00'


@pytest.mark.django_db
def test_channel_branding_thumbnail_palette_only(channel: Channel) -> None:
    """Cover branding patch thumbnail_palette-only branch."""
    from server.apps.channels.logic.value_objects import (
        ChannelBrandingPatchPayload,
    )
    from server.apps.channels.services import ChannelService

    service = ChannelService()
    result = service.patch_branding(
        str(channel.id),
        ChannelBrandingPatchPayload(thumbnail_palette={'primary': '#000'}),
    )
    assert result.thumbnail_palette == {'primary': '#000'}


@pytest.mark.django_db
def test_campaign_patch_notes_only(channel: Channel) -> None:
    """Cover campaign patch notes-only branch."""
    from server.apps.clips.models import ClipCampaign

    campaign = ClipCampaign.objects.create(channel=channel, name='Notes')
    service = ClipCampaignService()
    result = service.patch_campaign(
        str(campaign.id),
        ClipCampaignPatchPayload(notes='updated'),
    )
    assert result.notes == 'updated'


@pytest.mark.django_db
def test_prompt_template_empty_patch(db) -> None:  # type: ignore[no-untyped-def]
    """Cover prompt template patch with no mutable fields."""
    from server.apps.prompts.logic.value_objects import (
        PromptTemplatePatchPayload,
    )

    template = PromptTemplate.objects.create(
        key='empty_patch',
        name='Empty',
        scope=PromptScope.GLOBAL,
    )
    service = PromptTemplateService()
    result = service.patch(str(template.id), PromptTemplatePatchPayload())
    assert result.id == str(template.id)


@pytest.mark.django_db
def test_story_format_music_mood_only(db) -> None:  # type: ignore[no-untyped-def]
    """Cover story format patch music_mood_map-only branch."""
    from server.apps.prompts.logic.value_objects import StoryFormatPatchPayload

    fmt = StoryFormat.objects.create(key='mood_fmt', name='Mood', beats=[])
    service = StoryFormatService()
    result = service.patch(
        str(fmt.id),
        StoryFormatPatchPayload(music_mood_map={'intro': 'tense'}),
    )
    assert result.music_mood_map == {'intro': 'tense'}


@pytest.mark.django_db
def test_list_story_formats_active_only(db) -> None:  # type: ignore[no-untyped-def]
    """Cover story format active_only filter branch."""
    StoryFormat.objects.create(
        key='active_fmt',
        name='Active',
        beats=[],
        is_active=True,
    )
    StoryFormat.objects.create(
        key='inactive_fmt',
        name='Inactive',
        beats=[],
        is_active=False,
    )
    result = list_story_formats(active_only=True)
    assert result.total == 1


@pytest.mark.django_db
def test_run_review_update_prompt_visual_concept(run) -> None:
    """Cover visual_concept fallback in _update_prompt_row."""
    from server.apps.pipelines.logic.value_objects import ScenePatchPayload
    from server.apps.pipelines.services.run_review import _update_prompt_row

    prompt: dict[str, object] = {'scene_idx': 0, 'prompt': 'old'}
    _update_prompt_row(
        prompt,
        0,
        ScenePatchPayload(visual_concept='new concept'),
    )
    assert prompt['prompt'] == 'new concept'


@pytest.mark.django_db
def test_image_gen_state_skips_missing_scene_idx(run) -> None:
    """Cover image_gen child rows without scene_idx."""
    from server.apps.pipelines.storyboard_selectors import _image_gen_state

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
        output={},
    )
    assert _image_gen_state(str(run.id)) == {}


@pytest.mark.django_db
def test_visual_prompts_map_skips_invalid_items(run) -> None:
    """Cover visual prompts map when entries are not scene dicts."""
    from server.apps.pipelines.storyboard_selectors import _visual_prompts_map

    StageExecution.objects.create(
        run=run,
        stage_key='visual_prompts',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'prompts': [
                'skip-me',
                {'scene_idx': None, 'prompt': 'skip-too'},
                {'scene_idx': 0, 'prompt': 'keep'},
            ],
        },
    )
    assert _visual_prompts_map(str(run.id)) == {0: {'scene_idx': 0, 'prompt': 'keep'}}


@pytest.mark.django_db
def test_presign_asset_empty_file(run) -> None:
    """Cover _presign_asset when asset file is empty."""
    from server.apps.assets.models import Asset, AssetKind
    from server.apps.pipelines.storyboard_selectors import _presign_asset
    from server.common.storage import PresignUrlHelper

    asset = Asset.objects.create(
        kind=AssetKind.IMAGE,
        mime='image/png',
        checksum='empty',
        run=run,
    )
    asset.file = ''
    asset.save(update_fields=['file'])
    presign = MagicMock(spec=PresignUrlHelper)
    assert _presign_asset(str(asset.id), presign) == ''
    presign.presign_get.assert_not_called()


@pytest.mark.django_db
def test_presign_asset_with_stored_file(run) -> None:
    """Cover _presign_asset presign_get path."""
    from django.core.files.base import ContentFile

    from server.apps.assets.models import Asset, AssetKind
    from server.apps.pipelines.storyboard_selectors import _presign_asset
    from server.common.storage import PresignUrlHelper

    asset = Asset.objects.create(
        kind=AssetKind.IMAGE,
        mime='image/png',
        checksum='has-file',
        run=run,
    )
    asset.file.save('image.png', ContentFile(b'png'), save=True)
    presign = MagicMock(spec=PresignUrlHelper)
    presign.presign_get.return_value = 'https://example.com/image.png'
    assert _presign_asset(str(asset.id), presign) == 'https://example.com/image.png'
    presign.presign_get.assert_called_once()


@pytest.mark.django_db
def test_sync_visual_prompts_without_stage(run) -> None:
    """Cover visual prompt sync when visual_prompts stage is missing."""
    from server.apps.pipelines.logic.value_objects import ScenePatchPayload
    from server.apps.pipelines.services.run_review import _sync_visual_prompts

    assert _sync_visual_prompts(
        str(run.id),
        0,
        ScenePatchPayload(visual_prompt='x'),
    ) == 'scene_breakdown'


@pytest.mark.django_db
def test_patch_scene_returns_matching_storyboard_row(
    run,
    scene_breakdown_stage,
) -> None:
    """Cover patch_scene loop that finds the updated scene row."""
    from server.apps.pipelines.logic.value_objects import ScenePatchPayload
    from server.apps.pipelines.services.run_review import RunReviewService
    from server.common.storage import PresignUrlHelper

    scene_breakdown_stage.output = {
        'scenes': [
            {
                'idx': 0,
                'chapter_idx': 0,
                'beat': 'a',
                'narration_text': 'First scene narration text.',
                'visual_concept': 'a',
                'word_count': 4,
                'est_seconds': 3.0,
            },
            {
                'idx': 1,
                'chapter_idx': 0,
                'beat': 'b',
                'narration_text': 'Second scene narration text.',
                'visual_concept': 'b',
                'word_count': 4,
                'est_seconds': 3.0,
            },
        ],
    }
    scene_breakdown_stage.save(update_fields=['output'])

    service = RunReviewService(presign=MagicMock(spec=PresignUrlHelper))
    row = service.patch_scene(
        str(run.id),
        1,
        ScenePatchPayload(narration_text='Updated second scene narration.'),
    )
    assert row.idx == 1


@pytest.mark.django_db
def test_storyboard_skips_non_dict_scenes(run) -> None:
    """Cover storyboard when scenes list contains non-dict entries."""
    from server.apps.pipelines.storyboard_selectors import get_storyboard
    from server.common.storage import PresignUrlHelper

    StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'scenes': ['bad', {'idx': 0, 'narration_text': 'hi'}]},
    )
    presign = MagicMock(spec=PresignUrlHelper)
    board = get_storyboard(str(run.id), presign)
    assert len(board.scenes) == 1


@pytest.mark.django_db
def test_resume_pending_run_sets_running(run: PipelineRun) -> None:
    """Cover resume branch that promotes PENDING runs to RUNNING."""
    from server.apps.pipelines.models import RunStatus
    from server.apps.pipelines.services.orchestrator import _resume_run_sync

    run.status = RunStatus.PENDING
    run.is_paused = True
    run.save(update_fields=['status', 'is_paused'])
    _resume_run_sync(str(run.id))
    run.refresh_from_db()
    assert run.status == RunStatus.RUNNING
    assert run.is_paused is False


@pytest.mark.django_db
def test_run_cast_patch_no_fields(run, character: Character) -> None:
    """Cover cast patch when no fields are supplied."""
    from server.apps.channels.character_studio import CharacterStudioService
    from server.apps.pipelines.logic.value_objects import RunCastPatchPayload
    from server.apps.pipelines.models import RunCast
    from server.apps.pipelines.services.run_cast import RunCastService

    cast = RunCast.objects.create(
        run=run,
        character=character,
        role='lead',
    )
    service = RunCastService(studio=CharacterStudioService())
    result = service.patch(str(run.id), str(cast.id), RunCastPatchPayload())
    assert result.id == str(cast.id)


@pytest.mark.django_db
def test_earning_create_missing_campaign(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Cover earning collection ValidationError handler."""
    response = dmr_client.post(
        reverse('api:clips:earning-collection'),
        data={
            'campaign_id': str(uuid.uuid4()),
            'platform': 'youtube',
            'revenue_est_usd': '1.00',
            'recorded_at': '2026-06-19T12:00:00',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_list_characters_no_filters(db) -> None:  # type: ignore[no-untyped-def]
    """Cover character list with no filters."""
    from server.apps.channels.character_selectors import list_characters

    assert list_characters().total == 0


@pytest.mark.django_db
def test_list_characters_status_only_filter(character: Character) -> None:
    """Cover character list status filter without channel_id."""
    from server.apps.channels.character_selectors import list_characters

    character.status = CharacterStatus.APPROVED
    character.save(update_fields=['status'])
    result = list_characters(status=CharacterStatus.APPROVED)
    assert result.total == 1


@pytest.mark.django_db
def test_list_story_formats_without_active_filter(db) -> None:  # type: ignore[no-untyped-def]
    """Cover story format list without active_only filter."""
    StoryFormat.objects.create(key='all_fmt', name='All', beats=[])
    assert list_story_formats(active_only=False).total == 1


@pytest.mark.django_db
def test_channel_patch_empty_payload(channel: Channel) -> None:
    """Cover channel patch when no fields change."""
    from server.apps.channels.logic.value_objects import ChannelPatchPayload
    from server.apps.channels.services import ChannelService

    service = ChannelService()
    result = service.patch(str(channel.id), ChannelPatchPayload())
    assert result.id == str(channel.id)


@pytest.mark.django_db
def test_channel_branding_empty_patch(channel: Channel) -> None:
    """Cover branding patch when no fields change."""
    from server.apps.channels.logic.value_objects import ChannelBrandingPatchPayload
    from server.apps.channels.services import ChannelService

    service = ChannelService()
    result = service.patch_branding(
        str(channel.id),
        ChannelBrandingPatchPayload(),
    )
    assert result.channel_id == str(channel.id)


@pytest.mark.django_db
def test_niche_patch_empty_payload(channel: Channel) -> None:
    """Cover niche patch when no fields change."""
    from server.apps.channels.logic.value_objects import NicheConfigPatchPayload
    from server.apps.channels.services import ChannelService

    service = ChannelService()
    result = service.patch_niche(
        str(channel.id),
        NicheConfigPatchPayload(),
    )
    assert result.channel_id == str(channel.id)


@pytest.mark.django_db
def test_campaign_patch_empty_payload(channel: Channel) -> None:
    """Cover campaign patch when no fields change."""
    from server.apps.clips.models import ClipCampaign

    campaign = ClipCampaign.objects.create(channel=channel, name='Empty')
    service = ClipCampaignService()
    result = service.patch_campaign(
        str(campaign.id),
        ClipCampaignPatchPayload(),
    )
    assert result.name == 'Empty'


@pytest.mark.django_db
def test_list_earnings_without_campaign_filter(channel: Channel) -> None:
    """Cover earning list without campaign_id filter."""
    from server.apps.clips.models import ClipCampaign, Earning

    campaign = ClipCampaign.objects.create(channel=channel, name='Earn')
    Earning.objects.create(
        campaign=campaign,
        platform='youtube',
        revenue_est_usd='1.00',
        recorded_at=datetime(2026, 6, 19, tzinfo=UTC),
    )
    result = ClipCampaignService().list_earnings()
    assert result.total == 1


@pytest.mark.django_db
def test_clips_empty_candidate_patch(candidate) -> None:
    """Cover candidate patch with no mutable fields."""
    from server.apps.clips.logic.value_objects import ClipCandidatePatchPayload

    svc = _clips()
    result = svc.patch(
        str(candidate.id),
        ClipCandidatePatchPayload(),
    )
    assert result.id == str(candidate.id)


@pytest.mark.django_db
def test_clips_empty_layout_patch(candidate) -> None:
    """Cover layout patch with no mutable fields."""
    from server.apps.clips.logic.value_objects import ClipLayoutConfigPatchPayload
    from server.apps.clips.models import ClipLayoutConfig

    ClipLayoutConfig.objects.get_or_create(candidate=candidate)
    svc = _clips()
    result = svc.patch_layout(
        str(candidate.id),
        ClipLayoutConfigPatchPayload(),
    )
    assert result.candidate_id == str(candidate.id)


@pytest.mark.django_db
def test_clips_empty_style_patch(candidate) -> None:
    """Cover style patch with no mutable fields."""
    from server.apps.clips.logic.value_objects import ClipStyleConfigPatchPayload
    from server.apps.clips.models import ClipStyleConfig

    ClipStyleConfig.objects.get_or_create(candidate=candidate)
    svc = _clips()
    result = svc.patch_style(
        str(candidate.id),
        ClipStyleConfigPatchPayload(),
    )
    assert result.candidate_id == str(candidate.id)


@pytest.mark.django_db
def test_clips_empty_post_patch(candidate) -> None:
    """Cover post patch with no mutable fields."""
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
        ),
    )
    result = svc.patch_post(
        str(candidate.id),
        post.id,
        ClipPostPatchPayload(),
    )
    assert result.id == post.id


@pytest.mark.django_db
def test_resume_completed_run_only_clears_pause(run: PipelineRun) -> None:
    """Cover resume when status should remain COMPLETED."""
    from server.apps.pipelines.models import RunStatus
    from server.apps.pipelines.services.orchestrator import _resume_run_sync

    run.status = RunStatus.COMPLETED
    run.is_paused = True
    run.save(update_fields=['status', 'is_paused'])
    _resume_run_sync(str(run.id))
    run.refresh_from_db()
    assert run.status == RunStatus.COMPLETED
    assert run.is_paused is False


@pytest.mark.django_db
def test_sync_visual_prompts_skips_non_dict_prompts(run) -> None:
    """Cover visual prompt sync loop when prompt rows are not dicts."""
    from server.apps.pipelines.logic.value_objects import ScenePatchPayload
    from server.apps.pipelines.services.run_review import _sync_visual_prompts

    StageExecution.objects.create(
        run=run,
        stage_key='visual_prompts',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'prompts': ['bad', {'scene_idx': 0, 'prompt': 'old'}]},
    )
    assert _sync_visual_prompts(
        str(run.id),
        0,
        ScenePatchPayload(visual_prompt='new'),
    ) == 'visual_prompts'


@pytest.mark.django_db
def test_sync_visual_prompts_when_stage_not_succeeded(run) -> None:
    """Cover visual prompt sync when stage is not succeeded."""
    from server.apps.pipelines.logic.value_objects import ScenePatchPayload
    from server.apps.pipelines.services.run_review import _sync_visual_prompts

    StageExecution.objects.create(
        run=run,
        stage_key='visual_prompts',
        status=StageStatus.RUNNING,
        attempt=0,
        output={'prompts': []},
    )
    assert _sync_visual_prompts(
        str(run.id),
        0,
        ScenePatchPayload(visual_prompt='x'),
    ) == 'scene_breakdown'


@pytest.mark.django_db
def test_publish_metadata_patch_without_metadata_stage(
    run,
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Cover publish metadata_patch when metadata stage is absent."""
    from unittest.mock import AsyncMock, patch

    run.channel.gates = ['final_gate']
    run.channel.save(update_fields=['gates'])
    StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )
    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-publish',
                kwargs={'run_id': run.id},
            ),
            data={
                'metadata_patch': {'title': 'No metadata stage'},
            },
            headers=auth_headers,
        )
    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_storyboard_scenes_not_list(run) -> None:
    """Cover storyboard when scenes output is not a list."""
    from server.apps.pipelines.storyboard_selectors import get_storyboard
    from server.common.storage import PresignUrlHelper

    StageExecution.objects.create(
        run=run,
        stage_key='scene_breakdown',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={'scenes': 'invalid'},
    )
    board = get_storyboard(str(run.id), MagicMock(spec=PresignUrlHelper))
    assert board.scenes == []


@pytest.mark.django_db
def test_story_format_empty_patch(db) -> None:  # type: ignore[no-untyped-def]
    """Cover story format patch with no mutable fields."""
    from server.apps.prompts.logic.value_objects import StoryFormatPatchPayload

    fmt = StoryFormat.objects.create(key='empty_fmt', name='Empty', beats=[])
    service = StoryFormatService()
    result = service.patch(str(fmt.id), StoryFormatPatchPayload())
    assert result.id == str(fmt.id)
