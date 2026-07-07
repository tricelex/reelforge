"""Pure cosine-similarity math for cross-run script duplication detection."""

import math

_SIMILARITY_THRESHOLD = 0.92


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 for empty/mismatched/zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def max_similarity(
    new_vec: list[float],
    recent_vecs: list[list[float]],
) -> float:
    """Highest cosine similarity between new_vec and any recent vector."""
    if not recent_vecs:
        return 0.0
    return max(cosine_similarity(new_vec, v) for v in recent_vecs)


def is_too_similar(
    new_vec: list[float],
    recent_vecs: list[list[float]],
) -> bool:
    """True when new_vec is a near-duplicate of any recent script embedding."""
    return max_similarity(new_vec, recent_vecs) >= _SIMILARITY_THRESHOLD
