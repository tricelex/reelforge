from __future__ import annotations

import logging

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob

logger = logging.getLogger("reelforge.clipping")


class ClipAnalysisService:
    def __init__(self, clipping_job: ClippingJob) -> None:
        self.job = clipping_job

    def analyze(
        self,
        enriched_transcript: list[dict] | None = None,
        diarization: dict | None = None,
    ) -> list[ClipCandidate]:
        from django.conf import settings

        from reelforge.ai.agents.clip_analysis import clip_analysis_agent

        transcript = self.job.transcript_text
        user_prompt = self._build_prompt(
            transcript,
            enriched_transcript=enriched_transcript,
            diarization=diarization,
            platform_context=self._system_prompt(),
        )

        result = clip_analysis_agent.run_sync(
            user_prompt,
            model=settings.CLIP_ANALYSIS_MODEL,
        )
        raw_clips = result.output.clips

        candidates: list[ClipCandidate] = []
        for clip_data in raw_clips[: self.job.clips_requested]:
            excerpt = self._extract_transcript_excerpt(
                start_sec=clip_data.start_sec,
                end_sec=clip_data.end_sec,
            )
            candidate = ClipCandidate(
                clipping_job=self.job,
                start_sec=clip_data.start_sec,
                end_sec=clip_data.end_sec,
                title=clip_data.title,
                hook_text=clip_data.hook_text,
                caption_template=clip_data.caption_template,
                relevance_score=clip_data.relevance_score,
                reason=clip_data.reason,
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
                        "start_sec": clip_data.start_sec,
                        "end_sec": clip_data.end_sec,
                        "error": str(exc),
                    },
                )

        self.job.analysis_provider = settings.CLIP_ANALYSIS_MODEL
        self.job.save(update_fields=["analysis_provider", "updated_at"])

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
        platform_context: str = "",
    ) -> str:
        lines = []
        if platform_context:
            lines.append(platform_context)
        lines.extend([
            f"Source video transcript:\n{transcript}\n",
            f"Number of clips to identify: {self.job.clips_requested}",
        ])
        if diarization and diarization.get("segments"):
            speaker_count = len({s["speaker_id"] for s in diarization["segments"]})
            lines.append(f"\nThis video has {speaker_count} speaker(s).")
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

