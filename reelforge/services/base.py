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
        self, prompt: str, system: str = "", temperature: float = 0.7, max_tokens: int = 4000, **kwargs
    ) -> LLMResponse: ...

    @abstractmethod
    def complete_json(self, prompt: str, system: str = "", **kwargs) -> dict: ...


class BaseTTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, **settings) -> TTSResponse: ...


class BaseImageProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str, width: int, height: int, **kwargs) -> list[ImageResponse]: ...


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
