"""Tests for ClipAnalysisService."""

from unittest.mock import MagicMock, patch

import pytest

from server.apps.clips.analysis import ClipAnalysisService, ClipSegment, ClipsOutput


def test_clip_segment_schema() -> None:
    seg = ClipSegment(
        start_sec=10.0,
        end_sec=70.0,
        title='Test',
        hook_text='Hook',
        caption_template='',
        relevance_score=0.9,
        reason='good',
    )
    assert seg.start_sec == 10.0
    assert seg.end_sec == 70.0


def test_clips_output_schema() -> None:
    output = ClipsOutput(
        clips=[
            ClipSegment(
                start_sec=0.0,
                end_sec=60.0,
                title='T',
                hook_text='H',
                caption_template='',
                relevance_score=0.8,
                reason='r',
            ),
        ],
    )
    assert len(output.clips) == 1


def test_clip_segment_default_caption_template() -> None:
    seg = ClipSegment(
        start_sec=0.0,
        end_sec=30.0,
        title='T',
        hook_text='H',
        relevance_score=0.5,
        reason='r',
    )
    assert seg.caption_template == ''


def test_build_prompt_includes_duration() -> None:
    run = MagicMock()
    svc = ClipAnalysisService(run=run, clips_requested=3)
    prompt = svc._build_prompt(
        'Hello world', None, None, None, video_duration=120.5,
    )
    assert 'VIDEO_DURATION_SECONDS: 120.500' in prompt
    assert 'Number of clips to identify: 3' in prompt


def test_build_prompt_includes_speaker_count() -> None:
    run = MagicMock()
    svc = ClipAnalysisService(run=run)
    diarization = {
        'segments': [
            {'speaker_id': 'A', 'start': 0.0, 'end': 5.0},
            {'speaker_id': 'B', 'start': 5.0, 'end': 10.0},
            {'speaker_id': 'A', 'start': 10.0, 'end': 15.0},
        ],
    }
    prompt = svc._build_prompt('text', None, diarization, None, None)
    assert '2 speaker(s)' in prompt


def test_build_prompt_includes_scene_cuts() -> None:
    run = MagicMock()
    svc = ClipAnalysisService(run=run)
    prompt = svc._build_prompt('text', None, None, [5.0, 10.0, 20.5], None)
    assert 'SCENE_CUTS' in prompt
    assert '5.0' in prompt


def test_build_prompt_includes_words_json() -> None:
    run = MagicMock()
    svc = ClipAnalysisService(run=run)
    enriched = [
        {'word': 'Hello', 'start': 0.0, 'end': 0.5, 'speaker_id': 'A'},
        {'word': 'world', 'start': 0.5, 'end': 1.0, 'speaker_id': 'A'},
    ]
    prompt = svc._build_prompt('Hello world', enriched, None, None, None)
    assert 'WORDS_JSON' in prompt
    assert 'Hello' in prompt


def test_extract_excerpt() -> None:
    run = MagicMock()
    svc = ClipAnalysisService(run=run)
    enriched = [
        {'word': 'Hello', 'start': 0.0, 'end': 0.5},
        {'word': 'world', 'start': 0.5, 'end': 1.0},
        {'word': 'outside', 'start': 5.0, 'end': 5.5},
    ]
    excerpt = svc._extract_excerpt(enriched, 0.0, 2.0)
    assert 'Hello' in excerpt
    assert 'world' in excerpt
    assert 'outside' not in excerpt


def test_extract_excerpt_empty() -> None:
    run = MagicMock()
    svc = ClipAnalysisService(run=run)
    assert svc._extract_excerpt([], 0.0, 60.0) == ''


@pytest.mark.django_db
def test_analyze_creates_candidates() -> None:
    from server.apps.channels.models import Channel, ChannelKind, PublishMode  # noqa: PLC0415
    from server.apps.clips.models import ClipCandidate
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind, PipelineRun

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
        topic='https://youtube.com/test',
    )

    mock_output = ClipsOutput(
        clips=[
            ClipSegment(
                start_sec=10.0,
                end_sec=70.0,
                title='Great clip',
                hook_text='Watch this!',
                caption_template='',
                relevance_score=0.95,
                reason='High energy moment',
            ),
        ],
    )
    mock_result = MagicMock()
    mock_result.output = mock_output

    with patch('server.apps.clips.analysis.clip_analysis_agent') as mock_agent:
        mock_agent.run_sync.return_value = mock_result
        svc = ClipAnalysisService(run=run, clips_requested=5)
        candidates = svc.analyze(
            transcript_text='Hello world',
            enriched_transcript=[
                {'word': 'Hello', 'start': 10.0, 'end': 10.5, 'speaker_id': 'A'},
            ],
            diarization={'segments': []},
            scene_cuts=[5.0, 20.0],
            video_duration=120.0,
        )

    assert len(candidates) == 1
    assert ClipCandidate.objects.filter(run=run).count() == 1
    assert candidates[0].title == 'Great clip'
    assert candidates[0].relevance_score == 0.95


@pytest.mark.django_db
def test_analyze_skips_invalid_candidates_with_warning() -> None:
    from server.apps.channels.models import Channel, ChannelKind, PublishMode  # noqa: PLC0415
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind, PipelineRun

    channel = Channel.objects.create(
        name='Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    bp = PipelineBlueprint.objects.create(
        name='clipping_v1_bad',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/test',
    )

    mock_output = ClipsOutput(
        clips=[
            ClipSegment(
                start_sec=10.0,
                end_sec=70.0,
                title='Valid clip',
                hook_text='H',
                relevance_score=0.9,
                reason='r',
            ),
        ],
    )
    mock_result = MagicMock()
    mock_result.output = mock_output

    with patch('server.apps.clips.analysis.clip_analysis_agent') as mock_agent:
        with patch(
            'server.apps.clips.models.ClipCandidate.objects.create',
        ) as mock_create:
            mock_create.side_effect = [ValueError('DB error')]
            mock_agent.run_sync.return_value = mock_result
            svc = ClipAnalysisService(run=run, clips_requested=5)
            candidates = svc.analyze(transcript_text='text')

    assert candidates == []


@pytest.mark.django_db
def test_analyze_clips_requested_limits_results() -> None:
    from server.apps.channels.models import Channel, ChannelKind, PublishMode  # noqa: PLC0415
    from server.apps.clips.models import ClipCandidate
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind, PipelineRun

    channel = Channel.objects.create(
        name='Limit Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    bp = PipelineBlueprint.objects.create(
        name='clipping_limit',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/limit',
    )

    mock_output = ClipsOutput(
        clips=[
            ClipSegment(
                start_sec=float(i * 60),
                end_sec=float(i * 60 + 50),
                title=f'Clip {i}',
                hook_text='H',
                relevance_score=0.9,
                reason='r',
            )
            for i in range(5)
        ],
    )
    mock_result = MagicMock()
    mock_result.output = mock_output

    with patch('server.apps.clips.analysis.clip_analysis_agent') as mock_agent:
        mock_agent.run_sync.return_value = mock_result
        svc = ClipAnalysisService(run=run, clips_requested=2)
        candidates = svc.analyze(transcript_text='text')

    assert len(candidates) == 2
    assert ClipCandidate.objects.filter(run=run).count() == 2
