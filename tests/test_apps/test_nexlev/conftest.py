"""Shared fixtures for NexLev tests.

Async NexLevService methods run their ORM work via `sync_to_async`, which
(with the default thread-sensitive executor) executes on a single shared
worker thread with its own DB connection — separate from the main test
thread's connection. That connection is never closed by pytest-django's
normal per-test teardown, which can leave it open into session teardown
and block dropping the test database. `DjangoDbMiddleware`
(server/common/taskiq_middleware.py) solves this for real TaskIQ task
runs; tests that call async service/task code directly need the same
close, run on that same worker thread via `sync_to_async`.
"""

import asyncio
from collections.abc import Iterator

import pytest
from asgiref.sync import sync_to_async
from django.db import close_old_connections

_close_old_connections = sync_to_async(close_old_connections)


@pytest.fixture(autouse=True)
def _close_sync_to_async_db_connections() -> Iterator[None]:
    yield
    asyncio.run(_close_old_connections())
