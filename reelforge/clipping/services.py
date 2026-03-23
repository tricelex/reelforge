from __future__ import annotations

import json
import logging
from typing import Any

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.services.providers.registry import get_llm_provider

logger = logging.getLogger("***REMOVED***.clipping")


class ClipAnalysisService:
    def __init__(self, clipping_job: ClippingJob) -> None:
        self.job = clipping_job

    def analyze(self) -> list[ClipCandidate]:
        transcript = self.job.transcript_text
        prompt = self._build_prompt(transcript)
        llm = get_llm_provider(self.job.channel)
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
        self.job.analysis_cost_usd = getattr(response, "cost_usd", 0) or 0
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

    def _build_prompt(self, transcript: str) -> str:
        channel = self.job.channel
        niche = getattr(channel, "niche_category", None) or getattr(channel, "custom_niche", None) or "general"
        return (
            f"Analyze this video transcript from a {niche} YouTube channel. "
            f"Identify the {self.job.clips_requested} most engaging moments for short-form clips.\n\n"
            f"TRANSCRIPT:\n{transcript}\n\n"
            f"Return a JSON array with {self.job.clips_requested} clip objects. "
            f"Each object must have: start_sec (float), end_sec (float), title (str, max 100 chars), "
            f"hook_text (str, max 100 chars — the opening statement), "
            f"caption_template (str — social media caption with hashtags), "
            f"relevance_score (float 0-10), reason (str).\n"
            f"Clips must be 30–180 seconds. No overlapping clips. "
            f"Order by relevance_score descending."
        )

    def _system_prompt(self) -> str:
        return (
            "You are an expert short-form content strategist. You identify the highest-value moments "
            "in long-form videos that work as standalone clips without needing context. "
            "Focus on: surprising facts, emotional peaks, actionable insights, and strong hooks. "
            "Always respond with valid JSON array only, no markdown fences."
        )

    def _parse_llm_response(self, response_text: str) -> list[dict[str, Any]]:
        text = response_text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
