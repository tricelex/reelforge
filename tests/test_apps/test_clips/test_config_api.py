"""Tests for clip config, overlay, post, and batch APIs."""

import uuid
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import Asset, AssetKind
from server.apps.clips.logic.constants import CandidateStatus
from server.apps.clips.models import ClipCandidate, ClipTimedOverlay
from server.apps.pipelines.models import StageExecution, StageStatus


@pytest.fixture
def channel(db):  # type: ignore[no-untyped-def]
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )

    return Channel.objects.create(
        name='Config Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def blueprint(db):  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
    )

    return PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )


@pytest.fixture
def run(channel, blueprint):  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import PipelineRun

    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=test',
    )


@pytest.fixture
def candidate(run):  # type: ignore[no-untyped-def]
    return ClipCandidate.objects.create(
        run=run,
        start_sec=10.0,
        end_sec=70.0,
        title='Config Clip',
    )


@pytest.mark.django_db
def test_patch_candidate(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """PATCH /candidates/{id}/ updates editable fields."""
    response = dmr_client.patch(
        reverse(
            'clips:candidate_detail',
            kwargs={'candidate_id': candidate.id},
        ),
        data={'title': 'Updated Title', 'start_sec': 12.0},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['title'] == 'Updated Title'
    assert data['start_sec'] == 12.0


@pytest.mark.django_db
def test_get_candidate_includes_caption_template_and_channel_id(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    channel: object,
    auth_headers: dict[str, str],
) -> None:
    """GET candidate returns caption_template and channel_id."""
    candidate.caption_template = 'Hello {word}'
    candidate.save(update_fields=['caption_template'])

    response = dmr_client.get(
        reverse(
            'clips:candidate_detail',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['caption_template'] == 'Hello {word}'
    assert data['channel_id'] == str(channel.id)  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_approve_all_candidates(
    dmr_client: DMRClient,
    run: object,
    auth_headers: dict[str, str],
) -> None:
    """POST approve-all approves every PROPOSED candidate."""
    ClipCandidate.objects.create(
        run=run,  # type: ignore[arg-type]
        start_sec=0.0,
        end_sec=30.0,
        title='Clip A',
    )
    ClipCandidate.objects.create(
        run=run,  # type: ignore[arg-type]
        start_sec=40.0,
        end_sec=70.0,
        title='Clip B',
    )

    response = dmr_client.post(
        reverse(
            'clips:candidate_approve_all',
            kwargs={'run_id': run.id},  # type: ignore[attr-defined]
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['approved_count'] == 2
    assert (
        ClipCandidate.objects.filter(status=CandidateStatus.APPROVED).count()
        == 2
    )


@pytest.mark.django_db
def test_layout_config_get_and_patch(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """Layout config can be read and patched."""
    get_resp = dmr_client.get(
        reverse(
            'clips:layout_config',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )
    assert get_resp.status_code == HTTPStatus.OK
    assert get_resp.json()['render_mode'] == 'SMART_CROP'

    patch_resp = dmr_client.patch(
        reverse(
            'clips:layout_config',
            kwargs={'candidate_id': candidate.id},
        ),
        data={'render_mode': 'CENTER_CROP', 'stack_ratio': 0.5},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['render_mode'] == 'CENTER_CROP'
    assert patch_resp.json()['stack_ratio'] == 0.5


@pytest.mark.django_db
def test_layout_config_includes_source_dimensions(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    run: object,
    auth_headers: dict[str, str],
) -> None:
    """Layout GET returns source_width/height from clip_ingest asset meta."""
    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='source.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=run,  # type: ignore[arg-type]
        meta={'width': 1920, 'height': 1080},
    )
    StageExecution.objects.create(
        run=run,  # type: ignore[arg-type]
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        output={'asset_id': str(asset.id)},
    )

    response = dmr_client.get(
        reverse(
            'clips:layout_config',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['source_width'] == 1920
    assert data['source_height'] == 1080


@pytest.mark.django_db
def test_layout_smart_crop_endpoint(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """POST smart-crop delegates to ClipsService.reset_smart_crop."""
    from server.apps.clips.api.views import ClipLayoutSmartCropView
    from server.apps.clips.logic.value_objects import ClipLayoutConfigPayload

    layout = candidate.layout_config
    fake_payload = ClipLayoutConfigPayload(
        id=str(layout.id),
        candidate_id=str(candidate.id),
        render_mode='SMART_CROP',
        render_format='VERTICAL_9_16',
        source_width=1920,
        source_height=1080,
        manual_crop_x=None,
        manual_crop_y=None,
        manual_crop_w=None,
        manual_crop_h=None,
        region_a_x=None,
        region_a_y=None,
        region_a_w=None,
        region_a_h=None,
        region_b_x=None,
        region_b_y=None,
        region_b_w=None,
        region_b_h=None,
        stack_ratio=0.6,
        fit_mode='CROP',
        face_detected=None,
        detection_confidence=None,
    )
    mock_svc = MagicMock()
    mock_svc.reset_smart_crop.return_value = fake_payload
    with patch.object(
        ClipLayoutSmartCropView,
        'resolve',
        return_value=mock_svc,
    ):
        response = dmr_client.post(
            reverse(
                'clips:layout_config_smart_crop',
                kwargs={'candidate_id': candidate.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['render_mode'] == 'SMART_CROP'
    assert data['manual_crop_x'] is None
    assert data['face_detected'] is None
    mock_svc.reset_smart_crop.assert_called_once_with(str(candidate.id))


@pytest.mark.django_db
def test_style_config_get_and_patch(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """Style config can be read and patched."""
    get_resp = dmr_client.get(
        reverse(
            'clips:style_config',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )
    assert get_resp.status_code == HTTPStatus.OK
    assert get_resp.json()['caption_enabled'] is True

    patch_resp = dmr_client.patch(
        reverse(
            'clips:style_config',
            kwargs={'candidate_id': candidate.id},
        ),
        data={'caption_enabled': False, 'hook_size': 72},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['caption_enabled'] is False
    assert patch_resp.json()['hook_size'] == 72


@pytest.mark.django_db
def test_style_config_patch_emoji_keyword_map(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """Style PATCH accepts emoji_keyword_map."""
    response = dmr_client.patch(
        reverse(
            'clips:style_config',
            kwargs={'candidate_id': candidate.id},
        ),
        data={'emoji_keyword_map': {'money': '💰', 'fire': '🔥'}},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['emoji_keyword_map'] == {
        'money': '💰',
        'fire': '🔥',
    }


@pytest.mark.django_db
def test_overlay_crud(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """Overlays can be created, listed, patched, and deleted."""
    create_resp = dmr_client.post(
        reverse(
            'clips:overlay_list',
            kwargs={'candidate_id': candidate.id},
        ),
        data={
            'text': 'Subscribe',
            'start_sec': 1.0,
            'end_sec': 3.0,
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == HTTPStatus.CREATED
    overlay_id = create_resp.json()['id']

    list_resp = dmr_client.get(
        reverse(
            'clips:overlay_list',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert len(list_resp.json()['items']) == 1

    patch_resp = dmr_client.patch(
        reverse(
            'clips:overlay_detail',
            kwargs={
                'candidate_id': candidate.id,
                'overlay_id': overlay_id,
            },
        ),
        data={'text': 'Follow'},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['text'] == 'Follow'

    delete_resp = dmr_client.delete(
        reverse(
            'clips:overlay_detail',
            kwargs={
                'candidate_id': candidate.id,
                'overlay_id': overlay_id,
            },
        ),
        headers=auth_headers,
    )
    assert delete_resp.status_code == HTTPStatus.NO_CONTENT
    assert ClipTimedOverlay.objects.count() == 0


@pytest.mark.django_db
def test_post_create_and_list(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """Posts can be created and listed."""
    create_resp = dmr_client.post(
        reverse(
            'clips:post_list',
            kwargs={'candidate_id': candidate.id},
        ),
        data={
            'platform': 'youtube_shorts',
            'caption': 'Check this out',
            'hashtags': ['podcast', 'clips'],
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == HTTPStatus.CREATED
    post_id = create_resp.json()['id']

    list_resp = dmr_client.get(
        reverse(
            'clips:post_list',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert len(list_resp.json()['items']) == 1

    patch_resp = dmr_client.patch(
        reverse(
            'clips:post_detail',
            kwargs={
                'candidate_id': candidate.id,
                'post_id': post_id,
            },
        ),
        data={'caption': 'Updated caption'},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['caption'] == 'Updated caption'


@pytest.mark.django_db
def test_layout_config_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET layout config returns 404 for unknown candidate."""
    response = dmr_client.get(
        reverse(
            'clips:layout_config',
            kwargs={'candidate_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_source_frame_endpoint(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    run: object,
    auth_headers: dict[str, str],
) -> None:
    """GET source-frame returns presigned JPEG URL."""
    from pathlib import Path

    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='source.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=run,  # type: ignore[arg-type]
        meta={'width': 1920, 'height': 1080},
    )
    StageExecution.objects.create(
        run=run,  # type: ignore[arg-type]
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        output={'asset_id': str(asset.id)},
    )

    def _fake_ffmpeg(cmd: list[str], **kwargs: object) -> MagicMock:
        Path(cmd[-1]).write_bytes(b'jpeg-bytes')
        return MagicMock(returncode=0, stderr='')

    with patch('subprocess.run', side_effect=_fake_ffmpeg):
        response = dmr_client.get(
            reverse(
                'clips:candidate_source_frame',
                kwargs={'candidate_id': candidate.id},
            )
            + '?time_sec=15',
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['time_sec'] == 15.0
    assert data['url']
    assert data['width'] == 1920


@pytest.mark.django_db
def test_source_frame_missing_source_video(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """GET source-frame returns 400 when clip_ingest output is missing."""
    response = dmr_client.get(
        reverse(
            'clips:candidate_source_frame',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_source_frame_invalid_time_sec(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """GET source-frame returns 400 for non-numeric time_sec."""
    response = dmr_client.get(
        reverse(
            'clips:candidate_source_frame',
            kwargs={'candidate_id': candidate.id},
        )
        + '?time_sec=abc',
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_style_config_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET style config returns 404 for unknown candidate."""
    response = dmr_client.get(
        reverse(
            'clips:style_config',
            kwargs={'candidate_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_overlay_detail_not_found(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """GET overlay detail returns 404 for unknown overlay."""
    response = dmr_client.get(
        reverse(
            'clips:overlay_detail',
            kwargs={
                'candidate_id': candidate.id,
                'overlay_id': uuid.uuid4(),
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_post_detail_not_found(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """GET post detail returns 404 for unknown post."""
    response = dmr_client.get(
        reverse(
            'clips:post_detail',
            kwargs={
                'candidate_id': candidate.id,
                'post_id': uuid.uuid4(),
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_overlay_detail_get_success(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """GET overlay detail returns one overlay."""
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        text='Hello overlay',
        start_sec=1.0,
        end_sec=3.0,
    )

    response = dmr_client.get(
        reverse(
            'clips:overlay_detail',
            kwargs={
                'candidate_id': candidate.id,
                'overlay_id': overlay.id,
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['text'] == 'Hello overlay'


@pytest.mark.django_db
def test_post_detail_get_success(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """GET post detail returns one distribution post."""
    from server.apps.clips.models import ClipPost

    post = ClipPost.objects.create(
        candidate=candidate,
        platform='youtube_shorts',
        caption='Detail caption',
    )

    response = dmr_client.get(
        reverse(
            'clips:post_detail',
            kwargs={
                'candidate_id': candidate.id,
                'post_id': post.id,
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['caption'] == 'Detail caption'
