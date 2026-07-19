"""Tests for ClipAnalysisService."""

from unittest.mock import MagicMock, patch

import pytest

from server.apps.clips.analysis import (
    ClipAnalysisService,
    ClipSegment,
    ClipsOutput,
)


def _segment(**overrides: object) -> ClipSegment:
    data: dict[str, object] = {
        'start_sec': 10.0,
        'end_sec': 70.0,
        'title': 'Test',
        'hook_text': 'Hook',
        'caption_template': '',
        'hook_score': 90.0,
        'flow_score': 85.0,
        'value_score': 88.0,
        'trend_score': 80.0,
        'reason': 'good',
    }
    data.update(overrides)
    return ClipSegment(**data)  # type: ignore[arg-type]


def test_clip_segment_schema() -> None:
    seg = _segment()
    assert seg.start_sec == 10.0
    assert seg.end_sec == 70.0
    assert seg.hook_score == 90.0


def test_clips_output_schema() -> None:
    output = ClipsOutput(clips=[_segment(title='T', hook_text='H')])
    assert len(output.clips) == 1


def test_clip_segment_default_caption_template() -> None:
    seg = _segment(caption_template='')
    assert seg.caption_template == ''


def test_build_prompt_includes_duration() -> None:
    run = MagicMock()
    run.prompt_snapshot = {}
    svc = ClipAnalysisService(run=run, clips_requested=3)
    prompt = svc._build_prompt(
        'Hello world',
        [],
        [],
        video_duration=120.5,
        window_start=0.0,
        window_end=120.5,
    )
    assert 'VIDEO_DURATION_SECONDS: 120.500' in prompt
    assert 'Number of clips to identify: 3' in prompt


def test_build_prompt_includes_speaker_count() -> None:
    run = MagicMock()
    run.prompt_snapshot = {}
    svc = ClipAnalysisService(run=run)
    enriched = [
        {'word': 'Hi', 'start': 0.0, 'end': 0.5, 'speaker_id': 'A'},
        {'word': 'there', 'start': 0.5, 'end': 1.0, 'speaker_id': 'B'},
        {'word': 'you', 'start': 1.0, 'end': 1.5, 'speaker_id': 'A'},
    ]
    prompt = svc._build_prompt(
        'text',
        enriched,
        [],
        None,
        window_start=0.0,
        window_end=10.0,
    )
    assert '2 speaker(s)' in prompt


def test_build_prompt_omits_speaker_count_when_all_unknown() -> None:
    run = MagicMock()
    run.prompt_snapshot = {}
    svc = ClipAnalysisService(run=run)
    enriched = [
        {'word': 'Hi', 'start': 0.0, 'end': 0.5, 'speaker_id': 'UNKNOWN'},
        {'word': 'there', 'start': 0.5, 'end': 1.0, 'speaker_id': 'UNKNOWN'},
    ]
    prompt = svc._build_prompt(
        'text',
        enriched,
        [],
        None,
        window_start=0.0,
        window_end=10.0,
    )
    assert 'speaker(s)' not in prompt


def test_build_prompt_includes_scene_cuts() -> None:
    run = MagicMock()
    run.prompt_snapshot = {}
    svc = ClipAnalysisService(run=run)
    prompt = svc._build_prompt(
        'text',
        [],
        [5.0, 10.0, 20.5],
        None,
        window_start=0.0,
        window_end=30.0,
    )
    assert 'SCENE_CUTS' in prompt
    assert '5.0' in prompt


def test_build_prompt_includes_creator_brief() -> None:
    run = MagicMock()
    run.prompt_snapshot = {
        'clip_options': {'moments_prompt': 'find product launches'},
    }
    svc = ClipAnalysisService(run=run)
    prompt = svc._build_prompt(
        'text',
        [],
        [],
        None,
        window_start=0.0,
        window_end=30.0,
    )
    assert 'CREATOR_BRIEF' in prompt
    assert 'find product launches' in prompt


