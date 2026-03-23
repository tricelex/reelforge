from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from reelforge.channels.models import SocialAccount
from reelforge.services.providers.distribution.base import AnalyticsResult
from reelforge.services.providers.distribution.base import BaseClipDistributionProvider
from reelforge.services.providers.distribution.base import PostResult

if TYPE_CHECKING:
    from reelforge.clipping.models import ClipPost

logger = logging.getLogger("reelforge.providers.distribution.youtube")


class YouTubeClipProvider(BaseClipDistributionProvider):
    def __init__(self, social_account: SocialAccount) -> None:
        self._account = social_account

    def post_clip(self, clip_post: ClipPost) -> PostResult:
        raise NotImplementedError("YouTube Shorts posting not yet implemented")

    def get_analytics(self, clip_post: ClipPost) -> AnalyticsResult:
        raise NotImplementedError("YouTube clip analytics not yet implemented")
