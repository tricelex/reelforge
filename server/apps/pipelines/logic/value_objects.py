"""API DTOs for pipeline run operations."""

from typing import Any

import msgspec


class StageErrorPayload(msgspec.Struct, frozen=True):
    """Failure details for a stage execution attempt."""

    type: str
    message: str
    retryable: bool


class StageSummaryPayload(msgspec.Struct, frozen=True):
    """Summary of one stage execution attempt."""

    stage_key: str
    status: str
    attempt: int
    cost_usd: str
    started_at: str | None
    finished_at: str | None
    error: StageErrorPayload | None = None


class RunSummaryPayload(msgspec.Struct, frozen=True):
    """Lightweight run row for list views."""

    id: str
    channel_id: str
    channel_name: str
    topic: str
    status: str
    is_paused: bool
    total_cost_usd: str
    created_at: str
    started_at: str | None
    finished_at: str | None


class RunDetailPayload(msgspec.Struct, frozen=True):
    """Full run detail including stage tree."""

    id: str
    channel_id: str
    channel_name: str
    blueprint_name: str
    topic: str
    status: str
    is_paused: bool
    total_cost_usd: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    stages: list[StageSummaryPayload]
    blueprint_snapshot: dict[str, Any] = {}
    source_idea_id: str | None = None
    source_id: str | None = None
    watch_url: str | None = None
    external_video_id: str | None = None


class ClipRunOptionsPayload(msgspec.Struct, frozen=True):
    """Pre-run discovery controls for a clipping pipeline run."""

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


class RunCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a new pipeline run."""

    channel_id: str
    topic: str = ''
    blueprint_name: str | None = None
    source_idea_id: str | None = None
    source_id: str | None = None
    clip_options: ClipRunOptionsPayload | None = None
    auto_approve: bool = False


class RunListPayload(msgspec.Struct, frozen=True):
    """Cursor-paginated run list."""

    items: list[RunSummaryPayload]
    next_cursor: str | None
    total: int


class RerunStagePayload(msgspec.Struct, frozen=True):
    """Input for rerunning a stage."""

    shard_indices: list[int] | None = None


class SseTokenPayload(msgspec.Struct, frozen=True):
    """Short-lived token for subscribing to run SSE events."""

    token: str
    expires_at: str


class GateApprovePayload(msgspec.Struct, frozen=True):
    """Gate approval body — fields vary by gate type."""

    approved_candidate_ids: list[str] | None = None
    thumbnail_asset_id: str | None = None
    schedule_at: str | None = None


class GateApproveResultPayload(msgspec.Struct, frozen=True):
    """Result of approving a pipeline gate."""

    status: str
    approved_count: int | None = None


class TranscriptWordPayload(msgspec.Struct, frozen=True):
    """One word in a clip transcript."""

    word: str
    start: float
    end: float
    speaker_id: str


class TranscriptChapterPayload(msgspec.Struct, frozen=True):
    """Scene-cut chapter marker in seconds."""

    start_sec: float


class TranscriptPayload(msgspec.Struct, frozen=True):
    """Transcript data from clip_transcribe stage output."""

    asset_id: str | None
    source_asset_url: str | None
    words: list[TranscriptWordPayload]
    chapters: list[TranscriptChapterPayload]


class RunAssetPayload(msgspec.Struct, frozen=True):
    """Presigned run-owned asset."""

    id: str
    kind: str
    mime: str
    url: str
    stage_key: str | None = None
    label: str | None = None


class RunAssetListPayload(msgspec.Struct, frozen=True):
    """Paginated run asset list."""

    items: list[RunAssetPayload]
    next_cursor: str | None
    total: int


class StageOutputPayload(msgspec.Struct, frozen=True):
    """Rendered output of a single pipeline stage for the frontend."""

    stage_key: str
    status: str
    kind: str
    summary: str | None
    text: str | None
    data: dict[str, Any] | None
    assets: list[RunAssetPayload]


class BlueprintSummaryPayload(msgspec.Struct, frozen=True):
    """Active pipeline blueprint summary."""

    id: str
    name: str
    kind: str
    version: int
    is_active: bool


class BlueprintListPayload(msgspec.Struct, frozen=True):
    """List of pipeline blueprints."""

    items: list[BlueprintSummaryPayload]
    next_cursor: str | None
    total: int


class RunActionResultPayload(msgspec.Struct, frozen=True):
    """Generic result for cancel/pause/resume actions."""

    status: str


class RunCastPayload(msgspec.Struct, frozen=True):
    """Character cast assignment on a run."""

    id: str
    run_id: str
    character_id: str
    character_name: str
    role: str
    is_ephemeral: bool
    design_status: str
    hero_ref_asset_id: str | None
    importance: str = 'SECONDARY'
    draft_prompt: str = ''


class RunCastListPayload(msgspec.Struct, frozen=True):
    """Cast list for a run."""

    items: list[RunCastPayload]
    total: int


class RunCastPatchPayload(msgspec.Struct, frozen=True):
    """Partial cast update."""

    role: str | None = None
    design_status: str | None = None


class RunCastApprovePayload(msgspec.Struct, frozen=True):
    """Approve cast member design."""

    winning_asset_id: str | None = None


class StoryboardRunSummaryPayload(msgspec.Struct, frozen=True):
    """Run summary embedded in storyboard response."""

    id: str
    status: str
    gate: str | None
    spent_usd: str
    projected_next_usd: str
    budget_usd: str | None


class StoryboardSceneImagePayload(msgspec.Struct, frozen=True):
    """Image asset for one storyboard scene."""

    asset_id: str
    url: str
    seed: int | None


class StoryboardScenePayload(msgspec.Struct, frozen=True):
    """One scene row in the storyboard grid."""

    idx: int
    chapter: int
    beat: str
    narration: str
    visual_prompt: str
    visual_prompt_version: int
    image: StoryboardSceneImagePayload | None
    status: str
    is_hero: bool
    cast: list[str]
    est_seconds: float
    attempts: int
    cost_usd: str


class StoryboardPayload(msgspec.Struct, frozen=True):
    """Storyboard grid per spec §13.2."""

    run: StoryboardRunSummaryPayload
    scenes: list[StoryboardScenePayload]


class SceneBreakdownPayload(msgspec.Struct, frozen=True):
    """Raw scene breakdown output."""

    scenes: list[StoryboardScenePayload]
    total: int


class ScenePatchPayload(msgspec.Struct, frozen=True):
    """Partial update for one scene."""

    narration_text: str | None = None
    visual_concept: str | None = None
    visual_prompt: str | None = None
    is_hero: bool | None = None
    foreground_cast: list[str] | None = None


class PreviewPayload(msgspec.Struct, frozen=True):
    """Presigned URL for latest assembly preview."""

    asset_id: str | None
    url: str | None
    duration_s: float | None


class PublishPayload(msgspec.Struct, frozen=True):
    """Manual publish / final gate approval."""

    thumbnail_asset_id: str | None = None
    schedule_at: str | None = None
    gate_key: str | None = None
    metadata_patch: dict[str, str | list[str]] | None = None


class PublishResultPayload(msgspec.Struct, frozen=True):
    """Result of initiating publish."""

    status: str
    gate_key: str
    publish_job_id: str | None = None


class PublishMetadataPayload(msgspec.Struct, frozen=True):
    """YouTube publish metadata for final review."""

    title: str
    description: str
    tags: list[str]
    category: str
    thumbnail_asset_id: str | None


class PublishMetadataPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for publish metadata."""

    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    category: str | None = None
    thumbnail_asset_id: str | None = None


