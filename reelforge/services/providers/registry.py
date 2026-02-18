from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.services.base import BaseImageProvider
    from ***REMOVED***.services.base import BaseLLMProvider
    from ***REMOVED***.services.base import BaseTTSProvider

logger = logging.getLogger("***REMOVED***.providers")

_providers: dict[str, object] = {}


def get_llm_provider(channel: Channel | None = None) -> BaseLLMProvider:
    """Returns the configured LLM provider, optionally channel-specific."""
    provider_name = channel.llm_provider if channel and channel.llm_provider else settings.DEFAULT_LLM_PROVIDER
    cache_key = f"llm_{provider_name}"
    if cache_key not in _providers:
        _providers[cache_key] = _build_llm_provider(provider_name)
    return _providers[cache_key]  # type: ignore


def get_tts_provider(channel: Channel | None = None) -> BaseTTSProvider:
    """Returns the configured TTS provider, optionally channel-specific.

    TODO: Implement actual TTS provider instantiation.
    """
    provider_name = (
        channel.tts_provider
        if channel and hasattr(channel, "tts_provider") and channel.tts_provider
        else getattr(settings, "DEFAULT_TTS_PROVIDER", "elevenlabs")
    )
    cache_key = f"tts_{provider_name}"
    if cache_key not in _providers:
        logger.warning("TTS provider '%s' requested (placeholder implementation)", provider_name)
        _providers[cache_key] = _build_tts_provider(provider_name)
    return _providers[cache_key]  # type: ignore


def get_image_provider(channel: Channel | None = None) -> BaseImageProvider:
    """Returns the configured image generation provider, optionally channel-specific.

    TODO: Implement actual image provider instantiation.
    """
    provider_name = (
        channel.image_provider
        if channel and hasattr(channel, "image_provider") and channel.image_provider
        else getattr(settings, "DEFAULT_IMAGE_PROVIDER", "fal_ai")
    )
    cache_key = f"image_{provider_name}"
    if cache_key not in _providers:
        logger.warning("Image provider '%s' requested (placeholder implementation)", provider_name)
        _providers[cache_key] = _build_image_provider(provider_name)
    return _providers[cache_key]  # type: ignore


def _build_llm_provider(name: str) -> BaseLLMProvider:
    from ***REMOVED***.services.providers.llm.claude import ClaudeProvider
    from ***REMOVED***.services.providers.llm.openai import OpenAIProvider

    if name == "claude":
        return ClaudeProvider(api_key=settings.ANTHROPIC_API_KEY)
    if name == "openai":
        return OpenAIProvider(api_key=settings.OPENAI_API_KEY)
    msg = f"Unknown LLM provider: {name}"
    raise ValueError(msg)


def _build_tts_provider(name: str) -> BaseTTSProvider:
    """Build TTS provider instance.

    TODO: Implement actual TTS providers (ElevenLabs, OpenAI TTS, Azure TTS).
    For now, returns a mock provider.
    """
    from ***REMOVED***.services.providers.tts.mock import MockTTSProvider

    logger.warning("Building mock TTS provider for: %s", name)
    return MockTTSProvider(name=name)


def _build_image_provider(name: str) -> BaseImageProvider:
    """Build image generation provider instance.

    TODO: Implement actual image providers (Fal.ai, Replicate, DALL-E).
    For now, returns a mock provider.
    """
    from ***REMOVED***.services.providers.image.mock import MockImageProvider

    logger.warning("Building mock image provider for: %s", name)
    return MockImageProvider(name=name)
