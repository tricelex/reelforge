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


class RunCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a new pipeline run."""

    channel_id: str
    topic: str
    blueprint_name: str | None = None


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


class RunActionResultPayload(msgspec.Struct, frozen=True):
    """Generic result for cancel/pause/resume actions."""

    status: str
