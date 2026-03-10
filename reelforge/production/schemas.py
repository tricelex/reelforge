from __future__ import annotations

from pydantic import BaseModel
from pydantic import RootModel


class SceneItem(BaseModel):
    """Single scene in a scene breakdown."""

    scene_id: int
    narration: str
    duration_estimate: float
    visual_keywords: list[str] = []
    mood: str = ""
    caption_text: str = ""
    section_tag: str = ""  # HOOK | INTRO_BRIDGE | SECTION_1 | etc.
    animation_type: str = "body_concept"  # hook | intro | body_stat | body_concept | outro
    image_prompt: str = ""  # Flux Pro prompt built from broll suggestion
    image_style_preset: str = "cinematic_realism"  # style preset key
    broll_indices: list[int] = []  # indices into script_job.broll_suggestions


class SceneList(RootModel[list[SceneItem]]):
    """Validated list of scenes for a SceneBreakdownJob."""

    root: list[SceneItem] = []


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
