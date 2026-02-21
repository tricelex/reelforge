from __future__ import annotations

from pydantic import BaseModel
from pydantic import RootModel


class TrafficSourceData(RootModel[dict[str, float]]):
    """YouTube Analytics traffic source breakdown: source_name → percentage."""

    root: dict[str, float] = {}


class AIInsights(BaseModel):
    """AI-generated performance analysis for the research feedback loop."""

    what_worked: list[str] = []
    what_to_improve: list[str] = []
    title_assessment: str = ""
    recommendations: list[str] = []
