from dataclasses import dataclass
from typing import Any


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
