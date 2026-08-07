"""Value objects (DTOs) for the clips domain."""

from typing import Annotated

import msgspec

from server.apps.clips.logic.types import (
    _CROP_COORD_DESC,
    BackgroundModeLiteral,
    CandidateStatusLiteral,
    CaptionAnimationLiteral,
    CaptionFontLiteral,
    CaptionPositionLiteral,
    CaptionStyleLiteral,
    ColorFilterPresetLiteral,
    FitModeLiteral,
    ForegroundTreatmentLiteral,
    HookStyleLiteral,
    OverlayAnimationLiteral,
    OverlayShapeLiteral,
    OverlayTypeLiteral,
    ProgressBarPositionLiteral,
    RenderFormatLiteral,
    RenderModeLiteral,
    TransitionStyleLiteral,
    WatermarkPositionLiteral,
    WatermarkTypeLiteral,
)


class ClipBeatPayload(msgspec.Struct, frozen=True):
    """One Hook/Story/Payoff beat on a clip candidate."""

    role: str
    start_sec: float
    end_sec: float
    label: str = ''
    note: str = ''


class ClipCandidatePayload(msgspec.Struct, frozen=True):
    """Read-only representation of a ClipCandidate."""

    id: str
    run_id: str
    channel_id: str
    title: str
    hook_text: str
    caption_template: str
    start_sec: float
    end_sec: float
    duration_sec: float
    relevance_score: float
    status: CandidateStatusLiteral
    reason: str
    transcript_excerpt: str
    rejection_reason: str
    render_asset_id: str | None
    is_manual: bool
    headline: str = ''
    hook_score: float = 0.0
    flow_score: float = 0.0
    value_score: float = 0.0
    trend_score: float = 0.0
    virality_score: float = 0.0
    intent_match_score: float = 0.0
    confidence: float = 0.0
    score_version: str = ''
    hook_reason: str = ''
    flow_reason: str = ''
    value_reason: str = ''
    trend_reason: str = ''
    hook_grade: str = ''
    flow_grade: str = ''
    value_grade: str = ''
    trend_grade: str = ''
    arrangement: str = 'contiguous'
    beats: list[ClipBeatPayload] = []


class ClipRunOptionsPayload(msgspec.Struct, frozen=True):
    """Pre-run discovery and styling controls for a clipping project."""

    genre: str = 'auto'
    clip_length: str = 'auto'
    moments_prompt: str = ''
    timeframe_start: float | None = None
    timeframe_end: float | None = None
    custom_min_sec: float | None = None
    custom_max_sec: float | None = None
    auto_headline: bool = True
    candidate_count: int = 5
    brand_template_id: str | None = None
    auto_approve: bool = False


class CaptionPresetPayload(msgspec.Struct, frozen=True):
    """One caption style preset for galleries and brand templates."""

    key: str
    name: str
    description: str
    caption_style: str
    caption_font: str
    caption_size: int
    caption_color: str
    caption_highlight_color: str
    caption_stroke_color: str
    caption_stroke_width: int
    caption_position: str
    caption_animation: str
    caption_uppercase: bool
    sample_phrase: str


class CaptionPresetListPayload(msgspec.Struct, frozen=True):
    """Caption preset catalog."""

    items: list[CaptionPresetPayload]


class ClipCandidatePatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a clip candidate."""

    title: str | None = None
    hook_text: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None
    caption_template: str | None = None


class ClipCandidateListPayload(msgspec.Struct, frozen=True):
    """Paginated list of clip candidates."""

    items: list[ClipCandidatePayload]
    next_cursor: str | None
    total: int


class ClipRenderPayload(msgspec.Struct, frozen=True):
    """Export render job state + presigned URL for a rendered clip."""

    candidate_id: str
    asset_id: str | None
    url: str | None
    status: str = 'idle'
    error: str | None = None


class ClipPreviewStatusPayload(msgspec.Struct, frozen=True):
    """Preview render job state for one candidate."""

    candidate_id: str
    status: str
    url: str | None
    config_version: int
    error: str | None = None


class ClipSourceFramePayload(msgspec.Struct, frozen=True):
    """Presigned JPEG frame from the source video at a given time."""

    candidate_id: str
    time_sec: float
    url: str
    width: int | None
    height: int | None


class SourceFrameQuery(msgspec.Struct, frozen=True):
    """Query parameters for source frame extraction."""

    time_sec: float = 0.0


class ClipOverlayListPayload(msgspec.Struct, frozen=True):
    """Paginated overlay list."""

    items: list['ClipTimedOverlayPayload']
    next_cursor: str | None
    total: int


class ClipPostListPayload(msgspec.Struct, frozen=True):
    """Paginated post list."""

    items: list['ClipPostPayload']
    next_cursor: str | None
    total: int


class ApproveGatePayload(msgspec.Struct, frozen=True):
    """Input payload for gate approval / start-render API."""

    approved_candidate_ids: list[str] | None = None


class GateApprovalResultPayload(msgspec.Struct, frozen=True):
    """Result of approving a clip gate."""

    status: str
    approved_count: int


class ApproveAllResultPayload(msgspec.Struct, frozen=True):
    """Result of bulk-approving all proposed candidates."""

    approved_count: int


class ClipLayoutConfigPayload(msgspec.Struct, frozen=True):
    """Layout config for a clip candidate."""

    id: str
    candidate_id: str
    render_mode: RenderModeLiteral
    render_format: RenderFormatLiteral
    source_width: int | None
    source_height: int | None
    manual_crop_x: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    manual_crop_y: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    manual_crop_w: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    manual_crop_h: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_a_x: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_a_y: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_a_w: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_a_h: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_b_x: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_b_y: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_b_w: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    region_b_h: Annotated[int | None, msgspec.Meta(description=_CROP_COORD_DESC)]
    stack_ratio: float
    fit_mode: FitModeLiteral
    foreground_treatment: ForegroundTreatmentLiteral
    background_mode: BackgroundModeLiteral
    background_color: str
    blur_strength: int
    face_detected: bool | None
    detection_confidence: float | None


class ClipLayoutConfigPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for layout config."""

    render_mode: RenderModeLiteral | None = None
    render_format: RenderFormatLiteral | None = None
    manual_crop_x: int | None = None
    manual_crop_y: int | None = None
    manual_crop_w: int | None = None
    manual_crop_h: int | None = None
    region_a_x: int | None = None
    region_a_y: int | None = None
    region_a_w: int | None = None
    region_a_h: int | None = None
    region_b_x: int | None = None
    region_b_y: int | None = None
    region_b_w: int | None = None
    region_b_h: int | None = None
    stack_ratio: float | None = None
    fit_mode: FitModeLiteral | None = None
    foreground_treatment: ForegroundTreatmentLiteral | None = None
    background_mode: BackgroundModeLiteral | None = None
    background_color: str | None = None
    blur_strength: int | None = None


