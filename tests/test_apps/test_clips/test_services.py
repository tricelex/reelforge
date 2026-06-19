"""Tests for ClipCandidateService."""

from unittest.mock import AsyncMock, MagicMock, patch

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
)
from server.apps.clips.models import ClipCandidate, ClipPost
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
        run=run, start_sec=10.0, end_sec=70.0, title='Test Clip',
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
        run=run, start_sec=0.0, end_sec=10.0, title='Keep',
    )
    rejected = ClipCandidate.objects.create(
        run=run, start_sec=20.0, end_sec=30.0, title='Drop',
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


@pytest.mark.django_db
def test_get_preview_status_idle(candidate: ClipCandidate) -> None:
    """Preview status is idle when no cache entry or render exists."""
    result = _clips_service().get_preview_status(str(candidate.id))
    assert result.status == 'idle'
    assert result.url is None


@pytest.mark.django_db
def test_approve_gate_mocks_orchestrator(candidate: ClipCandidate) -> None:
    """approve_gate syncs candidates and resumes the clip approval gate."""
    with patch(
        'server.apps.pipelines.services.orchestrator._approve_gate_sync',
    ) as mock_sync, patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new=AsyncMock(return_value=None),
    ):
        result = _clips_service().approve_gate(
            str(candidate.run_id),
            [str(candidate.id)],
        )

    assert result.status == 'approved'
    assert result.approved_count == 1
    mock_sync.assert_called_once()


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
    assert svc.get_post(str(candidate.id), str(posting.id)).distribution_status == 'posting'

    failed = ClipPost.objects.create(
        candidate=candidate,
        platform='instagram',
        status=PostStatus.FAILED,
    )
    assert svc.get_post(str(candidate.id), str(failed.id)).distribution_status == 'failed'

    posted = ClipPost.objects.create(
        candidate=candidate,
        platform='youtube',
        status=PostStatus.POSTED,
        platform_url='https://youtube.com/shorts/abc',
    )
    assert svc.get_post(str(candidate.id), str(posted.id)).distribution_status == 'posted'
