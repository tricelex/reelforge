from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import Any

from reelforge.services.dataclass import ImageResponse
from reelforge.services.dataclass import LLMResponse
from reelforge.services.dataclass import TTSResponse
from reelforge.services.dataclass import VideoClipResponse


class BaseLLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(
        self, prompt: str, system: str = "", temperature: float = 0.7, max_tokens: int = 4000, **kwargs: Any
    ) -> LLMResponse: ...

    @abstractmethod
    def complete_json(self, prompt: str, system: str = "", **kwargs: Any) -> dict: ...


class BaseTTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, **settings: Any) -> TTSResponse: ...


class BaseImageProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str, width: int, height: int, **kwargs: Any) -> list[ImageResponse]: ...

    async def generate_batch_async(
        self, scene_prompts: list[dict[str, Any]]
    ) -> list[ImageResponse | BaseException]:
        """Generate images for multiple scenes. Default: sequential fallback."""
        results: list[ImageResponse | BaseException] = []
        for sp in scene_prompts:
            try:
                responses = self.generate(
                    prompt=sp["prompt"],
                    width=sp.get("width", 1920),
                    height=sp.get("height", 1080),
                )
                results.append(responses[0])
            except Exception as exc:
                results.append(exc)
        return results


class BaseVideoClipProvider(ABC):
    name: str

    @abstractmethod
    def generate_clip(
        self,
        image_path: str,
        prompt: str,
        duration_sec: float = 5.0,
        **kwargs: Any,
    ) -> VideoClipResponse: ...

    async def generate_clips_async(
        self, clip_requests: list[dict[str, Any]]
    ) -> list[VideoClipResponse | BaseException]:
        """Generate video clips for multiple images. Default: sequential fallback."""
        results: list[VideoClipResponse | BaseException] = []
        for req in clip_requests:
            try:
                results.append(
                    self.generate_clip(
                        image_path=req["image_path"],
                        prompt=req["prompt"],
                        duration_sec=req.get("duration_sec", 5.0),
                    )
                )
            except Exception as exc:
                results.append(exc)
        return results
