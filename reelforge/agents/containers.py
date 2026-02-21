from __future__ import annotations

from dependency_injector import containers
from dependency_injector import providers

from reelforge.agents.providers.reddit import RedditProvider
from reelforge.agents.providers.trends import GoogleTrendsProvider
from reelforge.agents.providers.web_search import PerplexityProvider
from reelforge.agents.providers.youtube import YouTubeProvider
from reelforge.services.exploding_topics.client import ExplodingTopicsClient
from reelforge.services.google_trends.client import GoogleTrendsClient
from reelforge.services.perplexity.client import PerplexityClient
from reelforge.services.providers.image.mock import MockImageProvider
from reelforge.services.providers.llm.claude import ClaudeProvider
from reelforge.services.providers.llm.openai import OpenAIProvider
from reelforge.services.providers.tts.mock import MockTTSProvider
from reelforge.services.reddit.client import RedditClient
from reelforge.services.youtube.client import YouTubeClient


class AgentContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    # ── Service clients — Singleton: stateless, one per container ────────────

    youtube_client: providers.Singleton[YouTubeClient] = providers.Singleton(
        YouTubeClient,
        api_key=config.youtube_api_key,
    )

    google_trends_client: providers.Singleton[GoogleTrendsClient] = providers.Singleton(
        GoogleTrendsClient,
    )

    exploding_topics_client: providers.Singleton[ExplodingTopicsClient] = providers.Singleton(
        ExplodingTopicsClient,
    )

    reddit_client: providers.Singleton[RedditClient] = providers.Singleton(
        RedditClient,
        client_id=config.reddit_client_id,
        client_secret=config.reddit_client_secret,
    )

    perplexity_client: providers.Singleton[PerplexityClient] = providers.Singleton(
        PerplexityClient,
        api_key=config.perplexity_api_key,
    )

    # ── Providers — what consumers depend on ─────────────────────────────────

    video_search: providers.Singleton[YouTubeProvider] = providers.Singleton(
        YouTubeProvider,
        client=youtube_client,
    )

    trends: providers.Singleton[GoogleTrendsProvider] = providers.Singleton(
        GoogleTrendsProvider,
        google_client=google_trends_client,
        exploding_client=exploding_topics_client,
    )

    reddit: providers.Singleton[RedditProvider] = providers.Singleton(
        RedditProvider,
        client=reddit_client,
    )

    web_search: providers.Singleton[PerplexityProvider] = providers.Singleton(
        PerplexityProvider,
        client=perplexity_client,
    )

    # ── LLM providers ─────────────────────────────────────────────────────────

    llm_claude: providers.Singleton[ClaudeProvider] = providers.Singleton(
        ClaudeProvider,
        api_key=config.anthropic_api_key,
    )

    llm_openai: providers.Singleton[OpenAIProvider] = providers.Singleton(
        OpenAIProvider,
        api_key=config.openai_api_key,
    )

    # ── TTS provider ──────────────────────────────────────────────────────────

    tts: providers.Singleton[MockTTSProvider] = providers.Singleton(
        MockTTSProvider,
        name="mock",
    )

    # ── Image provider ────────────────────────────────────────────────────────

    image: providers.Singleton[MockImageProvider] = providers.Singleton(
        MockImageProvider,
        name="mock",
    )
