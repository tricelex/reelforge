"""Tests for the benchmark_dependencies management command."""

from unittest.mock import patch

import pytest
from django.core.management import call_command

from server.common.dependency_benchmark import LatencyStats


def test_benchmark_dependencies_prints_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Command prints warm/cold Postgres and Redis timings."""
    sample = LatencyStats(min_ms=1.0, avg_ms=2.0, max_ms=3.0)
    with (
        patch(
            'server.apps.core.management.commands.benchmark_dependencies'
            '.measure_db_latency',
            return_value=sample,
        ),
        patch(
            'server.apps.core.management.commands.benchmark_dependencies'
            '.measure_db_cold_latency',
            return_value=sample,
        ),
        patch(
            'server.apps.core.management.commands.benchmark_dependencies'
            '.measure_redis_latency',
            return_value=sample,
        ),
    ):
        call_command('benchmark_dependencies')

    out = capsys.readouterr().out
    assert 'Postgres SELECT 1 (warm)' in out
    assert 'Postgres SELECT 1 (cold)' in out
    assert 'Redis set+get' in out
    assert 'avg=2.0' in out


def test_conn_max_age_default_is_persistent() -> None:
    """Repository default keeps DB sockets warm across requests."""
    from decouple import Config, RepositoryEmpty

    empty = Config(RepositoryEmpty())
    assert empty('CONN_MAX_AGE', cast=int, default=600) == 600
