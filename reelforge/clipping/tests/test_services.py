from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from reelforge.services.transcription.whisper import WhisperTranscriptionService


def test_whisper_service_parses_response() -> None:
    mock_response = {
        "text": "Hello world this is a test",
        "segments": [
            {
                "start": 0.0,
                "end": 2.5,
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.5},
                    {"word": "world", "start": 0.6, "end": 1.0},
                ],
            }
        ],
        "duration": 2.5,
        "language": "en",
    }

    with patch("openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = MagicMock(
            model_dump=lambda: mock_response
        )

        service = WhisperTranscriptionService(api_key="test-key")
        result = service._parse_response(mock_response)

    assert result.transcript_text == "Hello world this is a test"
    assert result.duration_sec == 2.5
    assert len(result.transcript_json["segments"]) == 1


def test_whisper_service_calculates_cost() -> None:
    service = WhisperTranscriptionService(api_key="test-key")
    cost = service._calculate_cost(duration_sec=60.0)
    # Whisper costs $0.006 per minute
    assert cost == Decimal("0.006")


from reelforge.clipping.services import ClipAnalysisService
from reelforge.clipping.tests.factories import ClippingJobFactory

SAMPLE_TRANSCRIPT_JSON = {
    "text": "This is amazing. You should try this. The results will surprise you.",
    "segments": [
        {
            "start": 0.0, "end": 60.0, "text": "This is amazing.",
            "words": [
                {"word": "This", "start": 0.0, "end": 0.3},
                {"word": "is", "start": 0.4, "end": 0.5},
                {"word": "amazing.", "start": 0.6, "end": 1.0},
            ],
        },
        {
            "start": 60.0, "end": 120.0, "text": "You should try this.",
            "words": [
                {"word": "You", "start": 60.0, "end": 60.2},
                {"word": "should", "start": 60.3, "end": 60.6},
                {"word": "try", "start": 60.7, "end": 60.9},
                {"word": "this.", "start": 61.0, "end": 61.3},
            ],
        },
    ],
    "duration": 120.0,
}


@pytest.mark.django_db
def test_clip_analysis_service_creates_candidates() -> None:
    from reelforge.ai.schemas.clipping import ClipData
    from reelforge.clipping.models import ClipCandidate

    job = ClippingJobFactory(
        transcript_json=SAMPLE_TRANSCRIPT_JSON,
        transcript_text="This is amazing. You should try this.",
        clips_requested=2,
    )

    mock_clips = [
        ClipData(
            start_sec=0.0,
            end_sec=61.3,
            title="Amazing discovery",
            hook_text="This will blow your mind",
            caption_template="Amazing discovery",
            relevance_score=9.0,
            reason="High engagement opener",
        ),
        ClipData(
            start_sec=65.0,
            end_sec=120.0,
            title="Try this method",
            hook_text="The method that changes everything",
            caption_template="Try this method",
            relevance_score=8.5,
            reason="Actionable advice",
        ),
    ]

    mock_result = MagicMock()
    mock_result.output.clips = mock_clips

    with patch(
        "reelforge.ai.agents.clip_analysis.clip_analysis_agent.run_sync",
        return_value=mock_result,
    ):
        service = ClipAnalysisService(job)
        candidates = service.analyze()

    assert len(candidates) == 2
    assert ClipCandidate.objects.filter(clipping_job=job).count() == 2
    assert candidates[0].relevance_score == 9.0
    assert candidates[0].transcript_excerpt != ""


@pytest.mark.django_db
def test_build_prompt_includes_words_json() -> None:
    import json

    job = ClippingJobFactory(
        transcript_json=SAMPLE_TRANSCRIPT_JSON,
        transcript_text="This is amazing.",
        clips_requested=1,
    )
    enriched = [
        {"word": "This", "start": 0.0, "end": 0.3, "speaker_id": "SPEAKER_00"},
        {"word": "is", "start": 0.4, "end": 0.5, "speaker_id": "SPEAKER_00"},
        {"word": "amazing.", "start": 0.6, "end": 1.0, "speaker_id": "SPEAKER_00"},
    ]
    service = ClipAnalysisService(job)
    prompt = service._build_prompt(
        "This is amazing.",
        enriched_transcript=enriched,
        scene_cuts=[30.0, 60.5],
        video_duration=120.0,
    )

    assert "WORDS_JSON" in prompt
    assert "VIDEO_DURATION_SECONDS: 120.000" in prompt
    assert "SCENE_CUTS" in prompt
    words_line = next(line for line in prompt.split("\n") if line.startswith("[{"))
    parsed = json.loads(words_line)
    assert len(parsed) == 3
    assert parsed[0] == {"w": "This", "s": 0.0, "e": 0.3, "spk": "SPEAKER_00"}


@pytest.mark.django_db
def test_build_prompt_without_enriched_transcript() -> None:
    job = ClippingJobFactory(
        transcript_json=SAMPLE_TRANSCRIPT_JSON,
        transcript_text="This is amazing.",
        clips_requested=1,
    )
    service = ClipAnalysisService(job)
    prompt = service._build_prompt("This is amazing.")

    assert "This is amazing." in prompt
    assert "WORDS_JSON" not in prompt
    assert "SCENE_CUTS" not in prompt
    assert "VIDEO_DURATION_SECONDS" not in prompt
    assert "Number of clips to identify: 1" in prompt


@pytest.mark.django_db
def test_clip_analysis_service_extracts_transcript_excerpt() -> None:
    job = ClippingJobFactory(transcript_json=SAMPLE_TRANSCRIPT_JSON)
    service = ClipAnalysisService(job)

    excerpt = service._extract_transcript_excerpt(start_sec=0.0, end_sec=2.0)
    assert "This" in excerpt
    assert "amazing" in excerpt