class ClipStyleConfigPayload(msgspec.Struct, frozen=True):
    """Style config for a clip candidate."""

    id: str
    candidate_id: str
    caption_enabled: bool
    caption_style: CaptionStyleLiteral
    caption_font: CaptionFontLiteral
    caption_size: int
    caption_color: str
    caption_stroke_color: str
    caption_stroke_width: int
    caption_bg_color: str
    caption_position: CaptionPositionLiteral
    caption_animation: CaptionAnimationLiteral
    caption_language: str
    caption_translate_to: str
    caption_font_asset_id: str | None
    caption_highlight_color: str
    caption_uppercase: bool
    emoji_keyword_map: dict[str, str]
    hook_enabled: bool
    hook_style: HookStyleLiteral
    hook_duration_sec: float
    hook_font: CaptionFontLiteral
    hook_size: int
    hook_color: str
    hook_bg_color: str
    hook_font_asset_id: str | None
    hook_animation: OverlayAnimationLiteral
    intro_transition: TransitionStyleLiteral
    outro_transition: TransitionStyleLiteral
    intro_transition_duration_sec: float
    outro_transition_duration_sec: float
    intro_transition_asset_id: str | None
    outro_transition_asset_id: str | None
    watermark_enabled: bool
    watermark_type: WatermarkTypeLiteral
    watermark_text: str
    watermark_image_id: str | None
    watermark_position: WatermarkPositionLiteral
    watermark_opacity: float
    watermark_size: int
    watermark_color: str
    watermark_font: CaptionFontLiteral
    watermark_font_asset_id: str | None
    progress_bar_enabled: bool
    progress_bar_position: ProgressBarPositionLiteral
    progress_bar_color: str
    progress_bar_height: int
    intro_asset_id: str | None
    outro_asset_id: str | None
    music_enabled: bool
    music_asset_id: str | None
    music_volume_db: float
    music_fade_in_sec: float
    music_fade_out_sec: float
    color_filter: ColorFilterPresetLiteral
    brightness: float
    contrast: float
    saturation: float
    lut_asset_id: str | None
    playback_speed: float


class ClipStyleConfigPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for style config."""

    caption_enabled: bool | None = None
    caption_style: CaptionStyleLiteral | None = None
    caption_font: CaptionFontLiteral | None = None
    caption_size: int | None = None
    caption_color: str | None = None
    caption_stroke_color: str | None = None
    caption_stroke_width: int | None = None
    caption_bg_color: str | None = None
    caption_position: CaptionPositionLiteral | None = None
    caption_animation: CaptionAnimationLiteral | None = None
    caption_language: str | None = None
    caption_translate_to: str | None = None
    caption_font_asset_id: str | None = None
    caption_highlight_color: str | None = None
    caption_uppercase: bool | None = None
    emoji_keyword_map: dict[str, str] | None = None
    hook_enabled: bool | None = None
    hook_style: HookStyleLiteral | None = None
    hook_duration_sec: float | None = None
    hook_font: CaptionFontLiteral | None = None
    hook_size: int | None = None
    hook_color: str | None = None
    hook_bg_color: str | None = None
    hook_font_asset_id: str | None = None
    hook_animation: OverlayAnimationLiteral | None = None
    intro_transition: TransitionStyleLiteral | None = None
    outro_transition: TransitionStyleLiteral | None = None
    intro_transition_duration_sec: float | None = None
    outro_transition_duration_sec: float | None = None
    intro_transition_asset_id: str | None = None
    outro_transition_asset_id: str | None = None
    watermark_enabled: bool | None = None
    watermark_type: WatermarkTypeLiteral | None = None
    watermark_text: str | None = None
    watermark_image_id: str | None = None
    watermark_position: WatermarkPositionLiteral | None = None
    watermark_opacity: float | None = None
    watermark_size: int | None = None
    watermark_color: str | None = None
    watermark_font: CaptionFontLiteral | None = None
    watermark_font_asset_id: str | None = None
    progress_bar_enabled: bool | None = None
    progress_bar_position: ProgressBarPositionLiteral | None = None
    progress_bar_color: str | None = None
    progress_bar_height: int | None = None
    intro_asset_id: str | None = None
    outro_asset_id: str | None = None
    music_enabled: bool | None = None
    music_asset_id: str | None = None
    music_volume_db: float | None = None
    music_fade_in_sec: float | None = None
    music_fade_out_sec: float | None = None
    color_filter: ColorFilterPresetLiteral | None = None
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    lut_asset_id: str | None = None
    playback_speed: float | None = None


class ClipTimedOverlayPayload(msgspec.Struct, frozen=True):
    """Timed overlay on a clip candidate."""

    id: str
    candidate_id: str
    overlay_type: OverlayTypeLiteral
    text: str
    image_asset_id: str | None
    video_asset_id: str | None
    shape: OverlayShapeLiteral
    start_sec: float
    end_sec: float
    x: int
    y: int
    font_size: int
    color: str
    opacity: float
    font: CaptionFontLiteral
    font_asset_id: str | None
    width: int | None
    animation: OverlayAnimationLiteral


class ClipTimedOverlayCreatePayload(msgspec.Struct, frozen=True):
    """Create a timed overlay."""

    overlay_type: OverlayTypeLiteral = 'TEXT'
    text: str = ''
    image_asset_id: str | None = None
    video_asset_id: str | None = None
    shape: OverlayShapeLiteral = 'RECTANGLE'
    start_sec: float = 0.0
    end_sec: float = 1.0
    x: int = 0
    y: int = 0
    font_size: int = 40
    color: str = '#FFFFFF'
    opacity: float = 1.0
    font: CaptionFontLiteral = 'MONTSERRAT_BOLD'
    font_asset_id: str | None = None
    width: int | None = None
    animation: OverlayAnimationLiteral = 'NONE'


class ClipTimedOverlayPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a timed overlay."""

    overlay_type: OverlayTypeLiteral | None = None
    text: str | None = None
    image_asset_id: str | None = None
    video_asset_id: str | None = None
    shape: OverlayShapeLiteral | None = None
    start_sec: float | None = None
    end_sec: float | None = None
    x: int | None = None
    y: int | None = None
    font_size: int | None = None
    color: str | None = None
    opacity: float | None = None
    font: CaptionFontLiteral | None = None
    font_asset_id: str | None = None
    width: int | None = None
    animation: OverlayAnimationLiteral | None = None


