"""Tests for dependency latency measurement helpers."""

from unittest.mock import MagicMock, patch

from server.common.dependency_benchmark import (
    LatencyStats,
    measure_db_latency,
    measure_redis_latency,
    summarize,
)


def test_summarize_returns_min_avg_max() -> None:
    stats = summarize([10.0, 20.0, 30.0])
    assert stats == LatencyStats(min_ms=10.0, avg_ms=20.0, max_ms=30.0)


def test_summarize_empty_returns_zeros() -> None:
    assert summarize([]) == LatencyStats(min_ms=0.0, avg_ms=0.0, max_ms=0.0)


def test_measure_db_latency_runs_warm_samples() -> None:
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    connection = MagicMock()
    connection.cursor.return_value = cursor

    with patch(
        'server.common.dependency_benchmark.connection',
        connection,
    ):
        stats = measure_db_latency(samples=3)

    assert cursor.execute.call_count >= 4  # warm-up + 3
    assert stats.min_ms >= 0.0
    assert stats.avg_ms >= 0.0
    assert stats.max_ms >= 0.0


def test_measure_redis_latency_set_and_get() -> None:
    cache = MagicMock()
    with patch(
        'server.common.dependency_benchmark.cache',
        cache,
    ):
        stats = measure_redis_latency(samples=2)

    assert cache.set.call_count >= 3  # warm-up + 2
    assert cache.get.call_count >= 3
    assert stats.avg_ms >= 0.0


def test_measure_db_cold_latency_closes_connection() -> None:
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    connection = MagicMock()
    connection.cursor.return_value = cursor

    with patch(
        'server.common.dependency_benchmark.connection',
        connection,
    ):
        from server.common.dependency_benchmark import measure_db_cold_latency

        stats = measure_db_cold_latency(samples=2)

    assert connection.close.call_count >= 3  # warm-up + 2
    assert stats.avg_ms >= 0.0


def test_time_samples_rejects_non_positive() -> None:
    import pytest

    from server.common.dependency_benchmark import _time_samples

    with pytest.raises(ValueError, match='samples'):
        _time_samples(lambda: None, samples=0)
