"""Tests for ClipCandidateService."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.files.base import ContentFile

from server.apps.assets.models import (
    Asset,
    AssetKind,
    LibraryAsset,
    LibraryAssetKind,
)
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.clips.logic.constants import CandidateStatus, PostStatus
from server.apps.clips.logic.value_objects import (
    ClipCandidatePayload,
    ClipLayoutConfigPatchPayload,
    ClipPostPatchPayload,
    ClipStyleConfigPatchPayload,
    ClipTimedOverlayPatchPayload,
    ClipTimedSfxCreatePayload,
    ClipTimedSfxPatchPayload,
)
from server.apps.clips.models import ClipCandidate, ClipPost, ClipTimedOverlay
from server.apps.clips.services import ClipsService
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
)
from server.common.storage import PresignUrlHelper


def _clips_service() -> ClipsService:
    presign = MagicMock(spec=PresignUrlHelper)
    presign.presign_get.return_value = 'https://storage.example/file'
    return ClipsService(presign=presign)


@pytest.fixture
def candidate(db: None) -> ClipCandidate:
    channel = Channel.objects.create(
        name='Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    bp = PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=test',
    )
    return ClipCandidate.objects.create(
        run=run,
        start_sec=10.0,
        end_sec=70.0,
        title='Test Clip',
    )


@pytest.mark.django_db
def test_list_for_run(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    results = svc.list_for_run(str(candidate.run_id))
    assert results.total == 1
    assert len(results.items) == 1
    assert results.items[0].title == 'Test Clip'
    assert results.items[0].status == CandidateStatus.PROPOSED


@pytest.mark.django_db
def test_list_for_run_empty(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    results = svc.list_for_run('00000000-0000-0000-0000-000000000000')
    assert results.items == []
    assert results.total == 0


@pytest.mark.django_db
def test_approve(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    result = svc.approve(str(candidate.id))
    assert result.status == CandidateStatus.APPROVED
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.APPROVED


@pytest.mark.django_db
def test_reject(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    result = svc.reject(str(candidate.id), reason='Not relevant')
    assert result.status == CandidateStatus.REJECTED
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.REJECTED
    assert candidate.rejection_reason == 'Not relevant'


@pytest.mark.django_db
def test_reject_default_reason(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    result = svc.reject(str(candidate.id))
    assert result.rejection_reason == ''


@pytest.mark.django_db
def test_get_by_id(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    result = svc.get_by_id(str(candidate.id))
    assert result.id == str(candidate.id)
    assert isinstance(result, ClipCandidatePayload)


@pytest.mark.django_db
def test_approved_for_run(candidate: ClipCandidate) -> None:
    candidate.status = CandidateStatus.APPROVED
    candidate.save(update_fields=['status'])
    svc = _clips_service()
    approved = svc.approved_for_run(str(candidate.run_id))
    assert len(approved) == 1
    assert approved[0].status == CandidateStatus.APPROVED


@pytest.mark.django_db
def test_approved_for_run_empty_when_proposed(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    approved = svc.approved_for_run(str(candidate.run_id))
    assert approved == []


@pytest.mark.django_db
def test_sync_gate_candidates() -> None:
    """Gate sync marks approved IDs and rejects remaining proposed."""
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )

    channel = Channel.objects.create(
        name='Gate Sync',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    bp = PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='test',
    )
    approved = ClipCandidate.objects.create(
        run=run,
        start_sec=0.0,
        end_sec=10.0,
        title='Keep',
    )
    rejected = ClipCandidate.objects.create(
        run=run,
        start_sec=20.0,
        end_sec=30.0,
        title='Drop',
    )

    count = _clips_service().sync_gate_candidates(
        str(run.id),
        [str(approved.id)],
    )

    assert count == 1
    approved.refresh_from_db()
    rejected.refresh_from_db()
    assert approved.status == CandidateStatus.APPROVED
    assert rejected.status == CandidateStatus.REJECTED


@pytest.mark.django_db
def test_payload_duration_sec(candidate: ClipCandidate) -> None:
    svc = _clips_service()
    result = svc.get_by_id(str(candidate.id))
    assert result.duration_sec == 60.0


@pytest.mark.django_db
def test_get_render_with_asset(candidate: ClipCandidate) -> None:
    """Render payload includes presigned URL when render asset exists."""
    from django.core.files.base import ContentFile

    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='clip.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=candidate.run,
    )
    candidate.render_asset_id = asset.id
    candidate.save(update_fields=['render_asset_id'])

    result = _clips_service().get_render(str(candidate.id))
    assert result.asset_id == str(asset.id)
    assert result.url == 'https://storage.example/file'
    assert result.status == 'ready'


@pytest.mark.django_db
def test_get_render_without_asset_is_idle(candidate: ClipCandidate) -> None:
    result = _clips_service().get_render(str(candidate.id))
    assert result.asset_id is None
    assert result.url is None
    assert result.status == 'idle'


@pytest.mark.django_db
def test_get_render_reports_failed_state(candidate: ClipCandidate) -> None:
    from django.core.cache import cache

    from server.apps.clips.export_render import export_cache_key

    cache.set(
        export_cache_key(str(candidate.id)),
        {'status': 'failed', 'error': 'ffmpeg exploded'},
    )
    result = _clips_service().get_render(str(candidate.id))
    assert result.status == 'failed'
    assert result.error == 'ffmpeg exploded'


@pytest.mark.django_db
def test_trigger_render_requires_approval(candidate: ClipCandidate) -> None:
    from server.common.exceptions import ConflictError

    with pytest.raises(ConflictError, match='must be approved'):
        _clips_service().trigger_render(str(candidate.id))


@pytest.mark.django_db
def test_trigger_render_queues_task(candidate: ClipCandidate) -> None:
    from server.apps.clips.export_render import get_export_state

    candidate.status = CandidateStatus.APPROVED
    candidate.save(update_fields=['status'])

    with patch('server.apps.clips.services.kiq_task') as mock_kiq:
        result = _clips_service().trigger_render(str(candidate.id))

    assert result.status == 'queued'
    mock_kiq.assert_called_once()
    state = get_export_state(str(candidate.id))
    assert state is not None
    assert state['status'] == 'queued'


@pytest.mark.django_db
def test_trigger_render_short_circuits_when_in_progress(
    candidate: ClipCandidate,
) -> None:
    from django.core.cache import cache

    from server.apps.clips.export_render import export_cache_key

    candidate.status = CandidateStatus.APPROVED
    candidate.save(update_fields=['status'])
    cache.set(export_cache_key(str(candidate.id)), {'status': 'rendering'})

    with patch('server.apps.clips.services.kiq_task') as mock_kiq:
        result = _clips_service().trigger_render(str(candidate.id))

    assert result.status == 'rendering'
    mock_kiq.assert_not_called()


@pytest.mark.django_db
def test_get_preview_status_ready(candidate: ClipCandidate) -> None:
    """Preview status is ready when render asset exists."""
    from django.core.files.base import ContentFile

    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='clip.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=candidate.run,
    )
    candidate.render_asset_id = asset.id
    candidate.save(update_fields=['render_asset_id'])

    result = _clips_service().get_preview_status(str(candidate.id))
    assert result.status == 'ready'
    assert result.url == 'https://storage.example/file'
    assert result.config_version > 0


@pytest.mark.django_db
def test_get_preview_status_ready_prefers_preview_asset(
    candidate: ClipCandidate,
) -> None:
    """Preview asset takes precedence over the full render asset."""
    from django.core.files.base import ContentFile

    render_asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'render', name='render.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=candidate.run,
    )
    preview_asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'preview', name='preview.mp4'),
        mime='video/mp4',
        checksum='def',
        run=candidate.run,
    )
    candidate.render_asset_id = render_asset.id
    candidate.preview_asset_id = preview_asset.id
    candidate.save(
        update_fields=['render_asset_id', 'preview_asset_id'],
    )

    result = _clips_service().get_preview_status(str(candidate.id))
    assert result.status == 'ready'
    assert result.url == 'https://storage.example/file'


@pytest.mark.django_db
def test_get_preview_status_failed(candidate: ClipCandidate) -> None:
    """Preview status is failed when the cache records a failure."""
    from django.core.cache import cache

    from server.apps.clips.preview_render import preview_cache_key

    cache.set(
        preview_cache_key(str(candidate.id)),
        {'status': 'failed', 'error': 'ffmpeg failed'},
    )

    result = _clips_service().get_preview_status(str(candidate.id))
    assert result.status == 'failed'
    assert result.url is None


@pytest.mark.django_db
def test_trigger_preview_enqueues_task(candidate: ClipCandidate) -> None:
    """trigger_preview enqueues the render worker task."""
    with patch('server.apps.clips.services.kiq_task') as mock_kiq:
        result = _clips_service().trigger_preview(str(candidate.id))

    assert result.status == 'queued'
    mock_kiq.assert_called_once()
    assert mock_kiq.call_args.args[1] == str(candidate.id)


@pytest.mark.django_db
def test_trigger_preview_skips_when_already_queued(
    candidate: ClipCandidate,
) -> None:
    """trigger_preview does not enqueue a second job while one is active."""
    from django.core.cache import cache

    from server.apps.clips.preview_render import preview_cache_key

    cache.set(
        preview_cache_key(str(candidate.id)),
        {'status': 'rendering'},
    )
    with patch('server.apps.clips.services.kiq_task') as mock_kiq:
        result = _clips_service().trigger_preview(str(candidate.id))
    assert result.status == 'queued'
    mock_kiq.assert_not_called()


@pytest.mark.django_db
def test_trigger_preview_skips_when_ready_and_fresh(
    candidate: ClipCandidate,
) -> None:
    """trigger_preview does not enqueue when a fresh preview exists."""
    from django.core.cache import cache
    from django.core.files.base import ContentFile

    from server.apps.clips.preview_render import (
        preview_cache_key,
        preview_config_version,
    )

    preview_asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'preview', name='preview.mp4'),
        mime='video/mp4',
        checksum='def',
        run=candidate.run,
    )
    candidate.preview_asset_id = preview_asset.id
    candidate.save(update_fields=['preview_asset_id'])
    version = preview_config_version(str(candidate.id))
    cache.set(
        preview_cache_key(str(candidate.id)),
        {'status': 'ready', 'config_version': version},
    )

    with patch('server.apps.clips.services.kiq_task') as mock_kiq:
        result = _clips_service().trigger_preview(str(candidate.id))

    assert result.status == 'ready'
    assert result.url == 'https://storage.example/file'
    mock_kiq.assert_not_called()


@pytest.mark.django_db
def test_trigger_preview_atomic_claim(candidate: ClipCandidate) -> None:
    """Only the first trigger_preview call enqueues a worker task."""
    from django.core.cache import cache

    from server.apps.clips.preview_render import preview_cache_key

    cache_key = preview_cache_key(str(candidate.id))

    with patch('server.apps.clips.services.kiq_task') as mock_kiq:
        first = _clips_service().trigger_preview(str(candidate.id))
        second = _clips_service().trigger_preview(str(candidate.id))

    assert first.status == 'queued'
    assert second.status == 'queued'
    mock_kiq.assert_called_once()
    cached = cache.get(cache_key)
    assert cached is not None
    assert cached['status'] == 'queued'


@pytest.mark.django_db
def test_patch_layout_invalidates_preview_cache(
    candidate: ClipCandidate,
) -> None:
    """Layout patches clear cached preview state."""
    from django.core.cache import cache

    from server.apps.clips.preview_render import preview_cache_key

    cache.set(
        preview_cache_key(str(candidate.id)),
        {'status': 'ready', 'config_version': 123},
    )

    _clips_service().patch_layout(
        str(candidate.id),
        ClipLayoutConfigPatchPayload(render_mode='CENTER_CROP'),
    )

    assert cache.get(preview_cache_key(str(candidate.id))) is None


@pytest.mark.django_db
def test_get_preview_status_idle(candidate: ClipCandidate) -> None:
    """Preview status is idle when no cache entry or render exists."""
    result = _clips_service().get_preview_status(str(candidate.id))
    assert result.status == 'idle'
    assert result.url is None
    assert result.config_version > 0


@pytest.mark.django_db
def test_trigger_preview_force_clears_ready(
    candidate: ClipCandidate,
) -> None:
    """force=True queues preview even when render asset exists."""
    from django.core.cache import cache

    from server.apps.clips.preview_render import preview_cache_key

    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='clip.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=candidate.run,
    )
    candidate.render_asset_id = asset.id
    candidate.save(update_fields=['render_asset_id'])

    with patch('server.apps.clips.services.kiq_task'):
        result = _clips_service().trigger_preview(str(candidate.id), force=True)
    assert result.status == 'queued'
    assert result.url is None

    status = _clips_service().get_preview_status(str(candidate.id))
    assert status.status == 'queued'
    cache.delete(preview_cache_key(str(candidate.id)))


@pytest.mark.django_db
def test_patch_style_emoji_keyword_map(candidate: ClipCandidate) -> None:
    """patch_style updates emoji_keyword_map."""
    result = _clips_service().patch_style(
        str(candidate.id),
        ClipStyleConfigPatchPayload(
            emoji_keyword_map={'win': '🏆'},
        ),
    )
    assert result.emoji_keyword_map == {'win': '🏆'}


@pytest.mark.django_db
def test_get_by_id_includes_channel_and_caption_template(
    candidate: ClipCandidate,
) -> None:
    """get_by_id returns channel_id and caption_template."""
    candidate.caption_template = 'Caption {word}'
    candidate.save(update_fields=['caption_template'])
    result = _clips_service().get_by_id(str(candidate.id))
    assert result.channel_id == str(candidate.run.channel_id)
    assert result.caption_template == 'Caption {word}'


@pytest.mark.django_db
def test_approve_gate_mocks_orchestrator(candidate: ClipCandidate) -> None:
    """approve_gate syncs candidates and resumes the clip approval gate."""
    with (
        patch(
            'server.apps.pipelines.services.orchestrator._approve_gate_sync',
        ) as mock_sync,
        patch(
            'server.apps.clips.services.kiq_task',
        ),
    ):
        result = _clips_service().approve_gate(
            str(candidate.run_id),
            [str(candidate.id)],
        )

    assert result.status == 'approved'
    assert result.approved_count == 1
    mock_sync.assert_called_once()


@pytest.mark.django_db
def test_start_render_requires_parked_gate(candidate: ClipCandidate) -> None:
    """start_render rejects runs that are not at clip_approval_gate."""
    from server.common.exceptions import ConflictError

    with pytest.raises(ConflictError, match='clip approval gate'):
        _clips_service().start_render(str(candidate.run_id))


@pytest.mark.django_db
def test_start_render_requires_approved_candidates(
    candidate: ClipCandidate,
) -> None:
    """start_render rejects when no candidates are approved."""
    from django.core.exceptions import ValidationError

    from server.apps.pipelines.models import (
        RunStatus,
        StageExecution,
        StageStatus,
    )

    run = candidate.run
    run.status = RunStatus.AWAITING_REVIEW
    run.save(update_fields=['status'])
    StageExecution.objects.create(
        run=run,
        stage_key='clip_approval_gate',
        status=StageStatus.NEEDS_INPUT,
        input_hash='',
    )

    with pytest.raises(
        ValidationError,
        match='Approve at least one candidate',
    ):
        _clips_service().start_render(str(run.id))


@pytest.mark.django_db
def test_reset_smart_crop_enqueues_detection(candidate: ClipCandidate) -> None:
    """reset_smart_crop clears crop fields and enqueues worker detection."""
    from server.apps.assets.models import Asset, AssetKind
    from server.apps.pipelines.models import StageExecution, StageStatus

    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='source.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=candidate.run,
        meta={'width': 1920, 'height': 1080},
    )
    StageExecution.objects.create(
        run=candidate.run,
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        output={'asset_id': str(asset.id)},
    )
    layout = candidate.layout_config
    layout.manual_crop_x = 99
    layout.save()

    with patch(
        'server.apps.clips.services.kiq_task',
    ) as mock_kiq:
        result = _clips_service().reset_smart_crop(str(candidate.id))

    layout.refresh_from_db()
    assert result.render_mode == 'SMART_CROP'
    assert result.manual_crop_x is None
    assert result.face_detected is None
    assert layout.manual_crop_x is None
    mock_kiq.assert_called_once()


@pytest.mark.django_db
def test_apply_smart_crop_detection(candidate: ClipCandidate) -> None:
    """apply_smart_crop_detection stores MediaPipe crop output."""
    from server.apps.assets.models import Asset, AssetKind
    from server.apps.pipelines.models import StageExecution, StageStatus

    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='source.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=candidate.run,
        meta={'width': 1920, 'height': 1080},
    )
    StageExecution.objects.create(
        run=candidate.run,
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        output={'asset_id': str(asset.id)},
    )

    mock_result = MagicMock(
        crop_x=120,
        crop_y=0,
        crop_w=600,
        crop_h=1080,
        confidence=0.9,
        face_detected=True,
    )
    with patch(
        'server.apps.rendering.speaker_detection.SpeakerDetectionService.detect',
        return_value=mock_result,
    ):
        result = _clips_service().apply_smart_crop_detection(str(candidate.id))

    assert result.manual_crop_x == 120
    assert result.face_detected is True
    assert result.source_width == 1920


@pytest.mark.django_db
def test_patch_layout_region_fields(candidate: ClipCandidate) -> None:
    """patch_layout updates spatial region fields."""
    svc = _clips_service()
    result = svc.patch_layout(
        str(candidate.id),
        ClipLayoutConfigPatchPayload(
            region_a_x=0,
            region_a_y=0,
            region_a_w=1920,
            region_a_h=540,
            manual_crop_x=10,
            manual_crop_y=20,
        ),
    )
    assert result.region_a_w == 1920
    assert result.manual_crop_x == 10


@pytest.mark.django_db
def test_patch_style_fk_fields(candidate: ClipCandidate) -> None:
    """patch_style updates asset FK fields."""
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.WATERMARK,
        name='wm.png',
        file=ContentFile(b'img', name='wm.png'),
    )
    music = LibraryAsset.objects.create(
        kind=LibraryAssetKind.MUSIC,
        name='track.mp3',
        file=ContentFile(b'audio', name='track.mp3'),
    )

    result = _clips_service().patch_style(
        str(candidate.id),
        ClipStyleConfigPatchPayload(
            watermark_image_id=str(asset.id),
            music_asset_id=str(music.id),
        ),
    )
    assert result.watermark_image_id == str(asset.id)
    assert result.music_asset_id == str(music.id)


@pytest.mark.django_db
def test_get_post_and_patch_hashtags_scheduled_at(
    candidate: ClipCandidate,
) -> None:
    """get_post and patch_post handle hashtags and scheduled_at."""
    svc = _clips_service()
    post = ClipPost.objects.create(
        candidate=candidate,
        platform='youtube_shorts',
        caption='Original',
    )

    fetched = svc.get_post(str(candidate.id), str(post.id))
    assert fetched.caption == 'Original'
    assert fetched.distribution_status == 'pending_implementation'

    updated = svc.patch_post(
        str(candidate.id),
        str(post.id),
        ClipPostPatchPayload(
            hashtags=['shorts', 'clips'],
            scheduled_at='2026-06-20T15:00:00+00:00',
        ),
    )
    assert updated.hashtags == ['shorts', 'clips']
    assert updated.scheduled_at is not None


@pytest.mark.django_db
def test_distribution_status_branches(candidate: ClipCandidate) -> None:
    """_distribution_status maps post lifecycle states."""
    svc = _clips_service()

    posting = ClipPost.objects.create(
        candidate=candidate,
        platform='tiktok',
        status=PostStatus.POSTING,
    )
    assert (
        svc.get_post(str(candidate.id), str(posting.id)).distribution_status
        == 'posting'
    )

    failed = ClipPost.objects.create(
        candidate=candidate,
        platform='instagram',
        status=PostStatus.FAILED,
    )
    assert (
        svc.get_post(str(candidate.id), str(failed.id)).distribution_status
        == 'failed'
    )

    posted = ClipPost.objects.create(
        candidate=candidate,
        platform='youtube',
        status=PostStatus.POSTED,
        platform_url='https://youtube.com/shorts/abc',
    )
    assert (
        svc.get_post(str(candidate.id), str(posted.id)).distribution_status
        == 'posted'
    )


@pytest.mark.django_db
def test_patch_style_updates_new_font_and_transition_fields(
    candidate: ClipCandidate,
) -> None:
    result = _clips_service().patch_style(
        str(candidate.id),
        ClipStyleConfigPatchPayload(
            watermark_color='#00FF00',
            watermark_font='POPPINS_BOLD',
            hook_animation='FADE',
            intro_transition='CROSSFADE',
            intro_transition_duration_sec=0.75,
            caption_uppercase=True,
            color_filter='VIVID',
            brightness=0.2,
            playback_speed=1.5,
        ),
    )
    assert result.watermark_color == '#00FF00'
    assert result.watermark_font == 'POPPINS_BOLD'
    assert result.hook_animation == 'FADE'
    assert result.intro_transition == 'CROSSFADE'
    assert result.intro_transition_duration_sec == 0.75
    assert result.caption_uppercase is True
    assert result.color_filter == 'VIVID'
    assert result.brightness == 0.2
    assert result.playback_speed == 1.5


@pytest.mark.django_db
def test_patch_layout_updates_fit_mode(candidate: ClipCandidate) -> None:
    result = _clips_service().patch_layout(
        str(candidate.id),
        ClipLayoutConfigPatchPayload(fit_mode='BLUR_FILL'),
    )
    assert result.fit_mode == 'BLUR_FILL'


@pytest.mark.django_db
def test_patch_overlay_updates_font_and_animation(
    candidate: ClipCandidate,
) -> None:
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        start_sec=0.0,
        end_sec=1.0,
    )
    result = _clips_service().patch_overlay(
        str(candidate.id),
        str(overlay.id),
        ClipTimedOverlayPatchPayload(font='OSWALD_BOLD', animation='POP'),
    )
    assert result.font == 'OSWALD_BOLD'
    assert result.animation == 'POP'


@pytest.mark.django_db
def test_sfx_crud_lifecycle(candidate: ClipCandidate) -> None:
    sfx_asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.SFX,
        name='whoosh.mp3',
        file=ContentFile(b'audio', name='whoosh.mp3'),
    )
    svc = _clips_service()

    created = svc.create_sfx(
        str(candidate.id),
        ClipTimedSfxCreatePayload(
            sfx_asset_id=str(sfx_asset.id),
            start_sec=2.0,
            volume_db=-3.0,
        ),
    )
    assert created.start_sec == 2.0
    assert created.volume_db == -3.0

    listed = svc.list_sfx(str(candidate.id))
    assert listed.total == 1
    assert listed.items[0].id == created.id

    fetched = svc.get_sfx(str(candidate.id), created.id)
    assert fetched.id == created.id

    patched = svc.patch_sfx(
        str(candidate.id),
        created.id,
        ClipTimedSfxPatchPayload(volume_db=-6.0),
    )
    assert patched.volume_db == -6.0

    svc.delete_sfx(str(candidate.id), created.id)
    assert svc.list_sfx(str(candidate.id)).total == 0


@pytest.mark.django_db
def test_create_sfx_rejects_empty_asset_id(candidate: ClipCandidate) -> None:
    """create_sfx raises ValidationError for an empty sfx_asset_id."""
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        _clips_service().create_sfx(
            str(candidate.id),
            ClipTimedSfxCreatePayload(sfx_asset_id='', start_sec=0.0),
        )


@pytest.mark.django_db
def test_create_sfx_rejects_malformed_asset_id(
    candidate: ClipCandidate,
) -> None:
    """create_sfx raises ValidationError for a malformed sfx_asset_id."""
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        _clips_service().create_sfx(
            str(candidate.id),
            ClipTimedSfxCreatePayload(sfx_asset_id='not-a-uuid'),
        )


@pytest.mark.django_db
def test_patch_sfx_rejects_empty_asset_id(candidate: ClipCandidate) -> None:
    """patch_sfx raises ValidationError for an empty sfx_asset_id."""
    from django.core.exceptions import ValidationError

    sfx_asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.SFX,
        name='whoosh.mp3',
        file=ContentFile(b'audio', name='whoosh.mp3'),
    )
    svc = _clips_service()
    created = svc.create_sfx(
        str(candidate.id),
        ClipTimedSfxCreatePayload(sfx_asset_id=str(sfx_asset.id)),
    )

    with pytest.raises(ValidationError):
        svc.patch_sfx(
            str(candidate.id),
            created.id,
            ClipTimedSfxPatchPayload(sfx_asset_id=''),
        )
