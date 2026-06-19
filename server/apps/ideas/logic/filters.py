"""Deterministic post-processing for ideation agent output."""

from server.apps.ideas.logic.schemas import TopicCandidate


def touches_banned(text: str, banned_topics: list[str]) -> bool:
    """Return True when text contains a banned topic substring."""
    lowered = text.lower()
    return any(
        term.lower() in lowered for term in banned_topics if term.strip()
    )


def filter_ideation_candidates(
    candidates: list[TopicCandidate],
    *,
    count: int,
    existing: set[str],
    banned_topics: list[str],
) -> list[TopicCandidate]:
    """Dedupe, enforce banned topics, and return top-scored ideas."""
    accepted: list[TopicCandidate] = []
    seen = set(existing)
    ranked = sorted(candidates, key=lambda row: row.score, reverse=True)
    for candidate in ranked:
        if len(accepted) >= count:
            break
        topic_key = candidate.topic.lower().strip()
        if not topic_key or topic_key in seen:
            continue
        if touches_banned(candidate.topic, banned_topics):
            continue
        if touches_banned(candidate.title, banned_topics):
            continue
        seen.add(topic_key)
        accepted.append(candidate)
    return accepted
