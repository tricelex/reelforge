from __future__ import annotations

from typing import TYPE_CHECKING

from agents import Agent
from agents import Tool

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel


def build_research_agent(channel: Channel) -> Agent:
    """ResearchAgent: Discovers trending topics, analyzes competitors,
    identifies content gaps for a specific channel's niche.
    """

    @Tool(
        name="search_youtube_trends",
        description="Search YouTube for trending videos in a niche. Returns titles, views, dates, durations.",
    )
    def search_youtube_trends(niche: str, days_back: int = 7, limit: int = 20) -> dict:
        from ***REMOVED***.services.youtube.scraper import YouTubeTrendScraper

        scraper = YouTubeTrendScraper()
        return scraper.get_trending(niche=niche, days_back=days_back, limit=limit)

    @Tool(name="check_google_trends", description="Get search volume trend data for a keyword from Google Trends.")
    def check_google_trends(keyword: str, timeframe: str = "today 30-d") -> dict:
        from ***REMOVED***.services.external.google_trends import GoogleTrendsClient

        return GoogleTrendsClient().get_interest(keyword=keyword, timeframe=timeframe)

    @Tool(
        name="scrape_reddit_questions", description="Get top questions and posts from relevant subreddits for a niche."
    )
    def scrape_reddit_questions(niche: str, subreddits: list[str] | None = None, limit: int = 20) -> list[dict]:
        from ***REMOVED***.services.external.reddit_client import RedditClient

        return RedditClient().get_top_posts(niche=niche, subreddits=subreddits, limit=limit)

    @Tool(
        name="analyze_competitor_channels",
        description="Analyze competitor YouTube channels for content patterns and gaps.",
    )
    def analyze_competitor_channels(channel_ids: list[str]) -> dict:
        from ***REMOVED***.services.youtube.competitor_analyzer import CompetitorAnalyzer

        analyzer = CompetitorAnalyzer()
        return analyzer.analyze(channel_ids=channel_ids)

    @Tool(name="check_exploding_topics", description="Find rising keyword trends before they peak.")
    def check_exploding_topics(category: str) -> list[dict]:
        from ***REMOVED***.services.external.exploding_topics import ExplodingTopicsClient

        return ExplodingTopicsClient().get_rising(category=category)

    @Tool(
        name="score_topic_opportunity",
        description="Score a topic idea on opportunity (search vol, competition, trend direction). Returns 0-100.",
    )
    def score_topic_opportunity(title_idea: str, keyword: str, search_vol: int, competition: str, trend: str) -> dict:
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
        return {
            "score": round(min(score, 100), 1),
            "breakdown": {
                "search_volume_score": min(search_vol // 2000, 30),
                "competition_score": comp_map.get(competition.upper(), 10),
                "trend_score": trend_map.get(trend.upper(), 10),
            },
        }

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

        OUTPUT FORMAT: Return valid JSON array of TopicIdea objects:
        [{{
            "title_idea": str,
            "hook_angle": str,
            "target_keyword": str,
            "estimated_search_vol": int,
            "competition_level": "LOW|MEDIUM|HIGH",
            "opportunity_score": float,
            "trend_direction": "RISING|STABLE|DECLINING",
            "thumbnail_concept": str,
            "why_it_works": str
        }}, ...]
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
