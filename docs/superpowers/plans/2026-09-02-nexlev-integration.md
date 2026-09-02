# NexLev Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the paid DataForSEO YouTube-data tools in the channel-research
agent with a new NexLev integration (disabled-not-deleted DataForSEO), backed
by persistent per-channel/per-video records that drastically cut NexLev quota
spend, plus an operator-triggered "Deep Analysis" action that feeds
suggested topics into channel setup.

**Architecture:** A new `server/apps/nexlev` app owns an `httpx`-based NexLev
client, msgspec DTOs, and a `NexLevService` that reads/writes persistent
`NexLevChannelRecord` / `NexLevVideoRecord` rows (per-section staleness, not
a blanket TTL) plus a short-TTL `NexLevSearchCacheEntry` for live search.
`server/apps/channel_research/agent.py` gates DataForSEO behind a settings
flag (default off) and registers NexLev-backed tools instead. A new
"Deep Analysis" flow (service method + TaskIQ task + two DMR endpoints)
creates/polls NexLev's async channel-analysis job and lets an operator merge
`suggested_topics` into the job's `channel_spec.seed_ideas` before import.

**Tech Stack:** Django 6.0, `httpx` (async), `msgspec`, `attrs`, `punq` DI,
pydantic-ai, TaskIQ, `pytest` + `pytest-django`.

**Spec:** `docs/superpowers/specs/2026-09-02-nexlev-integration-design.md`

## Global Constraints

- Never add `from __future__ import annotations` to `server/apps/nexlev/services.py`
  or `server/apps/channel_research/services.py` — both are punq-registered.
- `ruff` single quotes, 80-char lines. `mypy server` runs in strict mode —
  every public function needs type annotations.
- 100% test coverage required (`pytest` with `--cov-fail-under=100` from
  `pyproject.toml`); run `pytest --no-cov` while iterating, full `pytest`
  before the final task.
- Migrations must be zero-downtime (new tables/fields only in this plan —
  no column alterations on existing tables besides additive
  `ChannelResearchJob` fields with defaults).
- Every cross-app import needs an explicit `ignore_imports` entry in
  `.importlinter` (see Task 7 and Task 8) — `lint-imports` fails hard
  otherwise.
- All commands run via `docker compose exec web <cmd>` per this repo's
  CLAUDE.md, except `manage.py` commands which use `just run <cmd>`.

---

## Task 1: NexLev app scaffold, models, and staleness helper

**Files:**
- Create: `server/apps/nexlev/__init__.py` (empty)
- Create: `server/apps/nexlev/apps.py`
- Create: `server/apps/nexlev/models.py`
- Create: `server/apps/nexlev/logic/__init__.py` (empty)
- Create: `server/apps/nexlev/logic/constants.py`
- Create: `server/apps/nexlev/logic/staleness.py`
- Create: `server/apps/nexlev/migrations/__init__.py` (empty)
- Modify: `server/settings/components/common.py:44-54` (INSTALLED_APPS),
  `server/settings/components/common.py:577-598` (settings)
- Test: `tests/test_apps/test_nexlev/__init__.py` (empty)
- Test: `tests/test_apps/test_nexlev/test_models.py`
- Test: `tests/test_apps/test_nexlev/test_staleness.py`

**Interfaces:**
- Produces: `server.apps.nexlev.models.NexLevChannelRecord` (fields:
  `channel_id`, `about`, `about_fetched_at`, `outliers`,
  `outliers_fetched_at`, `analytics`, `analytics_fetched_at`,
  `similar_channels`, `similar_channels_fetched_at`, `niche_overview`,
  `niche_overview_fetched_at`, `channel_analysis`,
  `channel_analysis_fetched_at`, `quota_spent`, `created_at`, `updated_at`).
- Produces: `server.apps.nexlev.models.NexLevVideoRecord` (fields:
  `video_id`, `details`, `details_fetched_at`, `transcript`,
  `transcript_fetched_at`, `comments`, `comments_fetched_at`,
  `quota_spent`, `created_at`, `updated_at`).
- Produces: `server.apps.nexlev.models.NexLevSearchCacheEntry` (fields:
  `cache_key`, `payload`, `fetched_at`, `quota_spent`).
- Produces: `server.apps.nexlev.logic.staleness.is_stale(fetched_at:
  datetime | None, *, window: timedelta) -> bool`.
- Produces: settings `NEXLEV_API_KEY: str`, `NEXLEV_BASE_URL: str`,
  `NEXLEV_ENABLED: bool`, `DATAFORSEO_ENABLED: bool`.

- [ ] **Step 1: Write the failing staleness test**

```python
# tests/test_apps/test_nexlev/test_staleness.py
"""Tests for the NexLev section staleness helper."""

from datetime import timedelta

from django.utils import timezone

from server.apps.nexlev.logic.staleness import is_stale


def test_is_stale_when_never_fetched() -> None:
    assert is_stale(None, window=timedelta(days=7)) is True


def test_is_stale_when_older_than_window() -> None:
    fetched_at = timezone.now() - timedelta(days=8)
    assert is_stale(fetched_at, window=timedelta(days=7)) is True


def test_is_stale_when_within_window() -> None:
    fetched_at = timezone.now() - timedelta(days=1)
    assert is_stale(fetched_at, window=timedelta(days=7)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_staleness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.apps.nexlev'`

- [ ] **Step 3: Create the app package and staleness helper**

```python
# server/apps/nexlev/apps.py
"""App config for the NexLev integration app."""

from django.apps import AppConfig


class NexlevConfig(AppConfig):
    """Owns NexLev's HTTP client, persisted records, and cache."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.nexlev'
    verbose_name = 'NexLev'
```

```python
# server/apps/nexlev/logic/constants.py
"""Quota costs and per-section staleness windows for NexLev data."""

from datetime import timedelta

ABOUT_STALE_AFTER = timedelta(days=14)
OUTLIERS_STALE_AFTER = timedelta(days=7)
ANALYTICS_STALE_AFTER = timedelta(days=30)
SIMILAR_CHANNELS_STALE_AFTER = timedelta(days=45)
NICHE_OVERVIEW_STALE_AFTER = timedelta(days=45)
VIDEO_STALE_AFTER = timedelta(days=90)
SEARCH_CACHE_TTL = timedelta(hours=24)

QUOTA_COST_ABOUT = 1
QUOTA_COST_OUTLIERS = 1
QUOTA_COST_ANALYTICS = 10
QUOTA_COST_SIMILAR_CHANNELS = 20
QUOTA_COST_NICHE_OVERVIEW = 20
QUOTA_COST_CHANNEL_ANALYSIS_CREATE = 20
QUOTA_COST_CHANNEL_ANALYSIS_STATUS = 1
QUOTA_COST_VIDEO_DETAILS = 1
QUOTA_COST_VIDEO_TRANSCRIPT = 1
QUOTA_COST_VIDEO_COMMENTS = 1
QUOTA_COST_SEARCH = 1
```

```python
# server/apps/nexlev/logic/staleness.py
"""Staleness check for one persisted NexLev section timestamp."""

from datetime import datetime, timedelta

from django.utils import timezone


def is_stale(fetched_at: datetime | None, *, window: timedelta) -> bool:
    """True when the section was never fetched or is older than window."""
    if fetched_at is None:
        return True
    return timezone.now() - fetched_at > window
```

```python
# server/apps/nexlev/models.py
"""Persistent NexLev records: per-channel, per-video, and search cache."""

from typing import override

from django.db import models


class NexLevChannelRecord(models.Model):
    """One row per NexLev channel_id; each section tracks its own fetch."""

    channel_id = models.CharField(max_length=64, unique=True, db_index=True)

    about = models.JSONField(null=True, blank=True)
    about_fetched_at = models.DateTimeField(null=True, blank=True)

    outliers = models.JSONField(null=True, blank=True)
    outliers_fetched_at = models.DateTimeField(null=True, blank=True)

    analytics = models.JSONField(null=True, blank=True)
    analytics_fetched_at = models.DateTimeField(null=True, blank=True)

    similar_channels = models.JSONField(null=True, blank=True)
    similar_channels_fetched_at = models.DateTimeField(null=True, blank=True)

    niche_overview = models.JSONField(null=True, blank=True)
    niche_overview_fetched_at = models.DateTimeField(null=True, blank=True)

    channel_analysis = models.JSONField(null=True, blank=True)
    channel_analysis_fetched_at = models.DateTimeField(null=True, blank=True)

    quota_spent = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for NexLevChannelRecord."""

        verbose_name = 'NexLev channel record'

    @override
    def __str__(self) -> str:
        return self.channel_id


class NexLevVideoRecord(models.Model):
    """One row per NexLev video_id; content is effectively immutable."""

    video_id = models.CharField(max_length=32, unique=True, db_index=True)

    details = models.JSONField(null=True, blank=True)
    details_fetched_at = models.DateTimeField(null=True, blank=True)

    transcript = models.JSONField(null=True, blank=True)
    transcript_fetched_at = models.DateTimeField(null=True, blank=True)

    comments = models.JSONField(null=True, blank=True)
    comments_fetched_at = models.DateTimeField(null=True, blank=True)

    quota_spent = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for NexLevVideoRecord."""

        verbose_name = 'NexLev video record'

    @override
    def __str__(self) -> str:
        return self.video_id


class NexLevSearchCacheEntry(models.Model):
    """Short-TTL blob cache for live `youtube/search` results only."""

    cache_key = models.CharField(max_length=64, unique=True, db_index=True)
    payload = models.JSONField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    quota_spent = models.PositiveIntegerField(default=0)

    class Meta:
        """Meta options for NexLevSearchCacheEntry."""

        verbose_name = 'NexLev search cache entry'

    @override
    def __str__(self) -> str:
        return self.cache_key
```

Create empty `server/apps/nexlev/__init__.py`,
`server/apps/nexlev/logic/__init__.py`, and
`server/apps/nexlev/migrations/__init__.py`.

- [ ] **Step 4: Add settings and INSTALLED_APPS entries**

In `server/settings/components/common.py`, add `'server.apps.nexlev',`
to the `INSTALLED_APPS` tuple right after `'server.apps.channel_research',`
(line 54).

Add near the `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD` lines (577-598):

```python
DATAFORSEO_LOGIN: str = config('DATAFORSEO_LOGIN', default='')
DATAFORSEO_PASSWORD: str = config('DATAFORSEO_PASSWORD', default='')
# DataForSEO is disabled by default — NexLev replaces it as the channel
# research YouTube-data provider. Flip to re-enable without code changes.
DATAFORSEO_ENABLED: bool = config(
    'DATAFORSEO_ENABLED',
    default=False,
    cast=bool,
)
NEXLEV_API_KEY: str = config('NEXLEV_API_KEY', default='')
NEXLEV_BASE_URL: str = config(
    'NEXLEV_BASE_URL',
    default='https://prod.dashboard.nexlev.io',
)
NEXLEV_ENABLED: bool = config('NEXLEV_ENABLED', default=True, cast=bool)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_staleness.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Write the failing model test**

```python
# tests/test_apps/test_nexlev/test_models.py
"""Tests for NexLev persistent record models."""

import pytest

from server.apps.nexlev.models import (
    NexLevChannelRecord,
    NexLevSearchCacheEntry,
    NexLevVideoRecord,
)


