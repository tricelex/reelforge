from __future__ import annotations

from pydantic import BaseModel


class ClipData(BaseModel):
    start_sec: float = 0.0
    end_sec: float = 0.0
    title: str = ""
    hook_text: str = ""
    caption_template: str = ""
    relevance_score: float = 0.0
    reason: str = ""


class ClipAnalysisOutput(BaseModel):
    clips: list[ClipData] = []
