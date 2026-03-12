from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ***REMOVED***.services.base import BaseImageProvider
from ***REMOVED***.services.dataclass import ImageResponse
from ***REMOVED***.services.fal.client import FalAiClient

logger = logging.getLogger("***REMOVED***.providers.image.fal_ai")

_NEGATIVE_PROMPT = (
    "ugly, blurry, low quality, distorted faces, extra limbs, watermark, "
    "text overlay, logo, signature, out of frame, bad anatomy, duplicate, "
    "error, jpeg artifacts, worst quality, low resolution"
)


def _download_bytes(url: str) -> bytes:
    """Download image bytes from a URL."""
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


class FalAiImageProvider(BaseImageProvider):
    """Fal.ai Flux Pro 1.1 image generation provider.

    Uses fal-client for API communication. Set FAL_KEY env variable
    before using, or pass api_key to the constructor.
    """

    name = "fal_ai"
    MODEL = "fal-ai/flux-pro/v1.1"
    COST_PER_IMAGE = 0.05  # Flux Pro ~$0.05/image

    def __init__(self, client: FalAiClient) -> None:
        self._client = client

    def generate(self, prompt: str, width: int, height: int, **kwargs: Any) -> list[ImageResponse]:
        """Generate images using Flux Pro.

        Args:
            prompt: Generation prompt.
            width: Desired width (used to select image_size preset).
            height: Desired height (used to select image_size preset).
            **kwargs: num_images (default 1).

        Returns:
            List of ImageResponse objects.
        """
        num_images = int(kwargs.get("num_images", 1))

        # Map dimensions to fal.ai image_size presets
        if height >= 1080:
            image_size = "landscape_16_9"  # 1920×1080
            out_w, out_h = 1920, 1080
        else:
            image_size = "landscape_4_3"  # 1280×960
            out_w, out_h = 1280, 720

        result: dict[str, Any] = asyncio.run(
            self._client.run_async(
                self.MODEL,
                arguments={
                    "prompt": prompt,
                    "negative_prompt": _NEGATIVE_PROMPT,
                    "image_size": image_size,
                    "num_inference_steps": 28,
                    "guidance_scale": 3.5,
                    "num_images": num_images,
                    "safety_tolerance": "2",
                    "output_format": "jpeg",
                    "enable_safety_checker": True,
                },
            )
        )

        responses: list[ImageResponse] = []
        for img in result.get("images", []):
            image_bytes = _download_bytes(img["url"])
            responses.append(
                ImageResponse(
                    image_bytes=image_bytes,
                    width=out_w,
                    height=out_h,
                    provider=self.name,
                    cost_usd=self.COST_PER_IMAGE,
                )
            )

        logger.info(
            "Fal.ai image generation complete",
            extra={"model": self.MODEL, "num_images": len(responses), "prompt_length": len(prompt)},
        )
        return responses

    async def generate_batch_async(
        self, scene_prompts: list[dict[str, Any]]
    ) -> list[ImageResponse | BaseException]:
        """Generate all images in parallel using asyncio.gather."""

        async def _generate_one(sp: dict[str, Any]) -> ImageResponse:
            prompt = sp["prompt"]
            height = sp.get("height", 1080)
            if height >= 1080:
                image_size = "landscape_16_9"
                out_w, out_h = 1920, 1080
            else:
                image_size = "landscape_4_3"
                out_w, out_h = 1280, 720

            result: dict[str, Any] = await self._client.run_async(
                self.MODEL,
                arguments={
                    "prompt": prompt,
                    "negative_prompt": _NEGATIVE_PROMPT,
                    "image_size": image_size,
                    "num_inference_steps": 28,
                    "guidance_scale": 3.5,
                    "num_images": 1,
                    "safety_tolerance": "2",
                    "output_format": "jpeg",
                    "enable_safety_checker": True,
                },
            )
            images = result.get("images", [])
            if not images:
                raise ValueError("No images returned from fal.ai")
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(images[0]["url"])
                resp.raise_for_status()
                image_bytes = resp.content
            return ImageResponse(
                image_bytes=image_bytes,
                width=out_w,
                height=out_h,
                provider=self.name,
                cost_usd=self.COST_PER_IMAGE,
            )

        tasks = [_generate_one(sp) for sp in scene_prompts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        succeeded = sum(1 for r in results if not isinstance(r, BaseException))
        logger.info(
            "Fal.ai batch image generation complete",
            extra={"model": self.MODEL, "total": len(results), "succeeded": succeeded},
        )
        return list(results)
