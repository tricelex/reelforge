"""API DTOs for pipeline run operations."""

import msgspec


class StageSummaryPayload(msgspec.Struct, frozen=True):
    """Summary of one stage execution attempt."""

    stage_key: str
    status: str
    attempt: int
    cost_usd: str
    started_at: str | None
    finished_at: str | None


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
    source_idea_id: str | None = None


class RunCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a new pipeline run."""

    channel_id: str
    topic: str
    blueprint_name: str | None = None
    source_idea_id: str | None = None


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


class RunAssetListPayload(msgspec.Struct, frozen=True):
    """Paginated run asset list."""

    items: list[RunAssetPayload]
    next_cursor: str | None
    total: int


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
