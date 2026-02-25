from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict


class TrendDataRaw(BaseModel):
    """Raw data collected from Google Trends and YouTube search APIs."""

    model_config = ConfigDict(extra="allow")

    google_trends: list[dict[str, Any]] = []
    youtube_results: list[dict[str, Any]] = []
    community_data: list[dict[str, Any]] = []
    collected_at: str = ""


class CompetitorDataRaw(BaseModel):
    """Raw competitor channel analysis data from YouTube Data API."""

    model_config = ConfigDict(extra="allow")

    channels: dict[str, Any] = {}  # keyed by channel_id
    analyzed_at: str = ""


class GapAnalysisRaw(BaseModel):
    """Raw gap detection and opportunity scoring output from agent."""

    model_config = ConfigDict(extra="allow")

    opportunities: list[dict[str, Any]] = []
    coverage_gaps: list[str] = []
    analyzed_at: str = ""
