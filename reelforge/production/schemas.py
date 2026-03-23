from __future__ import annotations

from pydantic import BaseModel
from pydantic import RootModel

from reelforge.agents.schemas import VisualSegment


class SceneList(RootModel[list[VisualSegment]]):
    """Validated list of VisualSegment scenes for a SceneBreakdownJob."""

    root: list[VisualSegment] = []


class RenderSpec(BaseModel):
    """Full render configuration consumed by VideoRenderer."""

    resolution: str = "1920x1080"
    fps: int = 30
    codec: str = "libx264"
    crf: int = 18
    preset: str = "slow"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    movflags: str = "+faststart"
    ken_burns_max_zoom_delta: float = 0.03
    subtitle_font: str = "Montserrat-Bold"
    subtitle_size: int = 52
    subtitle_color: str = "#FFFFFF"
    subtitle_stroke_color: str = "#000000"
    subtitle_stroke_width: int = 3


class QAResults(RootModel[dict[str, bool]]):
    """QA check results: check_name → pass/fail. e.g. {"audio_sync": True, ...}"""

    root: dict[str, bool] = {}