@pytest.mark.django_db
def test_channel_record_defaults() -> None:
    record = NexLevChannelRecord.objects.create(channel_id='UC123')
    assert record.about is None
    assert record.about_fetched_at is None
    assert record.quota_spent == 0
    assert str(record) == 'UC123'


@pytest.mark.django_db
def test_channel_record_channel_id_is_unique() -> None:
    NexLevChannelRecord.objects.create(channel_id='UC123')
    with pytest.raises(Exception, match='unique'):
        NexLevChannelRecord.objects.create(channel_id='UC123')


@pytest.mark.django_db
def test_video_record_defaults() -> None:
    record = NexLevVideoRecord.objects.create(video_id='v1')
    assert record.details is None
    assert record.quota_spent == 0
    assert str(record) == 'v1'


@pytest.mark.django_db
def test_search_cache_entry_stores_payload() -> None:
    entry = NexLevSearchCacheEntry.objects.create(
        cache_key='abc123',
        payload={'results': []},
    )
    assert entry.payload == {'results': []}
    assert str(entry) == 'abc123'
```

- [ ] **Step 7: Generate the migration and run tests**

Run: `just run makemigrations nexlev`
Run: `docker compose exec web pytest tests/test_apps/test_nexlev/ -v`
Expected: PASS (7 tests total)

- [ ] **Step 8: Register the (still-empty) NexLevService stub in DI**

```python
# server/apps/nexlev/services.py
"""NexLev read/write service — populated in later tasks."""

from typing import final

import attrs


@final
@attrs.define(slots=True, frozen=True)
class NexLevService:
    """Records-first NexLev reads: refetch only stale sections."""
```

In `server/implemented.py`, add after `_inject_channel_research` (line 83):

```python
def _inject_nexlev(container: Container) -> None:
    from server.apps.nexlev.services import NexLevService

    container.register(NexLevService, scope=Scope.singleton)
```

And add `_inject_nexlev(container)` to `populate_dependencies` (after
`_inject_channel_research(container)`, line 106).

- [ ] **Step 9: Run the full test suite for a sanity check and commit**

Run: `docker compose exec web pytest --no-cov -q`
Expected: PASS, no regressions

```bash
git add server/apps/nexlev server/settings/components/common.py \
  server/implemented.py tests/test_apps/test_nexlev
git commit -m "feat(nexlev): scaffold app, persistent records, settings flags"
```

---

## Task 2: NexLev value objects and HTTP client

**Files:**
- Create: `server/apps/nexlev/logic/value_objects.py`
- Create: `server/apps/nexlev/clients/__init__.py` (empty)
- Create: `server/apps/nexlev/clients/nexlev_client.py`
- Test: `tests/test_apps/test_nexlev/test_client.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `server.apps.nexlev.logic.value_objects.{NexLevChannelAbout,
  NexLevOutlierVideo, NexLevChannelAnalytics, NexLevSimilarChannel,
  NexLevNicheOverview, NexLevVideoDetails, NexLevTranscriptSegment,
  NexLevComment, NexLevSearchResultItem, NexLevSuggestedTopic,
  NexLevScriptStage, NexLevTitleFormatGroup, NexLevChannelAnalysisResult}`
  (all `msgspec.Struct`).
- Produces: `server.apps.nexlev.clients.nexlev_client` async functions:
  `get_channel_about`, `get_channel_outliers`, `get_channel_analytics`,
  `get_similar_channels`, `get_niche_overview`, `get_video_details`,
  `get_video_transcript`, `get_video_comments`, `search_youtube`,
  `create_channel_analysis_job`, `get_channel_analysis_result` — every
  function takes `*, api_key: str, base_url: str` plus its specific
  params, and returns a plain `dict`/`list[dict]` (JSON-shaped, not yet
  converted to a struct — struct conversion happens in `NexLevService`,
  Tasks 3-5).

- [ ] **Step 1: Write the failing value-objects import test**

```python
# tests/test_apps/test_nexlev/test_client.py
"""Tests for the NexLev value objects and HTTP client."""

import httpx
import msgspec
import pytest

from server.apps.nexlev.logic.value_objects import NexLevChannelAbout


def test_channel_about_decodes_camel_case_json() -> None:
    raw = {
        'channelId': 'UC123',
        'title': 'Test Channel',
        'description': 'A channel',
        'subscriberCount': 1000,
        'videosCount': 42,
        'viewCount': 99999,
    }
    result = msgspec.convert(raw, type=NexLevChannelAbout)
    assert result.channel_id == 'UC123'
    assert result.subscriber_count == 1000
    assert result.videos_count == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'server.apps.nexlev.logic.value_objects'`

- [ ] **Step 3: Write the value objects**

```python
# server/apps/nexlev/logic/value_objects.py
"""msgspec DTOs for NexLev API responses — only fields we consume.

NexLev's outer envelope fields are camelCase (about/outliers/analytics/
similar_channels/niche_overview/video/search) so those structs decode
with `rename='camel'`. The nested `strategic_insights` fields inside the
async channel-analysis job result are already snake_case in NexLev's own
JSON, so those structs use plain (unrenamed) field names.
"""

import msgspec


class NexLevChannelAbout(msgspec.Struct, rename='camel'):
    """GET /api/external/channels/about."""

    channel_id: str
    title: str
    description: str = ''
    subscriber_count: int = 0
    videos_count: int = 0
    view_count: int = 0


class NexLevOutlierVideo(msgspec.Struct, rename='camel'):
    """One item of GET /api/external/channels/outliers → outliers[]."""

    video_id: str
    title: str
    view_count: str = ''
    outlier_score: str = ''
    published_at: str = ''


class NexLevChannelAnalytics(msgspec.Struct, rename='camel'):
    """Flattened POST /api/external/analytics/channel-analytics."""

    subscriber_count: int = 0
    view_count: int = 0
    video_count: int = 0
    country: str = ''
    categories: list[str] = []
    tags: list[str] = []


class NexLevSimilarChannel(msgspec.Struct, rename='camel'):
    """One item shared by similar-channels search and niche overview."""

    channel_id: str
    channel_name: str
    similarity_score: int = 0


class NexLevNicheOverview(msgspec.Struct, rename='camel'):
    """POST /api/external/niche-overview/analyze."""

    original_channel_id: str
    similar_channels: list[NexLevSimilarChannel] = []
    total_channels: int = 0
    total_videos: int = 0


class NexLevVideoDetails(msgspec.Struct, rename='camel'):
    """GET /api/external/videos/details (first item of the response)."""

    id: str
    title: str
    channel_title: str = ''
    channel_id: str = ''
    view_count: str = ''
    length_seconds: str = ''


class NexLevTranscriptSegment(msgspec.Struct, rename='camel'):
    """One item of GET /api/external/videos/transcript → transcript[]."""

    start_ms: str
    end_ms: str
    start_time: str = ''
    text: str = ''


class NexLevComment(msgspec.Struct, rename='camel'):
    """One item of GET /api/external/videos/comments → data[]."""

    comment_id: str
    author_text: str = ''
    text_display: str = ''
    likes_count: str = ''


class NexLevSearchResultItem(msgspec.Struct, rename='camel'):
    """One polymorphic item of GET /api/external/youtube/search → results[].

    Shape varies by `type` (video/shorts/channel/playlist) — every field
    beyond `type` is optional so one struct covers all four.
    """

    type: str
    title: str = ''
    video_id: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    view_count: str | int | None = None


class NexLevSuggestedTopic(msgspec.Struct):
    """strategic_insights.suggested_topics.topics[] (already snake_case)."""

    title: str
    description: str = ''


class NexLevScriptStage(msgspec.Struct):
    """strategic_insights.script_blueprint.recommended_stages[]."""

    stage: str
    purpose: str = ''
    recommended_length_seconds: int = 0
    winning_formula: str = ''


class NexLevTitleFormatGroup(msgspec.Struct):
    """strategic_insights.title_format_strategy.format_groups[]."""

    format_name: str
    format_description: str = ''
    video_count: int = 0


class NexLevChannelAnalysisResult(msgspec.Struct):
    """Trimmed result of the async channel-analysis job (Deep Analysis)."""

    suggested_topics: list[NexLevSuggestedTopic] = []
    script_blueprint: list[NexLevScriptStage] = []
    title_format_groups: list[NexLevTitleFormatGroup] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_client.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Write failing client tests (one per endpoint family)**

Append to `tests/test_apps/test_nexlev/test_client.py`:

```python
from server.apps.nexlev.clients import nexlev_client
from server.common.exceptions import FatalProviderError, RetryableProviderError

_API_KEY = 'test-key'
_BASE_URL = 'https://prod.dashboard.nexlev.io'


def _patch_get(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    async def _fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx.AsyncClient, 'get', _fake_get)


