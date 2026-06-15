"""Value objects (DTOs) for the clips domain."""

import msgspec


class ClipCandidatePayload(msgspec.Struct, frozen=True):
    """Read-only representation of a ClipCandidate."""

    id: str
    run_id: str
    title: str
    hook_text: str
    start_sec: float
    end_sec: float
    duration_sec: float
    relevance_score: float
    status: str
    reason: str
    transcript_excerpt: str
    rejection_reason: str


class ClipCandidateListPayload(msgspec.Struct, frozen=True):
    """Paginated list of clip candidates."""

    candidates: list[ClipCandidatePayload]
    total: int


class ApproveGatePayload(msgspec.Struct, frozen=True):
    """Input payload for gate approval API."""

    approved_candidate_ids: list[str]
