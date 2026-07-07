"""Tests for cross-run script similarity math."""

from server.apps.pipelines.logic.similarity import (
    cosine_similarity,
    is_too_similar,
    max_similarity,
)


def test_cosine_similarity_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_mismatched_length_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0


def test_cosine_similarity_zero_vector_is_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_max_similarity_empty_recent_is_zero() -> None:
    assert max_similarity([1.0, 0.0], []) == 0.0


def test_max_similarity_returns_highest() -> None:
    result = max_similarity([1.0, 0.0], [[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]])
    assert result == 1.0


def test_is_too_similar_true_above_threshold() -> None:
    assert is_too_similar([1.0, 0.0], [[1.0, 0.0001]]) is True


def test_is_too_similar_false_below_threshold() -> None:
    assert is_too_similar([1.0, 0.0], [[0.0, 1.0]]) is False
