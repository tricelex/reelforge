from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from reelforge.channels.models import Channel
    from reelforge.channels.models import SocialAccount
    from reelforge.services.base import BaseImageProvider
    from reelforge.services.base import BaseTTSProvider
    from reelforge.services.base import BaseVideoClipProvider
    from reelforge.services.providers.distribution.base import BaseClipDistributionProvider

logger = logging.getLogger("reelforge.providers")

_singletons: dict[str, object] = {}


def get_tts_provider(channel: Channel | None = None) -> BaseTTSProvider:
    from reelforge.services.providers.tts.elevenlabs import ElevenLabsProvider
    from reelforge.services.providers.tts.mock import MockTTSProvider

    name = channel.tts_provider if channel and channel.tts_provider else settings.DEFAULT_TTS_PROVIDER
    key = f"tts_{name}"
    if key not in _singletons:
        if name == "mock":
            _singletons[key] = MockTTSProvider(name="mock")
        else:
            _singletons[key] = ElevenLabsProvider(api_key=settings.ELEVENLABS_API_KEY)
    return _singletons[key]  # type: ignore[return-value]


def get_image_provider(channel: Channel | None = None) -> BaseImageProvider:
    from reelforge.services.fal.client import FalAiClient
    from reelforge.services.providers.image.fal_ai import FalAiImageProvider
    from reelforge.services.providers.image.mock import MockImageProvider

    name = channel.image_provider if channel and channel.image_provider else settings.DEFAULT_IMAGE_PROVIDER
    key = f"image_{name}"
    if key not in _singletons:
        if name == "mock":
            _singletons[key] = MockImageProvider(name="mock")
        else:
            _singletons[key] = FalAiImageProvider(client=FalAiClient(api_key=settings.FAL_API_KEY))
    return _singletons[key]  # type: ignore[return-value]


def get_video_clip_provider(channel: Channel | None = None) -> BaseVideoClipProvider:
    from reelforge.services.fal.client import FalAiClient
    from reelforge.services.providers.video_clip.fal_ai import FalAiVideoClipProvider
    from reelforge.services.providers.video_clip.mock import MockVideoClipProvider

    name = (
        getattr(channel, "video_clip_provider", None) if channel else None
    ) or settings.DEFAULT_VIDEO_CLIP_PROVIDER
    key = f"video_clip_{name}"
    if key not in _singletons:
        if name == "mock":
            _singletons[key] = MockVideoClipProvider(name="mock")
        else:
            _singletons[key] = FalAiVideoClipProvider(client=FalAiClient(api_key=settings.FAL_API_KEY))
    return _singletons[key]  # type: ignore[return-value]


def get_distribution_provider(
    social_account: SocialAccount,
) -> BaseClipDistributionProvider:
    from reelforge.channels.models import SocialAccount as _SocialAccount
    from reelforge.services.providers.distribution.instagram import InstagramClipProvider
    from reelforge.services.providers.distribution.tiktok import TikTokClipProvider
    from reelforge.services.providers.distribution.youtube import YouTubeClipProvider

    platform = social_account.platform
    if platform == _SocialAccount.Platform.YOUTUBE:
        return YouTubeClipProvider(social_account)
    if platform == _SocialAccount.Platform.TIKTOK:
        return TikTokClipProvider(social_account)
    if platform == _SocialAccount.Platform.INSTAGRAM:
        return InstagramClipProvider(social_account)
    msg = f"Distribution provider not implemented for platform: {platform}"
    raise NotImplementedError(msg)
