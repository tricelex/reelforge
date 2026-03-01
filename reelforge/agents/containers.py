from __future__ import annotations

from dependency_injector import containers
from dependency_injector import providers

from ***REMOVED***.agents.providers.hackernews import HackerNewsProvider
from ***REMOVED***.agents.providers.tavily import TavilyProvider
from ***REMOVED***.agents.providers.trends import GoogleTrendsProvider
from ***REMOVED***.agents.providers.web_search import PerplexityProvider
from ***REMOVED***.agents.providers.youtube import YouTubeProvider
from ***REMOVED***.services.exploding_topics.client import ExplodingTopicsClient
from ***REMOVED***.services.google_trends.client import GoogleTrendsClient
from ***REMOVED***.services.hackernews.client import HackerNewsClient
from ***REMOVED***.services.perplexity.client import PerplexityClient
from ***REMOVED***.services.providers.image.mock import MockImageProvider
from ***REMOVED***.services.providers.llm.claude import ClaudeProvider
from ***REMOVED***.services.providers.llm.openai import OpenAIProvider
from ***REMOVED***.services.providers.tts.elevenlabs import ElevenLabsProvider
from ***REMOVED***.services.providers.tts.mock import MockTTSProvider
from ***REMOVED***.services.rising_topics.client import RisingTopicsClient
from ***REMOVED***.services.tavily.client import TavilyResearchClient
from ***REMOVED***.services.youtube.client import YouTubeClient


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

    hackernews_client: providers.Singleton[HackerNewsClient] = providers.Singleton(
        HackerNewsClient,
    )

    rising_topics_client: providers.Singleton[RisingTopicsClient] = providers.Singleton(
        RisingTopicsClient,
        google_client=google_trends_client,
        hackernews_client=hackernews_client,
    )

    perplexity_client: providers.Singleton[PerplexityClient] = providers.Singleton(
        PerplexityClient,
        api_key=config.perplexity_api_key,
    )

    tavily_client: providers.Singleton[TavilyResearchClient] = providers.Singleton(
        TavilyResearchClient,
        api_key=config.tavily_api_key,
    )

    # ── Providers — what consumers depend on ─────────────────────────────────

    video_search: providers.Singleton[YouTubeProvider] = providers.Singleton(
        YouTubeProvider,
        client=youtube_client,
    )

    trends: providers.Singleton[GoogleTrendsProvider] = providers.Singleton(
        GoogleTrendsProvider,
        google_client=google_trends_client,
        rising_client=rising_topics_client,
    )

    community: providers.Singleton[HackerNewsProvider] = providers.Singleton(
        HackerNewsProvider,
        client=hackernews_client,
    )

    web_search_perplexity: providers.Singleton[PerplexityProvider] = providers.Singleton(
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

    web_search_tavily: providers.Singleton[TavilyProvider] = providers.Singleton(
        TavilyProvider,
        client=tavily_client,
    )

    # Default web_search uses Tavily AI search
    web_search = web_search_tavily

    # ── TTS providers ─────────────────────────────────────────────────────────

    tts_mock: providers.Singleton[MockTTSProvider] = providers.Singleton(
        MockTTSProvider,
        name="mock",
    )

    tts_elevenlabs: providers.Singleton[ElevenLabsProvider] = providers.Singleton(
        ElevenLabsProvider,
        api_key=config.elevenlabs_api_key,
    )

    # ── Image providers ────────────────────────────────────────────────────────

    image_mock: providers.Singleton[MockImageProvider] = providers.Singleton(
        MockImageProvider,
        name="mock",
    )
