"""ClipAnalysisService — LLM-powered clip candidate identification."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import pydantic
from pydantic_ai import Agent

from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL

if TYPE_CHECKING:
    from server.apps.clips.models import ClipCandidate

logger = logging.getLogger('***REMOVED***.clips.analysis')

_WORDS_JSON_CAP = 2000
_SCENE_CUTS_CAP = 50


class ClipSegment(pydantic.BaseModel):
    """One clip candidate returned by the LLM."""

    start_sec: float
    end_sec: float
    title: str
    hook_text: str
    caption_template: str = ''
    relevance_score: float
    reason: str


class ClipsOutput(pydantic.BaseModel):
    """Structured output from the clip analysis agent."""

    clips: list[ClipSegment]


clip_analysis_agent: Agent[None, ClipsOutput] = Agent(
    PYDANTIC_AI_MODEL,
    output_type=ClipsOutput,
    system_prompt=(
        'You are an expert short-form video editor. '
        'Identify the most engaging segments from the transcript that '
        'will make great clips. Each clip should be 30-180 seconds long. '
        'Return a valid JSON object with a "clips" array.'
    ),
)


class ClipAnalysisService:
    """Identifies clip candidates from transcript using GPT 5.6 Terra (PydanticAI)."""

    def __init__(self, run: Any, clips_requested: int = 5) -> None:
        """Initialise with the pipeline run and requested clip count."""
        self.run = run
        self.clips_requested = clips_requested

    def analyze(
        self,
        transcript_text: str,
        enriched_transcript: list[dict[str, Any]] | None = None,
        diarization: dict[str, Any] | None = None,
        scene_cuts: list[float] | None = None,
        video_duration: float | None = None,
    ) -> list[ClipCandidate]:
        """Run LLM analysis and persist ClipCandidate records.

        Returns the list of created ClipCandidate model instances.
        """
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        prompt = self._build_prompt(
            transcript_text,
            enriched_transcript,
            diarization,
            scene_cuts,
            video_duration,
        )
        result = clip_analysis_agent.run_sync(prompt)
        raw_clips = result.output.clips

        candidates: list[ClipCandidate] = []
        for clip_data in raw_clips[: self.clips_requested]:
            excerpt = self._extract_excerpt(
                enriched_transcript or [],
                clip_data.start_sec,
                clip_data.end_sec,
            )
            try:
                candidate = ClipCandidate.objects.create(
                    run=self.run,
                    start_sec=clip_data.start_sec,
                    end_sec=clip_data.end_sec,
                    title=clip_data.title,
                    hook_text=clip_data.hook_text,
                    caption_template=clip_data.caption_template,
                    relevance_score=clip_data.relevance_score,
                    reason=clip_data.reason,
                    transcript_excerpt=excerpt,
                )
                candidates.append(candidate)
            except Exception:
                logger.warning(
                    'Skipping invalid clip candidate',
                    extra={
                        'run_id': str(self.run.id),
                        'start_sec': clip_data.start_sec,
                        'end_sec': clip_data.end_sec,
                    },
                    exc_info=True,
                )
        return candidates

    def _build_prompt(
        self,
        transcript_text: str,
        enriched_transcript: list[dict[str, Any]] | None,
        diarization: dict[str, Any] | None,
        scene_cuts: list[float] | None,
        video_duration: float | None,
    ) -> str:
        lines = [
            f'Source video transcript:\n{transcript_text}\n',
            f'Number of clips to identify: {self.clips_requested}',
        ]
        if diarization and diarization.get('segments'):
            speaker_count = len(
                {s.get('speaker_id') for s in diarization['segments']},
            )
            lines.append(f'\nThis video has {speaker_count} speaker(s).')
        if video_duration is not None:
            lines.append(f'\nVIDEO_DURATION_SECONDS: {video_duration:.3f}')
        if enriched_transcript:
            compact = [
                {
                    'w': e['word'],
                    's': round(e['start'], 3),
                    'e': round(e['end'], 3),
                    'spk': e.get('speaker_id', '?'),
                }
                for e in enriched_transcript[:_WORDS_JSON_CAP]
            ]
            lines.append(
                f'\nWORDS_JSON:\n{json.dumps(compact, separators=(",", ":"))}',
            )
        if scene_cuts:
            cuts_json = json.dumps(
                [round(t, 3) for t in scene_cuts[:_SCENE_CUTS_CAP]],
            )
            lines.append(f'\nSCENE_CUTS (seconds):\n{cuts_json}')
        return '\n'.join(lines)

    def _extract_excerpt(
        self,
        enriched_transcript: list[dict[str, Any]],
        start_sec: float,
        end_sec: float,
    ) -> str:
        words = [
            e['word']
            for e in enriched_transcript
            if start_sec <= float(e.get('start', 0))
            and float(e.get('end', 0)) <= end_sec
        ]
        return ' '.join(w.strip() for w in words)
