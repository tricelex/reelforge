from __future__ import annotations

import logging

from ***REMOVED***.services.base import BaseImageProvider
from ***REMOVED***.services.dataclass import ImageResponse

logger = logging.getLogger("***REMOVED***.providers.image.mock")


class MockImageProvider(BaseImageProvider):
    """Mock image generation provider for placeholder functionality.
    TODO: Replace with real implementations (Fal.ai, Replicate, DALL-E).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        logger.warning(f"MockImageProvider initialized for: {name}")

    def generate(self, prompt: str, width: int, height: int, **kwargs) -> list[ImageResponse]:
        """Generate mock images.

        Args:
            prompt: Image generation prompt
            width: Image width in pixels
            height: Image height in pixels
            **kwargs: Additional parameters (num_images, etc.)

        Returns:
            List of ImageResponse objects with mock image data

        TODO: Replace with actual image generation API call
        """
        num_images = kwargs.get("num_images", 1)
        logger.warning(
            f"MockImageProvider.generate called - prompt_length={len(prompt)}, "
            f"size={width}x{height}, num_images={num_images}"
        )

        # Mock image bytes (1x1 PNG)
        mock_image = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        results = []
        for _ in range(num_images):
            results.append(
                ImageResponse(
                    image_bytes=mock_image,
                    width=width,
                    height=height,
                    provider=self.name,
                    cost_usd=0.0,  # Mock cost
                )
            )

        return results
