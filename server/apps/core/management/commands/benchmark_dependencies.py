"""Measure latency from this host to Postgres, Redis, and related deps."""

from typing import override

from django.core.management.base import BaseCommand

from server.common.dependency_benchmark import (
    LatencyStats,
    measure_db_cold_latency,
    measure_db_latency,
    measure_redis_latency,
)


class Command(BaseCommand):
    """Print dependency round-trip timings for capacity planning."""

    help = (
        'Measure Postgres/Redis latency from the current host. '
        'Run on the production app VPS for accurate Contabo-to-Contabo numbers.'
    )

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Probe dependencies and write a human-readable report."""
        db_warm = measure_db_latency(samples=10)
        db_cold = measure_db_cold_latency(samples=5)
        redis_rt = measure_redis_latency(samples=10)

        self.stdout.write('Dependency latency (ms) from this host:')
        self._write_row('Postgres SELECT 1 (warm)', db_warm)
        self._write_row('Postgres SELECT 1 (cold)', db_cold)
        self._write_row('Redis set+get', redis_rt)
        self.stdout.write(
            self.style.NOTICE(
                'Compare warm vs cold: a large gap means CONN_MAX_AGE is too '
                'low or connections are being closed every request.',
            ),
        )

    def _write_row(self, label: str, stats: LatencyStats) -> None:
        self.stdout.write(
            f'  {label}: '
            f'min={stats.min_ms:.1f} avg={stats.avg_ms:.1f} '
            f'max={stats.max_ms:.1f}',
        )
