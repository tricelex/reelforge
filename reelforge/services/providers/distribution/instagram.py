from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ***REMOVED***.channels.models import SocialAccount
from ***REMOVED***.services.providers.distribution.base import AnalyticsResult
from ***REMOVED***.services.providers.distribution.base import BaseClipDistributionProvider
from ***REMOVED***.services.providers.distribution.base import PostResult

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipPost

logger = logging.getLogger("***REMOVED***.providers.distribution.instagram")


class InstagramClipProvider(BaseClipDistributionProvider):
    def __init__(self, social_account: SocialAccount) -> None:
        self._account = social_account

    def post_clip(self, clip_post: ClipPost) -> PostResult:
        raise NotImplementedError("Instagram Graph API Reels not yet implemented")

    def get_analytics(self, clip_post: ClipPost) -> AnalyticsResult:
        raise NotImplementedError("Instagram clip analytics not yet implemented")
