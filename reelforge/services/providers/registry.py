from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.channels.models import SocialAccount
    from ***REMOVED***.services.base import BaseImageProvider
    from ***REMOVED***.services.base import BaseLLMProvider
    from ***REMOVED***.services.base import BaseTTSProvider
    from ***REMOVED***.services.base import BaseVideoClipProvider
    from ***REMOVED***.services.providers.distribution.base import BaseClipDistributionProvider

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
    if name == "fal_ai":
        return _container().image_fal()
    msg = f"Unknown image provider: {name}"
    raise ValueError(msg)


def get_video_clip_provider(channel: Channel | None = None) -> BaseVideoClipProvider:
    """Returns the configured video clip generation provider, optionally channel-specific."""
    name = (getattr(channel, "video_clip_provider", None) if channel else None) or getattr(
        settings, "DEFAULT_VIDEO_CLIP_PROVIDER", "fal_ai_kling"
    )
    if name == "mock":
        return _container().video_clip_mock()
    if name in ("fal_ai_kling", "fal_ai"):
        return _container().video_clip_fal()
    msg = f"Unknown video clip provider: {name}"
    raise ValueError(msg)


def get_distribution_provider(
    social_account: SocialAccount,
) -> BaseClipDistributionProvider:
    """Returns the appropriate distribution provider for the given social account platform."""
    from ***REMOVED***.channels.models import SocialAccount as _SocialAccount
    from ***REMOVED***.services.providers.distribution.base import BaseClipDistributionProvider  # noqa: F401
    from ***REMOVED***.services.providers.distribution.instagram import InstagramClipProvider
    from ***REMOVED***.services.providers.distribution.tiktok import TikTokClipProvider
    from ***REMOVED***.services.providers.distribution.youtube import YouTubeClipProvider

    platform = social_account.platform
    if platform == _SocialAccount.Platform.YOUTUBE:
        return YouTubeClipProvider(social_account)
    if platform == _SocialAccount.Platform.TIKTOK:
        return TikTokClipProvider(social_account)
    if platform == _SocialAccount.Platform.INSTAGRAM:
        return InstagramClipProvider(social_account)
    msg = f"Distribution provider not implemented for platform: {platform}"
    raise NotImplementedError(msg)
