from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import runtime_checkable

if TYPE_CHECKING:
    from reelforge.ai.schemas.research import CommunityPost
    from reelforge.ai.schemas.research import RisingTopic
    from reelforge.ai.schemas.research import TrendData
    from reelforge.ai.schemas.research import VideoResult
    from reelforge.services.dataclass import ImageResponse
    from reelforge.services.dataclass import TTSResponse


@runtime_checkable
class VideoSearchProvider(Protocol):
    def search_trending(self, niche: str, days_back: int, limit: int) -> list[VideoResult]: ...

    def search_videos(self, query: str, max_results: int) -> list[VideoResult]: ...

    def get_channel_videos(self, channel_id: str, max_results: int) -> list[VideoResult]: ...

    def analyze_competitors(self, channel_ids: list[str]) -> dict[str, Any]: ...


@runtime_checkable
class TrendsProvider(Protocol):
    def get_interest(self, keyword: str, timeframe: str) -> TrendData: ...

    def get_interest_batch(self, keywords: list[str], timeframe: str) -> list[TrendData]: ...

    def get_trending_searches(self, region: str) -> list[str]: ...

    def get_rising_topics(self, category: str) -> list[RisingTopic]: ...


@runtime_checkable
class CommunitySearchProvider(Protocol):
    def search_discussions(self, niche: str, query: str | None, limit: int) -> list[CommunityPost]: ...


@runtime_checkable
class WebSearchProvider(Protocol):
    def research(self, topic: str, depth: str) -> dict[str, Any]: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, voice_id: str, **settings: Any) -> TTSResponse: ...


@runtime_checkable
class ImageProvider(Protocol):
    name: str

    def generate(self, prompt: str, width: int, height: int, **kwargs: Any) -> list[ImageResponse]: ...
