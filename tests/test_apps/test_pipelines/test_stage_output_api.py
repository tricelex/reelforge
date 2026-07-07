"""Tests for the per-stage output endpoint and asset attribution."""

import uuid
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import Asset, AssetKind
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.clips.models import ClipCandidate
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)

_PRESIGN = 'server.common.storage.PresignUrlHelper.presign_get'
_URL = 'api:pipelines_api:run-stage-output'


@pytest.fixture
def channel(db: None) -> Channel:
    """Longform channel for stage output tests."""
    return Channel.objects.create(
        name='Stage Output Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def blueprint(db: None) -> PipelineBlueprint:
    """Active longform blueprint."""
    return PipelineBlueprint.objects.create(
        name='stage_output_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
        is_active=True,
        version=1,
    )


@pytest.fixture
def run(channel: Channel, blueprint: PipelineBlueprint) -> PipelineRun:
    """Pipeline run for stage output endpoints."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Stage output test',
    )


def _stage(
    run: PipelineRun,
    stage_key: str,
    output: dict[str, Any],
    *,
    status: str = StageStatus.SUCCEEDED,
    attempt: int = 0,
    parent: StageExecution | None = None,
    shard_index: int | None = None,
) -> StageExecution:
    return StageExecution.objects.create(
        run=run,
        stage_key=stage_key,
        status=status,
        attempt=attempt,
        parent=parent,
        shard_index=shard_index,
        output=output,
    )


def _asset(
    run: PipelineRun,
    kind: str,
    stage_exec: StageExecution | None,
    *,
    name: str = 'file.bin',
    mime: str = 'application/octet-stream',
    checksum: str = 'chk',
) -> Asset:
    return Asset.objects.create(
        kind=kind,
        file=ContentFile(b'data', name=name),
        mime=mime,
        checksum=checksum,
        run=run,
        stage_execution=stage_exec,
    )


def _get(
    dmr_client: DMRClient,
    run_id: Any,
    stage_key: str,
    auth_headers: dict[str, str],
) -> Any:
    with patch(_PRESIGN, return_value='https://storage.example/x'):
        return dmr_client.get(
            reverse(_URL, kwargs={'run_id': run_id, 'stage_key': stage_key}),
            headers=auth_headers,
        )


@pytest.mark.django_db
def test_unknown_run_returns_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """A run id that does not exist yields 404."""
    response = _get(dmr_client, uuid.uuid4(), 'research', auth_headers)
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_unknown_stage_returns_404(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """An unrecognised stage key yields 404."""
    response = _get(dmr_client, run.id, 'not_a_stage', auth_headers)
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_unexpected_error_propagates(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Non-404 exceptions fall through the controller error handler."""
    with (
        patch(
            'server.apps.pipelines.api.views.get_stage_output',
            side_effect=ValueError('boom'),
        ),
        pytest.raises(ValueError, match='boom'),
    ):
        dmr_client.get(
            reverse(_URL, kwargs={'run_id': run.id, 'stage_key': 'research'}),
            headers=auth_headers,
        )


@pytest.mark.django_db
def test_empty_when_stage_not_run(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """A valid stage with no execution returns empty content."""
    response = _get(dmr_client, run.id, 'outline', auth_headers)
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['stage_key'] == 'outline'
    assert body['status'] == StageStatus.PENDING
    assert body['kind'] == 'text'
    assert body['text'] is None
    assert body['data'] is None
    assert body['assets'] == []


@pytest.mark.django_db
def test_status_reflects_latest_failed_attempt(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Output uses the succeeded attempt while status shows the latest."""
    _stage(
        run,
        'research',
        {
            'brief': {
                'topic': 'A',
                'key_facts': ['f'],
                'narrative_angles': ['x'],
            },
            'sources': [{'url': 'u'}],
        },
        attempt=0,
    )
    _stage(run, 'research', {}, status=StageStatus.FAILED, attempt=1)

    body = _get(dmr_client, run.id, 'research', auth_headers).json()
    assert body['status'] == StageStatus.FAILED
    assert body['kind'] == 'text'
    assert 'Research: A' in body['text']
    assert body['summary'] == 'A - 1 sources'


@pytest.mark.django_db
def test_outline_text(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Outline stage renders as text."""
    _stage(
        run,
        'outline',
        {'chapters': [{'idx': 1, 'title': 'Intro', 'thesis': 'why'}]},
    )
    body = _get(dmr_client, run.id, 'outline', auth_headers).json()
    assert body['kind'] == 'text'
    assert body['summary'] == '1 chapters'
    assert 'Intro' in body['text']


@pytest.mark.django_db
def test_script_text(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Script stage renders full narration text with duration summary."""
    _stage(
        run,
        'script',
        {'chapters': [{'text': 'Once upon a time'}], 'total_word_count': 300},
    )
    body = _get(dmr_client, run.id, 'script', auth_headers).json()
    assert body['kind'] == 'text'
    assert body['text'] == 'Once upon a time'
    assert body['summary'] == '300 words (~2 min)'


@pytest.mark.django_db
def test_scene_breakdown_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Scene breakdown returns structured scene data."""
    _stage(
        run,
        'scene_breakdown',
        {'scenes': [{'idx': 0, 'beat': 'open', 'narration_text': 'hi'}]},
    )
    body = _get(dmr_client, run.id, 'scene_breakdown', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data']['scenes'][0] == {
        'index': 0,
        'heading': 'open',
        'text': 'hi',
    }


@pytest.mark.django_db
def test_visual_prompts_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Visual prompts stage returns prompt data."""
    _stage(
        run,
        'visual_prompts',
        {
            'prompts': [
                {'scene_idx': 0, 'prompt': 'a cat', 'negative_prompt': 'b'},
            ],
        },
    )
    body = _get(dmr_client, run.id, 'visual_prompts', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data']['prompts'][0]['scene_index'] == 0
    assert body['data']['prompts'][0]['prompt'] == 'a cat'


@pytest.mark.django_db
def test_music_plan_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Music plan stage returns entry data."""
    _stage(run, 'music_plan', {'entries': [{'chapter_idx': 0}]})
    body = _get(dmr_client, run.id, 'music_plan', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['summary'] == '1 tracks'
    assert body['data']['entries'] == [{'chapter_idx': 0}]


@pytest.mark.django_db
def test_alignment_mixed(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Alignment returns timing data plus a subtitle asset (mixed)."""
    exec_ = _stage(
        run,
        'alignment',
        {'scenes': [{'start_s': 0.0, 'end_s': 1.0}]},
    )
    _asset(run, AssetKind.SUBTITLE, exec_, name='c.ass', mime='text/x-ssa')
    body = _get(dmr_client, run.id, 'alignment', auth_headers).json()
    assert body['kind'] == 'mixed'
    assert body['data']['scenes'][0]['start_s'] == 0.0
    assert body['assets'][0]['label'] == 'captions'
    assert body['assets'][0]['stage_key'] == 'alignment'


@pytest.mark.django_db
def test_qc_passed_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """QC passing returns passed=True with no checks."""
    _stage(run, 'qc', {'passed': True, 'qc_report': {'failures': []}})
    body = _get(dmr_client, run.id, 'qc', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data']['passed'] is True
    assert body['data']['checks'] == []
    assert body['summary'] == 'QC passed'


@pytest.mark.django_db
def test_qc_failed_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """QC failing lists the failed checks."""
    _stage(
        run,
        'qc',
        {
            'passed': False,
            'qc_report': {
                'failures': [{'check': 'loudness', 'detail': 'quiet'}],
            },
        },
    )
    body = _get(dmr_client, run.id, 'qc', auth_headers).json()
    assert body['data']['passed'] is False
    assert body['data']['checks'][0]['name'] == 'loudness'
    assert body['summary'] == '1 QC failures'


@pytest.mark.django_db
def test_metadata_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Metadata stage returns YouTube metadata fields."""
    _stage(
        run,
        'metadata',
        {'title': 'Great Video', 'description': 'd', 'tags': ['t']},
    )
    body = _get(dmr_client, run.id, 'metadata', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['summary'] == 'Great Video'
    assert body['data']['title'] == 'Great Video'
    assert body['data']['made_for_kids'] is False
    assert body['data']['ai_disclosure'] is True


@pytest.mark.django_db
def test_gate_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """A gate stage returns its decision data."""
    _stage(run, 'storyboard_gate', {'approved': True})
    body = _get(dmr_client, run.id, 'storyboard_gate', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data'] == {'approved': True}


@pytest.mark.django_db
def test_publish_published_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Publish stage exposes watch_url and external id once uploaded."""
    _stage(run, 'publish', {'youtube_video_id': 'vid123'})
    _stage(run, 'review_gate', {'schedule_at': '2026-07-07T10:00:00'})
    body = _get(dmr_client, run.id, 'publish', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data']['external_video_id'] == 'vid123'
    assert 'watch?v=vid123' in body['data']['watch_url']
    assert body['data']['status'] == 'COMPLETED'
    assert body['data']['scheduled_at'] == '2026-07-07T10:00:00'
    assert body['summary'] == 'Published to YouTube'


@pytest.mark.django_db
def test_publish_pending_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Publish stage without a video id or gate returns empty publish data."""
    _stage(run, 'publish', {})
    body = _get(dmr_client, run.id, 'publish', auth_headers).json()
    assert body['data']['status'] == 'PENDING'
    assert body['data']['watch_url'] is None
    assert body['data']['external_video_id'] is None
    assert body['data']['scheduled_at'] is None
    assert body['summary'] is None


@pytest.mark.django_db
def test_clip_ingest_mixed_with_resolution(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Clip ingest returns source metadata plus the source asset."""
    exec_ = _stage(
        run,
        'clip_ingest',
        {
            'source_duration_sec': 60.0,
            'source_width': 1920,
            'source_height': 1080,
            'source_title': 'My Video',
        },
    )
    _asset(run, AssetKind.VIDEO_SEGMENT, exec_, name='s.mp4', mime='video/mp4')
    body = _get(dmr_client, run.id, 'clip_ingest', auth_headers).json()
    assert body['kind'] == 'mixed'
    assert body['data']['resolution'] == '1920x1080'
    assert body['summary'] == 'My Video'
    assert body['assets'][0]['label'] is None


@pytest.mark.django_db
def test_clip_ingest_without_resolution(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Clip ingest without probe dimensions returns null resolution."""
    _stage(run, 'clip_ingest', {'source_duration_sec': 60.0})
    body = _get(dmr_client, run.id, 'clip_ingest', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data']['resolution'] is None


@pytest.mark.django_db
def test_clip_transcribe_text(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Clip transcribe returns the transcript text."""
    _stage(run, 'clip_transcribe', {'transcript_text': 'hello world'})
    body = _get(dmr_client, run.id, 'clip_transcribe', auth_headers).json()
    assert body['kind'] == 'text'
    assert body['text'] == 'hello world'


@pytest.mark.django_db
def test_clip_detect_alias_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """clip_detect aliases to clip_analyze and lists candidate windows."""
    _stage(run, 'clip_analyze', {'candidate_count': 1})
    candidate = ClipCandidate.objects.create(
        run=run,
        start_sec=1.0,
        end_sec=5.0,
        title='Wild fact',
        reason='funny',
        relevance_score=0.9,
    )
    body = _get(dmr_client, run.id, 'clip_detect', auth_headers).json()
    assert body['stage_key'] == 'clip_detect'
    assert body['kind'] == 'json'
    entry = body['data']['candidates'][0]
    assert entry['id'] == str(candidate.id)
    assert entry['start_s'] == 1.0
    assert entry['reason'] == 'funny'


@pytest.mark.django_db
def test_clip_score_alias_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """clip_score aliases to clip_analyze and lists candidate scores."""
    _stage(run, 'clip_analyze', {'candidate_count': 1})
    ClipCandidate.objects.create(
        run=run,
        start_sec=1.0,
        end_sec=5.0,
        title='Wild fact',
        reason='funny',
        relevance_score=0.9,
    )
    body = _get(dmr_client, run.id, 'clip_score', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data']['candidates'][0]['score'] == 0.9
    assert body['summary'] == '1 scored clips'


@pytest.mark.django_db
def test_clip_approval_alias_json(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """clip_approval aliases to clip_approval_gate and returns its output."""
    _stage(run, 'clip_approval_gate', {'approved_candidate_ids': ['a']})
    body = _get(dmr_client, run.id, 'clip_approval', auth_headers).json()
    assert body['kind'] == 'json'
    assert body['data'] == {'approved_candidate_ids': ['a']}


@pytest.mark.django_db
def test_assembly_media_matches_preview(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Assembly output and /preview expose the same playable asset."""
    asset = _asset(
        run,
        AssetKind.FINAL_VIDEO,
        None,
        name='final.mp4',
        mime='video/mp4',
    )
    exec_ = _stage(
        run,
        'assembly',
        {'asset_id': str(asset.id), 'duration_s': 42.0},
    )
    asset.stage_execution = exec_
    asset.save(update_fields=['stage_execution'])

    with patch(_PRESIGN, return_value='https://storage.example/final.mp4'):
        out = dmr_client.get(
            reverse(_URL, kwargs={'run_id': run.id, 'stage_key': 'assembly'}),
            headers=auth_headers,
        ).json()
        preview = dmr_client.get(
            reverse(
                'api:pipelines_api:run-preview',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        ).json()

    assert out['kind'] == 'media'
    assert out['assets'][0]['id'] == str(asset.id)
    assert out['assets'][0]['label'] == 'assembled video'
    assert preview['asset_id'] == str(asset.id)
    assert out['assets'][0]['id'] == preview['asset_id']


@pytest.mark.django_db
def test_image_gen_media_scene_label(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Image gen returns per-scene image assets labelled by scene."""
    parent = _stage(run, 'image_gen', {'shards': []})
    child = _stage(
        run,
        'image_gen',
        {'scene_idx': 4, 'asset_id': 'x'},
        parent=parent,
        shard_index=0,
    )
    _asset(run, AssetKind.IMAGE, child, name='s.png', mime='image/png')
    body = _get(dmr_client, run.id, 'image_gen', auth_headers).json()
    assert body['kind'] == 'media'
    assert body['assets'][0]['label'] == 'scene 4'
    assert body['assets'][0]['stage_key'] == 'image_gen'


@pytest.mark.django_db
def test_run_detail_exposes_watch_url(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Run detail surfaces watch_url once the publish stage succeeds."""
    _stage(run, 'publish', {'youtube_video_id': 'abc987'})
    response = dmr_client.get(
        reverse('api:pipelines_api:run-detail', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['external_video_id'] == 'abc987'
    assert body['watch_url'] == 'https://www.youtube.com/watch?v=abc987'


@pytest.mark.django_db
def test_asset_labels_cover_all_stages(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """The run assets endpoint attributes and labels each asset."""
    motion_child = _stage(
        run,
        'motion',
        {'scene_idx': 1},
        shard_index=0,
    )
    _asset(run, AssetKind.VIDEO_SEGMENT, motion_child, name='m.mp4')
    img_no_idx = _stage(run, 'image_gen', {}, shard_index=None)
    _asset(run, AssetKind.IMAGE, img_no_idx, name='i.png')
    tts_child = _stage(run, 'tts', {'chapter_idx': 3}, shard_index=0)
    _asset(run, AssetKind.AUDIO_VO, tts_child, name='a.mp3')
    tts_no_idx = _stage(run, 'tts', {}, shard_index=None)
    _asset(run, AssetKind.AUDIO_VO, tts_no_idx, name='a2.mp3')
    thumb = _stage(run, 'thumbnail', {})
    _asset(run, AssetKind.THUMBNAIL, thumb, name='t.jpg')

    candidate = ClipCandidate.objects.create(
        run=run,
        start_sec=0,
        end_sec=1,
        title='Best Clip',
    )
    render_titled = _stage(
        run,
        'clip_render',
        {'candidate_id': str(candidate.id)},
        shard_index=0,
    )
    _asset(run, AssetKind.FINAL_VIDEO, render_titled, name='r1.mp4')
    render_missing = _stage(
        run,
        'clip_render',
        {'candidate_id': str(uuid.uuid4())},
        shard_index=1,
    )
    _asset(run, AssetKind.FINAL_VIDEO, render_missing, name='r2.mp4')
    render_noid = _stage(run, 'clip_render', {}, shard_index=2)
    _asset(run, AssetKind.FINAL_VIDEO, render_noid, name='r3.mp4')

    with patch(_PRESIGN, return_value='https://storage.example/x'):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-assets',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    labels = {item['id']: item['label'] for item in response.json()['items']}
    values = set(labels.values())
    assert 'scene 1' in values
    assert 'chapter 3' in values
    assert 'thumbnail' in values
    assert 'clip: Best Clip' in values
    assert 'clip' in values
    assert None in values