class ClipTimedSfxPayload(msgspec.Struct, frozen=True):
    """A one-shot sound effect on a clip candidate."""

    id: str
    candidate_id: str
    sfx_asset_id: str
    start_sec: float
    volume_db: float


class ClipTimedSfxCreatePayload(msgspec.Struct, frozen=True):
    """Create a timed SFX drop."""

    sfx_asset_id: str
    start_sec: float = 0.0
    volume_db: float = 0.0


class ClipTimedSfxPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a timed SFX drop."""

    sfx_asset_id: str | None = None
    start_sec: float | None = None
    volume_db: float | None = None


class ClipSfxListPayload(msgspec.Struct, frozen=True):
    """Paginated list of timed SFX drops."""

    items: list[ClipTimedSfxPayload]
    next_cursor: str | None
    total: int


class ClipPostPayload(msgspec.Struct, frozen=True):
    """Distribution post for a rendered clip."""

    id: str
    candidate_id: str
    platform: str
    caption: str
    title: str
    hashtags: list[str]
    scheduled_at: str | None
    posted_at: str | None
    status: str
    platform_post_id: str
    platform_url: str
    last_error: str
    views: int
    likes: int
    comments: int
    shares: int
    revenue_est_usd: str
    distribution_status: str


class ClipPostCreatePayload(msgspec.Struct, frozen=True):
    """Create a distribution post."""

    platform: str
    caption: str = ''
    title: str = ''
    hashtags: list[str] | None = None
    scheduled_at: str | None = None


class ClipPostPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a distribution post."""

    platform: str | None = None
    caption: str | None = None
    title: str | None = None
    hashtags: list[str] | None = None
    scheduled_at: str | None = None
    status: str | None = None


class ClipCampaignPayload(msgspec.Struct, frozen=True):
    """Read representation of a clip campaign."""

    id: str
    channel_id: str
    name: str
    status: str
    notes: str
    created_at: str


class ClipCampaignCreatePayload(msgspec.Struct, frozen=True):
    """Create a clip campaign."""

    channel_id: str
    name: str
    notes: str = ''


class ClipCampaignPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a clip campaign."""

    name: str | None = None
    status: str | None = None
    notes: str | None = None


class ClipCampaignListPayload(msgspec.Struct, frozen=True):
    """Paginated campaign list."""

    items: list[ClipCampaignPayload]
    next_cursor: str | None
    total: int


class EarningPayload(msgspec.Struct, frozen=True):
    """Read representation of one earning row."""

    id: str
    campaign_id: str
    candidate_id: str | None
    platform: str
    revenue_est_usd: str
    recorded_at: str
    notes: str


class EarningCreatePayload(msgspec.Struct, frozen=True):
    """Create a manual earning entry."""

    campaign_id: str
    platform: str
    revenue_est_usd: str
    recorded_at: str
    candidate_id: str | None = None
    notes: str = ''


class EarningListPayload(msgspec.Struct, frozen=True):
    """List of earning rows."""

    items: list[EarningPayload]
    total: int


class ClipSourcePayload(msgspec.Struct, frozen=True):
    """Read representation of a clip source."""

    id: str
    channel_id: str
    run_id: str | None
    title: str
    status: str
    duration_sec: float | None
    candidate_count: int
    campaign_id: str | None
    source_type: str
    url: str
    library_asset_id: str | None = None
    error_message: str | None = None


class ClipSourceCreatePayload(msgspec.Struct, frozen=True):
    """Register a new clip source for probing."""

    channel_id: str
    source_type: str
    url: str = ''
    library_asset_id: str | None = None
    campaign_id: str | None = None
    auto_start: bool = False
    clip_options: ClipRunOptionsPayload | None = None


class ClipSourceListPayload(msgspec.Struct, frozen=True):
    """Paginated clip source list."""

    items: list[ClipSourcePayload]
    next_cursor: str | None
    total: int


class ClipBrandTemplatePayload(msgspec.Struct, frozen=True):
    """Read representation of a reusable clip brand template."""

    id: str
    channel_id: str
    name: str
    archived: bool
    render_format: str
    render_mode: str
    fit_mode: str
    foreground_treatment: str
    background_mode: str
    background_color: str
    blur_strength: int
    caption_preset_key: str
    logo_asset_id: str | None
    logo_position: str
    logo_opacity: float
    intro_asset_id: str | None
    outro_asset_id: str | None
    music_asset_id: str | None
    music_volume_db: float
    keyword_highlighter: bool
    auto_transitions: bool
    notes: str
    created_at: str


class ClipBrandTemplateCreatePayload(msgspec.Struct, frozen=True):
    """Create a brand template."""

    channel_id: str
    name: str
    render_format: str = 'VERTICAL_9_16'
    render_mode: str = 'SMART_CROP'
    fit_mode: str = 'CROP'
    foreground_treatment: str = 'FILL'
    background_mode: str = 'SOLID'
    background_color: str = '#000000'
    blur_strength: int = 20
    caption_preset_key: str = 'chunk_three'
    logo_asset_id: str | None = None
    logo_position: str = 'BOTTOM_RIGHT'
    logo_opacity: float = 0.85
    intro_asset_id: str | None = None
    outro_asset_id: str | None = None
    music_asset_id: str | None = None
    music_volume_db: float = -20.0
    keyword_highlighter: bool = True
    auto_transitions: bool = False
    notes: str = ''


class ClipBrandTemplatePatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a brand template."""

    name: str | None = None
    archived: bool | None = None
    render_format: str | None = None
    render_mode: str | None = None
    fit_mode: str | None = None
    foreground_treatment: str | None = None
    background_mode: str | None = None
    background_color: str | None = None
    blur_strength: int | None = None
    caption_preset_key: str | None = None
    logo_asset_id: str | None = None
    logo_position: str | None = None
    logo_opacity: float | None = None
    intro_asset_id: str | None = None
    outro_asset_id: str | None = None
    music_asset_id: str | None = None
    music_volume_db: float | None = None
    keyword_highlighter: bool | None = None
    auto_transitions: bool | None = None
    notes: str | None = None


class ClipBrandTemplateListPayload(msgspec.Struct, frozen=True):
    """Paginated brand template list."""

    items: list[ClipBrandTemplatePayload]
    next_cursor: str | None
    total: int
