from __future__ import annotations

from dependency_injector import containers
from dependency_injector import providers

from reelforge.agents.providers.community import SerpApiCommunityProvider
from reelforge.agents.providers.trends import SerpApiTrendsProvider
from reelforge.agents.providers.web_search import TavilyProvider
from reelforge.agents.providers.youtube import SerpApiYouTubeProvider
from reelforge.services.providers.image.mock import MockImageProvider
from reelforge.services.providers.video_clip.mock import MockVideoClipProvider
from reelforge.services.providers.llm.claude import ClaudeProvider
from reelforge.services.providers.llm.openai import OpenAIProvider
from reelforge.services.providers.tts.elevenlabs import ElevenLabsProvider
from reelforge.services.providers.tts.mock import MockTTSProvider
from reelforge.services.serpapi.client import SerpApiClient
from reelforge.services.tavily.client import TavilyResearchClient


class AgentContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    # ── Service clients — Singleton: stateless, one per container ────────────

    serpapi_client: providers.Singleton[SerpApiClient] = providers.Singleton(
        SerpApiClient,
        api_key=config.serpapi_api_key,
    )

    tavily_client: providers.Singleton[TavilyResearchClient] = providers.Singleton(
        TavilyResearchClient,
        api_key=config.tavily_api_key,
    )

    # ── Providers — what consumers depend on ─────────────────────────────────

    video_search: providers.Singleton[SerpApiYouTubeProvider] = providers.Singleton(
        SerpApiYouTubeProvider,
        client=serpapi_client,
    )

    trends: providers.Singleton[SerpApiTrendsProvider] = providers.Singleton(
        SerpApiTrendsProvider,
        client=serpapi_client,
    )

    community: providers.Singleton[SerpApiCommunityProvider] = providers.Singleton(
        SerpApiCommunityProvider,
        client=serpapi_client,
    )

    web_search_tavily: providers.Singleton[TavilyProvider] = providers.Singleton(
        TavilyProvider,
        client=tavily_client,
    )

    # Default web_search uses Tavily AI search
    web_search = web_search_tavily

    # ── LLM providers ─────────────────────────────────────────────────────────

    llm_claude: providers.Singleton[ClaudeProvider] = providers.Singleton(
        ClaudeProvider,
        api_key=config.anthropic_api_key,
    )

    llm_openai: providers.Singleton[OpenAIProvider] = providers.Singleton(
        OpenAIProvider,
        api_key=config.openai_api_key,
    )

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

    # ── Video clip providers ───────────────────────────────────────────────────

    video_clip_mock: providers.Singleton[MockVideoClipProvider] = providers.Singleton(
        MockVideoClipProvider,
        name="mock",
    )
