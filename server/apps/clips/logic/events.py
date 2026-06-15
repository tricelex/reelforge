import attrs


@attrs.define(frozen=True)
class ClipCandidatesCreated:
    """Emitted after clip_analyze stage creates candidates."""

    run_id: str
    candidate_count: int
