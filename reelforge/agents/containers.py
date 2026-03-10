from __future__ import annotations

from dependency_injector import containers
from dependency_injector import providers

from ***REMOVED***.agents.providers.community import SerpApiCommunityProvider
from ***REMOVED***.agents.providers.trends import SerpApiTrendsProvider
from ***REMOVED***.agents.providers.web_search import TavilyProvider
from ***REMOVED***.agents.providers.youtube import SerpApiYouTubeProvider
from ***REMOVED***.services.providers.image.fal_ai import FalAiImageProvider
from ***REMOVED***.services.providers.image.mock import MockImageProvider
from ***REMOVED***.services.providers.video_clip.fal_ai import FalAiVideoClipProvider
from ***REMOVED***.services.providers.video_clip.mock import MockVideoClipProvider
from ***REMOVED***.services.providers.llm.claude import ClaudeProvider
from ***REMOVED***.services.providers.llm.openai import OpenAIProvider
from ***REMOVED***.services.providers.tts.elevenlabs import ElevenLabsProvider
from ***REMOVED***.services.providers.tts.mock import MockTTSProvider
from ***REMOVED***.services.serpapi.client import SerpApiClient
from ***REMOVED***.services.tavily.client import TavilyResearchClient


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

    image_fal: providers.Singleton[FalAiImageProvider] = providers.Singleton(
        FalAiImageProvider,
        api_key=config.fal_api_key,
    )

    # ── Video clip providers ───────────────────────────────────────────────────

    video_clip_mock: providers.Singleton[MockVideoClipProvider] = providers.Singleton(
        MockVideoClipProvider,
        name="mock",
    )

    video_clip_fal: providers.Singleton[FalAiVideoClipProvider] = providers.Singleton(
        FalAiVideoClipProvider,
        api_key=config.fal_api_key,
    )
