"""msgspec DTOs for NexLev API responses — only fields we consume.

NexLev's outer envelope fields are camelCase (about/outliers/analytics/
similar_channels/niche_overview/video/search) so those structs decode
with `rename='camel'`. The nested `strategic_insights` fields inside the
async channel-analysis job result are already snake_case in NexLev's own
JSON, so those structs use plain (unrenamed) field names.
"""

import msgspec


class NexLevChannelAbout(msgspec.Struct, rename='camel'):
    """GET /api/external/channels/about."""

    channel_id: str
    title: str
    description: str = ''
    subscriber_count: int = 0
    videos_count: int = 0
    view_count: int = 0


class NexLevOutlierVideo(msgspec.Struct, rename='camel'):
    """One item of GET /api/external/channels/outliers → outliers[]."""

    video_id: str
    title: str
    view_count: str = ''
    outlier_score: str = ''
    published_at: str = ''


class NexLevChannelAnalytics(msgspec.Struct, rename='camel'):
    """Flattened POST /api/external/analytics/channel-analytics."""

    subscriber_count: int = 0
    view_count: int = 0
    video_count: int = 0
    country: str = ''
    categories: list[str] = []
    tags: list[str] = []


class NexLevSimilarChannel(msgspec.Struct, rename='camel'):
    """One item shared by similar-channels search and niche overview."""

    channel_id: str
    channel_name: str
    similarity_score: int = 0


class NexLevNicheOverview(msgspec.Struct, rename='camel'):
    """POST /api/external/niche-overview/analyze."""

    original_channel_id: str
    similar_channels: list[NexLevSimilarChannel] = []
    total_channels: int = 0
    total_videos: int = 0


class NexLevVideoDetails(msgspec.Struct, rename='camel'):
    """GET /api/external/videos/details (first item of the response)."""

    id: str
    title: str
    channel_title: str = ''
    channel_id: str = ''
    view_count: str = ''
    length_seconds: str = ''


class NexLevTranscriptSegment(msgspec.Struct, rename='camel'):
    """One item of GET /api/external/videos/transcript → transcript[]."""

    start_ms: str
    end_ms: str
    start_time: str = ''
    text: str = ''


class NexLevComment(msgspec.Struct, rename='camel'):
    """One item of GET /api/external/videos/comments → data[]."""

    comment_id: str
    author_text: str = ''
    text_display: str = ''
    likes_count: str = ''


class NexLevSearchResultItem(msgspec.Struct, rename='camel'):
    """One polymorphic item of GET /api/external/youtube/search → results[].

    Shape varies by `type` (video/shorts/channel/playlist) — every field
    beyond `type` is optional so one struct covers all four.
    """

    type: str
    title: str = ''
    video_id: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    view_count: str | int | None = None


class NexLevSuggestedTopic(msgspec.Struct):
    """strategic_insights.suggested_topics.topics[] (already snake_case)."""

    title: str
    description: str = ''


class NexLevScriptStage(msgspec.Struct):
    """strategic_insights.script_blueprint.recommended_stages[]."""

    stage: str
    purpose: str = ''
    recommended_length_seconds: int = 0
    winning_formula: str = ''


class NexLevTitleFormatGroup(msgspec.Struct):
    """strategic_insights.title_format_strategy.format_groups[]."""

    format_name: str
    format_description: str = ''
    video_count: int = 0


class NexLevChannelAnalysisResult(msgspec.Struct):
    """Trimmed result of the async channel-analysis job (Deep Analysis)."""

    suggested_topics: list[NexLevSuggestedTopic] = []
    script_blueprint: list[NexLevScriptStage] = []
    title_format_groups: list[NexLevTitleFormatGroup] = []
