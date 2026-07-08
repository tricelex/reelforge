# Money-Loop Foundations (Milestone 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop from real YouTube demand and performance data back into
ideation, thumbnail selection, and metadata — replacing pure LLM invention with
data-grounded decisions, using only the free YouTube Data API v3 / YouTube Analytics API
(no paid third-party tools).

**Architecture:** New provider clients under `server/apps/generation/clients/` (same
shape as the existing `fal.py`/`youtube.py`/`search.py`), a small new `NicheOutlierScan`
and `PublishJobMetric` model, and two new scheduled `@broker.task` functions that follow
the exact pattern of the existing `analytics/tasks.py::refresh_analytics_views` and this
repo's Milestone-1 `pipelines/tasks.py::resume_publish_held_runs`.

**Tech Stack:** Django 6.0, `httpx` (YouTube API calls — same client already used in
`generation/clients/youtube.py`), `pydantic` (LLM/API schemas), `msgspec`/`attrs` (DTOs
and services).

**Prerequisite:** This plan assumes
`docs/superpowers/plans/2026-07-07-policy-risk-mitigations.md` (Milestone 1) is already
merged — it reuses `Channel.max_publishes_per_day`-style patterns and the
`pipelines/tasks.py` file Milestone 1 extends. Migration numbers below are illustrative
(`just makemigrations` assigns the real next number); if Milestone 1 hasn't landed yet,
the actual numbers will differ but the field/model changes are unaffected.

**Full design context:** `/Users/chuckz/.claude/plans/the-clipping-feature-is-misty-rossum.md`
(sections 2.1–2.4) — read this for the "why."

## Global Constraints

- Same as Milestone 1's plan: Python 3.13.x, Django 6.0.x, `ruff` single quotes/80-char,
  `mypy` strict, 100% coverage (`pytest --cov-fail-under=100`), migrations generated via
  `just run makemigrations <app_label>` (never hand-written) then
  `just run lintmigrations` + `just run check_migrations --exclude-apps=axes`, `@final`
  + `@attrs.define(slots=True, frozen=True)` for services, `msgspec.Struct(frozen=True)`
  for API DTOs, never `from __future__ import annotations` in punq-registered files.
- **No paid third-party APIs.** Every data source here is the YouTube Data API v3 or
  YouTube Analytics API, both free (quota-limited, not billed). Do not introduce
  OutlierKit/vidIQ/TubeBuddy or similar.
- **Quota discipline:** `search.list` has its own ~100-calls/day bucket (per the design
  doc's Costs section). Task 2 explicitly caches scan results — do not call
  `search_videos` more than once per niche per day anywhere in this codebase.
- **Tasks must be implemented in order 1 → 9** within this document — Task 3 depends on
  Task 2's model, Task 5 depends on Task 4's model, Task 6 depends on Task 4's model, and
  several tasks share migration sequencing within the same Django app (`publishing`
  0001→0002 in Task 6; `analytics` →0003 in Task 4; `assets` →0005 in Task 9).
- Run `docker compose exec web pytest <touched test paths> --no-cov` after each task's
  implementation, `docker compose exec web pytest --cov-fail-under=100` before that
  task's final commit, and `ruff check .` / `ruff format --check .` / `mypy server` /
  `lint-imports` before every commit — identical gate to Milestone 1.

---

### Task 1: YouTube search/outlier client

**Files:**
- Modify: `server/settings/components/common.py:486-487` (near `YOUTUBE_CLIENT_ID`)
- Create: `server/apps/generation/clients/youtube_search.py`
- Test: `tests/test_apps/test_generation/test_youtube_search.py`

**Interfaces:**
- Produces: `youtube_search.search_videos(query, api_key, published_after=None, max_results=25) -> list[dict]`,
  `youtube_search.get_video_statistics(video_ids, api_key) -> list[dict]`,
  `youtube_search.get_channel_statistics(channel_ids, api_key) -> list[dict]`,
  `youtube_search.compute_outlier_score(view_count, subscriber_count, days_since_publish) -> float`
  (pure — consumed by Task 2).

- [ ] **Step 1: Add the API key setting**

In `server/settings/components/common.py`, right after the existing block:
```python
YOUTUBE_CLIENT_ID: str = config('YOUTUBE_CLIENT_ID', default='')
YOUTUBE_CLIENT_SECRET: str = config('YOUTUBE_CLIENT_SECRET', default='')
```
add:
```python
YOUTUBE_DATA_API_KEY: str = config('YOUTUBE_DATA_API_KEY', default='')
```
(A simple API key — not the per-channel OAuth credential — since `search.list`/
`videos.list`/`channels.list` read public data and don't need a connected channel's
token. This mirrors how `EXA_API_KEY` is already read in `research.py` via
`getattr(settings, 'EXA_API_KEY', '')`.)

- [ ] **Step 2: Write the failing pure-function test**

Create `tests/test_apps/test_generation/test_youtube_search.py`:
```python
"""Tests for the YouTube search/outlier client."""

from server.apps.generation.clients.youtube_search import compute_outlier_score


def test_compute_outlier_score_views_exceed_subscribers() -> None:
    """A video with 5x its channel's subscriber count in views scores > 1.0."""
    score = compute_outlier_score(
        view_count=500_000,
        subscriber_count=100_000,
        days_since_publish=10,
    )
    assert score > 1.0


def test_compute_outlier_score_zero_subscribers_does_not_divide_by_zero() -> None:
    score = compute_outlier_score(
        view_count=1000,
        subscriber_count=0,
        days_since_publish=1,
    )
    assert score >= 0.0


def test_compute_outlier_score_recent_video_scores_higher_than_old() -> None:
    """Same views/subs ratio, but the more recent video scores higher (velocity)."""
    recent = compute_outlier_score(
        view_count=10_000, subscriber_count=10_000, days_since_publish=2,
    )
    old = compute_outlier_score(
        view_count=10_000, subscriber_count=10_000, days_since_publish=200,
    )
    assert recent > old
```

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_youtube_search.py -v --no-cov`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `compute_outlier_score`**

Create `server/apps/generation/clients/youtube_search.py`:
```python
"""YouTube Data API v3 client — public search/statistics for demand-grounded
ideation. Uses a simple API key (YOUTUBE_DATA_API_KEY), not per-channel OAuth,
since it only reads public video/channel data.
"""

from typing import Any

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
_VIDEOS_URL = 'https://www.googleapis.com/youtube/v3/videos'
_CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'
_MIN_DAYS_SINCE_PUBLISH = 0.5
_MIN_SUBSCRIBER_FLOOR = 1000


def _classify_response(resp: httpx.Response) -> None:
    if resp.status_code == httpx.codes.OK:
        return
    if resp.status_code in _RETRYABLE_CODES:
        raise RetryableProviderError(
            f'YouTube search API {resp.status_code}',
            provider='youtube_search',
            status_code=resp.status_code,
        )
    raise FatalProviderError(
        f'YouTube search API error {resp.status_code}: {resp.text[:300]}',
        provider='youtube_search',
    )


def compute_outlier_score(
    view_count: int,
    subscriber_count: int,
    days_since_publish: float,
) -> float:
    """Views-per-subscriber, boosted by recency (views accrued faster = higher)."""
    subs = max(subscriber_count, _MIN_SUBSCRIBER_FLOOR)
    days = max(days_since_publish, _MIN_DAYS_SINCE_PUBLISH)
    views_per_sub = view_count / subs
    recency_boost = 30.0 / days
    return views_per_sub * (1.0 + recency_boost)


async def search_videos(
    query: str,
    api_key: str,
    published_after: str | None = None,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    """youtube#search.list — up to max_results videos ordered by view count."""
    params: dict[str, Any] = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': max_results,
        'order': 'viewCount',
        'key': api_key,
    }
    if published_after:
        params['publishedAfter'] = published_after
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_SEARCH_URL, params=params)
    _classify_response(resp)
    return list(resp.json().get('items', []))


async def get_video_statistics(
    video_ids: list[str],
    api_key: str,
) -> list[dict[str, Any]]:
    """youtube#videos.list?part=statistics,snippet for a batch of video IDs."""
    if not video_ids:
        return []
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _VIDEOS_URL,
            params={
                'part': 'statistics,snippet',
                'id': ','.join(video_ids),
                'key': api_key,
            },
        )
    _classify_response(resp)
    return list(resp.json().get('items', []))


async def get_channel_statistics(
    channel_ids: list[str],
    api_key: str,
) -> list[dict[str, Any]]:
    """youtube#channels.list?part=statistics for a batch of channel IDs."""
    if not channel_ids:
        return []
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _CHANNELS_URL,
            params={
                'part': 'statistics',
                'id': ','.join(channel_ids),
                'key': api_key,
            },
        )
    _classify_response(resp)
    return list(resp.json().get('items', []))
```

- [ ] **Step 4: Add a client-level test for `search_videos` (mocked HTTP)**

Add to the same test file:
```python
def test_search_videos_returns_items() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.generation.clients.youtube_search import search_videos

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'items': [{'id': {'videoId': 'abc'}}]}

    async def _inner() -> list:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=fake_resp),
        ):
            return await search_videos('roman empire', api_key='key123')

    result = asyncio.run(_inner())
    assert result == [{'id': {'videoId': 'abc'}}]


def test_get_video_statistics_empty_ids_returns_empty_without_request() -> None:
    import asyncio

    from server.apps.generation.clients.youtube_search import get_video_statistics

    result = asyncio.run(get_video_statistics([], api_key='key'))
    assert result == []
```

- [ ] **Step 5: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_youtube_search.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add server/settings/components/common.py server/apps/generation/clients/youtube_search.py tests/test_apps/test_generation/test_youtube_search.py
git commit -m "feat(generation): add YouTube search/outlier client (Data API v3, free tier)"
```

