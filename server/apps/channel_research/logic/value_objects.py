"""API DTOs for channel research jobs."""

from typing import Any

import msgspec

from server.apps.channel_research.logic.types import (
    ChannelResearchKindLiteral,
    ChannelResearchStatusLiteral,
    RecommendedModeLiteral,
    VisualMediumLiteral,
)


class ChannelSpecProviderCapPayload(msgspec.Struct, frozen=True):
    """One provider spend cap inside ChannelSpec.channel."""

    provider: str
    daily_cap_usd: str


class ChannelSpecChannelPayload(msgspec.Struct, frozen=True):
    """ChannelSpec.channel."""

    name: str
    kind: ChannelResearchKindLiteral
    publish_mode: str = 'review'
    character_design_mode: str = 'none'
    voice_id: str = ''
    stability: float = 0.5
    similarity_boost: float = 0.75
    wpm: int = 150
    default_budget_usd: str = '15.00'
    max_publishes_per_day: int = 1
    default_blueprint_name: str = 'longform_v1'
    gates: list[str] = []
    provider_daily_caps: list[ChannelSpecProviderCapPayload] = []
    config_overrides: dict[str, Any] = {}


class ChannelSpecNichePayload(msgspec.Struct, frozen=True):
    """ChannelSpec.niche."""

    angle: str
    audience: str = ''
    banned_topics: list[str] = []
    lore_document: str = ''
    format_key: str = 'factual_documentary'
    visual_bible: str = ''
    visual_medium: VisualMediumLiteral | None = None
    style_tokens: list[str] = []
    style_negatives: list[str] = []


class ChannelSpecStoryFormatBeatPayload(msgspec.Struct, frozen=True):
    """One beat in ChannelSpec.story_format."""

    name: str
    description: str


class ChannelSpecStoryFormatPayload(msgspec.Struct, frozen=True):
    """ChannelSpec.story_format."""

    key: str
    name: str
    create_if_missing: bool = False
    fiction: bool = False
    narration_pov: str = 'narrator'
    beats: list[ChannelSpecStoryFormatBeatPayload] = []
    pacing: dict[str, int] = {}
    music_mood_map: dict[str, str] = {}
    prompt_overrides: dict[str, str] = {}


class ChannelSpecPromptTemplatePayload(msgspec.Struct, frozen=True):
    """One prompt template to import with the spec."""

    key: str
    name: str
    scope: str = 'GLOBAL'
    description: str = ''
    system_prompt: str = ''
    user_prompt: str = ''
    model: str = 'gpt-5.6-terra'
    temperature: float = 1.0
    max_tokens: int = 8192


class ChannelSpecBrandingPayload(msgspec.Struct, frozen=True):
    """ChannelSpec.branding."""

    watermark_position: str = 'bottom_right'
    watermark_opacity: float = 0.5
    music_pool_tags: list[str] = []
    thumbnail_palette: dict[str, str] = {}


class ChannelSpecAssemblyStylePayload(msgspec.Struct, frozen=True):
    """ChannelSpec.assembly_style."""

    camera_movements: list[str] = []
    transition_styles: list[str] = []
    sfx_pool_tags: list[str] = []
    min_cuts_per_minute: int = 4
    max_cuts_per_minute: int = 8
    music_bed_gain_db: float = -22
    enable_background_music: bool = True


class ChannelSpecFootageSourcingPayload(msgspec.Struct, frozen=True):
    """ChannelSpec.footage_sourcing."""

    enabled_providers: list[str] = []
    sourcing_mode: str = 'stock_first'
    ai_fallback_enabled: bool = True
    rerank_mode: str = 'vision'
    candidates_per_scene: int = 8
    min_clip_width: int = 1280
    min_clip_duration_s: float = 3.0
    allowed_licenses: list[str] = []
    require_attribution: bool = True


class ChannelSpecCharacterPayload(msgspec.Struct, frozen=True):
    """ChannelSpec.character."""

    include: bool = False
    name: str = ''
    appearance_prompt: str = ''
    persona: str = ''
    status: str = 'APPROVED'


class ChannelSpecSeedIdeaPayload(msgspec.Struct, frozen=True):
    """One seed idea for LONGFORM import."""

    title: str
    topic: str
    score: float = 0.8


class ChannelSpecPayload(msgspec.Struct, frozen=True):
    """Importer-ready ChannelSpec (mirrors channel-onboarding-spec.md)."""

    channel: ChannelSpecChannelPayload
    niche: ChannelSpecNichePayload
    story_format: ChannelSpecStoryFormatPayload
    prompt_templates: list[ChannelSpecPromptTemplatePayload] = []
    branding: ChannelSpecBrandingPayload = ChannelSpecBrandingPayload()
    assembly_style: ChannelSpecAssemblyStylePayload = (
        ChannelSpecAssemblyStylePayload()
    )
    footage_sourcing: ChannelSpecFootageSourcingPayload = (
        ChannelSpecFootageSourcingPayload()
    )
    character: ChannelSpecCharacterPayload = ChannelSpecCharacterPayload()
    seed_ideas: list[ChannelSpecSeedIdeaPayload] = []
    post_import_notes: list[str] = []


