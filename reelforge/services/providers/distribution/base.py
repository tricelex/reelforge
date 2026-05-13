from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipPost


@dataclass
class PostResult:
    platform_post_id: str
    platform_url: str
    success: bool
    error_message: str = ""


@dataclass
class AnalyticsResult:
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    revenue_est_usd: Decimal = Decimal(0)


class BaseClipDistributionProvider(ABC):
    @abstractmethod
    def post_clip(self, clip_post: ClipPost) -> PostResult: ...

    @abstractmethod
    def get_analytics(self, clip_post: ClipPost) -> AnalyticsResult: ...
