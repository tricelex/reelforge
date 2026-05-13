from __future__ import annotations

import pytest

from reelforge.channels.models import SocialAccount
from reelforge.services.providers.registry import get_distribution_provider


@pytest.mark.django_db
def test_get_distribution_provider_youtube_returns_provider() -> None:
    from reelforge.channels.tests.factories import SocialAccountFactory
    from reelforge.services.providers.distribution.youtube import YouTubeClipProvider

    account = SocialAccountFactory(platform=SocialAccount.Platform.YOUTUBE)
    provider = get_distribution_provider(account)
    assert isinstance(provider, YouTubeClipProvider)


@pytest.mark.django_db
def test_get_distribution_provider_tiktok_returns_provider() -> None:
    from reelforge.channels.tests.factories import SocialAccountFactory
    from reelforge.services.providers.distribution.tiktok import TikTokClipProvider

    account = SocialAccountFactory(platform=SocialAccount.Platform.TIKTOK)
    provider = get_distribution_provider(account)
    assert isinstance(provider, TikTokClipProvider)


@pytest.mark.django_db
def test_tiktok_provider_post_clip_raises_not_implemented() -> None:
    from reelforge.channels.tests.factories import SocialAccountFactory
    from reelforge.services.providers.distribution.tiktok import TikTokClipProvider

    account = SocialAccountFactory(platform=SocialAccount.Platform.TIKTOK)
    provider = TikTokClipProvider(account)
    with pytest.raises(NotImplementedError):
        provider.post_clip(None)
