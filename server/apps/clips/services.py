"""ClipCandidateService — all read/write operations on ClipCandidate."""

import uuid
from typing import TYPE_CHECKING, final

import attrs

from server.apps.clips.logic.constants import CandidateStatus
from server.apps.clips.logic.value_objects import ClipCandidatePayload

if TYPE_CHECKING:
    from server.apps.clips.models import ClipCandidate


def _to_payload(candidate: 'ClipCandidate') -> ClipCandidatePayload:
    return ClipCandidatePayload(
        id=str(candidate.id),
        run_id=str(candidate.run_id),
        title=candidate.title,
        hook_text=candidate.hook_text,
        start_sec=candidate.start_sec,
        end_sec=candidate.end_sec,
        duration_sec=candidate.duration_sec,
        relevance_score=candidate.relevance_score,
        status=candidate.status,
        reason=candidate.reason,
        transcript_excerpt=candidate.transcript_excerpt,
        rejection_reason=candidate.rejection_reason,
    )


@final
@attrs.define(slots=True, frozen=True)
class ClipCandidateService:
    """Reads and writes ClipCandidate records."""

    def list_for_run(self, run_id: str) -> list[ClipCandidatePayload]:
        """Return all candidates for a run, ordered by relevance."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        return [
            _to_payload(c)
            for c in ClipCandidate.objects.filter(
                run_id=uuid.UUID(run_id),
            ).order_by('-relevance_score')
        ]

    def approved_for_run(self, run_id: str) -> list[ClipCandidatePayload]:
        """Return only approved candidates for a run."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        return [
            _to_payload(c)
            for c in ClipCandidate.objects.filter(
                run_id=uuid.UUID(run_id),
                status=CandidateStatus.APPROVED,
            ).order_by('-relevance_score')
        ]

    def get_by_id(self, candidate_id: str) -> ClipCandidatePayload:
        """Return a single candidate by ID."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        return _to_payload(ClipCandidate.objects.get(id=candidate_id))

    def approve(self, candidate_id: str) -> ClipCandidatePayload:
        """Mark a candidate as APPROVED."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.get(id=candidate_id)
        candidate.status = CandidateStatus.APPROVED
        candidate.save(update_fields=['status'])
        return _to_payload(candidate)

    def reject(
        self, candidate_id: str, reason: str = '',
    ) -> ClipCandidatePayload:
        """Mark a candidate as REJECTED with an optional reason."""
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

        candidate = ClipCandidate.objects.get(id=candidate_id)
        candidate.status = CandidateStatus.REJECTED
        candidate.rejection_reason = reason
        candidate.save(update_fields=['status', 'rejection_reason'])
        return _to_payload(candidate)
