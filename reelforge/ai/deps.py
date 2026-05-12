from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reelforge.ai.providers.community import SerpApiCommunityProvider
    from reelforge.ai.providers.trends import SerpApiTrendsProvider
    from reelforge.ai.providers.web_search import TavilyProvider
    from reelforge.ai.providers.youtube import SerpApiYouTubeProvider
    from reelforge.channels.models import Channel
    from reelforge.research.models import TopicIdea


@dataclass
class ResearchDeps:
    video_search: SerpApiYouTubeProvider
    web_search: TavilyProvider
    trends: SerpApiTrendsProvider
    community: SerpApiCommunityProvider
    channel: Channel


@dataclass
class ScriptDeps:
    web_search: TavilyProvider
    channel: Channel
    topic: TopicIdea


@dataclass
class VisualPlannerDeps:
    sections: list[dict]
    broll_suggestions: list[dict]
    total_duration_seconds: float
    channel_tone: str
    narrative_mode: str