def test_build_prompt_includes_words_json() -> None:
    run = MagicMock()
    run.prompt_snapshot = {}
    svc = ClipAnalysisService(run=run)
    enriched = [
        {'word': 'Hello', 'start': 0.0, 'end': 0.5, 'speaker_id': 'A'},
        {'word': 'world', 'start': 0.5, 'end': 1.0, 'speaker_id': 'A'},
    ]
    prompt = svc._build_prompt(
        'Hello world',
        enriched,
        [],
        None,
        window_start=0.0,
        window_end=10.0,
    )
    assert 'WORDS_JSON' in prompt
    assert 'Hello' in prompt


def test_extract_excerpt() -> None:
    run = MagicMock()
    run.prompt_snapshot = {}
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
    run.prompt_snapshot = {}
    svc = ClipAnalysisService(run=run)
    assert svc._extract_excerpt([], 0.0, 60.0) == ''


@pytest.mark.django_db
def test_analyze_creates_candidates() -> None:
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )
    from server.apps.clips.models import ClipCandidate
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )

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
            _segment(
                title='Great clip',
                hook_text='Watch this!',
                hook_score=95.0,
                flow_score=90.0,
                value_score=92.0,
                trend_score=88.0,
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
                {
                    'word': 'Hello',
                    'start': 10.0,
                    'end': 10.5,
                    'speaker_id': 'A',
                },
                {
                    'word': 'world',
                    'start': 60.0,
                    'end': 60.5,
                    'speaker_id': 'A',
                },
            ],
            scene_cuts=[5.0, 20.0],
            video_duration=120.0,
        )

    assert len(candidates) == 1
    assert ClipCandidate.objects.filter(run=run).count() == 1
    assert candidates[0].title == 'Great clip'
    assert candidates[0].virality_score > 0
    assert candidates[0].hook_score == 95.0


@pytest.mark.django_db
def test_analyze_skips_invalid_candidates_with_warning() -> None:
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

    mock_output = ClipsOutput(clips=[_segment(title='Valid clip')])
    mock_result = MagicMock()
    mock_result.output = mock_output

    with patch('server.apps.clips.analysis.clip_analysis_agent') as mock_agent:
        with patch(
            'server.apps.clips.models.ClipCandidate.objects.create',
        ) as mock_create:
            mock_create.side_effect = [ValueError('DB error')]
            mock_agent.run_sync.return_value = mock_result
            svc = ClipAnalysisService(run=run, clips_requested=5)
            candidates = svc.analyze(
                transcript_text='text',
                enriched_transcript=[
                    {'word': 'a', 'start': 10.0, 'end': 10.2},
                    {'word': 'b', 'start': 70.0, 'end': 70.2},
                ],
                video_duration=120.0,
            )

    assert candidates == []


@pytest.mark.django_db
def test_analyze_clips_requested_limits_results() -> None:
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )
    from server.apps.clips.models import ClipCandidate
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )

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
            _segment(
                start_sec=float(i * 70),
                end_sec=float(i * 70 + 50),
                title=f'Clip {i}',
                hook_score=90.0 - i,
                flow_score=85.0,
                value_score=80.0,
                trend_score=75.0,
            )
            for i in range(5)
        ],
    )
    mock_result = MagicMock()
    mock_result.output = mock_output

    with patch('server.apps.clips.analysis.clip_analysis_agent') as mock_agent:
        mock_agent.run_sync.return_value = mock_result
        svc = ClipAnalysisService(run=run, clips_requested=2)
        candidates = svc.analyze(
            transcript_text='text',
            enriched_transcript=[
                {'word': 'x', 'start': 0.0, 'end': 0.2},
                {'word': 'y', 'start': 400.0, 'end': 400.2},
            ],
            video_duration=500.0,
        )

    assert len(candidates) == 2
    assert ClipCandidate.objects.filter(run=run).count() == 2
