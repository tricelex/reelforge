from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from agents import Agent
from agents import function_tool

if TYPE_CHECKING:
    from reelforge.agents.providers.protocols import RedditProvider
    from reelforge.agents.providers.protocols import TrendsProvider
    from reelforge.agents.providers.protocols import VideoSearchProvider
    from reelforge.channels.models import Channel


def build_research_agent(
    channel: Channel,
    video_search: VideoSearchProvider,
    trends: TrendsProvider,
    reddit: RedditProvider,
) -> Agent:
    """Build the ResearchAgent with injected providers.

    Discovers trending topics, analyzes competitors, and identifies
    content gaps for a specific channel's niche.
    """

    @function_tool
    def search_youtube_trends(niche: str, days_back: int = 7, limit: int = 20) -> str:
        """Search YouTube for trending videos in a niche. Returns titles, views, dates, durations."""
        results = video_search.search_trending(niche=niche, days_back=days_back, limit=limit)
        return json.dumps([asdict(r) for r in results], default=str)

    @function_tool
    def check_google_trends(keyword: str, timeframe: str = "today 30-d") -> str:
        """Get search volume trend data for a keyword from Google Trends."""
        data = trends.get_interest(keyword=keyword, timeframe=timeframe)
        return json.dumps(asdict(data), default=str)

    @function_tool
    def scrape_reddit_questions(
        niche: str,
        subreddits: list[str] | None = None,
        limit: int = 20,
    ) -> str:
        """Get top questions and posts from relevant subreddits for a niche."""
        posts = reddit.get_top_posts(niche=niche, subreddits=subreddits, limit=limit)
        return json.dumps([asdict(p) for p in posts], default=str)

    @function_tool
    def analyze_competitor_channels(channel_ids: list[str]) -> str:
        """Analyze competitor YouTube channels for content patterns and gaps."""
        result = video_search.analyze_competitors(channel_ids=channel_ids)
        return json.dumps(result, default=str)

    @function_tool
    def check_exploding_topics(category: str) -> str:
        """Find rising keyword trends before they peak using ExplodingTopics data."""
        rising = trends.get_rising_topics(category=category)
        return json.dumps([asdict(t) for t in rising], default=str)

    @function_tool
    def score_topic_opportunity(
        title_idea: str,
        keyword: str,
        search_vol: int,
        competition: str,
        trend: str,
    ) -> str:
        """Score a topic idea on opportunity (search vol, competition, trend direction). Returns 0-100."""
        score = 0.0
        if search_vol > 50000:
            score += 30
        elif search_vol > 20000:
            score += 20
        elif search_vol > 5000:
            score += 10
        comp_map = {"LOW": 35, "MEDIUM": 20, "HIGH": 5}
        score += comp_map.get(competition.upper(), 10)
        trend_map = {"RISING": 25, "STABLE": 10, "DECLINING": 0}
        score += trend_map.get(trend.upper(), 10)
        result = {
            "title_idea": title_idea,
            "keyword": keyword,
            "score": round(min(score, 100), 1),
            "breakdown": {
                "search_volume_score": min(search_vol // 2000, 30),
                "competition_score": comp_map.get(competition.upper(), 10),
                "trend_score": trend_map.get(trend.upper(), 10),
            },
        }
        return json.dumps(result)

    return Agent(
        name="ResearchAgent",
        model="gpt-4o",
        instructions=f"""
        You are an expert YouTube content research strategist for a faceless channel in: {channel.target_niches}.
        Target audience: {channel.target_audience_description}
        Channel tone: {channel.content_tone}

        Your job: Discover high-opportunity video topics using the available tools.

        PROCESS:
        1. Search YouTube trends for each niche (last 7 days)
        2. Check Google Trends for top keywords
        3. Scrape Reddit for audience questions and pain points
        4. Analyze competitor channels for content gaps
        5. Check Exploding Topics for emerging angles
        6. Score each opportunity
        7. Return exactly 8-12 topic ideas ranked by opportunity score

        CRITERIA for good topics:
        - Search volume > 10,000/month
        - Competition LOW or MEDIUM only
        - Suitable for FACELESS AI video (no talking head required)
        - 8-14 minute content potential
        - Strong thumbnail concept exists

        OUTPUT FORMAT: Return a JSON object with this exact structure:
        {{
            "topics": [{{
                "title_idea": str,
                "hook_angle": str,
                "target_keyword": str,
                "estimated_search_vol": int,
                "competition_level": "LOW|MEDIUM|HIGH",
                "opportunity_score": float,
                "trend_direction": "RISING|STABLE|DECLINING",
                "thumbnail_concept": str,
                "why_it_works": str
            }}],
            "research_summary": str
        }}
        """,
        tools=[
            search_youtube_trends,
            check_google_trends,
            scrape_reddit_questions,
            analyze_competitor_channels,
            check_exploding_topics,
            score_topic_opportunity,
        ],
    )
