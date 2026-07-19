"""Read-only latency probes for remote dependencies.

Run from the production app VPS (not a laptop) so results reflect the
real Contabo-to-Contabo path rather than a WAN hop from a developer machine.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from django.core.cache import cache
from django.db import connection


@dataclass(frozen=True, slots=True)
class LatencyStats:
    """Aggregated round-trip timings in milliseconds."""

    min_ms: float
    avg_ms: float
    max_ms: float


def summarize(samples_ms: list[float]) -> LatencyStats:
    """Return min/avg/max for a list of millisecond samples."""
    if not samples_ms:
        return LatencyStats(min_ms=0.0, avg_ms=0.0, max_ms=0.0)
    return LatencyStats(
        min_ms=min(samples_ms),
        avg_ms=sum(samples_ms) / len(samples_ms),
        max_ms=max(samples_ms),
    )


def _time_samples(
    operation: Callable[[], None],
    *,
    samples: int,
) -> LatencyStats:
    if samples <= 0:
        raise ValueError('samples must be positive')
    operation()  # warm-up
    measured: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        operation()
        measured.append((time.perf_counter() - started) * 1000.0)
    return summarize(measured)


def measure_db_latency(*, samples: int = 10) -> LatencyStats:
    """Time a warm ``SELECT 1`` against the configured database."""

    def _query() -> None:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()

    return _time_samples(_query, samples=samples)


def measure_db_cold_latency(*, samples: int = 5) -> LatencyStats:
    """Close the connection before each sample to include reconnect cost."""

    def _cold_query() -> None:
        connection.close()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()

    return _time_samples(_cold_query, samples=samples)


def measure_redis_latency(*, samples: int = 10) -> LatencyStats:
    """Time a cache ``set`` + ``get`` round trip."""

    def _round_trip() -> None:
        cache.set('dep_bench_probe', '1', timeout=10)
        cache.get('dep_bench_probe')

    return _time_samples(_round_trip, samples=samples)
