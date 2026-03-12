from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from reelforge.services.base import BaseVideoClipProvider
from reelforge.services.dataclass import VideoClipResponse
from reelforge.services.fal.client import FalAiClient

logger = logging.getLogger("reelforge.providers.video_clip.fal_ai")

# Per-scene animation prompts keyed by animation_type
ANIMATION_PROMPTS: dict[str, str] = {
    "hook": (
        "Dramatic push-in camera move, slight camera shake at start, subject comes sharply "
        "into focus, high energy motion, cinematic lens flare, no scene cuts"
    ),
    "intro": (
        "Smooth horizontal pan from left to right, slow and steady, slight parallax on "
        "foreground elements, cinematic depth of field shift, ambient atmosphere"
    ),
    "body_stat": (
        "Slow cinematic dolly push-in toward subject, subtle camera breathing, foreground "
        "elements drift slightly, subject stays centred, moody atmospheric haze"
    ),
    "body_person": (
        "Gentle floating parallax, subject has micro-movements, background drifts softly "
        "opposite to foreground, slight vignette pulse"
    ),
    "body_concept": (
        "Slow 3D orbit around the subject, particle dust motes floating in light beams, "
        "subtle colour temperature shift warm to cool"
    ),
    "outro": (
        "Slow pull-out camera move, scene softly de-focuses, warm colour grade intensifies, "
        "gentle fade to slight overexposure at clip end"
    ),
}

_NEGATIVE_PROMPT = (
    "shaky cam, jump cuts, strobing, fast motion, morphing faces, distortion, "
    "unnatural movement, glitch, flickering"
)


def _download_bytes(url: str) -> bytes:
    """Download video bytes from a URL."""
    with httpx.Client(timeout=120) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


class FalAiVideoClipProvider(BaseVideoClipProvider):
    """Fal.ai Kling 1.6 Pro image-to-video provider.

    Uses fal-client for API communication. Set FAL_KEY env variable
    before using, or pass api_key to the constructor.
    """

    name = "fal_ai_kling"
    MODEL = "fal-ai/kling-video/v1.6/pro/image-to-video"
    COST_PER_5S = 0.20   # Kling Pro ~$0.20 per 5-second clip
    COST_PER_10S = 0.40  # ~$0.40 per 10-second clip

    def __init__(self, client: FalAiClient) -> None:
        self._client = client

    def _upload_image(self, image_path: str) -> str:
        """Upload a local image file to fal.ai CDN and return the CDN URL."""
        url: str = asyncio.run(self._client.upload_file_async(Path(image_path)))
        return url

    def generate_clip(
        self,
        image_path: str,
        prompt: str,
        duration_sec: float = 5.0,
        **kwargs: Any,
    ) -> VideoClipResponse:
        """Animate a still image into a video clip using Kling 1.6 Pro.

        Args:
            image_path: Local filesystem path OR pre-uploaded CDN URL.
            prompt: Animation/motion description prompt.
            duration_sec: Target duration. ≤7s → 5s clip, >7s → 10s clip.
            **kwargs: Additional provider-specific parameters.

        Returns:
            VideoClipResponse with MP4 bytes.
        """
        clip_duration = 5 if duration_sec <= 7 else 10

        # Kling requires a URL; upload local files first
        if Path(image_path).exists():
            image_url = self._upload_image(image_path)
            logger.debug("Uploaded image to fal.ai CDN: %s", image_url)
        else:
            image_url = image_path  # assume already a URL

        result: dict[str, Any] = asyncio.run(
            self._client.run_async(
                self.MODEL,
                arguments={
                    "image_url": image_url,
                    "prompt": prompt,
                    "negative_prompt": _NEGATIVE_PROMPT,
                    "duration": clip_duration,
                    "aspect_ratio": "16:9",
                    "cfg_scale": 0.5,
                },
            )
        )

        clip_bytes = _download_bytes(result["video"]["url"])
        cost = self.COST_PER_5S if clip_duration == 5 else self.COST_PER_10S

        logger.info(
            "Fal.ai video clip generated",
            extra={
                "model": self.MODEL,
                "duration_sec": clip_duration,
                "prompt_length": len(prompt),
                "cost_usd": cost,
            },
        )

        return VideoClipResponse(
            clip_bytes=clip_bytes,
            duration_sec=float(clip_duration),
            width=1920,
            height=1080,
            provider=self.name,
            cost_usd=cost,
            raw=result,
        )

    async def generate_clips_async(
        self, clip_requests: list[dict[str, Any]]
    ) -> list[VideoClipResponse | BaseException]:
        """Generate all video clips in parallel using asyncio.gather.

        Uploads all images to fal CDN in parallel first, then generates all clips in parallel.
        """
        # Upload all images in parallel
        async def _upload(image_path: str) -> str:
            if Path(image_path).exists():
                return await self._client.upload_file_async(Path(image_path))
            return image_path  # already a URL

        upload_tasks = [_upload(req["image_path"]) for req in clip_requests]
        image_urls_or_exc: list[str | BaseException] = list(
            await asyncio.gather(*upload_tasks, return_exceptions=True)
        )

        async def _generate_one(
            req: dict[str, Any], image_url: str | BaseException
        ) -> VideoClipResponse:
            if isinstance(image_url, BaseException):
                raise image_url
            duration_sec = req.get("duration_sec", 5.0)
            clip_duration = 5 if duration_sec <= 7 else 10
            result: dict[str, Any] = await self._client.run_async(
                self.MODEL,
                arguments={
                    "image_url": image_url,
                    "prompt": req["prompt"],
                    "negative_prompt": _NEGATIVE_PROMPT,
                    "duration": clip_duration,
                    "aspect_ratio": "16:9",
                    "cfg_scale": 0.5,
                },
            )
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.get(result["video"]["url"])
                resp.raise_for_status()
                clip_bytes = resp.content
            cost = self.COST_PER_5S if clip_duration == 5 else self.COST_PER_10S
            return VideoClipResponse(
                clip_bytes=clip_bytes,
                duration_sec=float(clip_duration),
                width=1920,
                height=1080,
                provider=self.name,
                cost_usd=cost,
                raw=result,
            )

        clip_tasks = [_generate_one(req, url) for req, url in zip(clip_requests, image_urls_or_exc)]
        results = await asyncio.gather(*clip_tasks, return_exceptions=True)
        succeeded = sum(1 for r in results if not isinstance(r, BaseException))
        logger.info(
            "Fal.ai batch video clip generation complete",
            extra={"model": self.MODEL, "total": len(results), "succeeded": succeeded},
        )
        return list(results)