---

### Task 2: Niche outlier scan (cached, once per day)

**Files:**
- Create: `server/apps/ideas/models.py` — add `NicheOutlierScan` (same file, append)
- Create migration: `just run makemigrations ideas`
- Modify: `server/apps/ideas/logic/schemas.py` — add `OutlierVideo`
- Create: `server/apps/ideas/outlier_scan.py`
- Test: `tests/test_apps/test_ideas/test_outlier_scan.py`

**Interfaces:**
- Consumes: `youtube_search.search_videos`/`get_video_statistics`/`get_channel_statistics`/`compute_outlier_score` (Task 1).
- Produces: `NicheOutlierScan` model, `outlier_scan.run_niche_outlier_scan(niche) -> list[OutlierVideo]`
  (does the real API calls, always writes a fresh scan row),
  `outlier_scan.get_cached_scan(niche_id) -> list[OutlierVideo]` (checks for a scan from
  the last 24h before calling the API; consumed by Task 3).

- [ ] **Step 1: Add `OutlierVideo` schema**

In `server/apps/ideas/logic/schemas.py`, add after `SourceSnapshot`:
```python
class OutlierVideo(pydantic.BaseModel):
    """One over-performing video surfaced by a niche outlier scan."""

    video_id: str
    title: str
    channel_title: str
    view_count: int
    published_at: str
    outlier_score: float
```

- [ ] **Step 2: Add the `NicheOutlierScan` model**

In `server/apps/ideas/models.py`, append after `TopicIdea`:
```python
class NicheOutlierScan(UUIDModel, TimeStampedModel):
    """A cached outlier-video scan for one niche, refreshed at most daily."""

    niche = models.ForeignKey(
        'channels.NicheConfig',
        on_delete=models.CASCADE,
        related_name='outlier_scans',
    )
    query = models.CharField(max_length=200)
    results = models.JSONField(default=list)

    class Meta:
        ordering: ClassVar = ['-created_at']

    @override
    def __str__(self) -> str:
        return f'Outlier scan for {self.niche_id} ({self.created_at})'
```

Run:
```bash
docker compose exec web python manage.py makemigrations ideas
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration adding `NicheOutlierScan`; both exit 0.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_apps/test_ideas/test_outlier_scan.py`:
```python
"""Tests for the niche outlier scan (quota-aware, cached daily)."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import django.utils.timezone as tz
import pytest

from server.apps.channels.models import Channel, ChannelKind, NicheConfig
from server.apps.ideas.models import NicheOutlierScan
from server.apps.ideas.outlier_scan import get_cached_scan, run_niche_outlier_scan


@pytest.fixture
def niche(db) -> NicheConfig:  # type: ignore[no-untyped-def]
    channel = Channel.objects.create(name='Outlier Ch', kind=ChannelKind.LONGFORM)
    return NicheConfig.objects.create(
        channel=channel, audience='history buffs', angle='ancient empires',
    )


@pytest.mark.django_db
def test_run_niche_outlier_scan_persists_results(niche: NicheConfig) -> None:
    """A fresh scan calls the YouTube client and writes a NicheOutlierScan row."""
    search_items = [
        {'id': {'videoId': 'vid1'}, 'snippet': {'channelId': 'chan1'}},
    ]
    stats_items = [
        {
            'id': 'vid1',
            'snippet': {
                'title': 'Why Rome Really Fell',
                'channelTitle': 'History Hub',
                'channelId': 'chan1',
                'publishedAt': '2026-06-01T00:00:00Z',
            },
            'statistics': {'viewCount': '2000000'},
        },
    ]
    channel_stats_items = [
        {'id': 'chan1', 'statistics': {'subscriberCount': '50000'}},
    ]

    async def _inner() -> list:
        with (
            patch(
                'server.apps.ideas.outlier_scan.search_videos',
                new=AsyncMock(return_value=search_items),
            ),
            patch(
                'server.apps.ideas.outlier_scan.get_video_statistics',
                new=AsyncMock(return_value=stats_items),
            ),
            patch(
                'server.apps.ideas.outlier_scan.get_channel_statistics',
                new=AsyncMock(return_value=channel_stats_items),
            ),
        ):
            return await run_niche_outlier_scan(niche)

    results = asyncio.run(_inner())
    assert len(results) == 1
    assert results[0].video_id == 'vid1'
    assert results[0].outlier_score > 0

    assert NicheOutlierScan.objects.filter(niche=niche).count() == 1


@pytest.mark.django_db
def test_get_cached_scan_returns_none_when_stale_or_missing(
    niche: NicheConfig,
) -> None:
    """get_cached_scan returns None when no scan exists, or the latest is >24h old."""
    assert get_cached_scan(str(niche.id)) is None

    stale = NicheOutlierScan.objects.create(
        niche=niche,
        query='ancient empires',
        results=[{'video_id': 'v1', 'title': 't', 'channel_title': 'c',
                  'view_count': 1, 'published_at': '2026-01-01T00:00:00Z',
                  'outlier_score': 1.0}],
    )
    stale.created_at = tz.now() - timedelta(hours=25)
    stale.save(update_fields=['created_at'])

    assert get_cached_scan(str(niche.id)) is None


@pytest.mark.django_db
def test_get_cached_scan_returns_results_within_24h(niche: NicheConfig) -> None:
    """get_cached_scan returns the parsed results of a scan from the last 24h."""
    NicheOutlierScan.objects.create(
        niche=niche,
        query='ancient empires',
        results=[{
            'video_id': 'v1', 'title': 'Fresh', 'channel_title': 'c',
            'view_count': 100, 'published_at': '2026-07-01T00:00:00Z',
            'outlier_score': 2.5,
        }],
    )

    cached = get_cached_scan(str(niche.id))
    assert cached is not None
    assert cached[0].title == 'Fresh'
```

Run: `docker compose exec web pytest tests/test_apps/test_ideas/test_outlier_scan.py -v --no-cov`
Expected: FAIL — `outlier_scan.py` doesn't exist.

- [ ] **Step 4: Implement `outlier_scan.py`**

Create `server/apps/ideas/outlier_scan.py`:
```python
"""Cached, quota-aware niche outlier scan (once/day per niche, per Costs note
in the design doc — search.list is capped at ~100 calls/day/project).
"""

import datetime as dt
from typing import TYPE_CHECKING

import django.utils.timezone as tz
from django.conf import settings

from server.apps.generation.clients.youtube_search import (
    compute_outlier_score,
    get_channel_statistics,
    get_video_statistics,
    search_videos,
)
from server.apps.ideas.logic.schemas import OutlierVideo

if TYPE_CHECKING:
    from server.apps.channels.models import NicheConfig

_CACHE_WINDOW = dt.timedelta(hours=24)
_MAX_RESULTS = 15


def _query_for_niche(niche: 'NicheConfig') -> str:
    """Build a search query from the niche's audience/angle."""
    parts = [niche.angle, niche.audience]
    return ' '.join(p for p in parts if p).strip() or 'documentary'


def _parse_days_since(published_at: str) -> float:
    published = dt.datetime.fromisoformat(published_at.replace('Z', '+00:00'))
    return max((tz.now() - published).total_seconds() / 86400, 0.0)


async def run_niche_outlier_scan(niche: 'NicheConfig') -> list[OutlierVideo]:
    """Run a fresh scan against the YouTube Data API and persist the result."""
    from server.apps.ideas.models import NicheOutlierScan  # noqa: PLC0415

    api_key: str = getattr(settings, 'YOUTUBE_DATA_API_KEY', '')
    query = _query_for_niche(niche)

    search_items = await search_videos(query, api_key=api_key, max_results=_MAX_RESULTS)
    video_ids = [
        item['id']['videoId']
        for item in search_items
        if item.get('id', {}).get('videoId')
    ]
    video_stats = await get_video_statistics(video_ids, api_key=api_key)

    channel_ids = list({
        item['snippet']['channelId']
        for item in video_stats
        if item.get('snippet', {}).get('channelId')
    })
    channel_stats = await get_channel_statistics(channel_ids, api_key=api_key)
    subs_by_channel = {
        c['id']: int(c.get('statistics', {}).get('subscriberCount', 0))
        for c in channel_stats
    }

    results: list[OutlierVideo] = []
    for item in video_stats:
        snippet = item.get('snippet', {})
        stats = item.get('statistics', {})
        view_count = int(stats.get('viewCount', 0))
        channel_id = snippet.get('channelId', '')
        subscriber_count = subs_by_channel.get(channel_id, 0)
        published_at = snippet.get('publishedAt', tz.now().isoformat())
        score = compute_outlier_score(
            view_count=view_count,
            subscriber_count=subscriber_count,
            days_since_publish=_parse_days_since(published_at),
        )
        results.append(
            OutlierVideo(
                video_id=item.get('id', ''),
                title=snippet.get('title', ''),
                channel_title=snippet.get('channelTitle', ''),
                view_count=view_count,
                published_at=published_at,
                outlier_score=score,
            ),
        )
    results.sort(key=lambda v: v.outlier_score, reverse=True)

    await NicheOutlierScan.objects.acreate(
        niche=niche,
        query=query,
        results=[r.model_dump() for r in results],
    )
    return results


def get_cached_scan(niche_id: str) -> list[OutlierVideo] | None:
    """Return the latest scan's results if it's less than 24h old, else None."""
    from server.apps.ideas.models import NicheOutlierScan  # noqa: PLC0415

    latest = (
        NicheOutlierScan.objects
        .filter(niche_id=niche_id)
        .order_by('-created_at')
        .first()
    )
    if latest is None or tz.now() - latest.created_at > _CACHE_WINDOW:
        return None
    return [OutlierVideo.model_validate(r) for r in latest.results]
```

