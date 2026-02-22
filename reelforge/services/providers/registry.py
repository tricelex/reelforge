from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.services.base import BaseImageProvider
    from ***REMOVED***.services.base import BaseLLMProvider
    from ***REMOVED***.services.base import BaseTTSProvider

logger = logging.getLogger("***REMOVED***.providers")


def _container() -> Any:
    """Return the AgentContainer singleton (avoids circular imports)."""
    from ***REMOVED***.agents.apps import AgentsConfig

    return AgentsConfig.container


def get_llm_provider(channel: Channel | None = None) -> BaseLLMProvider:
    """Returns the configured LLM provider, optionally channel-specific."""
    name = channel.llm_provider if channel and channel.llm_provider else settings.DEFAULT_LLM_PROVIDER
    if name == "claude":
        return _container().llm_claude()
    if name == "openai":
        return _container().llm_openai()
    msg = f"Unknown LLM provider: {name}"
    raise ValueError(msg)


def get_tts_provider(channel: Channel | None = None) -> BaseTTSProvider:
    """Returns the configured TTS provider, optionally channel-specific."""
    name = channel.tts_provider if channel and channel.tts_provider else settings.DEFAULT_TTS_PROVIDER
    if name == "mock":
        return _container().tts_mock()
    if name == "elevenlabs":
        return _container().tts_elevenlabs()
    msg = f"Unknown TTS provider: {name}"
    raise ValueError(msg)


def get_image_provider(channel: Channel | None = None) -> BaseImageProvider:
    """Returns the configured image generation provider, optionally channel-specific."""
    name = channel.image_provider if channel and channel.image_provider else settings.DEFAULT_IMAGE_PROVIDER
    if name == "mock":
        return _container().image_mock()
    msg = f"Unknown image provider: {name}"
    raise ValueError(msg)