class GateWaitingPayload(msgspec.Struct, frozen=True):
    """One run waiting at a review gate."""

    run_id: str
    gate_key: str
    channel_name: str
    topic: str
    spent_usd: str


class GateWaitingListPayload(msgspec.Struct, frozen=True):
    """All runs waiting at armed gates."""

    items: list[GateWaitingPayload]
    total: int


class GateCatalogEntryPayload(msgspec.Struct, frozen=True):
    """One known pipeline gate key."""

    key: str
    label: str
    description: str


class GateCatalogPayload(msgspec.Struct, frozen=True):
    """Catalog of gate keys for channel configuration."""

    items: list[GateCatalogEntryPayload]


class FootageCandidatePayload(msgspec.Struct, frozen=True):
    """One alternate footage option offered at the review gate."""

    external_id: str
    provider: str
    thumb_url: str
    preview_url: str
    width: int
    height: int
    duration_s: float | None
    license: str
    author: str
    source_url: str


class FootageSceneRow(msgspec.Struct, frozen=True):
    """One scene row in the documentary storyboard."""

    idx: int
    narration_text: str
    visual_concept: str
    status: str
    est_seconds: float
    asset_url: str | None
    media_type: str
    source: str
    license: str
    license_url: str
    attribution_required: bool
    author: str
    source_url: str
    rerank_score: float | None
    candidates: list[FootageCandidatePayload]


class FootageStoryboardPayload(msgspec.Struct, frozen=True):
    """Documentary storyboard review payload."""

    profile: str
    run: StoryboardRunSummaryPayload
    scenes: list[FootageSceneRow]
    ai_fallback_count: int