- [ ] **Step 5: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_ideas/test_outlier_scan.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add server/apps/ideas/models.py server/apps/ideas/migrations/*.py server/apps/ideas/logic/schemas.py server/apps/ideas/outlier_scan.py tests/test_apps/test_ideas/test_outlier_scan.py
git commit -m "feat(ideas): add cached niche outlier scan (YouTube Data API, once/day)"
```

---

### Task 3: Wire outliers into ideation

**Files:**
- Modify: `server/apps/ideas/ideation.py`
- Modify: `server/apps/ideas/services.py`
- Test: `tests/test_apps/test_ideas/test_ideation.py`

**Interfaces:**
- Consumes: `outlier_scan.get_cached_scan` (Task 2), `OutlierVideo` (Task 2).
- Produces: `run_ideation_agent(context, source, count, outliers=None)` (new optional
  param, backward compatible).

- [ ] **Step 1: Write the failing prompt test**

Add to `tests/test_apps/test_ideas/test_ideation.py`:
```python
def test_build_prompt_includes_trending_block_when_outliers_present() -> None:
    """Niche-only mode includes a TRENDING block when outliers are supplied."""
    from server.apps.ideas.logic.schemas import OutlierVideo

    context = IdeationContext(
        audience='history buffs', angle='ancient empires', lore_document='',
        banned_topics=[], format_name='', existing_topics=set(),
    )
    outliers = [
        OutlierVideo(
            video_id='v1', title='Why Rome Really Fell', channel_title='History Hub',
            view_count=2_000_000, published_at='2026-06-01T00:00:00Z',
            outlier_score=3.2,
        ),
    ]

    prompt = _build_prompt(context, None, count=3, outliers=outliers)
    assert 'TRENDING IN YOUR NICHE' in prompt
    assert 'Why Rome Really Fell' in prompt


def test_build_prompt_omits_trending_block_when_no_outliers() -> None:
    context = IdeationContext(
        audience='a', angle='b', lore_document='', banned_topics=[],
        format_name='', existing_topics=set(),
    )
    prompt = _build_prompt(context, None, count=3, outliers=None)
    assert 'TRENDING IN YOUR NICHE' not in prompt
```

Run: `docker compose exec web pytest tests/test_apps/test_ideas/test_ideation.py -v --no-cov -k trending`
Expected: FAIL — `_build_prompt()` doesn't accept `outliers`.

- [ ] **Step 2: Implement in `ideation.py`**

In `server/apps/ideas/ideation.py`, update imports and both functions:
```python
from server.apps.ideas.logic.schemas import IdeationOutput, OutlierVideo, SourceSnapshot
```

Change `_build_prompt`'s signature and add the trending block right before the final
`Each idea:` instruction line:
```python
def _build_prompt(
    context: 'IdeationContext',
    source: SourceSnapshot | None,
    count: int,
    outliers: list[OutlierVideo] | None = None,
) -> str:
    request_count = min(count + _AGENT_BUFFER, 22)
    lines = [
        f'Generate {request_count} unique longform video ideas.',
        f'Channel audience: {context.audience or "general"}',
        f'Channel angle: {context.angle or "educational"}',
    ]
    if context.format_name:
        lines.append(f'Story format: {context.format_name}')
    if context.lore_document:
        lines.append(f'Channel lore:\n{context.lore_document[:2000]}')
    if context.banned_topics:
        banned = json.dumps(context.banned_topics)
        lines.append(f'Never propose topics touching: {banned}')
    if context.existing_topics:
        recent = json.dumps(sorted(context.existing_topics)[:40])
        lines.append(f'Avoid overlap with these recent topics: {recent}')

    if source is not None:
        lines.extend([
            '',
            'REMIX MODE — source video:',
            f'Title: {source.title}',
            f'Channel: {source.channel}',
            f'Duration (sec): {source.duration_sec:.0f}',
            f'Views: {source.view_count if source.view_count is not None else "unknown"}',  # noqa: E501
            f'URL: {source.url}',
            f'Description:\n{source.description[:1500]}',
            f'Captions excerpt:\n{source.caption_text[:3000]}',
            (
                'Propose remix angles: contrarian takes, deeper dives, '
                'niche-localized versions, or structural hook swaps.'
            ),
        ])
    else:
        lines.append(
            'NICHE-ONLY MODE — invent fresh angles from audience and angle.',
        )
        if outliers:
            lines.extend(['', 'TRENDING IN YOUR NICHE (real YouTube data):'])
            lines.extend(
                f'- "{o.title}" ({o.channel_title}, {o.view_count:,} views, '
                f'outlier score {o.outlier_score:.2f})'
                for o in outliers[:10]
            )
            lines.append(
                'Use these as demand signal — propose ideas that share the '
                "underlying appeal (angle, hook pattern, or gap) with what's "
                'already resonating, without copying any single video.',
            )

    lines.append(
        'Each idea: title (<=120 chars), topic (run seed, 1-3 sentences), '
        'score 0.0-1.0, remix_strategy, hook_pattern, differentiation, '
        'source_refs (empty list if niche-only).',
    )
    return '\n'.join(lines)
```

Change `run_ideation_agent`:
```python
def run_ideation_agent(
    context: 'IdeationContext',
    *,
    source: SourceSnapshot | None,
    count: int,
    outliers: list[OutlierVideo] | None = None,
) -> IdeationOutput:
    """Run one bounded ideation LLM call and return structured candidates."""
    prompt = _build_prompt(context, source, count, outliers=outliers)
    result = _agent().run_sync(prompt)
    return result.output
```

- [ ] **Step 3: Wire the cached scan into `IdeationService.generate`**

In `server/apps/ideas/services.py`, add the import:
```python
from server.apps.ideas.outlier_scan import get_cached_scan
```

In `IdeationService.generate`, right before the `output = run_ideation_agent(...)` call,
add:
```python
        outliers = None
        if source is None:
            outliers = get_cached_scan(str(niche.id))
        output = run_ideation_agent(
            context,
            source=source,
            count=count,
            outliers=outliers,
        )
```
(replacing the existing `output = run_ideation_agent(context, source=source, count=count)`
call — only fetch outliers in niche-only mode, matching the "TRENDING" block's
niche-only-only placement in Step 2.)

- [ ] **Step 4: Add the service-level test**

Add to `tests/test_apps/test_ideas/test_ideation.py`:
```python
@pytest.mark.django_db
def test_generate_passes_cached_outliers_to_agent(niche: NicheConfig) -> None:
    """Niche-only generate() calls run_ideation_agent with cached outliers."""
    from server.apps.ideas.logic.schemas import OutlierVideo
    from server.apps.ideas.models import NicheOutlierScan

    NicheOutlierScan.objects.create(
        niche=niche,
        query='ancient empires history buffs',
        results=[{
            'video_id': 'v1', 'title': 'Cached Outlier', 'channel_title': 'c',
            'view_count': 1, 'published_at': '2026-01-01T00:00:00Z',
            'outlier_score': 1.0,
        }],
    )
    service = IdeationService(runs=MagicMock(spec=PipelineRunService))
    mock_output = IdeationOutput(
        ideas=[
            TopicCandidate(
                title='Rome supply lines', topic='Roman logistics',
                score=0.9, remix_strategy='a', hook_pattern='b',
                differentiation='c',
            ),
        ],
    )

    with patch(
        'server.apps.ideas.services.run_ideation_agent',
        return_value=mock_output,
    ) as mock_run:
        service.generate(str(niche.id), IdeaGeneratePayload(count=1))

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs['outliers'][0].title == 'Cached Outlier'
```

- [ ] **Step 5: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_ideas/ -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add server/apps/ideas/ideation.py server/apps/ideas/services.py tests/test_apps/test_ideas/test_ideation.py
git commit -m "feat(ideas): ground niche-only ideation in real YouTube outlier data"
```

---

### Task 4: YouTube performance feedback loop

**Files:**
- Modify: `server/apps/channels/services.py` (`_YOUTUBE_SCOPES`)
- Create: `server/apps/generation/clients/youtube_analytics.py`
- Modify: `server/apps/analytics/models.py` (`PublishJobMetric`)
- Create migration: `just run makemigrations analytics`
- Modify: `server/apps/analytics/tasks.py`
- Test: `tests/test_apps/test_generation/test_youtube_analytics.py`
- Test: `tests/test_apps/test_analytics/test_tasks.py`

**Interfaces:**
- Produces: `PublishJobMetric` model, `youtube_analytics.fetch_video_report(access_token, video_id) -> dict`
  (consumed by Task 6 for CTR), `analytics.tasks.pull_publish_job_metrics()` task.

- [ ] **Step 1: Add the Analytics OAuth scope**

In `server/apps/channels/services.py`, change:
```python
_YOUTUBE_SCOPES = (
    'https://www.googleapis.com/auth/youtube.upload '
    'https://www.googleapis.com/auth/youtube'
)
```
to:
```python
_YOUTUBE_SCOPES = (
    'https://www.googleapis.com/auth/youtube.upload '
    'https://www.googleapis.com/auth/youtube '
    'https://www.googleapis.com/auth/yt-analytics.readonly'
)
```

**Operational note (not a code step):** every already-connected `YouTubeCredential` was
authorized under the old scope string and must be reconnected (re-run the OAuth consent
flow) before `pull_publish_job_metrics` will work for that channel — the stored
`refresh_token` does not retroactively gain the new scope. Communicate this before
rollout; it is not something a migration can fix.

- [ ] **Step 2: Write the failing Analytics client test**

Create `tests/test_apps/test_generation/test_youtube_analytics.py`:
```python
"""Tests for the YouTube Analytics API client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.generation.clients.youtube_analytics import fetch_video_report


def test_fetch_video_report_parses_summary_and_retention() -> None:
    summary_resp = MagicMock()
    summary_resp.status_code = 200
    summary_resp.json.return_value = {
        'columnHeaders': [
            {'name': 'views'}, {'name': 'averageViewDuration'},
            {'name': 'averageViewPercentage'},
        ],
        'rows': [[1000, 245.5, 62.3]],
    }
    retention_resp = MagicMock()
    retention_resp.status_code = 200
    retention_resp.json.return_value = {
        'columnHeaders': [
            {'name': 'elapsedVideoTimeRatio'}, {'name': 'audienceWatchRatio'},
            {'name': 'relativeRetentionPerformance'},
        ],
        'rows': [[0.01, 0.98, 0.55], [0.5, 0.6, 0.4]],
    }

    async def _inner() -> dict:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(side_effect=[summary_resp, retention_resp]),
        ):
            return await fetch_video_report(
                access_token='tok', channel_youtube_id='UC123', video_id='vid1',
            )

    result = asyncio.run(_inner())
    assert result['views'] == 1000
    assert result['avg_view_duration_s'] == 245.5
    assert result['avg_view_percentage'] == 62.3
    assert result['retention_curve'] == [
        {'elapsed_ratio': 0.01, 'watch_ratio': 0.98, 'relative_performance': 0.55},
        {'elapsed_ratio': 0.5, 'watch_ratio': 0.6, 'relative_performance': 0.4},
    ]


def test_fetch_video_report_handles_empty_rows() -> None:
    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.json.return_value = {'columnHeaders': [], 'rows': []}

    async def _inner() -> dict:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=empty_resp),
        ):
            return await fetch_video_report(
                access_token='tok', channel_youtube_id='UC123', video_id='vid1',
            )

    result = asyncio.run(_inner())
    assert result['views'] == 0
    assert result['retention_curve'] == []
```

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_youtube_analytics.py -v --no-cov`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `youtube_analytics.py`**

Create `server/apps/generation/clients/youtube_analytics.py`:
```python
"""YouTube Analytics API client — per-video performance + retention curve.

Free API, quota-limited like the Data API. Requires the
yt-analytics.readonly OAuth scope on the connected channel's credential.
"""

from typing import Any

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_REPORTS_URL = 'https://youtubeanalytics.googleapis.com/v2/reports'
_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _classify_response(resp: httpx.Response) -> None:
    if resp.status_code == httpx.codes.OK:
        return
    if resp.status_code in _RETRYABLE_CODES:
        raise RetryableProviderError(
            f'YouTube Analytics API {resp.status_code}',
            provider='youtube_analytics',
            status_code=resp.status_code,
        )
    raise FatalProviderError(
        f'YouTube Analytics API error {resp.status_code}: {resp.text[:300]}',
        provider='youtube_analytics',
    )


async def _query_report(
    access_token: str,
    channel_youtube_id: str,
    video_id: str,
    metrics: str,
    dimensions: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        'ids': f'channel=={channel_youtube_id}',
        'startDate': '2020-01-01',
        'endDate': '2030-01-01',
        'metrics': metrics,
        'filters': f'video=={video_id}',
    }
    if dimensions:
        params['dimensions'] = dimensions
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _REPORTS_URL,
            params=params,
            headers={'Authorization': f'Bearer {access_token}'},
        )
    _classify_response(resp)
    return dict(resp.json())


async def fetch_video_report(
    access_token: str,
    channel_youtube_id: str,
    video_id: str,
) -> dict[str, Any]:
    """Fetch summary metrics + the 100-point audience-retention curve."""
    summary = await _query_report(
        access_token,
        channel_youtube_id,
        video_id,
        metrics='views,averageViewDuration,averageViewPercentage',
    )
    summary_rows = summary.get('rows', [])
    views, avg_duration, avg_pct = (
        summary_rows[0] if summary_rows else (0, 0.0, 0.0)
    )

    retention = await _query_report(
        access_token,
        channel_youtube_id,
        video_id,
        metrics='audienceWatchRatio,relativeRetentionPerformance',
        dimensions='elapsedVideoTimeRatio',
    )
    retention_curve = [
        {
            'elapsed_ratio': row[0],
            'watch_ratio': row[1],
            'relative_performance': row[2],
        }
        for row in retention.get('rows', [])
    ]

    return {
        'views': int(views),
        'avg_view_duration_s': float(avg_duration),
        'avg_view_percentage': float(avg_pct),
        'retention_curve': retention_curve,
    }
```

- [ ] **Step 4: Run the client tests, fix**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_youtube_analytics.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Add `PublishJobMetric`**

In `server/apps/analytics/models.py`, add (this is a plain managed model, unlike the
three existing `managed = False` materialized-view models — it's written to directly by
the pull task, not refreshed from SQL):
```python
class PublishJobMetric(models.Model):
    """One YouTube Analytics snapshot for a PublishJob, pulled daily."""

    id = models.BigAutoField(primary_key=True)
    publish_job = models.ForeignKey(
        'publishing.PublishJob',
        on_delete=models.CASCADE,
        related_name='metrics',
    )
    pulled_at = models.DateTimeField(auto_now_add=True)
    views = models.IntegerField(default=0)
    avg_view_duration_s = models.FloatField(default=0.0)
    avg_view_percentage = models.FloatField(default=0.0)
    impressions = models.IntegerField(null=True, blank=True)
    impressions_ctr = models.FloatField(null=True, blank=True)
    retention_curve = models.JSONField(default=list)

    class Meta:
        db_table = 'analytics_publish_job_metric'
        ordering: ClassVar = ['-pulled_at']
```
Add `ClassVar` to the existing `typing` import at the top of the file if not already
imported (check the file's current imports first — it currently only imports
`from django.db import models`; add `from typing import ClassVar`).

Run:
```bash
docker compose exec web python manage.py makemigrations analytics
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration creating `analytics_publish_job_metric`; both exit 0. (This is a
brand-new table, not an ALTER on the three existing unmanaged matview models, so no
constraint-compatibility concerns.)

- [ ] **Step 6: Write the failing pull-task test**

Add to `tests/test_apps/test_analytics/test_tasks.py`:
```python
@pytest.mark.django_db(transaction=True)
def test_pull_publish_job_metrics_writes_metric_rows() -> None:
    """pull_publish_job_metrics fetches a report per recent COMPLETED PublishJob."""
    from unittest.mock import AsyncMock, patch

    from server.apps.analytics.models import PublishJobMetric
    from server.apps.analytics.tasks import pull_publish_job_metrics
    from server.apps.channels.models import (
        Channel, ChannelKind, YouTubeCredential,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint, PipelineKind, PipelineRun,
    )
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel = Channel.objects.create(name='Metrics Ch', kind=ChannelKind.LONGFORM)
    YouTubeCredential.objects.create(
        channel=channel, access_token='tok', refresh_token='rtok',
    )
    bp = PipelineBlueprint.objects.create(
        name='metrics_test_v1', kind=PipelineKind.LONGFORM, graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel, blueprint=bp, blueprint_snapshot={}, topic='t',
    )
    job = PublishJob.objects.create(
        run=run, channel=channel, status=PublishStatus.COMPLETED,
        youtube_video_id='yt_vid_1',
    )

    fake_report = {
        'views': 500, 'avg_view_duration_s': 120.0, 'avg_view_percentage': 45.0,
        'retention_curve': [{'elapsed_ratio': 0.1, 'watch_ratio': 0.9,
                              'relative_performance': 0.5}],
    }

    async def _inner() -> None:
        with (
            patch(
                'server.apps.analytics.tasks.yt_client.refresh_token_if_needed',
                new=AsyncMock(return_value='fresh_tok'),
            ),
            patch(
                'server.apps.analytics.tasks.fetch_video_report',
                new=AsyncMock(return_value=fake_report),
            ),
            patch(
                'server.apps.analytics.tasks._get_channel_youtube_id',
                new=AsyncMock(return_value='UC123'),
            ),
        ):
            await pull_publish_job_metrics()

    asyncio.run(_inner())

    metric = PublishJobMetric.objects.get(publish_job=job)
    assert metric.views == 500
    assert metric.avg_view_percentage == 45.0
    assert metric.retention_curve[0]['watch_ratio'] == 0.9
```

Add `import asyncio` and `import pytest` at the top of `test_tasks.py` if not already
present (the file currently only imports `asyncio`, `MagicMock`, `patch` — `pytest` is
needed for the new `@pytest.mark.django_db` test; add it).

Run: `docker compose exec web pytest tests/test_apps/test_analytics/test_tasks.py -v --no-cov -k pull_publish_job_metrics`
Expected: FAIL — `pull_publish_job_metrics` doesn't exist.

- [ ] **Step 7: Implement the pull task**

In `server/apps/analytics/tasks.py`, add imports and a helper, then the task:
```python
from server.apps.generation.clients import youtube as yt_client
from server.apps.generation.clients.youtube_analytics import fetch_video_report


async def _get_channel_youtube_id(access_token: str) -> str:  # pragma: no cover
    """Look up the connected channel's own YouTube channel ID via channels.list.

    Implemented as a thin wrapper so tests can patch it directly; the real
    body calls GET https://www.googleapis.com/youtube/v3/channels?part=id&mine=true
    with the given bearer token and returns items[0]['id'].
    """
    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            'https://www.googleapis.com/youtube/v3/channels',
            params={'part': 'id', 'mine': 'true'},
            headers={'Authorization': f'Bearer {access_token}'},
        )
    resp.raise_for_status()
    return str(resp.json()['items'][0]['id'])


@broker.task(retry_on_error=False, queue='api')
async def pull_publish_job_metrics() -> None:
    """Pull YouTube Analytics for PublishJobs completed in the last 30 days."""
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415
    from server.apps.channels.models import YouTubeCredential  # noqa: PLC0415
    from server.apps.publishing.models import (  # noqa: PLC0415
        PublishJob,
        PublishStatus,
    )
    import django.utils.timezone as tz  # noqa: PLC0415
    import datetime  # noqa: PLC0415

    cutoff = tz.now() - datetime.timedelta(days=30)
    jobs = [
        job
        async for job in PublishJob.objects.filter(
            status=PublishStatus.COMPLETED,
            created_at__gte=cutoff,
        ).select_related('channel')
    ]
    for job in jobs:
        try:
            credential = await YouTubeCredential.objects.aget(channel=job.channel)
        except YouTubeCredential.DoesNotExist:  # noqa: PERF203
            continue
        access_token = await yt_client.refresh_token_if_needed(credential)
        channel_youtube_id = await _get_channel_youtube_id(access_token)
        report = await fetch_video_report(
            access_token,
            channel_youtube_id,
            job.youtube_video_id,
        )
        await PublishJobMetric.objects.acreate(
            publish_job=job,
            views=report['views'],
            avg_view_duration_s=report['avg_view_duration_s'],
            avg_view_percentage=report['avg_view_percentage'],
            retention_curve=report['retention_curve'],
        )
```

- [ ] **Step 8: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_analytics/ tests/test_apps/test_generation/test_youtube_analytics.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100`
Expected: passes; add a covering test for the real (non-`pragma: no cover`) body of
`_get_channel_youtube_id` if coverage flags it — the `# pragma: no cover` above only
excludes it if your team's coverage config respects that marker for `httpx` calls;
confirm against `pyproject.toml`'s coverage settings and remove the pragma + add a direct
test instead if the project doesn't use pragma exclusions elsewhere (grep the codebase
for `pragma: no cover` usage first to confirm the convention — it's already used in
`stages/research.py` and `stages/scene_breakdown.py` for PydanticAI decorator bodies, so
this matches existing style).

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add server/apps/channels/services.py server/apps/generation/clients/youtube_analytics.py server/apps/analytics/models.py server/apps/analytics/migrations/*.py server/apps/analytics/tasks.py tests/test_apps/test_generation/test_youtube_analytics.py tests/test_apps/test_analytics/test_tasks.py
git commit -m "feat(analytics): pull YouTube performance + retention-curve data daily"
```

---

### Task 5: Feed performance rollups into ideation context

**Files:**
- Modify: `server/apps/ideas/selectors.py` (`IdeationContext`, `build_ideation_context`)
- Modify: `server/apps/ideas/ideation.py` (`_build_prompt`)
- Test: `tests/test_apps/test_ideas/test_ideation.py`

**Interfaces:**
- Produces: `IdeationContext.performance_notes: str` (new field, default `''`).

- [ ] **Step 1: Write the failing selector test**

Add to `tests/test_apps/test_ideas/test_ideation.py`:
```python
@pytest.mark.django_db
def test_build_ideation_context_includes_performance_notes(
    niche: NicheConfig,
) -> None:
    """Context summarizes trailing AVD% for the channel's completed runs."""
    from server.apps.analytics.models import PublishJobMetric
    from server.apps.pipelines.models import (
        PipelineBlueprint, PipelineKind, PipelineRun, RunStatus,
    )
    from server.apps.publishing.models import PublishJob, PublishStatus

    bp = PipelineBlueprint.objects.create(
        name='perf_ctx_test_v1', kind=PipelineKind.LONGFORM, graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=niche.channel, blueprint=bp, blueprint_snapshot={}, topic='t',
        status=RunStatus.COMPLETED,
    )
    job = PublishJob.objects.create(
        run=run, channel=niche.channel, status=PublishStatus.COMPLETED,
        youtube_video_id='yt1',
    )
    PublishJobMetric.objects.create(
        publish_job=job, views=1000, avg_view_duration_s=200.0,
        avg_view_percentage=55.0,
    )

    context = build_ideation_context(niche)
    assert '55.0%' in context.performance_notes or '55.0' in context.performance_notes
```

Run: `docker compose exec web pytest tests/test_apps/test_ideas/test_ideation.py -v --no-cov -k performance_notes`
Expected: FAIL — `IdeationContext` has no `performance_notes` attribute.

- [ ] **Step 2: Implement in `selectors.py`**

In `server/apps/ideas/selectors.py`, add `performance_notes: str` to the
`@attrs.define`/`@dataclass`-decorated `IdeationContext` class (check the file's actual
decorator on `IdeationContext` — it was read earlier as a plain class with type-annotated
fields, confirm whether it's an `attrs`/`dataclass`/plain class before editing, and add
the field using that same mechanism):
```python
class IdeationContext:
    """Pre-fetched niche context injected into the ideation agent prompt."""

    audience: str
    angle: str
    lore_document: str
    banned_topics: list[str]
    format_name: str
    existing_topics: set[str]
    performance_notes: str = ''
```

Add a helper and wire it into `build_ideation_context`:
```python
def _performance_notes(channel_id: 'uuid.UUID') -> str:
    """Summarize trailing average-view-percentage across the channel's runs."""
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415

    values = list(
        PublishJobMetric.objects
        .filter(publish_job__channel_id=channel_id)
        .order_by('-pulled_at')
        .values_list('avg_view_percentage', flat=True)[:20],
    )
    if not values:
        return ''
    avg = sum(values) / len(values)
    return (
        f'This channel\'s last {len(values)} tracked videos averaged '
        f'{avg:.1f}% average-view-percentage.'
    )
```
```python
def build_ideation_context(niche: 'NicheConfig') -> IdeationContext:
    """Build the pre-fetch bundle for one niche ideation call."""
    story_format = niche.format
    format_name = story_format.name if story_format is not None else ''
    return IdeationContext(
        audience=niche.audience,
        angle=niche.angle,
        lore_document=niche.lore_document,
        banned_topics=list(niche.banned_topics),
        format_name=format_name,
        existing_topics=existing_topics(niche.channel_id),
        performance_notes=_performance_notes(niche.channel_id),
    )
```
Add `import uuid` at the top of `selectors.py` if not already imported (it very likely
already is, given `_decode_cursor`/`_encode_cursor` use `uuid.UUID` — confirm before
adding a duplicate import).

- [ ] **Step 3: Thread it into the prompt**

In `server/apps/ideas/ideation.py`'s `_build_prompt`, add right after the
`Channel angle:` line:
```python
    if context.format_name:
        lines.append(f'Story format: {context.format_name}')
    if context.performance_notes:
        lines.append(f'Performance history: {context.performance_notes}')
```

- [ ] **Step 4: Add the prompt-level test**

Add to `test_ideation.py`:
```python
def test_build_prompt_includes_performance_notes() -> None:
    context = IdeationContext(
        audience='a', angle='b', lore_document='', banned_topics=[],
        format_name='', existing_topics=set(),
        performance_notes="This channel's last 5 videos averaged 61.2% AVD.",
    )
    prompt = _build_prompt(context, None, count=3)
    assert '61.2%' in prompt
```

- [ ] **Step 5: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_ideas/ -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add server/apps/ideas/selectors.py server/apps/ideas/ideation.py tests/test_apps/test_ideas/test_ideation.py
git commit -m "feat(ideas): surface trailing channel performance in ideation prompts"
```

---

### Task 6: Thumbnail early-swap testing

**Files:**
- Modify: `server/apps/publishing/models.py` (`PublishJob`)
- Create migration: `just run makemigrations publishing`
- Modify: `server/apps/pipelines/stages/publish.py`
- Modify: `server/apps/generation/clients/youtube.py`
- Modify: `server/apps/pipelines/tasks.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_publish.py`
- Test: `tests/test_apps/test_generation/test_youtube_client.py`
- Test: `tests/test_apps/test_pipelines/test_tasks.py`

**Interfaces:**
- Consumes: `PublishJobMetric.impressions_ctr` (Task 4 — nullable; YouTube Analytics
  impressions/CTR data has its own separate reporting delay/availability, so this task
  treats a null CTR as "not enough data yet" and skips the job).
- Produces: `PublishJob.thumbnail_asset_id`, `.thumbnail_tested`,
  `.tested_candidate_ranks`.

- [ ] **Step 1: Add the new `PublishJob` fields**

In `server/apps/publishing/models.py`, add to `PublishJob` after `metadata_snapshot`:
```python
    metadata_snapshot = models.JSONField(default=dict)
    thumbnail_asset_id = models.CharField(max_length=64, blank=True, default='')
    thumbnail_tested = models.BooleanField(default=False)
    tested_candidate_ranks = models.JSONField(default=list, blank=True)
    error = models.JSONField(null=True, blank=True)
```
(inserting the three new fields between the existing `metadata_snapshot` and `error`
fields.)

Run:
```bash
docker compose exec web python manage.py makemigrations publishing
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration; both exit 0.

- [ ] **Step 2: Record the chosen thumbnail on the `PublishJob`**

In `server/apps/pipelines/stages/publish.py`, the existing `PublishStage.run()` creates
the job before the thumbnail is uploaded:
```python
        job = await PublishJob.objects.acreate(
            run=ctx.run,
            channel=ctx.channel,
            status=PublishStatus.UPLOADING,
            schedule_at=schedule_at,
            metadata_snapshot={
                'title': meta['title'],
                'description': meta['description'],
                'tags': meta.get('tags', []),
                'category': meta.get('category', 'Education'),
            },
        )
```
Change to also store `thumbnail_asset_id`:
```python
        job = await PublishJob.objects.acreate(
            run=ctx.run,
            channel=ctx.channel,
            status=PublishStatus.UPLOADING,
            schedule_at=schedule_at,
            thumbnail_asset_id=thumbnail_asset_id or '',
            metadata_snapshot={
                'title': meta['title'],
                'description': meta['description'],
                'tags': meta.get('tags', []),
                'category': meta.get('category', 'Education'),
            },
        )
```
(`thumbnail_asset_id` is already a local variable in this function, read a few lines
above from `gate.get('thumbnail_asset_id')` — no new variable needed.)

- [ ] **Step 3: Update the existing publish test for the new field**

`test_publish_run_creates_publish_job` in `test_publish.py` currently doesn't assert on
`PublishJob.objects.acreate`'s call kwargs. Add a targeted assertion:
```python
def test_publish_run_records_thumbnail_asset_id() -> None:
    """PublishJob.objects.acreate is called with the chosen thumbnail_asset_id."""
    ctx = _make_ctx()
    fake_credential = MagicMock()
    fake_credential.token_expiry = None
    fake_job = MagicMock(id='job-thumb')
    fake_job.asave = AsyncMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.publish.YouTubeCredential'
                '.objects.aget',
                new=AsyncMock(return_value=fake_credential),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client'
                '.refresh_token_if_needed',
                new=AsyncMock(return_value='access_token'),
            ),
            patch(
                'server.apps.pipelines.stages.publish._download_asset',
                new=AsyncMock(return_value=b'video bytes'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.upload_video',
                new=AsyncMock(return_value='yt_abc123'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.set_thumbnail',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.stages.publish.PublishJob.objects.acreate',
                new=AsyncMock(return_value=fake_job),
            ) as mock_acreate,
            patch(
                'server.apps.pipelines.stages.publish.Asset.objects.aget',
                new=AsyncMock(return_value=MagicMock()),
            ),
        ):
            return await PublishStage().run(ctx)

    asyncio.run(_inner())
    assert mock_acreate.call_args.kwargs['thumbnail_asset_id'] == 'asset-thumb'
```
(`_make_ctx()` already sets `ctx.upstream['review_gate']['thumbnail_asset_id'] =
'asset-thumb'`.)

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_publish.py -v --no-cov -k thumbnail_asset_id`
Expected: FAIL until Step 2 lands, then PASS.

- [ ] **Step 4: Add `yt_client.update_video_metadata` (used to set the new thumbnail)**

Thumbnail swapping reuses the already-existing `yt_client.set_thumbnail()` — no new
client function is needed for the thumbnail itself. Skip straight to Step 5.

- [ ] **Step 5: Write the failing swap-task test**

Add to `tests/test_apps/test_pipelines/test_tasks.py`:
```python
@pytest.mark.django_db(transaction=True)
def test_swap_underperforming_thumbnails_swaps_below_median_ctr() -> None:
    """A job with below-median CTR and an untested candidate gets swapped once."""
    from unittest.mock import AsyncMock, patch

    from server.apps.analytics.models import PublishJobMetric
    from server.apps.channels.models import (
        Channel, ChannelKind, YouTubeCredential,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint, PipelineKind, PipelineRun, StageExecution, StageStatus,
    )
    from server.apps.pipelines.tasks import swap_underperforming_thumbnails
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel = Channel.objects.create(name='Swap Ch', kind=ChannelKind.LONGFORM)
    YouTubeCredential.objects.create(
        channel=channel, access_token='tok', refresh_token='rtok',
    )
    bp = PipelineBlueprint.objects.create(
        name='swap_test_v1', kind=PipelineKind.LONGFORM, graph={'stages': []},
    )

    # A healthy prior job establishes the channel's median CTR at 0.06.
    good_run = PipelineRun.objects.create(
        channel=channel, blueprint=bp, blueprint_snapshot={}, topic='good',
    )
    good_job = PublishJob.objects.create(
        run=good_run, channel=channel, status=PublishStatus.COMPLETED,
        youtube_video_id='yt_good',
        created_at=tz.now() - timedelta(days=10),
    )
    PublishJobMetric.objects.create(
        publish_job=good_job, views=1000, impressions_ctr=0.06,
    )

    # The job under test: below-median CTR, 24-48h old, has an untested candidate.
    run = PipelineRun.objects.create(
        channel=channel, blueprint=bp, blueprint_snapshot={}, topic='under',
    )
    StageExecution.objects.create(
        run=run, stage_key='thumbnail', status=StageStatus.SUCCEEDED, input_hash='',
        output={'candidates': [
            {'rank': 0, 'asset_id': 'thumb-0'},
            {'rank': 1, 'asset_id': 'thumb-1'},
        ]},
    )
    job = PublishJob.objects.create(
        run=run, channel=channel, status=PublishStatus.COMPLETED,
        youtube_video_id='yt_under', thumbnail_asset_id='thumb-0',
        created_at=tz.now() - timedelta(hours=30),
    )
    PublishJobMetric.objects.create(
        publish_job=job, views=500, impressions_ctr=0.02,
    )

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.tasks.yt_client.refresh_token_if_needed',
                new=AsyncMock(return_value='fresh_tok'),
            ),
            patch(
                'server.apps.pipelines.tasks.yt_client.set_thumbnail',
                new=AsyncMock(),
            ) as mock_set_thumb,
            patch(
                'server.apps.pipelines.tasks._download_thumbnail_bytes',
                new=AsyncMock(return_value=b'thumb bytes'),
            ),
        ):
            await swap_underperforming_thumbnails()
            mock_set_thumb.assert_awaited_once_with(
                'fresh_tok', 'yt_under', b'thumb bytes',
            )

    asyncio.run(_inner())

    job.refresh_from_db()
    assert job.thumbnail_asset_id == 'thumb-1'
    assert job.thumbnail_tested is True
    assert job.tested_candidate_ranks == [1]
```

Add `import datetime`/`from datetime import timedelta` and
`import django.utils.timezone as tz` at the top of `test_tasks.py` if not already
present.

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_tasks.py -v --no-cov -k swap_underperforming`
Expected: FAIL — `swap_underperforming_thumbnails` doesn't exist.

- [ ] **Step 6: Implement the swap task**

In `server/apps/pipelines/tasks.py`, add imports and the task (after
`resume_publish_held_runs` from Milestone 1's Task 3):
```python
from server.apps.generation.clients import youtube as yt_client

_SWAP_MIN_AGE_H = 24
_SWAP_MAX_AGE_H = 48


async def _download_thumbnail_bytes(asset_id: str) -> bytes:  # pragma: no cover
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return asset.file.read()  # type: ignore[no-any-return]


def _channel_median_ctr(channel_id: 'uuid.UUID', exclude_job_id: 'uuid.UUID') -> float | None:
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415

    values = sorted(
        v
        for v in PublishJobMetric.objects
        .filter(
            publish_job__channel_id=channel_id,
            impressions_ctr__isnull=False,
        )
        .exclude(publish_job_id=exclude_job_id)
        .values_list('impressions_ctr', flat=True)
    )
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


@broker.task(retry_on_error=False, queue='api')
async def swap_underperforming_thumbnails() -> None:
    """Swap to an unused thumbnail candidate for jobs 24-48h old with
    below-median CTR — at most once per job (tracked via thumbnail_tested).
    """
    import uuid  # noqa: PLC0415

    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415
    from server.apps.channels.models import YouTubeCredential  # noqa: PLC0415
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
    from server.apps.publishing.models import (  # noqa: PLC0415
        PublishJob,
        PublishStatus,
    )
    import django.utils.timezone as tz  # noqa: PLC0415
    import datetime  # noqa: PLC0415

    now = tz.now()
    window_start = now - datetime.timedelta(hours=_SWAP_MAX_AGE_H)
    window_end = now - datetime.timedelta(hours=_SWAP_MIN_AGE_H)

    jobs = [
        job
        async for job in PublishJob.objects.filter(
            status=PublishStatus.COMPLETED,
            thumbnail_tested=False,
            created_at__gte=window_start,
            created_at__lte=window_end,
        ).select_related('channel', 'run')
    ]
    for job in jobs:
        metric = await PublishJobMetric.objects.filter(
            publish_job=job,
            impressions_ctr__isnull=False,
        ).order_by('-pulled_at').afirst()
        if metric is None:
            continue

        median = await sync_to_async(_channel_median_ctr)(job.channel_id, job.id)
        if median is None or metric.impressions_ctr >= median:
            continue

        thumb_exec = await StageExecution.objects.filter(
            run_id=job.run_id,
            stage_key='thumbnail',
            status=StageStatus.SUCCEEDED,
        ).afirst()
        if thumb_exec is None:
            continue
        candidates = thumb_exec.output.get('candidates', [])
        tested = set(job.tested_candidate_ranks)
        current_rank = next(
            (c['rank'] for c in candidates if c['asset_id'] == job.thumbnail_asset_id),
            None,
        )
        if current_rank is not None:
            tested.add(current_rank)
        untested = [c for c in candidates if c['rank'] not in tested]
        if not untested:
            job.thumbnail_tested = True
            await job.asave(update_fields=['thumbnail_tested'])
            continue

        next_candidate = untested[0]
        try:
            credential = await YouTubeCredential.objects.aget(channel=job.channel)
        except YouTubeCredential.DoesNotExist:  # noqa: PERF203
            continue
        access_token = await yt_client.refresh_token_if_needed(credential)
        thumb_bytes = await _download_thumbnail_bytes(next_candidate['asset_id'])
        await yt_client.set_thumbnail(access_token, job.youtube_video_id, thumb_bytes)

        job.thumbnail_asset_id = next_candidate['asset_id']
        job.thumbnail_tested = True
        job.tested_candidate_ranks = [*job.tested_candidate_ranks, next_candidate['rank']]
        await job.asave(
            update_fields=[
                'thumbnail_asset_id', 'thumbnail_tested', 'tested_candidate_ranks',
            ],
        )
```
Add `from asgiref.sync import sync_to_async` to the top-level imports of
`pipelines/tasks.py` if not already present (check the file first — Milestone 1's Task 3
didn't need it, so this is likely a new import for this file).

- [ ] **Step 7: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_tasks.py tests/test_apps/test_pipelines/test_stages/test_publish.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add server/apps/publishing/models.py server/apps/publishing/migrations/*.py server/apps/pipelines/stages/publish.py server/apps/pipelines/tasks.py tests/
git commit -m "feat(pipelines): swap underperforming thumbnails once, based on trailing CTR"
```

**Deferred within this task:** title A/B swapping (`videos.update` with an alternate
title) is not implemented here — it needs the same median-comparison infrastructure this
task just built, but title changes are riskier to auto-apply (they affect search
indexing, not just CTR) and deserve their own review cycle once thumbnail-swap has a
track record. Fast-follow, not forgotten.

---

### Task 7: Fix the publish category bug

**Files:**
- Modify: `server/apps/pipelines/stages/publish.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_publish.py`

**Interfaces:** none new — pure bugfix.

- [ ] **Step 1: Write the failing test**

Add to `test_publish.py`:
```python
def test_publish_passes_category_id_from_metadata() -> None:
    """upload_video receives the numeric category_id mapped from meta['category']."""
    ctx = _make_ctx()
    ctx.upstream['metadata']['category'] = 'Entertainment'
    fake_job = MagicMock(id='job-cat')
    fake_job.asave = AsyncMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.publish.YouTubeCredential'
                '.objects.aget',
                new=AsyncMock(return_value=MagicMock(token_expiry=None)),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client'
                '.refresh_token_if_needed',
                new=AsyncMock(return_value='tok'),
            ),
            patch(
                'server.apps.pipelines.stages.publish._download_asset',
                new=AsyncMock(return_value=b'video'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.upload_video',
                new=AsyncMock(return_value='yt_cat'),
            ) as mock_upload,
            patch(
                'server.apps.pipelines.stages.publish.yt_client.set_thumbnail',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.stages.publish.PublishJob.objects.acreate',
                new=AsyncMock(return_value=fake_job),
            ),
            patch(
                'server.apps.pipelines.stages.publish.Asset.objects.aget',
                new=AsyncMock(return_value=MagicMock()),
            ),
        ):
            return await PublishStage().run(ctx)

    asyncio.run(_inner())
    assert mock_upload.call_args.kwargs['category_id'] == '24'


def test_category_id_for_name_unknown_defaults_to_education() -> None:
    from server.apps.pipelines.stages.publish import _category_id_for_name

    assert _category_id_for_name('Education') == '27'
    assert _category_id_for_name('Entertainment') == '24'
    assert _category_id_for_name('Some Unmapped Category') == '27'
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_publish.py -v --no-cov -k category`
Expected: FAIL — `_category_id_for_name` doesn't exist; `upload_video` call has no
`category_id` kwarg today.

- [ ] **Step 2: Implement the fix**

In `server/apps/pipelines/stages/publish.py`, add a lookup table and helper near the top
(after the imports):
```python
_CATEGORY_NAME_TO_ID: dict[str, str] = {
    'film & animation': '1',
    'autos & vehicles': '2',
    'music': '10',
    'pets & animals': '15',
    'sports': '17',
    'travel & events': '19',
    'gaming': '20',
    'people & blogs': '22',
    'comedy': '23',
    'entertainment': '24',
    'news & politics': '25',
    'howto & style': '26',
    'education': '27',
    'science & technology': '28',
    'nonprofits & activism': '29',
}
_DEFAULT_CATEGORY_ID = '27'  # Education


def _category_id_for_name(name: str) -> str:
    """Map a YouTube category name to its numeric categoryId; unknown -> Education."""
    return _CATEGORY_NAME_TO_ID.get(name.strip().lower(), _DEFAULT_CATEGORY_ID)
```

Change the `upload_video` call:
```python
        youtube_video_id = await yt_client.upload_video(
            access_token=access_token,
            video_bytes=video_bytes,
            title=meta['title'],
            description=meta['description'],
            tags=meta.get('tags', []),
            category_id=_category_id_for_name(meta.get('category', 'Education')),
            schedule_at=schedule_at,
            contains_synthetic_media=True,
        )
```
(`upload_video` already accepts `category_id` — it was already a parameter on the
function, just never passed by this caller; `contains_synthetic_media=True` was added by
Milestone 1's Task 4 and stays unchanged here.)

- [ ] **Step 3: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_publish.py -v --no-cov`
Expected: all PASS (including every pre-existing test in the file — none of them assert
on `category_id`, so none should break).

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 4: Commit**

```bash
git add server/apps/pipelines/stages/publish.py tests/test_apps/test_pipelines/test_stages/test_publish.py
git commit -m "fix(publish): pass the metadata stage's chosen category to YouTube upload"
```

---

### Task 8: Real captions track upload

**Files:**
- Modify: `server/apps/pipelines/stages/alignment.py`
- Modify: `server/apps/generation/clients/youtube.py`
- Modify: `server/apps/pipelines/stages/publish.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_alignment.py`
- Test: `tests/test_apps/test_generation/test_youtube_client.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_publish.py`

**Interfaces:**
- Produces: `alignment.py::_build_srt_content(segments) -> bytes` (pure), output key
  `srt_asset_id`; `yt_client.upload_caption_track(access_token, video_id, srt_bytes, language='en', name='English') -> None`.

- [ ] **Step 1: Write the failing SRT-builder test**

Add to `tests/test_apps/test_pipelines/test_stages/test_alignment.py` (check the file's
existing test setup first and follow its style for constructing fake WhisperX segments):
```python
def test_build_srt_content_formats_timestamps() -> None:
    from server.apps.pipelines.stages.alignment import _build_srt_content

    segments = [
        {'start': 0.0, 'end': 2.5, 'text': 'In 476 AD,'},
        {'start': 2.5, 'end': 7.4, 'text': 'the last Roman emperor fell.'},
    ]
    srt = _build_srt_content(segments).decode()
    assert '1\n00:00:00,000 --> 00:00:02,500\nIn 476 AD,' in srt
    assert '2\n00:00:02,500 --> 00:00:07,400\nthe last Roman emperor fell.' in srt
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_alignment.py -v --no-cov -k srt`
Expected: FAIL — `_build_srt_content` doesn't exist.

- [ ] **Step 2: Implement `_build_srt_content` and wire it into the stage**

In `server/apps/pipelines/stages/alignment.py`, add next to `_fmt_ass_time`:
```python
def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _build_srt_content(segments: list[dict[str, Any]]) -> bytes:
    """Build a standard SRT file from WhisperX segment list."""
    blocks: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start = _fmt_srt_time(seg['start'])
        end = _fmt_srt_time(seg['end'])
        text = seg['text'].strip()
        blocks.append(f'{i}\n{start} --> {end}\n{text}')
    return '\n\n'.join(blocks).encode()
```

In `AlignmentStage.run`, after the existing `ass_asset` save, add an SRT save and include
it in the return dict:
```python
        ass_bytes = _build_ass_content(all_segments)
        ass_asset = await ctx.assets.save(
            kind=AssetKind.SUBTITLE,
            content=ass_bytes,
            filename='captions.ass',
            mime='text/x-ssa',
        )
        srt_bytes = _build_srt_content(all_segments)
        srt_asset = await ctx.assets.save(
            kind=AssetKind.SUBTITLE,
            content=srt_bytes,
            filename='captions.srt',
            mime='application/x-subrip',
        )
        return {
            'scenes': all_scenes,
            'ass_asset_id': str(ass_asset.id),
            'srt_asset_id': str(srt_asset.id),
        }
```

- [ ] **Step 3: Add `yt_client.upload_caption_track`**

Write the failing test first, added to `test_youtube_client.py`:
```python
def test_upload_caption_track_posts_multipart() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.generation.clients.youtube import upload_caption_track

    fake_resp = MagicMock()
    fake_resp.status_code = 200

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=fake_resp),
        ) as mock_post:
            await upload_caption_track(
                access_token='tok',
                video_id='yt_vid1',
                srt_bytes=b'1\n00:00:00,000 --> 00:00:01,000\nHi\n',
            )
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs['params']['part'] == 'snippet'
            assert 'metadata' in call_kwargs['files']
            assert 'file' in call_kwargs['files']

    asyncio.run(_inner())
```

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_youtube_client.py -v --no-cov -k caption_track`
Expected: FAIL — function doesn't exist.

Implement in `server/apps/generation/clients/youtube.py` (add `import json` to the
existing imports):
```python
_CAPTIONS_URL = 'https://www.googleapis.com/upload/youtube/v3/captions'


async def upload_caption_track(
    access_token: str,
    video_id: str,
    srt_bytes: bytes,
    language: str = 'en',
    name: str = 'English',
) -> None:
    """Upload an SRT caption track for an existing YouTube video."""
    metadata = json.dumps({
        'snippet': {
            'videoId': video_id,
            'language': language,
            'name': name,
            'isDraft': False,
        },
    })
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            _CAPTIONS_URL,
            params={'part': 'snippet', 'uploadType': 'multipart'},
            headers={'Authorization': f'Bearer {access_token}'},
            files={
                'metadata': (None, metadata, 'application/json'),
                'file': ('captions.srt', srt_bytes, 'application/octet-stream'),
            },
        )
    _classify_response(resp)
```

- [ ] **Step 4: Wire it into `PublishStage`**

In `server/apps/pipelines/stages/publish.py`, after the existing thumbnail-upload block
and before the `job.youtube_video_id = ...` lines, add:
```python
        alignment = ctx.upstream.get('alignment', {})
        srt_asset_id = alignment.get('srt_asset_id')
        if srt_asset_id:
            srt_asset = await Asset.objects.aget(id=srt_asset_id)
            srt_bytes = await asyncio.to_thread(srt_asset.file.read)
            await yt_client.upload_caption_track(
                access_token,
                youtube_video_id,
                srt_bytes,
            )
```
Add `import asyncio` to the top of `publish.py` if not already present (check first —
the file currently has no `asyncio` import since everything is already `await`-based
without needing `to_thread`; this is a new need specific to reading the SRT asset the
same way `qc.py`/`assembly.py` already do via `asyncio.to_thread(asset.file.read)`).

- [ ] **Step 5: Add the publish-stage integration test**

Add to `test_publish.py`:
```python
def test_publish_uploads_caption_track_when_srt_present() -> None:
    ctx = _make_ctx()
    ctx.upstream['alignment'] = {'srt_asset_id': 'asset-srt'}
    fake_job = MagicMock(id='job-srt')
    fake_job.asave = AsyncMock()
    fake_srt_asset = MagicMock()
    fake_srt_asset.file.read.return_value = b'srt content'

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.publish.YouTubeCredential'
                '.objects.aget',
                new=AsyncMock(return_value=MagicMock(token_expiry=None)),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client'
                '.refresh_token_if_needed',
                new=AsyncMock(return_value='tok'),
            ),
            patch(
                'server.apps.pipelines.stages.publish._download_asset',
                new=AsyncMock(return_value=b'video'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.upload_video',
                new=AsyncMock(return_value='yt_srt_test'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.set_thumbnail',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client'
                '.upload_caption_track',
                new=AsyncMock(),
            ) as mock_captions,
            patch(
                'server.apps.pipelines.stages.publish.PublishJob.objects.acreate',
                new=AsyncMock(return_value=fake_job),
            ),
            patch(
                'server.apps.pipelines.stages.publish.Asset.objects.aget',
                new=AsyncMock(return_value=fake_srt_asset),
            ),
        ):
            await PublishStage().run(ctx)
            mock_captions.assert_awaited_once_with(
                'tok', 'yt_srt_test', b'srt content',
            )

    asyncio.run(_inner())
```

- [ ] **Step 6: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_alignment.py tests/test_apps/test_generation/test_youtube_client.py tests/test_apps/test_pipelines/test_stages/test_publish.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add server/apps/pipelines/stages/alignment.py server/apps/generation/clients/youtube.py server/apps/pipelines/stages/publish.py tests/
git commit -m "feat(publish): upload a real SRT captions track alongside burned-in subtitles"
```

---

### Task 9: Music license gate

**Files:**
- Modify: `server/apps/assets/models.py` (`LibraryAsset`)
- Create migration: `just run makemigrations assets`
- Modify: `server/apps/pipelines/stages/music_plan.py`
- Test: `tests/test_apps/test_assets/test_models.py` (check exact filename first)
- Test: `tests/test_apps/test_pipelines/test_stages/test_music_plan.py`

**Interfaces:**
- Produces: `LibraryAsset.license_type` (choices), `LibraryAsset.license_note`.

- [ ] **Step 1: Add license fields to `LibraryAsset`**

In `server/apps/assets/models.py`, add a new `TextChoices` above `LibraryAsset` and two
fields inside it:
```python
class LibraryAssetLicense(models.TextChoices):
    """Licensing basis for a human-curated library asset (esp. music/SFX)."""

    UNSPECIFIED = 'UNSPECIFIED', 'Unspecified'
    OWNED = 'OWNED', 'Owned / original'
    LICENSED = 'LICENSED', 'Licensed (paid)'
    CREATIVE_COMMONS = 'CREATIVE_COMMONS', 'Creative Commons'
    ROYALTY_FREE_VERIFIED = 'ROYALTY_FREE_VERIFIED', 'Royalty-free (verified)'
```
Add to `LibraryAsset`, after `meta`:
```python
    meta = models.JSONField(default=dict)
    license_type = models.CharField(
        max_length=25,
        choices=LibraryAssetLicense.choices,
        default=LibraryAssetLicense.UNSPECIFIED,
    )
    license_note = models.TextField(blank=True)
```
Add a check constraint to `LibraryAsset.Meta.constraints` alongside the existing
`assets_libraryasset_kind_valid` one:
```python
            models.CheckConstraint(
                name='assets_libraryasset_license_type_valid',
                condition=models.Q(license_type__in=LibraryAssetLicense.values),
            ),
```

Run:
```bash
docker compose exec web python manage.py makemigrations assets
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration; both exit 0 (default `UNSPECIFIED` on a new field is
backward-compatible — existing rows just default to "not yet verified," which is the
correct conservative starting state, not an incorrect claim of being licensed).

- [ ] **Step 2: Write the failing music_plan test**

Add to `tests/test_apps/test_pipelines/test_stages/test_music_plan.py` (check the file's
existing `_fetch_music_library`-adjacent tests first and follow the same
mocking/fixture approach):
```python
@pytest.mark.django_db
async def test_fetch_music_library_excludes_unspecified_license() -> None:
    """Tracks with license_type=UNSPECIFIED are excluded from the music pool."""
    from server.apps.assets.models import LibraryAsset, LibraryAssetKind
    from server.apps.pipelines.stages.music_plan import _fetch_music_library

    LibraryAsset.objects.create(
        kind=LibraryAssetKind.MUSIC, name='Unverified track',
    )
    LibraryAsset.objects.create(
        kind=LibraryAssetKind.MUSIC, name='Verified track',
        license_type='ROYALTY_FREE_VERIFIED',
    )

    library = await _fetch_music_library(channel_id='')
    names = {track['name'] for track in library}
    assert names == {'Verified track'}
```

(Check whether the existing test file already has `pytest.mark.asyncio`/an `asyncio.run`
wrapper convention for this async selector function — mirror whichever style
`test_music_plan.py` already uses for testing `_fetch_music_library` directly, since it's
called with `await` in the real stage and the existing tests likely already exercise it
either directly with `asyncio.run` or via the full `run()` flow.)

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_music_plan.py -v --no-cov -k license`
Expected: FAIL — both tracks currently returned regardless of license.

- [ ] **Step 3: Implement the filter**

In `server/apps/pipelines/stages/music_plan.py`, change `_fetch_music_library`:
```python
async def _fetch_music_library(channel_id: str) -> list[dict[str, Any]]:
    """Query LibraryAsset for MUSIC kind with a verified license, channel then global."""
    from server.apps.assets.models import (  # noqa: PLC0415
        LibraryAsset,
        LibraryAssetKind,
        LibraryAssetLicense,
    )

    licensed = ~models.Q(license_type=LibraryAssetLicense.UNSPECIFIED)
    channel_qs = LibraryAsset.objects.filter(
        licensed,
        kind=LibraryAssetKind.MUSIC,
        is_active=True,
        channel__id=channel_id,
    )
    global_qs = LibraryAsset.objects.filter(
        licensed,
        kind=LibraryAssetKind.MUSIC,
        is_active=True,
        channel__isnull=True,
    )
    return [
        {
            'id': str(asset.id),
            'name': asset.name,
            'tags': asset.tags,
            'meta': asset.meta,
        }
        async for asset in (channel_qs | global_qs).order_by('name')[:50]
    ]
```
Add `from django.db import models` to the top of `music_plan.py` (needed for the `~Q(...)`
exclusion) if not already imported.

- [ ] **Step 4: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_music_plan.py tests/test_apps/test_assets/ -v --no-cov`
Expected: all PASS. If any pre-existing music_plan test seeded a `LibraryAsset` without
setting `license_type`, it now defaults to `UNSPECIFIED` and will disappear from the
library results — check for that and add `license_type='ROYALTY_FREE_VERIFIED'` (or
whichever value fits the fixture's intent) to any such existing test fixture so it keeps
passing for the right reason.

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add server/apps/assets/models.py server/apps/assets/migrations/*.py server/apps/pipelines/stages/music_plan.py tests/
git commit -m "feat(assets): require a verified license before a track enters the music pool"
```

---

## Final Verification (after Task 9)

- [ ] Run the full suite with coverage: `docker compose exec web pytest` (100% required).
- [ ] Run `ruff check .`, `ruff format --check .`, `mypy server`, `lint-imports`.
- [ ] Run `lintmigrations` and `check_migrations --exclude-apps=axes` across all
  migrations added by this plan (`ideas`, `analytics`, `publishing`, `assets`).
- [ ] Manually run one full ideation cycle for a niche with a live
  `YOUTUBE_DATA_API_KEY` configured, confirm a `NicheOutlierScan` row is written and the
  next niche-only `generate()` call's ideas metadata reflects outlier-informed framing.
- [ ] Manually reconnect a test channel's YouTube OAuth (to pick up the new
  `yt-analytics.readonly` scope) and run `pull_publish_job_metrics` against a real
  published video, confirming a `PublishJobMetric` row with a populated
  `retention_curve`.
- [ ] Hand off to `superpowers:requesting-code-review` for the final whole-branch review
  once all 9 tasks are committed, then `superpowers:finishing-a-development-branch`.