def _patch_post(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    async def _fake_post(
        self: httpx.AsyncClient,
        url: str,
        *,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx.AsyncClient, 'post', _fake_post)


def test_get_channel_about_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json={'channelId': 'UC1', 'title': 'X'}),
    )

    import asyncio

    result = asyncio.run(
        nexlev_client.get_channel_about(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result['channelId'] == 'UC1'


def test_get_channel_about_raises_fatal_on_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(monkeypatch, httpx.Response(401, json={'error': 'nope'}))

    import asyncio

    with pytest.raises(FatalProviderError):
        asyncio.run(
            nexlev_client.get_channel_about(
                'UC1',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_get_channel_about_raises_retryable_on_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(monkeypatch, httpx.Response(429, json={'error': 'quota'}))

    import asyncio

    with pytest.raises(RetryableProviderError):
        asyncio.run(
            nexlev_client.get_channel_about(
                'UC1',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_get_channel_analytics_flattens_about_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        httpx.Response(
            200,
            json=[
                {
                    'about': {
                        'subscriberCount': 10,
                        'viewCount': 20,
                        'videoCount': 3,
                        'country': 'US',
                    },
                    'categories': ['Tech'],
                    'tags': ['gadgets'],
                },
            ],
        ),
    )

    import asyncio

    result = asyncio.run(
        nexlev_client.get_channel_analytics(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result['subscriberCount'] == 10
    assert result['categories'] == ['Tech']


def test_get_similar_channels_flattens_about_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        httpx.Response(
            200,
            json={
                'data': [
                    {
                        'about': {'channelId': 'UC2', 'channelName': 'Rival'},
                        'similarityScore': 72,
                    },
                ],
            },
        ),
    )

    import asyncio

    result = asyncio.run(
        nexlev_client.get_similar_channels(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result[0]['channelId'] == 'UC2'
    assert result[0]['similarityScore'] == 72


def test_get_video_details_unwraps_list_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json=[{'id': 'v1', 'title': 'Video'}]),
    )

    import asyncio

    result = asyncio.run(
        nexlev_client.get_video_details(
            'v1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result['id'] == 'v1'


def test_create_channel_analysis_job_unwraps_list_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json=[{'job_id': 'job-1', 'channel_id': 'UC1'}]),
    )

    import asyncio

    job_id = asyncio.run(
        nexlev_client.create_channel_analysis_job(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert job_id == 'job-1'


def test_get_channel_analysis_result_returns_none_when_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json={'status': 'processing', 'progress': 40}),
    )

    import asyncio

    result = asyncio.run(
        nexlev_client.get_channel_analysis_result(
            'job-1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result is None


def test_get_channel_analysis_result_returns_data_when_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(
            200,
            json={'status': 'completed', 'result': {'channel_id': 'UC1'}},
        ),
    )

    import asyncio

    result = asyncio.run(
        nexlev_client.get_channel_analysis_result(
            'job-1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result is not None
    assert result['result']['channel_id'] == 'UC1'
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'server.apps.nexlev.clients'`

- [ ] **Step 7: Write the HTTP client**

```python
# server/apps/nexlev/clients/nexlev_client.py
"""Async NexLev API client — normalizes NexLev's inconsistent envelopes.

Every function returns plain dict/list JSON (not yet a msgspec struct);
NexLevService (Tasks 3-5) does the struct conversion after merging with
persisted records.
"""

from typing import Any

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_PROVIDER = 'nexlev'
_TIMEOUT = 30.0


def _auth_headers(api_key: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {api_key}'}


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == httpx.codes.UNAUTHORIZED:
        msg = 'NexLev request unauthorized'
        raise FatalProviderError(msg, provider=_PROVIDER, error_code='401')
    if response.status_code == httpx.codes.NOT_FOUND:
        msg = 'NexLev resource not found'
        raise FatalProviderError(msg, provider=_PROVIDER, error_code='404')
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        msg = 'NexLev quota or rate limit exceeded'
        raise RetryableProviderError(
            msg,
            provider=_PROVIDER,
            status_code=response.status_code,
        )
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        msg = f'NexLev upstream error {response.status_code}'
        raise RetryableProviderError(
            msg,
            provider=_PROVIDER,
            status_code=response.status_code,
        )
    if not response.is_success:
        msg = f'NexLev unexpected status {response.status_code}'
        raise FatalProviderError(
            msg,
            provider=_PROVIDER,
            error_code=str(response.status_code),
        )


def _parse_json(response: httpx.Response) -> Any:
    _raise_for_status(response)
    return response.json()


async def get_channel_about(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """GET /api/external/channels/about?id=<channel_id>. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/about',
            params={'id': channel_id},
            headers=_auth_headers(api_key),
        )
    return _parse_json(response)


async def get_channel_outliers(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
    max_videos: int = 30,
    min_outlier_threshold: float = 2.0,
) -> list[dict[str, Any]]:
    """GET /api/external/channels/outliers. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/outliers',
            params={
                'id': channel_id,
                'maxVideos': max_videos,
                'minOutlierThreshold': min_outlier_threshold,
            },
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    outliers = data.get('outliers', [])
    return list(outliers) if isinstance(outliers, list) else []


async def get_channel_analytics(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """POST /api/external/analytics/channel-analytics. 10 quota.

    Flattens the nested `about` block and top-level categories/tags into
    one dict matching NexLevChannelAnalytics.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f'{base_url}/api/external/analytics/channel-analytics',
            json={'channelId': channel_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    first = data[0] if isinstance(data, list) and data else {}
    about = first.get('about', {})
    return {
        'subscriberCount': about.get('subscriberCount', 0),
        'viewCount': about.get('viewCount', 0),
        'videoCount': about.get('videoCount', 0),
        'country': about.get('country', ''),
        'categories': first.get('categories', []),
        'tags': first.get('tags', []),
    }


async def get_similar_channels(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """POST /api/external/similar-channels/search. 20 quota.

    Flattens each item's `about` block into a flat channelId/channelName
    dict matching NexLevSimilarChannel.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f'{base_url}/api/external/similar-channels/search',
            json={'channelId': channel_id, 'channelType': 'all', 'level': 1},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    items = data.get('data', []) if isinstance(data, dict) else []
    return [
        {
            'channelId': item.get('about', {}).get('channelId', ''),
            'channelName': item.get('about', {}).get('channelName', ''),
            'similarityScore': item.get('similarityScore', 0),
        }
        for item in items
    ]


async def get_niche_overview(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """POST /api/external/niche-overview/analyze. 20 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f'{base_url}/api/external/niche-overview/analyze',
            json={'channelId': channel_id},
            headers=_auth_headers(api_key),
        )
    return _parse_json(response)


async def get_video_details(
    video_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """GET /api/external/videos/details. 1 quota. Unwraps list envelope."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/videos/details',
            params={'videoId': video_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    return data[0] if isinstance(data, list) and data else {}


async def get_video_transcript(
    video_id: str,
    *,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """GET /api/external/videos/transcript. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/videos/transcript',
            params={'videoId': video_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    first = data[0] if isinstance(data, list) and data else {}
    transcript = first.get('transcript', [])
    return list(transcript) if isinstance(transcript, list) else []


async def get_video_comments(
    video_id: str,
    *,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """GET /api/external/videos/comments. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/videos/comments',
            params={'videoId': video_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    comments = data.get('data', [])
    return list(comments) if isinstance(comments, list) else []


async def search_youtube(
    query: str,
    *,
    api_key: str,
    base_url: str,
    search_type: str | None = None,
) -> list[dict[str, Any]]:
    """GET /api/external/youtube/search. 1 quota, 20 req/min limit."""
    params: dict[str, Any] = {'query': query}
    if search_type is not None:
        params['type'] = search_type
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/youtube/search',
            params=params,
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    results = data.get('results', [])
    return list(results) if isinstance(results, list) else []


async def create_channel_analysis_job(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> str:
    """GET .../channels/analysis/job/create. 20 quota. List envelope."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/analysis/job/create',
            params={'channel_id': channel_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    first = data[0] if isinstance(data, list) and data else data
    return str(first['job_id'])


async def get_channel_analysis_result(
    job_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any] | None:
    """GET .../channels/analysis/job/status. 1 quota.

    Returns None while `status != 'completed'` so the caller can poll.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/analysis/job/status',
            params={'job_id': job_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    if data.get('status') != 'completed':
        return None
    return data
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_client.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
git add server/apps/nexlev/logic/value_objects.py \
  server/apps/nexlev/clients tests/test_apps/test_nexlev/test_client.py
git commit -m "feat(nexlev): add value objects and HTTP client"
```

---

## Task 3: NexLevService — channel-section methods

**Files:**
- Modify: `server/apps/nexlev/services.py`
- Test: `tests/test_apps/test_nexlev/test_services_channel.py`

**Interfaces:**
- Consumes: `NexLevChannelRecord` (Task 1), `nexlev_client.*` (Task 2),
  value objects (Task 2), `logic.staleness.is_stale`, `logic.constants.*`.
- Produces: `NexLevService.get_channel_about(channel_id: str, *,
  force_refresh: bool = False) -> NexLevChannelAbout`,
  `.get_channel_outliers(channel_id, *, force_refresh=False) ->
  list[NexLevOutlierVideo]`, `.get_channel_analytics(channel_id, *,
  force_refresh=False) -> NexLevChannelAnalytics`,
  `.get_similar_channels(channel_id, *, force_refresh=False) ->
  list[NexLevSimilarChannel]`, `.get_niche_overview(channel_id, *,
  force_refresh=False) -> NexLevNicheOverview`. All async.

- [ ] **Step 1: Write the failing staleness-boundary test**

```python
# tests/test_apps/test_nexlev/test_services_channel.py
"""Tests for NexLevService channel-section methods."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from django.utils import timezone

from server.apps.nexlev.logic import constants
from server.apps.nexlev.models import NexLevChannelRecord
from server.apps.nexlev.services import NexLevService


@pytest.mark.django_db
def test_get_channel_about_fetches_when_missing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(
                return_value={
                    'channelId': 'UC1',
                    'title': 'X',
                    'subscriberCount': 10,
                    'videosCount': 2,
                    'viewCount': 100,
                },
            ),
        ) as mock_call:
            result = await service.get_channel_about('UC1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.channel_id == 'UC1'
    mock_call.assert_awaited_once()
    record = NexLevChannelRecord.objects.get(channel_id='UC1')
    assert record.about_fetched_at is not None
    assert record.quota_spent == constants.QUOTA_COST_ABOUT


@pytest.mark.django_db
def test_get_channel_about_uses_fresh_record_without_calling_api() -> None:
    NexLevChannelRecord.objects.create(
        channel_id='UC1',
        about={
            'channelId': 'UC1',
            'title': 'Cached',
            'subscriberCount': 5,
            'videosCount': 1,
            'viewCount': 50,
        },
        about_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(),
        ) as mock_call:
            result = await service.get_channel_about('UC1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'Cached'
    mock_call.assert_not_awaited()


@pytest.mark.django_db
def test_get_channel_about_refetches_when_stale() -> None:
    stale_at = timezone.now() - constants.ABOUT_STALE_AFTER - timedelta(days=1)
    NexLevChannelRecord.objects.create(
        channel_id='UC1',
        about={'channelId': 'UC1', 'title': 'Old'},
        about_fetched_at=stale_at,
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(return_value={'channelId': 'UC1', 'title': 'New'}),
        ) as mock_call:
            result = await service.get_channel_about('UC1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'New'
    mock_call.assert_awaited_once()


@pytest.mark.django_db
def test_get_channel_about_force_refresh_ignores_freshness() -> None:
    NexLevChannelRecord.objects.create(
        channel_id='UC1',
        about={'channelId': 'UC1', 'title': 'Cached'},
        about_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(return_value={'channelId': 'UC1', 'title': 'Forced'}),
        ) as mock_call:
            result = await service.get_channel_about(
                'UC1',
                force_refresh=True,
            )
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'Forced'
    mock_call.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_services_channel.py -v`
Expected: FAIL — `AttributeError: 'NexLevService' object has no attribute
'get_channel_about'`

- [ ] **Step 3: Implement channel-section methods**

```python
# server/apps/nexlev/services.py
"""NexLev read service — records-first, staleness-aware, per section."""

from typing import final

import attrs
import msgspec
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from server.apps.nexlev.clients import nexlev_client
from server.apps.nexlev.logic import constants
from server.apps.nexlev.logic.staleness import is_stale
from server.apps.nexlev.logic.value_objects import (
    NexLevChannelAbout,
    NexLevChannelAnalytics,
    NexLevNicheOverview,
    NexLevOutlierVideo,
    NexLevSimilarChannel,
)
from server.apps.nexlev.models import NexLevChannelRecord


def _get_or_create_channel_record(channel_id: str) -> NexLevChannelRecord:
    record, _ = NexLevChannelRecord.objects.get_or_create(
        channel_id=channel_id,
    )
    return record


def _save_channel_record(
    record: NexLevChannelRecord,
    *,
    fields: list[str],
) -> None:
    record.save(update_fields=[*fields, 'updated_at'])


@final
@attrs.define(slots=True, frozen=True)
class NexLevService:
    """Records-first NexLev reads: refetch only stale sections."""

    async def get_channel_about(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevChannelAbout:
        """Return channel about-info, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.about_fetched_at,
            window=constants.ABOUT_STALE_AFTER,
        ):
            raw = await nexlev_client.get_channel_about(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.about = raw
            record.about_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_ABOUT
            await sync_to_async(_save_channel_record)(
                record,
                fields=['about', 'about_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(record.about, type=NexLevChannelAbout)

    async def get_channel_outliers(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevOutlierVideo]:
        """Return outlier videos, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.outliers_fetched_at,
            window=constants.OUTLIERS_STALE_AFTER,
        ):
            raw = await nexlev_client.get_channel_outliers(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.outliers = raw
            record.outliers_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_OUTLIERS
            await sync_to_async(_save_channel_record)(
                record,
                fields=['outliers', 'outliers_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(
            record.outliers or [],
            type=list[NexLevOutlierVideo],
        )

    async def get_channel_analytics(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevChannelAnalytics:
        """Return channel analytics, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.analytics_fetched_at,
            window=constants.ANALYTICS_STALE_AFTER,
        ):
            raw = await nexlev_client.get_channel_analytics(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.analytics = raw
            record.analytics_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_ANALYTICS
            await sync_to_async(_save_channel_record)(
                record,
                fields=['analytics', 'analytics_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(record.analytics, type=NexLevChannelAnalytics)

    async def get_similar_channels(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevSimilarChannel]:
        """Return similar channels, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.similar_channels_fetched_at,
            window=constants.SIMILAR_CHANNELS_STALE_AFTER,
        ):
            raw = await nexlev_client.get_similar_channels(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.similar_channels = raw
            record.similar_channels_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_SIMILAR_CHANNELS
            await sync_to_async(_save_channel_record)(
                record,
                fields=[
                    'similar_channels',
                    'similar_channels_fetched_at',
                    'quota_spent',
                ],
            )
        return msgspec.convert(
            record.similar_channels or [],
            type=list[NexLevSimilarChannel],
        )

    async def get_niche_overview(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevNicheOverview:
        """Return niche overview, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.niche_overview_fetched_at,
            window=constants.NICHE_OVERVIEW_STALE_AFTER,
        ):
            raw = await nexlev_client.get_niche_overview(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.niche_overview = raw
            record.niche_overview_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_NICHE_OVERVIEW
            await sync_to_async(_save_channel_record)(
                record,
                fields=[
                    'niche_overview',
                    'niche_overview_fetched_at',
                    'quota_spent',
                ],
            )
        return msgspec.convert(
            record.niche_overview,
            type=NexLevNicheOverview,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_services_channel.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add server/apps/nexlev/services.py \
  tests/test_apps/test_nexlev/test_services_channel.py
git commit -m "feat(nexlev): add channel-section NexLevService methods"
```

---

## Task 4: NexLevService — video-record and search-cache methods

**Files:**
- Modify: `server/apps/nexlev/services.py`
- Test: `tests/test_apps/test_nexlev/test_services_video_search.py`

**Interfaces:**
- Consumes: `NexLevVideoRecord`, `NexLevSearchCacheEntry` (Task 1),
  `nexlev_client.*` (Task 2).
- Produces: `NexLevService.get_video_details(video_id, *,
  force_refresh=False) -> NexLevVideoDetails`,
  `.get_video_transcript(video_id, *, force_refresh=False) ->
  list[NexLevTranscriptSegment]`, `.get_video_comments(video_id, *,
  force_refresh=False) -> list[NexLevComment]`,
  `.search_youtube(query: str, *, search_type: str | None = None) ->
  list[NexLevSearchResultItem]`. All async.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_nexlev/test_services_video_search.py
"""Tests for NexLevService video-record and search-cache methods."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest
from django.utils import timezone

from server.apps.nexlev.logic import constants
from server.apps.nexlev.models import NexLevSearchCacheEntry, NexLevVideoRecord
from server.apps.nexlev.services import NexLevService


@pytest.mark.django_db
def test_get_video_details_fetches_when_missing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_details',
            new=AsyncMock(return_value={'id': 'v1', 'title': 'X'}),
        ) as mock_call:
            result = await service.get_video_details('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.id == 'v1'
    mock_call.assert_awaited_once()
    record = NexLevVideoRecord.objects.get(video_id='v1')
    assert record.quota_spent == constants.QUOTA_COST_VIDEO_DETAILS


@pytest.mark.django_db
def test_get_video_details_uses_fresh_record() -> None:
    NexLevVideoRecord.objects.create(
        video_id='v1',
        details={'id': 'v1', 'title': 'Cached'},
        details_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_details',
            new=AsyncMock(),
        ) as mock_call:
            result = await service.get_video_details('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'Cached'
    mock_call.assert_not_awaited()


@pytest.mark.django_db
def test_search_youtube_caches_by_query() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.search_youtube',
            new=AsyncMock(return_value=[{'type': 'video', 'title': 'Hit'}]),
        ) as mock_call:
            first = await service.search_youtube('rome history')
            second = await service.search_youtube('rome history')
            return first, second, mock_call

    first, second, mock_call = asyncio.run(_inner())
    assert first[0].title == 'Hit'
    assert second[0].title == 'Hit'
    mock_call.assert_awaited_once()
    cache_key = hashlib.sha256(
        json.dumps(
            {'query': 'rome history', 'type': None},
            sort_keys=True,
        ).encode(),
    ).hexdigest()
    assert NexLevSearchCacheEntry.objects.filter(cache_key=cache_key).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_services_video_search.py -v`
Expected: FAIL — `AttributeError: 'NexLevService' object has no attribute
'get_video_details'`

- [ ] **Step 3: Add video-record and search-cache methods**

Add these imports to `server/apps/nexlev/services.py` (alongside the
existing ones from Task 3):

```python
import hashlib
import json

from server.apps.nexlev.logic.value_objects import (
    NexLevComment,
    NexLevSearchResultItem,
    NexLevTranscriptSegment,
    NexLevVideoDetails,
)
from server.apps.nexlev.models import NexLevSearchCacheEntry, NexLevVideoRecord
```

Add these module-level helpers next to `_get_or_create_channel_record`:

```python
def _get_or_create_video_record(video_id: str) -> NexLevVideoRecord:
    record, _ = NexLevVideoRecord.objects.get_or_create(video_id=video_id)
    return record


def _save_video_record(record: NexLevVideoRecord, *, fields: list[str]) -> None:
    record.save(update_fields=[*fields, 'updated_at'])


def _search_cache_key(query: str, search_type: str | None) -> str:
    raw = json.dumps({'query': query, 'type': search_type}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_fresh_search_cache_entry(
    cache_key: str,
) -> NexLevSearchCacheEntry | None:
    cutoff = timezone.now() - constants.SEARCH_CACHE_TTL
    return NexLevSearchCacheEntry.objects.filter(
        cache_key=cache_key,
        fetched_at__gte=cutoff,
    ).first()


def _upsert_search_cache_entry(
    cache_key: str,
    payload: list[dict[str, object]],
) -> None:
    NexLevSearchCacheEntry.objects.update_or_create(
        cache_key=cache_key,
        defaults={
            'payload': payload,
            'fetched_at': timezone.now(),
            'quota_spent': constants.QUOTA_COST_SEARCH,
        },
    )
```

Add these methods to the `NexLevService` class, after
`get_niche_overview`:

```python
    async def get_video_details(
        self,
        video_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevVideoDetails:
        """Return video details; content is immutable, long staleness."""
        record = await sync_to_async(_get_or_create_video_record)(video_id)
        if force_refresh or is_stale(
            record.details_fetched_at,
            window=constants.VIDEO_STALE_AFTER,
        ):
            raw = await nexlev_client.get_video_details(
                video_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.details = raw
            record.details_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_VIDEO_DETAILS
            await sync_to_async(_save_video_record)(
                record,
                fields=['details', 'details_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(record.details, type=NexLevVideoDetails)

    async def get_video_transcript(
        self,
        video_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevTranscriptSegment]:
        """Return the transcript; content is immutable, long staleness."""
        record = await sync_to_async(_get_or_create_video_record)(video_id)
        if force_refresh or is_stale(
            record.transcript_fetched_at,
            window=constants.VIDEO_STALE_AFTER,
        ):
            raw = await nexlev_client.get_video_transcript(
                video_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.transcript = raw
            record.transcript_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_VIDEO_TRANSCRIPT
            await sync_to_async(_save_video_record)(
                record,
                fields=[
                    'transcript',
                    'transcript_fetched_at',
                    'quota_spent',
                ],
            )
        return msgspec.convert(
            record.transcript or [],
            type=list[NexLevTranscriptSegment],
        )

    async def get_video_comments(
        self,
        video_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevComment]:
        """Return top comments; content is immutable, long staleness."""
        record = await sync_to_async(_get_or_create_video_record)(video_id)
        if force_refresh or is_stale(
            record.comments_fetched_at,
            window=constants.VIDEO_STALE_AFTER,
        ):
            raw = await nexlev_client.get_video_comments(
                video_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.comments = raw
            record.comments_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_VIDEO_COMMENTS
            await sync_to_async(_save_video_record)(
                record,
                fields=['comments', 'comments_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(record.comments or [], type=list[NexLevComment])

    async def search_youtube(
        self,
        query: str,
        *,
        search_type: str | None = None,
    ) -> list[NexLevSearchResultItem]:
        """Return live YouTube search results, short-TTL cached by query."""
        cache_key = _search_cache_key(query, search_type)
        cached = await sync_to_async(_get_fresh_search_cache_entry)(cache_key)
        if cached is not None:
            return msgspec.convert(
                cached.payload,
                type=list[NexLevSearchResultItem],
            )
        raw = await nexlev_client.search_youtube(
            query,
            api_key=settings.NEXLEV_API_KEY,
            base_url=settings.NEXLEV_BASE_URL,
            search_type=search_type,
        )
        await sync_to_async(_upsert_search_cache_entry)(cache_key, raw)
        return msgspec.convert(raw, type=list[NexLevSearchResultItem])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_services_video_search.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server/apps/nexlev/services.py \
  tests/test_apps/test_nexlev/test_services_video_search.py
git commit -m "feat(nexlev): add video-record and search-cache NexLevService methods"
```

---

## Task 5: NexLevService — async channel-analysis job methods

**Files:**
- Modify: `server/apps/nexlev/services.py`
- Test: `tests/test_apps/test_nexlev/test_services_channel_analysis.py`

**Interfaces:**
- Consumes: `NexLevChannelRecord` (Task 1), `nexlev_client.
  create_channel_analysis_job`/`get_channel_analysis_result` (Task 2).
- Produces: `NexLevService.create_channel_analysis_job(channel_id: str)
  -> str` (always live, never staleness-checked — Deep Analysis is
  operator-triggered), `.get_channel_analysis_result(nexlev_job_id: str,
  channel_id: str) -> NexLevChannelAnalysisResult | None` (returns `None`
  while NexLev is still processing; stores the result on the channel
  record only once complete).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_nexlev/test_services_channel_analysis.py
"""Tests for NexLevService's async channel-analysis job methods."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.nexlev.logic import constants
from server.apps.nexlev.models import NexLevChannelRecord
from server.apps.nexlev.services import NexLevService

_RAW_RESULT = {
    'status': 'completed',
    'result': {
        'strategic_insights': {
            'suggested_topics': {
                'topics': [{'title': 'Topic A', 'description': 'desc'}],
            },
            'script_blueprint': {
                'recommended_stages': [
                    {
                        'stage': 'Hook',
                        'purpose': 'grab attention',
                        'recommended_length_seconds': 30,
                        'winning_formula': 'shocking claim',
                    },
                ],
            },
            'title_format_strategy': {
                'format_groups': [
                    {
                        'format_name': 'X vs Y',
                        'format_description': 'comparison',
                        'video_count': 5,
                    },
                ],
            },
        },
    },
}


@pytest.mark.django_db
def test_create_channel_analysis_job_returns_job_id() -> None:
    service = NexLevService()

    async def _inner() -> str:
        with patch(
            'server.apps.nexlev.services.nexlev_client.create_channel_analysis_job',
            new=AsyncMock(return_value='job-1'),
        ):
            return await service.create_channel_analysis_job('UC1')

    assert asyncio.run(_inner()) == 'job-1'


@pytest.mark.django_db
def test_get_channel_analysis_result_returns_none_while_processing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_analysis_result',
            new=AsyncMock(return_value=None),
        ):
            return await service.get_channel_analysis_result('job-1', 'UC1')

    assert asyncio.run(_inner()) is None


@pytest.mark.django_db
def test_get_channel_analysis_result_stores_on_completion() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_analysis_result',
            new=AsyncMock(return_value=_RAW_RESULT),
        ):
            return await service.get_channel_analysis_result('job-1', 'UC1')

    result = asyncio.run(_inner())
    assert result is not None
    assert result.suggested_topics[0].title == 'Topic A'
    assert result.script_blueprint[0].stage == 'Hook'
    assert result.title_format_groups[0].format_name == 'X vs Y'
    record = NexLevChannelRecord.objects.get(channel_id='UC1')
    assert record.channel_analysis_fetched_at is not None
    assert record.quota_spent == constants.QUOTA_COST_CHANNEL_ANALYSIS_STATUS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_services_channel_analysis.py -v`
Expected: FAIL — `AttributeError: 'NexLevService' object has no attribute
'create_channel_analysis_job'`

- [ ] **Step 3: Add the channel-analysis job methods**

Add to the imports in `server/apps/nexlev/services.py`:

```python
from server.apps.nexlev.logic.value_objects import (
    NexLevChannelAnalysisResult,
    NexLevScriptStage,
    NexLevSuggestedTopic,
    NexLevTitleFormatGroup,
)
```

Add this method to `NexLevService`, after `search_youtube`:

```python
    async def create_channel_analysis_job(self, channel_id: str) -> str:
        """Kick off NexLev's async Deep Analysis job. Always live — never
        staleness-checked, since this is an explicit operator action.
        """
        return await nexlev_client.create_channel_analysis_job(
            channel_id,
            api_key=settings.NEXLEV_API_KEY,
            base_url=settings.NEXLEV_BASE_URL,
        )

    async def get_channel_analysis_result(
        self,
        nexlev_job_id: str,
        channel_id: str,
    ) -> NexLevChannelAnalysisResult | None:
        """Poll one Deep Analysis job; store the result once completed."""
        raw = await nexlev_client.get_channel_analysis_result(
            nexlev_job_id,
            api_key=settings.NEXLEV_API_KEY,
            base_url=settings.NEXLEV_BASE_URL,
        )
        if raw is None:
            return None
        insights = raw['result']['strategic_insights']
        result = NexLevChannelAnalysisResult(
            suggested_topics=[
                NexLevSuggestedTopic(
                    title=item['title'],
                    description=item.get('description', ''),
                )
                for item in insights['suggested_topics']['topics']
            ],
            script_blueprint=[
                NexLevScriptStage(
                    stage=item['stage'],
                    purpose=item.get('purpose', ''),
                    recommended_length_seconds=item.get(
                        'recommended_length_seconds',
                        0,
                    ),
                    winning_formula=item.get('winning_formula', ''),
                )
                for item in insights['script_blueprint']['recommended_stages']
            ],
            title_format_groups=[
                NexLevTitleFormatGroup(
                    format_name=item['format_name'],
                    format_description=item.get('format_description', ''),
                    video_count=item.get('video_count', 0),
                )
                for item in insights['title_format_strategy']['format_groups']
            ],
        )
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        record.channel_analysis = msgspec.to_builtins(result)
        record.channel_analysis_fetched_at = timezone.now()
        record.quota_spent += constants.QUOTA_COST_CHANNEL_ANALYSIS_STATUS
        await sync_to_async(_save_channel_record)(
            record,
            fields=[
                'channel_analysis',
                'channel_analysis_fetched_at',
                'quota_spent',
            ],
        )
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/test_services_channel_analysis.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full nexlev test suite and commit**

Run: `docker compose exec web pytest tests/test_apps/test_nexlev/ -v`
Expected: PASS (all tests)

```bash
git add server/apps/nexlev/services.py \
  tests/test_apps/test_nexlev/test_services_channel_analysis.py
git commit -m "feat(nexlev): add async channel-analysis job methods"
```

---

## Task 6: Disable DataForSEO behind a settings flag

**Files:**
- Modify: `server/apps/channel_research/agent.py:226-271`
- Modify: `tests/test_apps/test_channel_research/test_agent.py`

**Interfaces:**
- Consumes: `settings.DATAFORSEO_ENABLED` (Task 1).
- Produces: `_register_tools` only calls `_register_dataforseo_tools`
  when `settings.DATAFORSEO_ENABLED` is `True` (default `False`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_apps/test_channel_research/test_agent.py` (needs
`from django.test import override_settings` added to the imports):

```python
from django.test import override_settings


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=False)
def test_dataforseo_tools_not_registered_when_disabled() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-flags-off')
    assert 'youtube_search' not in fake.tools
    assert 'video_info' not in fake.tools
    assert 'video_comments' not in fake.tools
    assert 'video_subtitles' not in fake.tools


@override_settings(DATAFORSEO_ENABLED=True, NEXLEV_ENABLED=False)
def test_dataforseo_tools_registered_when_enabled() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-flags-on')
    assert 'youtube_search' in fake.tools
    assert 'video_info' in fake.tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_agent.py::test_dataforseo_tools_not_registered_when_disabled -v`
Expected: FAIL — DataForSEO tools are registered unconditionally today,
so `'youtube_search' not in fake.tools` is False.

- [ ] **Step 3: Gate `_register_dataforseo_tools` behind the flag**

In `server/apps/channel_research/agent.py`, add `from django.conf import
settings` to the imports (after the `pydantic_ai.usage` import, line 11),
then change `_register_tools` (lines 226-271):

```python
def _register_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach research tools with per-tool caps."""

    @agent.tool
    async def resolve_channel(
        ctx: RunContext[ChannelResearchDeps],
    ) -> dict[str, Any]:
        """Resolve the source URL to channel snippet, stats, and branding.

        Call exactly once at the start of research.
        """
        ctx.deps.trace.consume('resolve_channel')
        result = await yt_client.resolve_channel(
            ctx.deps.source_channel_url,
            ctx.deps.youtube_api_key,
        )
        ctx.deps.trace.record('resolve_channel', {}, result)
        return result

    @agent.tool
    async def list_channel_videos(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
        order: str = 'date',
    ) -> list[dict[str, Any]]:
        """List recent (`date`) or popular (`viewCount`) videos on a channel.

        Call at most twice - once recent, once popular.
        """
        ctx.deps.trace.consume('list_channel_videos')
        result = await yt_client.list_channel_videos(
            channel_id,
            ctx.deps.youtube_api_key,
            order=order,
        )
        ctx.deps.trace.record(
            'list_channel_videos',
            {'channel_id': channel_id, 'order': order},
            result,
        )
        return result

    if settings.DATAFORSEO_ENABLED:
        _register_dataforseo_tools(agent)
    _register_web_search_tool(agent)
```

(`_register_nexlev_tools(agent)` is added in Task 7 — do not add it
here yet, so this task's test only asserts on the DataForSEO flag.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_agent.py -v`
Expected: PASS — including the two new tests and all pre-existing ones
(pre-existing tests don't set `DATAFORSEO_ENABLED`, so they run against
the settings default of `False`; `test_agent_registers_tools_and_
validates_output`'s `expected_tools <= set(fake.tools)` assertion still
passes since `<=` only checks the expected tools are present, and
`test_registered_tools_call_provider_clients` will now fail because
`youtube_search`/`video_info`/`video_comments`/`video_subtitles` are no
longer registered by default — fix it in Step 5).

- [ ] **Step 5: Update the pre-existing provider-client test for the new default**

In `tests/test_apps/test_channel_research/test_agent.py`, add
`from django.test import override_settings` (if not already added in
Step 1) and wrap `test_registered_tools_call_provider_clients` with
`@override_settings(DATAFORSEO_ENABLED=True, NEXLEV_ENABLED=False)` so it
keeps testing the DataForSEO path explicitly rather than relying on the
(now-disabled) default:

```python
@override_settings(DATAFORSEO_ENABLED=True, NEXLEV_ENABLED=False)
def test_registered_tools_call_provider_clients() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-tools')
    ...  # body unchanged
```

- [ ] **Step 6: Run the full channel_research test suite**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/ -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add server/apps/channel_research/agent.py \
  tests/test_apps/test_channel_research/test_agent.py
git commit -m "feat(channel_research): disable DataForSEO tools behind a settings flag"
```

---

## Task 7: Add NexLev tools to the channel-research agent

**Files:**
- Modify: `server/apps/channel_research/agent.py`
- Modify: `.importlinter`
- Modify: `tests/test_apps/test_channel_research/test_agent.py`

**Interfaces:**
- Consumes: `server.apps.nexlev.services.NexLevService` (Tasks 3-4).
- Produces: `_register_nexlev_tools(agent)` registering tools
  `youtube_search`, `video_info`, `video_comments`, `video_subtitles`
  (NexLev-backed, same names as the DataForSEO tools they replace) plus
  new `channel_about`, `channel_outliers`, `similar_channels`. Extends
  `TOOL_CAPS` with `channel_about: 1`, `channel_outliers: 1`,
  `similar_channels: 1`.

- [ ] **Step 1: Declare the cross-app import in `.importlinter`**

In `.importlinter`, under `[importlinter:contract:apps-independence]`,
add after the existing channel_research/generation-clients lines
(after line 45, `server.apps.channel_research.agent ->
server.apps.generation.clients.youtube_search`):

```
  # Channel research agent uses NexLev as its YouTube data provider
  # (same provider-library pattern as the generation clients above)
  server.apps.channel_research.agent -> server.apps.nexlev.services
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_apps/test_channel_research/test_agent.py`:

```python
@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_nexlev_tools_registered_when_enabled() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-nexlev-on')
    expected = {
        'youtube_search',
        'video_info',
        'video_comments',
        'video_subtitles',
        'channel_about',
        'channel_outliers',
        'similar_channels',
    }
    assert expected <= set(fake.tools)


@override_settings(DATAFORSEO_ENABLED=False, NEXLEV_ENABLED=True)
def test_nexlev_tools_call_service_and_record_trace() -> None:
    _agent.cache_clear()
    with patch('server.apps.channel_research.agent.Agent', _FakeAgent):
        fake = _agent('unit-test-nexlev-tools')
    ctx = SimpleNamespace(deps=_deps())

    from server.apps.nexlev.logic.value_objects import (
        NexLevChannelAbout,
        NexLevOutlierVideo,
        NexLevSimilarChannel,
        NexLevSearchResultItem,
        NexLevVideoDetails,
        NexLevTranscriptSegment,
        NexLevComment,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.search_youtube',
                new=AsyncMock(
                    return_value=[NexLevSearchResultItem(type='video', title='hit')],
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_video_details',
                new=AsyncMock(
                    return_value=NexLevVideoDetails(id='v1', title='X'),
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_video_comments',
                new=AsyncMock(
                    return_value=[NexLevComment(comment_id='c1')],
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_video_transcript',
                new=AsyncMock(
                    return_value=[NexLevTranscriptSegment(
                        start_ms='0',
                        end_ms='100',
                    )],
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_channel_about',
                new=AsyncMock(
                    return_value=NexLevChannelAbout(
                        channel_id='UC1',
                        title='X',
                    ),
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_channel_outliers',
                new=AsyncMock(
                    return_value=[
                        NexLevOutlierVideo(video_id='v1', title='Hit'),
                    ],
                ),
            ),
            patch(
                'server.apps.channel_research.agent.NexLevService'
                '.get_similar_channels',
                new=AsyncMock(
                    return_value=[
                        NexLevSimilarChannel(
                            channel_id='UC2',
                            channel_name='Rival',
                        ),
                    ],
                ),
            ),
        ):
            search = await fake.tools['youtube_search'](ctx, keyword='rome')
            info = await fake.tools['video_info'](ctx, video_id='v1')
            comments = await fake.tools['video_comments'](ctx, video_id='v1')
            subs = await fake.tools['video_subtitles'](ctx, video_id='v1')
            about = await fake.tools['channel_about'](ctx, channel_id='UC1')
            outliers = await fake.tools['channel_outliers'](
                ctx,
                channel_id='UC1',
            )
            similar = await fake.tools['similar_channels'](
                ctx,
                channel_id='UC1',
            )
            return {
                'search': search,
                'info': info,
                'comments': comments,
                'subs': subs,
                'about': about,
                'outliers': outliers,
                'similar': similar,
            }

    results = asyncio.run(_inner())
    assert results['search'][0]['title'] == 'hit'
    assert results['info']['id'] == 'v1'
    assert results['about']['channelId'] == 'UC1'
    assert len(ctx.deps.trace.entries) == 7
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_agent.py::test_nexlev_tools_registered_when_enabled -v`
Expected: FAIL — `_register_nexlev_tools` doesn't exist yet.

- [ ] **Step 4: Add TOOL_CAPS entries, the NexLevService import, and `_register_nexlev_tools`**

In `server/apps/channel_research/agent.py`, add the import (alongside
the other `server.apps.generation.clients` imports, after line 19):

```python
from server.apps.nexlev.services import NexLevService
```

Extend `TOOL_CAPS` (lines 28-36):

```python
TOOL_CAPS: dict[str, int] = {
    'resolve_channel': 1,
    'list_channel_videos': 2,
    'youtube_search': 5,
    'video_info': 8,
    'video_comments': 3,
    'video_subtitles': 2,
    'web_search': 4,
    'channel_about': 1,
    'channel_outliers': 1,
    'similar_channels': 1,
}
```

Update `_register_tools` (from Task 6) to also register NexLev tools:

```python
    if settings.DATAFORSEO_ENABLED:
        _register_dataforseo_tools(agent)
    if settings.NEXLEV_ENABLED:
        _register_nexlev_tools(agent)
    _register_web_search_tool(agent)
```

Add `_register_nexlev_tools`, right after `_register_dataforseo_tools`
(after line 352):

```python
def _register_nexlev_tools(
    agent: Agent[ChannelResearchDeps, ChannelResearchAgentOutput],
) -> None:
    """Attach NexLev-backed YouTube data tools (replaces DataForSEO)."""
    service = NexLevService()

    @agent.tool
    async def youtube_search(
        ctx: RunContext[ChannelResearchDeps],
        keyword: str,
    ) -> list[dict[str, Any]]:
        """Search YouTube live via NexLev for videos and channels.

        Use for competitors and adjacent formats. Cap 5 queries.
        """
        ctx.deps.trace.consume('youtube_search')
        items = await service.search_youtube(keyword)
        result = [msgspec.to_builtins(item) for item in items]
        ctx.deps.trace.record('youtube_search', {'keyword': keyword}, result)
        return result

    @agent.tool
    async def video_info(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> dict[str, Any]:
        """Fetch NexLev video metadata for one video_id. Cap 8."""
        ctx.deps.trace.consume('video_info')
        details = await service.get_video_details(video_id)
        result = msgspec.to_builtins(details)
        ctx.deps.trace.record('video_info', {'video_id': video_id}, result)
        return result

    @agent.tool
    async def video_comments(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch comment themes for audience language. Cap 3."""
        ctx.deps.trace.consume('video_comments')
        comments = await service.get_video_comments(video_id)
        result = [msgspec.to_builtins(c) for c in comments]
        ctx.deps.trace.record(
            'video_comments',
            {'video_id': video_id},
            result,
        )
        return result

    @agent.tool
    async def video_subtitles(
        ctx: RunContext[ChannelResearchDeps],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch the transcript for pacing/format. Expensive - cap 2."""
        ctx.deps.trace.consume('video_subtitles')
        segments = await service.get_video_transcript(video_id)
        result = [msgspec.to_builtins(s) for s in segments]
        ctx.deps.trace.record(
            'video_subtitles',
            {'video_id': video_id},
            result,
        )
        return result

    @agent.tool
    async def channel_about(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
    ) -> dict[str, Any]:
        """Fetch channel about-info (subs, description, links). Cap 1."""
        ctx.deps.trace.consume('channel_about')
        about = await service.get_channel_about(channel_id)
        result = msgspec.to_builtins(about)
        ctx.deps.trace.record(
            'channel_about',
            {'channel_id': channel_id},
            result,
        )
        return result

    @agent.tool
    async def channel_outliers(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch the channel's highest-performing videos. Cap 1."""
        ctx.deps.trace.consume('channel_outliers')
        outliers = await service.get_channel_outliers(channel_id)
        result = [msgspec.to_builtins(o) for o in outliers]
        ctx.deps.trace.record(
            'channel_outliers',
            {'channel_id': channel_id},
            result,
        )
        return result

    @agent.tool
    async def similar_channels(
        ctx: RunContext[ChannelResearchDeps],
        channel_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch channels similar to this one for competitor mapping. Cap 1."""
        ctx.deps.trace.consume('similar_channels')
        similar = await service.get_similar_channels(channel_id)
        result = [msgspec.to_builtins(s) for s in similar]
        ctx.deps.trace.record(
            'similar_channels',
            {'channel_id': channel_id},
            result,
        )
        return result
```

Add `import msgspec` to the top imports of `agent.py` (it is not
currently imported there — needed for `msgspec.to_builtins`).

Also update the system prompt's tool-discipline bullet list (around
lines 61-68) to mention the new tools, and the docstring for the module
if desired — not required for tests to pass, but keep the prompt
accurate:

```python
Use tools with discipline:
- resolve_channel exactly once
- list_channel_videos up to twice (recent + popular)
- channel_about once, for subscriber count and links
- channel_outliers once, for the channel's best-performing videos
- similar_channels once, for competitor/niche mapping
- youtube_search for competitors/adjacent formats (cap 5)
- video_info on the strongest videos (cap 8)
- video_comments sparingly for audience language (cap 3)
- video_subtitles at most twice (expensive; pacing/format only)
- web_search for market/context (cap 4)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_agent.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 6: Run `lint-imports` to verify the new contract entry works**

Run: `docker compose exec web lint-imports`
Expected: PASS

- [ ] **Step 7: Run the full test suite and commit**

Run: `docker compose exec web pytest --no-cov -q`
Expected: PASS, no regressions

```bash
git add server/apps/channel_research/agent.py .importlinter \
  tests/test_apps/test_channel_research/test_agent.py
git commit -m "feat(channel_research): add NexLev-backed research tools"
```

---

## Task 8: ChannelResearchJob deep-analysis fields, constants, and selectors

**Files:**
- Modify: `server/apps/channel_research/logic/constants.py`
- Modify: `server/apps/channel_research/models.py`
- Modify: `server/apps/channel_research/logic/value_objects.py`
- Modify: `server/apps/channel_research/selectors.py`
- Modify: `.importlinter`
- Test: `tests/test_apps/test_channel_research/test_selectors.py`
  (create if it doesn't already exist — check first with `find
  tests/test_apps/test_channel_research -name 'test_selectors.py'`; if it
  exists, add to it instead of overwriting)

**Interfaces:**
- Consumes: `server.apps.nexlev.logic.value_objects.
  NexLevChannelAnalysisResult` (Task 2).
- Produces: `ChannelResearchJob.deep_analysis_status` (TextChoices field),
  `.deep_analysis_job_id`, `.deep_analysis_result`,
  `.deep_analysis_error_message`. `DeepAnalysisStatus(TextChoices)` in
  `logic/constants.py`. `ChannelResearchJobPayload.deep_analysis_status:
  DeepAnalysisStatusLiteral`, `.deep_analysis_result:
  NexLevChannelAnalysisResult | None`, `.deep_analysis_job_id: str`,
  `.deep_analysis_error_message: str`. `selectors._as_deep_analysis(raw:
  object) -> NexLevChannelAnalysisResult | None`.

- [ ] **Step 1: Declare the cross-app imports in `.importlinter`**

Add after the line added in Task 7:

```
  server.apps.channel_research.logic.value_objects -> server.apps.nexlev.logic.value_objects
  server.apps.channel_research.selectors -> server.apps.nexlev.logic.value_objects
```

- [ ] **Step 2: Write the failing model + selector test**

Create (or append to) `tests/test_apps/test_channel_research/test_selectors.py`:

```python
"""Tests for channel research selectors, including deep-analysis mapping."""

import pytest

from server.apps.channel_research.logic.constants import DeepAnalysisStatus
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.selectors import job_to_payload
from server.apps.nexlev.logic.value_objects import NexLevChannelAnalysisResult


@pytest.mark.django_db
def test_job_to_payload_defaults_deep_analysis_to_not_started(
    research_job: ChannelResearchJob,
) -> None:
    payload = job_to_payload(research_job)
    assert payload.deep_analysis_status == DeepAnalysisStatus.NOT_STARTED
    assert payload.deep_analysis_result is None
    assert payload.deep_analysis_job_id == ''
    assert payload.deep_analysis_error_message == ''


@pytest.mark.django_db
def test_job_to_payload_maps_completed_deep_analysis(
    research_job: ChannelResearchJob,
) -> None:
    result = NexLevChannelAnalysisResult(
        suggested_topics=[],
        script_blueprint=[],
        title_format_groups=[],
    )
    research_job.deep_analysis_status = DeepAnalysisStatus.SUCCEEDED
    research_job.deep_analysis_job_id = 'nexlev-job-1'
    research_job.deep_analysis_result = {
        'suggested_topics': [],
        'script_blueprint': [],
        'title_format_groups': [],
    }
    research_job.save()

    payload = job_to_payload(research_job)
    assert payload.deep_analysis_status == DeepAnalysisStatus.SUCCEEDED
    assert payload.deep_analysis_job_id == 'nexlev-job-1'
    assert payload.deep_analysis_result == result
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_selectors.py -v`
Expected: FAIL — `ImportError: cannot import name 'DeepAnalysisStatus'`

- [ ] **Step 4: Add `DeepAnalysisStatus` to constants**

Append to `server/apps/channel_research/logic/constants.py`:

```python
class DeepAnalysisStatus(models.TextChoices):
    """Lifecycle of the operator-triggered NexLev Deep Analysis action."""

    NOT_STARTED = 'NOT_STARTED', 'Not started'
    RUNNING = 'RUNNING', 'Running'
    SUCCEEDED = 'SUCCEEDED', 'Succeeded'
    FAILED = 'FAILED', 'Failed'
```

- [ ] **Step 5: Add model fields and a migration**

In `server/apps/channel_research/models.py`, add after `error_message`
(line 38):

```python
    deep_analysis_status = models.CharField(
        max_length=12,
        choices=DeepAnalysisStatus.choices,
        default=DeepAnalysisStatus.NOT_STARTED,
    )
    deep_analysis_job_id = models.CharField(max_length=64, blank=True)
    deep_analysis_result = models.JSONField(null=True, blank=True)
    deep_analysis_error_message = models.TextField(blank=True)
```

Update the import at the top of `models.py`:

```python
from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
    DeepAnalysisStatus,
)
```

Add a matching `CheckConstraint` in `Meta.constraints` (after the
existing two, line 61):

```python
            models.CheckConstraint(
                name='channel_research_job_deep_analysis_status_valid',
                condition=models.Q(
                    deep_analysis_status__in=DeepAnalysisStatus.values,
                ),
            ),
```

Run: `just run makemigrations channel_research`

- [ ] **Step 6: Add value objects for the deep-analysis payload**

In `server/apps/channel_research/logic/value_objects.py`, add the import:

```python
from server.apps.channel_research.logic.constants import DeepAnalysisStatus
from server.apps.nexlev.logic.value_objects import NexLevChannelAnalysisResult
```

and a type alias in `logic/types.py` — check the file first for the
existing `Literal` pattern used by `ChannelResearchStatusLiteral`, then
add:

```python
DeepAnalysisStatusLiteral = Literal[
    'NOT_STARTED',
    'RUNNING',
    'SUCCEEDED',
    'FAILED',
]
```

Extend `ChannelResearchJobPayload` in `value_objects.py` (after
`updated_at`, line 274):

```python
    deep_analysis_status: DeepAnalysisStatusLiteral
    deep_analysis_job_id: str
    deep_analysis_result: NexLevChannelAnalysisResult | None
    deep_analysis_error_message: str
```

- [ ] **Step 7: Wire the new fields into `job_to_payload`**

In `server/apps/channel_research/selectors.py`, add the import:

```python
from server.apps.nexlev.logic.value_objects import NexLevChannelAnalysisResult
```

Add a helper next to `_as_usage` (after line 48):

```python
def _as_deep_analysis(raw: object) -> NexLevChannelAnalysisResult | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return msgspec.convert(raw, type=NexLevChannelAnalysisResult)
```

Extend the `job_to_payload` return (after `updated_at=_iso(job.updated_at),`
line 71):

```python
        deep_analysis_status=job.deep_analysis_status,  # type: ignore[arg-type]
        deep_analysis_job_id=job.deep_analysis_job_id,
        deep_analysis_result=_as_deep_analysis(job.deep_analysis_result),
        deep_analysis_error_message=job.deep_analysis_error_message,
```

- [ ] **Step 8: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_selectors.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Run `lint-imports` and the full channel_research suite**

Run: `docker compose exec web lint-imports`
Run: `docker compose exec web pytest tests/test_apps/test_channel_research/ -v`
Expected: PASS (existing tests that build `ChannelResearchJobPayload`
directly — e.g. any polyfactory-based test — may need
`ChannelResearchJobPayload` factory usage checked; if a test constructs
`ChannelResearchJobPayload` with keyword args instead of via
`job_to_payload`, add the four new required fields there too)

- [ ] **Step 10: Commit**

```bash
git add server/apps/channel_research/logic server/apps/channel_research/models.py \
  server/apps/channel_research/selectors.py server/apps/channel_research/migrations \
  .importlinter tests/test_apps/test_channel_research/test_selectors.py
git commit -m "feat(channel_research): add deep-analysis fields and selector mapping"
```

---

## Task 9: Deep Analysis service methods and TaskIQ task

**Files:**
- Modify: `server/apps/channel_research/services.py`
- Modify: `server/apps/channel_research/tasks.py`
- Modify: `.importlinter`
- Test: `tests/test_apps/test_channel_research/test_services.py`
  (create if missing — check first)
- Test: `tests/test_apps/test_channel_research/test_tasks.py`
  (create if missing — check first)

**Interfaces:**
- Consumes: `NexLevService` (Task 5), `kiq_task` (existing), `research_job`
  fixture (existing, `tests/test_apps/test_channel_research/conftest.py`).
- Produces: `ChannelResearchService.trigger_deep_analysis(job_id: str) ->
  ChannelResearchJobPayload`, `.apply_suggested_topics(job_id: str) ->
  ChannelResearchJobPayload`. `channel_research.tasks.
  run_deep_analysis_task(job_id: str) -> None` (TaskIQ task).

- [ ] **Step 1: Declare the cross-app import in `.importlinter`**

Add after the lines from Task 8:

```
  server.apps.channel_research.tasks -> server.apps.nexlev.services
```

- [ ] **Step 2: Write the failing service test**

Create `tests/test_apps/test_channel_research/test_services.py` if it
doesn't exist yet (check first — if it exists, append these tests):

```python
"""Tests for ChannelResearchService — deep analysis and topic merging."""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
    DeepAnalysisStatus,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.services import ChannelResearchService


@pytest.mark.django_db
def test_trigger_deep_analysis_enqueues_and_sets_running(
    research_job: ChannelResearchJob,
) -> None:
    research_job.source_channel_id = 'UC1'
    research_job.save(update_fields=['source_channel_id'])
    with patch(
        'server.apps.channel_research.services.kiq_task',
    ) as mock_kiq:
        payload = ChannelResearchService().trigger_deep_analysis(
            str(research_job.id),
        )
    mock_kiq.assert_called_once()
    assert payload.deep_analysis_status == DeepAnalysisStatus.RUNNING


@pytest.mark.django_db
def test_trigger_deep_analysis_requires_source_channel_id(
    research_job: ChannelResearchJob,
) -> None:
    with pytest.raises(ValidationError, match='source_channel_id'):
        ChannelResearchService().trigger_deep_analysis(str(research_job.id))


@pytest.mark.django_db
def test_apply_suggested_topics_merges_into_seed_ideas(
    research_job: ChannelResearchJob,
) -> None:
    research_job.status = ChannelResearchStatus.SUCCEEDED
    research_job.channel_spec = {
        'channel': {'name': 'X', 'kind': ChannelResearchKind.LONGFORM},
        'niche': {'angle': 'a'},
        'story_format': {'key': 'k', 'name': 'n'},
        'seed_ideas': [{'title': 'Existing', 'topic': 'existing topic'}],
    }
    research_job.deep_analysis_status = DeepAnalysisStatus.SUCCEEDED
    research_job.deep_analysis_result = {
        'suggested_topics': [
            {'title': 'New Idea', 'description': 'new topic'},
        ],
        'script_blueprint': [],
        'title_format_groups': [],
    }
    research_job.save()

    payload = ChannelResearchService().apply_suggested_topics(
        str(research_job.id),
    )

    titles = [idea.title for idea in payload.channel_spec.seed_ideas]
    assert 'Existing' in titles
    assert 'New Idea' in titles


@pytest.mark.django_db
def test_apply_suggested_topics_requires_completed_deep_analysis(
    research_job: ChannelResearchJob,
) -> None:
    research_job.status = ChannelResearchStatus.SUCCEEDED
    research_job.channel_spec = {
        'channel': {'name': 'X', 'kind': ChannelResearchKind.LONGFORM},
        'niche': {'angle': 'a'},
        'story_format': {'key': 'k', 'name': 'n'},
    }
    research_job.save()
    with pytest.raises(ValidationError, match='deep_analysis'):
        ChannelResearchService().apply_suggested_topics(str(research_job.id))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_services.py -v`
Expected: FAIL — `AttributeError: 'ChannelResearchService' object has no
attribute 'trigger_deep_analysis'`

- [ ] **Step 4: Implement the two service methods**

In `server/apps/channel_research/services.py`, add to the imports:

```python
from server.apps.channel_research.logic.constants import DeepAnalysisStatus
from server.apps.channel_research.logic.value_objects import (
    ChannelSpecSeedIdeaPayload,
)
```

(`DeepAnalysisStatus` joins the existing `ChannelResearchKind,
ChannelResearchStatus` import; `ChannelSpecSeedIdeaPayload` joins the
existing `logic.value_objects` import block.)

Add module-level constants and helpers near `_RETRYABLE_STATUSES`
(line 41):

```python
_DEEP_ANALYSIS_APPLICABLE_STATUSES = frozenset({
    DeepAnalysisStatus.SUCCEEDED,
})
_MAX_MERGED_SEED_IDEAS = 12


def _validate_source_channel_id(job: ChannelResearchJob) -> str:
    if not job.source_channel_id:
        msg = 'source_channel_id is required before Deep Analysis can run'
        raise ValidationError(msg)
    return job.source_channel_id
```

Add the two methods to `ChannelResearchService`, after `retry` (line 195):

```python
    def trigger_deep_analysis(self, job_id: str) -> ChannelResearchJobPayload:
        """Kick off NexLev's async Deep Analysis job for this channel."""
        job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
        _validate_source_channel_id(job)
        job.deep_analysis_status = DeepAnalysisStatus.RUNNING
        job.deep_analysis_error_message = ''
        job.save(
            update_fields=[
                'deep_analysis_status',
                'deep_analysis_error_message',
                'updated_at',
            ],
        )
        from server.apps.channel_research.tasks import (  # noqa: PLC0415
            run_deep_analysis_task,
        )

        kiq_task(run_deep_analysis_task, str(job.id))
        return job_to_payload(job)

    def apply_suggested_topics(
        self,
        job_id: str,
    ) -> ChannelResearchJobPayload:
        """Merge NexLev's suggested_topics into channel_spec.seed_ideas."""
        job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
        if job.deep_analysis_status not in _DEEP_ANALYSIS_APPLICABLE_STATUSES:
            msg = (
                'deep_analysis must be SUCCEEDED before applying suggested'
                ' topics'
            )
            raise ValidationError(msg)
        result = job.deep_analysis_result or {}
        topics = result.get('suggested_topics', [])
        existing = list(job.channel_spec.get('seed_ideas', []))
        new_ideas = [
            msgspec.to_builtins(
                ChannelSpecSeedIdeaPayload(
                    title=topic['title'][:200],
                    topic=topic.get('description', ''),
                ),
            )
            for topic in topics
        ]
        merged = (existing + new_ideas)[:_MAX_MERGED_SEED_IDEAS]
        job.channel_spec = {**job.channel_spec, 'seed_ideas': merged}
        job.save(update_fields=['channel_spec', 'updated_at'])
        return job_to_payload(job)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_services.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Write the failing task test**

Create `tests/test_apps/test_channel_research/test_tasks.py` if it
doesn't exist (check first — if it exists, append):

```python
"""Tests for the run_deep_analysis_task TaskIQ task."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.channel_research.logic.constants import DeepAnalysisStatus
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.tasks import _run_deep_analysis


@pytest.mark.django_db
def test_run_deep_analysis_stores_result_on_success(
    research_job: ChannelResearchJob,
) -> None:
    research_job.source_channel_id = 'UC1'
    research_job.save(update_fields=['source_channel_id'])

    with (
        patch(
            'server.apps.channel_research.tasks.NexLevService'
            '.create_channel_analysis_job',
            new=AsyncMock(return_value='nexlev-job-1'),
        ),
        patch(
            'server.apps.channel_research.tasks.NexLevService'
            '.get_channel_analysis_result',
            new=AsyncMock(
                return_value=type(
                    'R',
                    (),
                    {
                        'suggested_topics': [],
                        'script_blueprint': [],
                        'title_format_groups': [],
                    },
                )(),
            ),
        ),
        patch('server.apps.channel_research.tasks.msgspec.to_builtins')
        as mock_to_builtins,
    ):
        mock_to_builtins.return_value = {
            'suggested_topics': [],
            'script_blueprint': [],
            'title_format_groups': [],
        }
        asyncio.run(_run_deep_analysis(str(research_job.id)))

    research_job.refresh_from_db()
    assert research_job.deep_analysis_status == DeepAnalysisStatus.SUCCEEDED
    assert research_job.deep_analysis_job_id == 'nexlev-job-1'


@pytest.mark.django_db
def test_run_deep_analysis_marks_failed_on_timeout(
    research_job: ChannelResearchJob,
) -> None:
    research_job.source_channel_id = 'UC1'
    research_job.save(update_fields=['source_channel_id'])

    with (
        patch(
            'server.apps.channel_research.tasks.NexLevService'
            '.create_channel_analysis_job',
            new=AsyncMock(return_value='nexlev-job-1'),
        ),
        patch(
            'server.apps.channel_research.tasks.NexLevService'
            '.get_channel_analysis_result',
            new=AsyncMock(return_value=None),
        ),
        patch('server.apps.channel_research.tasks.asyncio.sleep', new=AsyncMock()),
    ):
        asyncio.run(_run_deep_analysis(str(research_job.id)))

    research_job.refresh_from_db()
    assert research_job.deep_analysis_status == DeepAnalysisStatus.FAILED
    assert 'timed out' in research_job.deep_analysis_error_message
```

- [ ] **Step 7: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_tasks.py -v`
Expected: FAIL — `ImportError: cannot import name '_run_deep_analysis'`

- [ ] **Step 8: Implement `_run_deep_analysis` and `run_deep_analysis_task`**

In `server/apps/channel_research/tasks.py`, add to the imports:

```python
import asyncio

import msgspec

from server.apps.channel_research.logic.constants import DeepAnalysisStatus
from server.apps.nexlev.services import NexLevService
```

Add constants near the top (after `logger = structlog.get_logger(__name__)`,
line 22):

```python
_MAX_POLL_ATTEMPTS = 12
_POLL_INTERVAL_SECONDS = 10.0
_TIMEOUT_MESSAGE = (
    'NexLev Deep Analysis timed out after 120s; retry from the job'
    ' detail page.'
)
```

Add helper functions next to `_mark_failed` (after line 68):

```python
def _mark_deep_analysis_running(job_id: str) -> ChannelResearchJob:
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    job.deep_analysis_status = DeepAnalysisStatus.RUNNING
    job.deep_analysis_error_message = ''
    job.save(
        update_fields=[
            'deep_analysis_status',
            'deep_analysis_error_message',
            'updated_at',
        ],
    )
    return job


def _store_deep_analysis_job_id(job_id: str, nexlev_job_id: str) -> None:
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    job.deep_analysis_job_id = nexlev_job_id
    job.save(update_fields=['deep_analysis_job_id', 'updated_at'])


def _mark_deep_analysis_succeeded(job_id: str, result: Any) -> None:
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    job.deep_analysis_status = DeepAnalysisStatus.SUCCEEDED
    job.deep_analysis_result = msgspec.to_builtins(result)
    job.deep_analysis_error_message = ''
    job.save(
        update_fields=[
            'deep_analysis_status',
            'deep_analysis_result',
            'deep_analysis_error_message',
            'updated_at',
        ],
    )


def _mark_deep_analysis_failed(job_id: str, message: str) -> None:
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    job.deep_analysis_status = DeepAnalysisStatus.FAILED
    job.deep_analysis_error_message = message[:2000]
    job.save(
        update_fields=[
            'deep_analysis_status',
            'deep_analysis_error_message',
            'updated_at',
        ],
    )


async def _run_deep_analysis(job_id: str) -> None:
    job = await sync_to_async(_mark_deep_analysis_running)(job_id)
    service = NexLevService()
    try:
        nexlev_job_id = await service.create_channel_analysis_job(
            job.source_channel_id,
        )
        await sync_to_async(_store_deep_analysis_job_id)(
            job_id,
            nexlev_job_id,
        )
        result = None
        for _attempt in range(_MAX_POLL_ATTEMPTS):
            result = await service.get_channel_analysis_result(
                nexlev_job_id,
                job.source_channel_id,
            )
            if result is not None:
                break
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        if result is None:
            await sync_to_async(_mark_deep_analysis_failed)(
                job_id,
                _TIMEOUT_MESSAGE,
            )
            return
        await sync_to_async(_mark_deep_analysis_succeeded)(job_id, result)
    except Exception as exc:
        logger.exception('deep_analysis_failed', job_id=job_id)
        await sync_to_async(_mark_deep_analysis_failed)(job_id, str(exc))


@api_broker.task(retry_on_error=False)
async def run_deep_analysis_task(job_id: str) -> None:
    """Run NexLev's async channel-analysis job and store its result."""
    await _run_deep_analysis(job_id)
```

- [ ] **Step 9: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_tasks.py -v`
Expected: PASS (2 tests)

- [ ] **Step 10: Run `lint-imports` and the full channel_research suite, then commit**

Run: `docker compose exec web lint-imports`
Run: `docker compose exec web pytest tests/test_apps/test_channel_research/ -v`
Expected: PASS

```bash
git add server/apps/channel_research/services.py server/apps/channel_research/tasks.py \
  .importlinter tests/test_apps/test_channel_research/test_services.py \
  tests/test_apps/test_channel_research/test_tasks.py
git commit -m "feat(channel_research): add Deep Analysis trigger, task, and topic merge"
```

---

## Task 10: API endpoints and final verification

**Files:**
- Modify: `server/apps/channel_research/api/views.py`
- Modify: `server/apps/channel_research/api/urls.py`
- Test: `tests/test_apps/test_channel_research/test_api_views.py`
- Test: `tests/test_apps/test_channel_research/test_api.py`

**Interfaces:**
- Consumes: `ChannelResearchService.trigger_deep_analysis`/
  `.apply_suggested_topics` (Task 9).
- Produces: `POST /api/channel-research/<job_id>/deep-analysis/` and
  `POST /api/channel-research/<job_id>/deep-analysis/apply-topics/`.

- [ ] **Step 1: Write the failing DMR unit test**

Add to `tests/test_apps/test_channel_research/test_api_views.py` (open
the file first to match its existing per-controller test structure
exactly, then add a parallel block for the two new controllers):

```python
from unittest.mock import MagicMock

from server.apps.channel_research.api import views


def test_deep_analysis_controller_calls_service() -> None:
    controller = views.ChannelResearchDeepAnalysisController()
    controller.kwargs = {'job_id': 'job-1'}
    mock_service = MagicMock()
    controller.resolve = MagicMock(return_value=mock_service)
    controller.request = MagicMock()
    with patch(
        'server.apps.channel_research.api.views.get_request_user',
    ), patch('server.apps.channel_research.api.views.require_operator'):
        controller.post()
    mock_service.trigger_deep_analysis.assert_called_once_with('job-1')


def test_apply_suggested_topics_controller_calls_service() -> None:
    controller = views.ChannelResearchApplySuggestedTopicsController()
    controller.kwargs = {'job_id': 'job-1'}
    mock_service = MagicMock()
    controller.resolve = MagicMock(return_value=mock_service)
    controller.request = MagicMock()
    with patch(
        'server.apps.channel_research.api.views.get_request_user',
    ), patch('server.apps.channel_research.api.views.require_operator'):
        controller.post()
    mock_service.apply_suggested_topics.assert_called_once_with('job-1')
```

(Add `from unittest.mock import patch` to the file's imports if not
already present — check first.)

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_api_views.py -v`
Expected: FAIL — `AttributeError: module 'views' has no attribute
'ChannelResearchDeepAnalysisController'`

- [ ] **Step 3: Add the two controllers and routes**

In `server/apps/channel_research/api/views.py`, add after
`ChannelResearchRetryController` (after line 203):

```python
@final
class ChannelResearchDeepAnalysisController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Trigger NexLev's async Deep Analysis job for this channel."""

    auth = (jwt_sync_auth,)

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def post(self) -> ChannelResearchJobPayload:
        """Kick off Deep Analysis; poll job-detail GET for completion."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelResearchService).trigger_deep_analysis(
            str(self.kwargs['job_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        mapped = _validation_or_not_found(self, endpoint, exc)
        if mapped is not None:
            return mapped
        return super().handle_error(endpoint, controller, exc)


@final
class ChannelResearchApplySuggestedTopicsController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Merge NexLev's suggested_topics into channel_spec.seed_ideas."""

    auth = (jwt_sync_auth,)

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def post(self) -> ChannelResearchJobPayload:
        """Apply Deep Analysis suggested topics onto the job's spec."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelResearchService).apply_suggested_topics(
            str(self.kwargs['job_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        mapped = _validation_or_not_found(self, endpoint, exc)
        if mapped is not None:
            return mapped
        return super().handle_error(endpoint, controller, exc)
```

In `server/apps/channel_research/api/urls.py`, add after the
`job-retry` path (after line 34):

```python
    path(
        'channel-research/<uuid:job_id>/deep-analysis/',
        views.ChannelResearchDeepAnalysisController.as_view(),
        name='job-deep-analysis',
    ),
    path(
        'channel-research/<uuid:job_id>/deep-analysis/apply-topics/',
        views.ChannelResearchApplySuggestedTopicsController.as_view(),
        name='job-apply-suggested-topics',
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_api_views.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Write the failing full DMR API test**

Open `tests/test_apps/test_channel_research/test_api.py` first to copy
its exact `dmr_client`/`auth_headers`/`reverse` pattern for an existing
endpoint (e.g. `job-retry`), then add:

```python
@pytest.mark.django_db(transaction=True)
def test_deep_analysis_endpoint_requires_source_channel_id(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
    research_job: ChannelResearchJob,
) -> None:
    url = reverse(
        'api:channel_research_api:job-deep-analysis',
        kwargs={'job_id': research_job.id},
    )
    response = dmr_client.post(url, headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.django_db(transaction=True)
def test_deep_analysis_endpoint_enqueues_when_channel_id_present(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
    research_job: ChannelResearchJob,
) -> None:
    research_job.source_channel_id = 'UC1'
    research_job.save(update_fields=['source_channel_id'])
    url = reverse(
        'api:channel_research_api:job-deep-analysis',
        kwargs={'job_id': research_job.id},
    )
    with patch('server.apps.channel_research.services.kiq_task'):
        response = dmr_client.post(url, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()['deep_analysis_status'] == 'RUNNING'
```

(Match the exact imports — `DMRClient`, `reverse`, `patch` — already
used elsewhere in this file; add only what's missing.)

- [ ] **Step 6: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_channel_research/test_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit the API layer**

```bash
git add server/apps/channel_research/api tests/test_apps/test_channel_research/test_api_views.py \
  tests/test_apps/test_channel_research/test_api.py
git commit -m "feat(channel_research): add Deep Analysis API endpoints"
```

- [ ] **Step 8: Final full verification**

Run each of these and fix anything they surface before considering the
plan complete:

```bash
docker compose exec web pytest -q
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web mypy server
docker compose exec web lint-imports
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```

Expected: all pass, `pytest -q` reports 100% coverage (the
`--cov-fail-under=100` gate from `pyproject.toml`).

- [ ] **Step 9: Final commit if anything was fixed in Step 8**

```bash
git add -A
git commit -m "fix: address lint/type/migration findings from NexLev integration verification"
```
