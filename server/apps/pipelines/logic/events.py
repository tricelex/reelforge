"""Domain events for pipeline runs."""

import attrs


@attrs.define(frozen=True)
class PipelineRunCreated:
    """Emitted when a new pipeline run is created."""

    run_id: str
    channel_id: str
