from __future__ import annotations

import json
import logging
from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import Any

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.services.providers.registry import get_llm_provider

logger = logging.getLogger("***REMOVED***.clipping")
_SIX_PLACES = Decimal("0.000001")


class ClipAnalysisService:
    def __init__(self, clipping_job: ClippingJob) -> None:
        self.job = clipping_job

    def analyze(
        self,
        enriched_transcript: list[dict] | None = None,
        diarization: dict | None = None,
    ) -> list[ClipCandidate]:
        transcript = self.job.transcript_text
        prompt = self._build_prompt(transcript, enriched_transcript=enriched_transcript, diarization=diarization)
        llm = get_llm_provider()
        response = llm.complete(prompt=prompt, system=self._system_prompt())

        raw_clips = self._parse_llm_response(response.text)

        candidates: list[ClipCandidate] = []
        for clip_data in raw_clips[: self.job.clips_requested]:
            excerpt = self._extract_transcript_excerpt(
                start_sec=clip_data["start_sec"],
                end_sec=clip_data["end_sec"],
            )
            candidate = ClipCandidate(
                clipping_job=self.job,
                start_sec=clip_data["start_sec"],
                end_sec=clip_data["end_sec"],
                title=clip_data.get("title", ""),
                hook_text=clip_data.get("hook_text", ""),
                caption_template=clip_data.get("caption_template", ""),
                relevance_score=float(clip_data.get("relevance_score", 0)),
                reason=clip_data.get("reason", ""),
                transcript_excerpt=excerpt,
            )
            try:
                candidate.save()
                candidates.append(candidate)
            except Exception as exc:
                logger.warning(
                    "Skipping invalid clip candidate",
                    extra={
                        "clipping_job_id": str(self.job.id),
                        "start_sec": clip_data.get("start_sec"),
                        "end_sec": clip_data.get("end_sec"),
                        "error": str(exc),
                    },
                )

        # Update cost
        cost_usd = getattr(response, "cost_usd", 0)
        self.job.analysis_cost_usd = (
            Decimal(cost_usd).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP) if cost_usd else Decimal(0)
        )
        self.job.analysis_provider = llm.__class__.__name__
        self.job.save(update_fields=["analysis_cost_usd", "analysis_provider", "updated_at"])

        logger.info(
            "Clip analysis completed",
            extra={
                "clipping_job_id": str(self.job.id),
                "candidates_created": len(candidates),
                "clips_requested": self.job.clips_requested,
            },
        )
        return candidates

    def _extract_transcript_excerpt(self, start_sec: float, end_sec: float) -> str:
        segments = self.job.transcript_json.get("segments", [])
        words: list[str] = []
        for segment in segments:
            for word_data in segment.get("words", []):
                word_start = float(word_data.get("start", 0))
                word_end = float(word_data.get("end", 0))
                if word_start >= start_sec and word_end <= end_sec:
                    words.append(word_data.get("word", "").strip())
        return " ".join(words)

    def _build_prompt(
        self,
        transcript: str,
        enriched_transcript: list[dict] | None = None,
        diarization: dict | None = None,
    ) -> str:
        lines = [
            f"Source video transcript:\n{transcript}\n",
            f"Number of clips to identify: {self.job.clips_requested}",
        ]
        if diarization and diarization.get("segments"):
            speaker_count = len({s["speaker_id"] for s in diarization["segments"]})
            lines.append(f"\nThis video has {speaker_count} speaker(s).")
        lines.append(
            "\nReturn a JSON array of clip objects with keys: "
            "start_sec, end_sec, title, hook_text, caption_template, relevance_score (1-10), reason."
        )
        return "\n".join(lines)

    def _system_prompt(self) -> str:
        platform = self.job.social_account.platform
        account_name = self.job.social_account.handle or self.job.social_account.display_name
        return (
            f"You are an expert video editor specialising in short-form content for {platform}. "
            f"You are working on clips for the account @{account_name}. "
            "Identify the most engaging segments that will perform well on this platform. "
            "Return valid JSON only."
        )

    def _parse_llm_response(self, response_text: str) -> list[dict[str, Any]]:
        text = response_text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            text = text.removeprefix("json")
        return json.loads(text)
