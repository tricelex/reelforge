"""API DTOs for the channels app."""

from typing import Any

import msgspec


class ProviderDailyCapPayload(msgspec.Struct, frozen=True):
    """Per-provider daily spend cap for a channel."""

    provider: str
    daily_cap_usd: str


class ChannelSummaryPayload(msgspec.Struct, frozen=True):
    """Lightweight channel row."""

    id: str
    name: str
    kind: str
    publish_mode: str
    is_active: bool
    gates: list[str]
    default_blueprint_name: str | None
    niche_id: str | None
    niche_angle: str
    published_videos: int
    active_runs: int
    total_spend_usd: str
    last_activity_at: str | None
    youtube_status: str


class ChannelDetailPayload(msgspec.Struct, frozen=True):
    """Full channel configuration."""

    id: str
    name: str
    kind: str
    publish_mode: str
    gates: list[str]
    character_design_mode: str
    default_budget_usd: str | None
    voice_id: str
    stability: float
    similarity_boost: float
    wpm: int
    is_active: bool
    default_blueprint_name: str | None
    provider_daily_caps: list[ProviderDailyCapPayload]
    config_overrides: dict[str, Any]


class NicheCreatePayload(msgspec.Struct, frozen=True):
    """Optional niche block on channel create."""

    format_id: str | None = None
    audience: str = ''
    angle: str = ''
    banned_topics: list[str] | None = None
    lore_document: str = ''


class ChannelCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a channel."""

    name: str
    kind: str
    publish_mode: str = 'review'
    gates: list[str] | None = None
    character_design_mode: str = 'interactive'
    default_budget_usd: str | None = None
    voice_id: str = ''
    stability: float = 0.5
    similarity_boost: float = 0.75
    wpm: int = 158
    default_blueprint_name: str | None = None
    provider_daily_caps: list[ProviderDailyCapPayload] | None = None
    config_overrides: dict[str, Any] | None = None
    niche: NicheCreatePayload | None = None


class ChannelPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a channel."""

    name: str | None = None
    publish_mode: str | None = None
    gates: list[str] | None = None
    character_design_mode: str | None = None
    default_budget_usd: str | None = None
    voice_id: str | None = None
    stability: float | None = None
    similarity_boost: float | None = None
    wpm: int | None = None
    is_active: bool | None = None
    default_blueprint_name: str | None = None
    provider_daily_caps: list[ProviderDailyCapPayload] | None = None
    config_overrides: dict[str, Any] | None = None


class ChannelListPayload(msgspec.Struct, frozen=True):
    """List of channels."""

    items: list[ChannelSummaryPayload]
    next_cursor: str | None
    total: int


class ChannelBrandingPayload(msgspec.Struct, frozen=True):
    """Branding assets attached to a channel."""

    channel_id: str
    intro_asset_id: str | None
    outro_asset_id: str | None
    watermark_asset_id: str | None
    watermark_position: str
    watermark_opacity: float
    caption_style_asset_id: str | None
    font_asset_ids: list[str]
    music_pool_tags: list[str]
    thumbnail_palette: dict[str, str]
    warnings: list[str]


class GraduationStatusPayload(msgspec.Struct, frozen=True):
    """Review-to-auto graduation progress for a channel."""

    clean_run_count: int
    required_count: int
    eligible: bool


class ChannelBrandingPatchPayload(msgspec.Struct, frozen=True):
    """Partial branding update."""

    intro_asset_id: str | None = None
    outro_asset_id: str | None = None
    watermark_asset_id: str | None = None
    watermark_position: str | None = None
    watermark_opacity: float | None = None
    caption_style_asset_id: str | None = None
    font_asset_ids: list[str] | None = None
    music_pool_tags: list[str] | None = None
    thumbnail_palette: dict[str, str] | None = None


class AssemblyStyleConfigPayload(msgspec.Struct, frozen=True):
    """Per-channel cinematic style pool."""

    channel_id: str
    camera_movements: list[str]
    transition_styles: list[str]
    sfx_pool_tags: list[str]
    min_cuts_per_minute: int
    max_cuts_per_minute: int


class AssemblyStyleConfigPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a channel's assembly style config."""

    camera_movements: list[str] | None = None
    transition_styles: list[str] | None = None
    sfx_pool_tags: list[str] | None = None
    min_cuts_per_minute: int | None = None
    max_cuts_per_minute: int | None = None


class YouTubeConnectPayload(msgspec.Struct, frozen=True):
    """OAuth authorization URL for YouTube connect."""

    authorization_url: str


class YouTubeCallbackPayload(msgspec.Struct, frozen=True):
    """OAuth callback body."""

    code: str
    redirect_uri: str


class YouTubeStatusPayload(msgspec.Struct, frozen=True):
    """YouTube connection status (no secrets)."""

    connected: bool
    scope: str | None = None
    token_expiry: str | None = None


class YouTubeConnectResultPayload(msgspec.Struct, frozen=True):
    """Result of completing YouTube OAuth."""

    connected: bool
    scope: str


class NicheConfigPayload(msgspec.Struct, frozen=True):
    """Niche configuration for a channel."""

    id: str
    channel_id: str
    format_id: str | None
    audience: str
    angle: str
    banned_topics: list[str]
    lore_document: str


class NicheConfigPatchPayload(msgspec.Struct, frozen=True):
    """Partial niche update."""

    format_id: str | None = None
    audience: str | None = None
    angle: str | None = None
    banned_topics: list[str] | None = None
    lore_document: str | None = None


class CharacterSummaryPayload(msgspec.Struct, frozen=True):
    """Lightweight character row."""

    id: str
    channel_id: str | None
    name: str
    status: str
    origin: str
    hero_ref_asset_id: str | None


class CharacterDetailPayload(msgspec.Struct, frozen=True):
    """Full character detail."""

    id: str
    channel_id: str | None
    name: str
    status: str
    appearance_prompt: str
    persona: str
    hero_ref_asset_id: str | None
    total_creation_cost_usd: str
    origin: str
    source_run_id: str | None


class CharacterCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a character."""

    name: str
    channel_id: str | None = None
    appearance_prompt: str = ''
    persona: str = ''


class CharacterPatchPayload(msgspec.Struct, frozen=True):
    """Partial character update."""

    name: str | None = None
    appearance_prompt: str | None = None
    persona: str | None = None
    status: str | None = None


class CharacterListPayload(msgspec.Struct, frozen=True):
    """List of characters."""

    items: list[CharacterSummaryPayload]
    total: int


class CharacterRoundPayload(msgspec.Struct, frozen=True):
    """One recorded generation round."""

    prompt: str
    model: str
    n: int
    cost_usd: str
    candidate_asset_ids: list[str]
    picked: str | None = None


class CharacterSessionPayload(msgspec.Struct, frozen=True):
    """Character generation session."""

    id: str
    character_id: str
    rounds: list[CharacterRoundPayload]
    created_at: str


class CharacterRoundCreatePayload(msgspec.Struct, frozen=True):
    """Input for one generation round."""

    prompt: str
    ref_asset_ids: list[str] | None = None
    model: str = 'fal-ai/flux/dev'
    n: int = 4


class CharacterRoundResultPayload(msgspec.Struct, frozen=True):
    """Result of a generation round."""

    session_id: str
    candidate_asset_ids: list[str]
    cost_usd: str


class CharacterApprovePayload(msgspec.Struct, frozen=True):
    """Lock a winning candidate asset."""

    winning_asset_id: str
    appearance_prompt: str | None = None


class CharacterSheetExpandPayload(msgspec.Struct, frozen=True):
    """Guided sheet variant batch."""

    labels: list[str]
    model: str = 'fal-ai/flux/dev'


class CharacterSheetItemPayload(msgspec.Struct, frozen=True):
    """One sheet variant."""

    id: str
    label: str
    asset_id: str


class CharacterSheetExpandResultPayload(msgspec.Struct, frozen=True):
    """Created sheet items."""

    items: list[CharacterSheetItemPayload]
