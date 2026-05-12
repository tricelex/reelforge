from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ***REMOVED***.ai.providers.community import SerpApiCommunityProvider
    from ***REMOVED***.ai.providers.trends import SerpApiTrendsProvider
    from ***REMOVED***.ai.providers.web_search import TavilyProvider
    from ***REMOVED***.ai.providers.youtube import SerpApiYouTubeProvider
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.research.models import TopicIdea


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
