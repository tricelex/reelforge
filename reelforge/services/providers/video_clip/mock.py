from __future__ import annotations

import logging
from typing import Any

from ***REMOVED***.services.base import BaseVideoClipProvider
from ***REMOVED***.services.dataclass import VideoClipResponse

logger = logging.getLogger("***REMOVED***.providers.video_clip.mock")

# Minimal valid MP4 (ftyp + mdat boxes, ~100 bytes)
_STUB_MP4 = (
    b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    b"\x00\x00\x00\x08free"
    b"\x00\x00\x00\x08mdat"
)


class MockVideoClipProvider(BaseVideoClipProvider):
    """Mock video clip provider — returns a stub MP4 payload.
    TODO: Replace with real implementations (RunwayML, Kling, Pika).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        logger.warning("MockVideoClipProvider initialized for: %s", name)

    def generate_clip(
        self,
        image_path: str,
        prompt: str,
        duration_sec: float = 5.0,
        **kwargs: Any,
    ) -> VideoClipResponse:
        """Generate a mock video clip from a still image.

        Args:
            image_path: Path to the source still image.
            prompt: Animation/motion prompt describing desired clip.
            duration_sec: Desired clip duration in seconds.
            **kwargs: Additional provider-specific parameters.

        Returns:
            VideoClipResponse with stub MP4 bytes.

        TODO: Replace with actual video clip generation API call.
        """
        logger.warning(
            "MockVideoClipProvider.generate_clip called — image=%s prompt_length=%d duration=%.1fs",
            image_path,
            len(prompt),
            duration_sec,
        )
        return VideoClipResponse(
            clip_bytes=_STUB_MP4,
            duration_sec=duration_sec,
            width=1920,
            height=1080,
            provider=self.name,
            cost_usd=0.0,
            raw=None,
        )

    async def generate_clips_async(
        self, clip_requests: list[dict[str, Any]]
    ) -> list[VideoClipResponse | BaseException]:
        return [
            self.generate_clip(
                image_path=req["image_path"],
                prompt=req["prompt"],
                duration_sec=req.get("duration_sec", 5.0),
            )
            for req in clip_requests
        ]
