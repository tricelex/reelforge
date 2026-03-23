from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.services.transcription.whisper import WhistlerTranscriptionResult
from ***REMOVED***.services.transcription.whisper import WhisperTranscriptionService


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


from ***REMOVED***.clipping.services import ClipAnalysisService
from ***REMOVED***.clipping.tests.factories import ClippingJobFactory


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
    job = ClippingJobFactory(
        transcript_json=SAMPLE_TRANSCRIPT_JSON,
        transcript_text="This is amazing. You should try this.",
        clips_requested=2,
    )

    mock_llm_response = [
        {
            "start_sec": 0.0,
            "end_sec": 60.0,
            "title": "Amazing discovery",
            "hook_text": "This will blow your mind",
            "caption_template": "Amazing discovery 🎯",
            "relevance_score": 9.0,
            "reason": "High engagement opener",
        },
        {
            "start_sec": 60.0,
            "end_sec": 120.0,
            "title": "Try this method",
            "hook_text": "The method that changes everything",
            "caption_template": "Try this method 🔥",
            "relevance_score": 8.5,
            "reason": "Actionable advice",
        },
    ]

    from ***REMOVED***.clipping.models import ClipCandidate

    with patch("***REMOVED***.clipping.services.get_llm_provider") as mock_provider:
        mock_llm = MagicMock()
        mock_provider.return_value = mock_llm
        mock_llm.complete.return_value = MagicMock(text=str(mock_llm_response), cost_usd=0)

        with patch.object(ClipAnalysisService, "_parse_llm_response", return_value=mock_llm_response):
            service = ClipAnalysisService(job)
            candidates = service.analyze()

    assert len(candidates) == 2
    assert ClipCandidate.objects.filter(clipping_job=job).count() == 2
    assert candidates[0].relevance_score == 9.0
    assert candidates[0].transcript_excerpt != ""


@pytest.mark.django_db
def test_clip_analysis_service_extracts_transcript_excerpt() -> None:
    job = ClippingJobFactory(transcript_json=SAMPLE_TRANSCRIPT_JSON)
    service = ClipAnalysisService(job)

    excerpt = service._extract_transcript_excerpt(start_sec=0.0, end_sec=2.0)
    assert "This" in excerpt
    assert "amazing" in excerpt
