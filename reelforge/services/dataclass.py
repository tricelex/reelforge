from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    raw: Any = None


@dataclass
class TTSResponse:
    audio_bytes: bytes
    duration_sec: float
    provider: str
    cost_usd: float


@dataclass
class ImageResponse:
    image_bytes: bytes
    width: int
    height: int
    provider: str
    cost_usd: float


@dataclass
class VideoClipResponse:
    clip_bytes: bytes
    duration_sec: float
    width: int
    height: int
    provider: str
    cost_usd: float
    raw: Any = None
