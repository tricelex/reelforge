"""Pure ranking helpers for footage candidates.

Metadata scoring is a cheap term-overlap heuristic used when vision
re-ranking is disabled or has failed. It is deliberately simple — the vision
model is the quality path; this only has to beat provider default ordering.

>>> round(metadata_score_terms({'ocean', 'waves'}, {'ocean'}, set()), 2)
0.5
"""

from collections.abc import Sequence

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.pipelines.schemas import CandidateRanking

_NEGATIVE_PENALTY = 0.5


def _terms(text: str) -> set[str]:
    """Split text into a lowercase term set."""
    return {t for t in text.casefold().replace(',', ' ').split() if t}


def metadata_score_terms(
    concept_terms: set[str],
    candidate_terms: set[str],
    negative_terms: set[str],
) -> float:
    """Return an overlap score in 0..1, penalised for negative terms."""
    if not concept_terms:
        return 0.0
    overlap = len(concept_terms & candidate_terms) / len(concept_terms)
    if negative_terms & candidate_terms:
        overlap -= _NEGATIVE_PENALTY
    return max(0.0, min(1.0, overlap))


def metadata_score(
    candidate: FootageCandidate,
    *,
    visual_concept: str,
    negative_terms: Sequence[str],
) -> float:
    """Score one candidate on title/tag overlap with the scene concept."""
    candidate_terms = _terms(candidate.title) | {
        t.casefold() for t in candidate.tags
    }
    return metadata_score_terms(
        _terms(visual_concept),
        candidate_terms,
        {t.casefold() for t in negative_terms},
    )


def rank_by_metadata(
    candidates: Sequence[FootageCandidate],
    *,
    visual_concept: str,
    negative_terms: Sequence[str],
) -> list[FootageCandidate]:
    """Return candidates ordered by descending metadata score (stable)."""
    return sorted(
        candidates,
        key=lambda c: (
            -metadata_score(
                c,
                visual_concept=visual_concept,
                negative_terms=negative_terms,
            )
        ),
    )


def apply_vision_rankings(
    candidates: Sequence[FootageCandidate],
    rankings: Sequence[CandidateRanking],
) -> list[FootageCandidate]:
    """Reorder candidates by vision score; unscored ones sort last.

    Rankings naming an unknown ``external_id`` are ignored, so a model
    hallucination cannot introduce a candidate that was never fetched.
    """
    scores = {r.external_id: r.score for r in rankings}
    return sorted(
        candidates,
        key=lambda c: -scores.get(c.external_id, -1.0),
    )