class SourceChannelStatsPayload(msgspec.Struct, frozen=True):
    """Public stats for the source YouTube channel."""

    channel_id: str = ''
    channel_name: str = ''
    subscriber_count: int | None = None
    video_count: int | None = None
    view_count: int | None = None
    description: str = ''


class FormatProfilePayload(msgspec.Struct, frozen=True):
    """Identified storytelling format of the source channel."""

    hook_pattern: str
    title_formulas: list[str]
    pacing: str
    visual_world: str


class VideoRefPayload(msgspec.Struct, frozen=True):
    """One notable video from research."""

    title: str
    video_id: str = ''
    url: str = ''
    view_count: int | None = None
    notes: str = ''


class CompetitorRefPayload(msgspec.Struct, frozen=True):
    """A competing channel or adjacent format."""

    channel_name: str
    channel_id: str = ''
    url: str = ''
    notes: str = ''


class NicheBendOpportunityPayload(msgspec.Struct, frozen=True):
    """One market x format remix that is not a clone."""

    title: str
    market: str
    format_hook: str
    rationale: str


class ResearchSourceRefPayload(msgspec.Struct, frozen=True):
    """Provenance for a research claim."""

    url: str
    title: str = ''
    kind: str = ''


class ResearchReportPayload(msgspec.Struct, frozen=True):
    """Dossier produced before the ChannelSpec."""

    source_channel: SourceChannelStatsPayload
    identified_market: str
    identified_format: FormatProfilePayload
    top_videos: list[VideoRefPayload]
    competitors: list[CompetitorRefPayload]
    what_works: list[str]
    what_not_to_copy: list[str]
    gaps: list[str]
    niche_bend_opportunities: list[NicheBendOpportunityPayload]
    recommended_mode: RecommendedModeLiteral
    sources: list[ResearchSourceRefPayload]
    visual_medium: VisualMediumLiteral
    style_tokens: list[str] = []
    style_negatives: list[str] = []


class ToolTraceEntryPayload(msgspec.Struct, frozen=True):
    """One tool call in the research chronology."""

    tool: str
    args: dict[str, Any] = {}
    summary: str = ''
    ts: str = ''


class UsagePayload(msgspec.Struct, frozen=True):
    """Token and request usage for one research run."""

    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    tool_calls: int = 0


class ChannelResearchJobPayload(msgspec.Struct, frozen=True):
    """Read representation of one channel research job."""

    id: str
    source_channel_url: str
    target_market: str
    working_name: str
    kind: ChannelResearchKindLiteral
    notes: str
    source_channel_id: str
    source_channel_name: str
    status: ChannelResearchStatusLiteral
    research_report: ResearchReportPayload | None
    channel_spec: ChannelSpecPayload | None
    tool_trace: list[ToolTraceEntryPayload]
    usage: UsagePayload
    error_message: str
    created_by_id: str | None
    created_at: str
    updated_at: str


class ChannelResearchCreatePayload(msgspec.Struct, frozen=True):
    """Create a research job from a YouTube channel URL."""

    source_channel_url: str
    target_market: str = ''
    working_name: str = ''
    kind: ChannelResearchKindLiteral = 'LONGFORM'
    notes: str = ''


class ChannelResearchSpecPatchPayload(msgspec.Struct, frozen=True):
    """Replace channel_spec JSON on a succeeded job."""

    channel_spec: ChannelSpecPayload


class ChannelResearchListQuery(msgspec.Struct, frozen=True):
    """Query parameters for the research job list."""

    status: ChannelResearchStatusLiteral | None = None
    cursor: str | None = None
    limit: int = 20


class ChannelResearchListPayload(msgspec.Struct, frozen=True):
    """Cursor-paginated research job list."""

    items: list[ChannelResearchJobPayload]
    next_cursor: str | None
    total: int


class ChannelSpecValidateResultPayload(msgspec.Struct, frozen=True):
    """Result of POST /api/channel-research/validate-spec/."""

    ok: bool
    errors: list[str]


class ChannelSpecImportStepPayload(msgspec.Struct, frozen=True):
    """One step recorded by POST /api/channel-research/import/."""

    name: str
    ok: bool
    detail: str


class ChannelSpecImportResultPayload(msgspec.Struct, frozen=True):
    """Result of the atomic ChannelSpec importer."""

    channel_id: str
    steps: list[ChannelSpecImportStepPayload]
