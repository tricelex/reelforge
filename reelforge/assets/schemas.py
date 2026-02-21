from __future__ import annotations

from pydantic import BaseModel
from pydantic import RootModel


class VisualTimelineEntry(BaseModel):
    """A single entry in the visual timeline mapping time windows to images."""

    start_ms: int = 0
    end_ms: int = 0
    image_file_id: str = ""  # UUID or path of GeneratedImage
    segment_text: str = ""
    section: str = ""
    animation_type: str = "ken_burns_right"  # "ken_burns_right|left|zoom_in|static"


class VisualTimeline(RootModel[list[VisualTimelineEntry]]):
    """Composited timeline driving VideoRenderer — maps time windows to images."""

    root: list[VisualTimelineEntry] = []
