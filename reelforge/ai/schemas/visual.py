from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

_DURATION_GAP_TOLERANCE = 0.1
_COVERAGE_TOLERANCE = 0.5


class VisualSegment(BaseModel):
    scene_id: int = Field(..., description="Sequential 1-based integer")
    section_tag: str = Field(..., description="The script [SECTION_TAG] this segment belongs to")
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    duration: float = Field(..., gt=0, le=10)
    narration_excerpt: str
    image_prompt: str = Field(..., description="Minimum 40 words")
    style_preset: Literal["cinematic_realism", "flat_illustration", "dark_tech", "corporate_clean"]
    colour_palette: list[str] = Field(default_factory=list)
    animation_type: Literal[
        "hook", "intro", "body_concept", "body_stat", "body_story",
        "transition", "takeaway", "outro"
    ]
    video_prompt: str
    mood: Literal["calm", "tense", "inspiring", "curious", "urgent", "warm"]
    visual_keywords: list[str] = Field(default_factory=list)
    is_transition: bool = False

    @model_validator(mode="after")
    def check_duration_matches(self) -> VisualSegment:
        computed = round(self.end_seconds - self.start_seconds, 3)
        if abs(computed - self.duration) > _DURATION_GAP_TOLERANCE:
            msg = f"duration {self.duration} does not match end_seconds - start_seconds = {computed}"
            raise ValueError(msg)
        return self


class VisualPlannerOutput(BaseModel):
    segments: list[VisualSegment] = Field(..., min_length=10)
    total_duration_seconds: float
    segment_count: int
    coverage_confirmed: bool
    revision_notes: str = ""

    @model_validator(mode="after")
    def check_coverage(self) -> VisualPlannerOutput:
        if self.segment_count != len(self.segments):
            msg = f"segment_count={self.segment_count} does not match len(segments)={len(self.segments)}"
            raise ValueError(msg)
        segs = sorted(self.segments, key=lambda s: s.start_seconds)
        for i in range(1, len(segs)):
            gap = segs[i].start_seconds - segs[i - 1].end_seconds
            if abs(gap) > _DURATION_GAP_TOLERANCE:
                msg = f"Gap of {gap:.2f}s between segment {i} and {i+1}"
                raise ValueError(msg)
        if abs(segs[-1].end_seconds - self.total_duration_seconds) > _COVERAGE_TOLERANCE:
            msg = (
                f"Timeline ends at {segs[-1].end_seconds:.2f}s "
                f"but total_duration is {self.total_duration_seconds:.2f}s"
            )
            raise ValueError(msg)
        return self
