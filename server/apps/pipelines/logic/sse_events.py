"""Discriminated union of pipeline run SSE event payloads."""

import msgspec


class RunAdvancedEvent(
    msgspec.Struct,
    frozen=True,
    tag='run.advanced',
    tag_field='type',
):
    """Published when the orchestrator advances the DAG."""

    states: dict[str, str | None]


class RunCancelledEvent(
    msgspec.Struct,
    frozen=True,
    tag='run.cancelled',
    tag_field='type',
):
    """Published when a run is cancelled."""


class RunPausedEvent(
    msgspec.Struct,
    frozen=True,
    tag='run.paused',
    tag_field='type',
):
    """Published when a run is paused."""


class StageRerunEvent(
    msgspec.Struct,
    frozen=True,
    tag='stage.rerun',
    tag_field='type',
):
    """Published when a stage rerun is queued."""

    stage_key: str


class RunEventsQuery(msgspec.Struct, frozen=True):
    """Query parameters for subscribing to pipeline run events."""

    token: str


PipelineRunEvent = (
    RunAdvancedEvent
    | RunCancelledEvent
    | RunPausedEvent
    | StageRerunEvent
)
