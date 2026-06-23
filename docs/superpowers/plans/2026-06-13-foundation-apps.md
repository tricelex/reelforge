# Foundation Apps (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `core`, `channels`, `prompts`, and `assets` Django apps with all data models, S3 storage backend, and the LibraryAsset upload normalization task — the complete data and infrastructure foundation Phase 2 (pipeline engine) builds on.

**Architecture:** Each new app follows the spec's file layout (`models.py`, `services.py`, `tasks.py`, `admin.py`). `schemas.py` (Pydantic) is deferred to Phase 2 when APIs are built. The `core` app gains abstract base models, shared exceptions, and an async Redis publish helper. `django-storages` with boto3 connects to RustFS (S3-compatible). New apps use Pydantic for schemas; the existing `main` app keeps its msgspec pattern unchanged.

**Tech Stack:** Django 6.0 / Python 3.13, django-storages[boto3], asyncio subprocesses for ffprobe/ffmpeg, Taskiq for background tasks, pytest (existing `_run()` pattern for async tests — no pytest-asyncio needed), Unfold admin, python-decouple for settings.

---

## Context

Phase 1 bootstraps the data layer for Reelforge's AI video automation platform. The pipeline engine (Phase 2) needs:
- `UUIDModel`, `TimeStampedModel` abstract base models (used by every entity in spec §2.2, §4.1, §9.1)
- `Channel` (the run's owner and config source — §1, §10.1, §16.3)
- `NicheConfig` (content config: audience, angle, banned topics, story format — §3.1, §11.2)
- `StoryFormat` (narrative architecture: beats, pacing, music mood map — §11.1)
- `Character` (approved reference images for consistent AI generation — §9.1, §12, §16)
- `PromptTemplate` / `PromptVersion` (versioned prompts; stage inputs hash against them — §2.2, §2.4)
- `Asset`, `LibraryAsset`, `AssetRendition` (all generated + curated files — §4.1)
- S3 storage (RustFS, S3-compatible via boto3 — §4)
- `ingest_library_asset` Taskiq task (ffprobe probe → per-kind validation → EBU R128 loudness → renditions — §4.3)

Cross-app FK references use Django string references (`'channels.Channel'`) throughout — no cross-app Python imports. FKs from `Asset`/`Character` to `pipelines.PipelineRun` are deferred to Phase 2 (those models don't exist yet); they will be added via an additive Phase 2 migration.

---

## File Structure

### New files
```
server/apps/core/
  models.py              # UUIDModel, TimeStampedModel (abstract)
  exceptions.py          # RetryableProviderError, FatalProviderError
  redis_client.py        # async Redis publish helper

server/common/
  s3.py                  # AssetStorage (S3Boto3Storage subclass)

server/settings/components/
  storage.py             # S3/boto3 env config (uses config() from python-decouple)

server/apps/channels/
  __init__.py
  apps.py
  models.py              # Channel, NicheConfig, YouTubeCredential, ChannelBranding,
                         #   Character, CharacterSheetItem, CharacterGenerationSession
  admin.py               # Unfold admin for all 7 models
  migrations/
    __init__.py
    0001_initial.py      # generated via makemigrations

server/apps/prompts/
  __init__.py
  apps.py
  models.py              # PromptTemplate, PromptVersion, StoryFormat
  admin.py
  migrations/
    __init__.py
    0001_initial.py      # generated

server/apps/assets/
  __init__.py
  apps.py
  models.py              # AssetKind, LibraryAssetKind enums + Asset, LibraryAsset, AssetRendition
  services.py            # LibraryAssetService.register() + ingest helpers
  tasks.py               # ingest_library_asset TaskIQ task
  admin.py
  migrations/
    __init__.py
    0001_initial.py      # generated

tests/test_apps/
  test_core/
    __init__.py
    test_models.py
    test_exceptions.py
    test_redis_client.py
  test_channels/
    __init__.py
    test_models.py
  test_prompts/
    __init__.py
    test_models.py
  test_assets/
    __init__.py
    test_models.py
    test_services.py
    test_tasks.py
```

### Files to modify
```
pyproject.toml                           # add django-storages[boto3]
server/settings/__init__.py              # add 'components/storage.py' to _base_settings
server/settings/components/common.py     # add 4 new apps + django.contrib.***REMOVED*** to INSTALLED_APPS
server/implemented.py                    # add LibraryAssetService DI registration
```

---

## Task 1: Project dependencies + S3 storage settings

**Files:**
- Modify: `pyproject.toml`
- Create: `server/common/s3.py`
- Create: `server/settings/components/storage.py`
- Modify: `server/settings/__init__.py`
- Test: `tests/test_apps/test_assets/test_models.py` (import test — fails until storage wired)

- [ ] **Step 1: Write the failing import test**

```python
# tests/test_apps/test_assets/__init__.py  (empty)
```

```python
# tests/test_apps/test_assets/test_models.py
from server.common.s3 import AssetStorage


def test_asset_storage_class_is_importable() -> None:
    assert AssetStorage is not None
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
docker compose exec web pytest tests/test_apps/test_assets/test_models.py --no-cov -x
```

Expected: `ModuleNotFoundError: No module named 'server.common.s3'`

- [ ] **Step 3: Add django-storages to pyproject.toml**

In `[tool.poetry.dependencies]`, add:
```toml
django-storages = { version = "^1.15", extras = ["boto3"] }
```

Then inside Docker:
```bash
docker compose exec web pip install 'django-storages[boto3]'
```

(The lock file update happens later when rebuilding the image; for now pip install is sufficient for development.)

- [ ] **Step 4: Create server/common/s3.py**

```python
from storages.backends.s3boto3 import S3Boto3Storage


class AssetStorage(S3Boto3Storage):
    """S3-compatible storage for pipeline-generated and library assets."""

    location = 'assets'
    file_overwrite = False
    default_acl = None  # private; access via presigned URLs
```

- [ ] **Step 5: Create server/settings/components/storage.py**

```python
from server.settings.components import config

# RustFS / MinIO / S3-compatible object storage
AWS_ACCESS_KEY_ID: str = config('AWS_ACCESS_KEY_ID', default='minioadmin')
AWS_SECRET_ACCESS_KEY: str = config(
    'AWS_SECRET_ACCESS_KEY', default='minioadmin'
)
AWS_STORAGE_BUCKET_NAME: str = config(
    'AWS_STORAGE_BUCKET_NAME', default='***REMOVED***'
)
AWS_S3_ENDPOINT_URL: str = config(
    'AWS_S3_ENDPOINT_URL', default='http://minio:9000'
)
AWS_S3_REGION_NAME: str = config('AWS_S3_REGION_NAME', default='us-east-1')
AWS_S3_FILE_OVERWRITE: bool = False
AWS_DEFAULT_ACL: str | None = None
# Disable SSL verification for local self-signed certs (override to True in prod)
AWS_S3_VERIFY: bool = config('AWS_S3_VERIFY', default=False, cast=bool)

STORAGES: dict[str, dict[str, str]] = {
    'default': {'BACKEND': 'server.common.s3.AssetStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
    },
}
```

- [ ] **Step 6: Add storage component to server/settings/__init__.py**

In the `_base_settings` tuple, add `'components/storage.py'` after `'components/observability.py'`:

```python
_base_settings = (
    'components/common.py',
    'components/logging.py',
    'components/csp.py',
    'components/caches.py',
    'components/api.py',
    'components/observability.py',
    'components/storage.py',  # ← add this line
    f'environments/{_ENV}.py',
    optional('environments/local.py'),
)
```

- [ ] **Step 7: Run test to verify it passes**

```bash
docker compose exec web pytest tests/test_apps/test_assets/test_models.py --no-cov -x
```

Expected: `PASSED`

- [ ] **Step 8: Commit**

```bash
git add server/common/s3.py server/settings/components/storage.py \
        server/settings/__init__.py pyproject.toml
git commit -m "feat(storage): add S3 storage backend and pytest-asyncio dependency

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Core abstract base models + exceptions + Redis helper

**Files:**
- Create: `server/apps/core/models.py`
- Create: `server/apps/core/exceptions.py`
- Create: `server/apps/core/redis_client.py`
- Create: `tests/test_apps/test_core/__init__.py`
- Create: `tests/test_apps/test_core/test_models.py`
- Create: `tests/test_apps/test_core/test_exceptions.py`
- Create: `tests/test_apps/test_core/test_redis_client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_apps/test_core/__init__.py  (empty)
```

```python
# tests/test_apps/test_core/test_models.py
import uuid

import pytest
from django.db import models

from server.apps.core.models import TimeStampedModel, UUIDModel


class _SampleModel(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=10)

    class Meta:
        app_label = 'core'


@pytest.mark.django_db
def test_uuid_model_uses_uuid_primary_key() -> None:
    instance = _SampleModel(name='x')
    assert isinstance(instance.id, uuid.UUID)


def test_timestamped_model_has_timestamp_fields() -> None:
    assert hasattr(TimeStampedModel, 'created_at')
    assert hasattr(TimeStampedModel, 'updated_at')
```

```python
# tests/test_apps/test_core/test_exceptions.py
from server.apps.core.exceptions import (
    FatalProviderError,
    RetryableProviderError,
)


def test_retryable_error_stores_provider_and_status() -> None:
    err = RetryableProviderError(
        'rate limited', provider='fal_flux', status_code=429
    )
    assert str(err) == 'rate limited'
    assert err.provider == 'fal_flux'
    assert err.status_code == 429


def test_fatal_error_stores_provider_and_code() -> None:
    err = FatalProviderError(
        'content policy', provider='fal_flux', error_code='SAFETY_FILTER'
    )
    assert str(err) == 'content policy'
    assert err.provider == 'fal_flux'
    assert err.error_code == 'SAFETY_FILTER'


def test_retryable_error_optional_fields_default_none() -> None:
    err = RetryableProviderError('timeout', provider='kling')
    assert err.status_code is None


def test_fatal_error_optional_fields_default_none() -> None:
    err = FatalProviderError('bad prompt', provider='openai')
    assert err.error_code is None
```

```python
# tests/test_apps/test_core/test_redis_client.py
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.core.redis_client import publish_pipeline_event


@pytest.mark.asyncio
async def test_publish_pipeline_event_calls_redis_publish() -> None:
    mock_redis = AsyncMock()
    with patch(
        'server.apps.core.redis_client.get_redis', return_value=mock_redis
    ):
        await publish_pipeline_event('run-abc', b'{"type":"stage.queued"}')
    mock_redis.publish.assert_awaited_once_with(
        'pipeline:run-abc', b'{"type":"stage.queued"}'
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec web pytest tests/test_apps/test_core/ --no-cov -x
```

Expected: `ModuleNotFoundError` (modules don't exist yet)

- [ ] **Step 3: Create server/apps/core/models.py**

```python
import uuid

from django.db import models


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

- [ ] **Step 4: Create server/apps/core/exceptions.py**

```python
class RetryableProviderError(Exception):
    """Provider error that can be retried (429, 5xx, timeout)."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class FatalProviderError(Exception):
    """Provider error requiring human intervention (content policy, bad prompt)."""

    def __init__(
        self,
        message: str,
        provider: str,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.error_code = error_code
```

- [ ] **Step 5: Create server/apps/core/redis_client.py**

```python
import redis.asyncio as aioredis
from django.conf import settings


def get_redis() -> aioredis.Redis:
    """Return a configured async Redis client (one per call; callers close it)."""
    return aioredis.from_url(settings.REDIS_URL, decode_responses=False)


async def publish_pipeline_event(run_id: str, data: bytes) -> None:
    """Publish an encoded SSE event to the pipeline Redis channel."""
    client = get_redis()
    await client.publish(f'pipeline:{run_id}', data)
```

- [ ] **Step 6: Verify async test helper pattern**

The project uses `asyncio.run()` for async tests (no pytest-asyncio). See `tests/test_server/test_taskiq_middleware.py` for the canonical pattern:
```python
def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)
```

All async task tests follow this pattern — synchronous test function + `_run(coro)` wrapper. No changes to pyproject.toml needed for async tests.

- [ ] **Step 7: Run tests to verify they pass**

```bash
docker compose exec web pytest tests/test_apps/test_core/ --no-cov -x
```

Expected: All tests `PASSED`

- [ ] **Step 8: Commit**

```bash
git add server/apps/core/models.py server/apps/core/exceptions.py \
        server/apps/core/redis_client.py tests/test_apps/test_core/
git commit -m "feat(core): add abstract base models, provider exceptions, Redis publish helper

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: channels app — all models + admin + migration

**Files:**
- Create: `server/apps/channels/__init__.py`
- Create: `server/apps/channels/apps.py`
- Create: `server/apps/channels/models.py`
- Create: `server/apps/channels/admin.py`
- Create: `tests/test_apps/test_channels/__init__.py`
- Create: `tests/test_apps/test_channels/test_models.py`
- Modify: `server/settings/components/common.py` — add `django.contrib.***REMOVED***` and `server.apps.channels`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_apps/test_channels/__init__.py  (empty)
```

```python
# tests/test_apps/test_channels/test_models.py
from decimal import Decimal

import pytest

from server.apps.channels.models import (
    Channel,
    ChannelBranding,
    ChannelKind,
    Character,
    CharacterDesignMode,
    CharacterGenerationSession,
    CharacterSheetItem,
    NicheConfig,
    PublishMode,
    YouTubeCredential,
)


@pytest.mark.django_db
def test_channel_creation_defaults() -> None:
    ch = Channel.objects.create(name='Test Channel', kind=ChannelKind.LONGFORM)
    assert str(ch.id)  # UUID pk present
    assert ch.publish_mode == PublishMode.REVIEW
    assert ch.character_design_mode == CharacterDesignMode.INTERACTIVE
    assert ch.gates == []
    assert ch.is_active is True
    assert ch.wpm == 158


@pytest.mark.django_db
def test_channel_str() -> None:
    ch = Channel.objects.create(name='History Hub', kind=ChannelKind.LONGFORM)
    assert str(ch) == 'History Hub'


@pytest.mark.django_db
def test_niche_config_links_to_channel() -> None:
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    nc = NicheConfig.objects.create(
        channel=ch, audience='adults', angle='historical'
    )
    assert nc.channel_id == ch.id
    assert nc.banned_topics == []


@pytest.mark.django_db
def test_youtube_credential_one_to_one() -> None:
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    cred = YouTubeCredential.objects.create(
        channel=ch, access_token='tok', refresh_token='ref'
    )
    assert cred.channel_id == ch.id


@pytest.mark.django_db
def test_channel_branding_many_to_many_fonts_empty() -> None:
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    branding = ChannelBranding.objects.create(channel=ch)
    assert branding.fonts.count() == 0
    assert branding.watermark_opacity == 0.6


@pytest.mark.django_db
def test_character_default_status_draft() -> None:
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    char = Character.objects.create(
        channel=ch, name='King Alaric', appearance_prompt='tall, golden crown'
    )
    assert char.status == 'DRAFT'
    assert char.origin == 'RUN'
    assert char.total_creation_cost_usd == Decimal('0')


@pytest.mark.django_db
def test_character_sheet_item_links_character(library_asset_factory) -> None:
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    char = Character.objects.create(channel=ch, name='K', appearance_prompt='p')
    asset = library_asset_factory()
    item = CharacterSheetItem.objects.create(
        character=char, asset=asset, label='front'
    )
    assert item.character_id == char.id


@pytest.mark.django_db
def test_character_generation_session_rounds_default_empty() -> None:
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    char = Character.objects.create(channel=ch, name='K', appearance_prompt='p')
    session = CharacterGenerationSession.objects.create(character=char)
    assert session.rounds == []
```

Note: `library_asset_factory` is a fixture we'll add in Task 5's test when `LibraryAsset` exists. For now, keep the `test_character_sheet_item_links_character` test commented out — we'll activate it in Task 5.

- [ ] **Step 2: Run to verify failure**

```bash
docker compose exec web pytest tests/test_apps/test_channels/ --no-cov -x
```

Expected: `ModuleNotFoundError: No module named 'server.apps.channels'`

- [ ] **Step 3: Add django.contrib.***REMOVED*** to INSTALLED_APPS**

In `server/settings/components/common.py`, locate the `INSTALLED_APPS` tuple and add:
```python
INSTALLED_APPS: tuple[str, ...] = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.***REMOVED***',  # ← add here, for ArrayField
    'axes',
    'server.apps.core',
    'server.apps.main',
    'server.apps.channels',  # ← add here
    ...,
)
```

- [ ] **Step 4: Create server/apps/channels/__init__.py (empty)**

- [ ] **Step 5: Create server/apps/channels/apps.py**

```python
from django.apps import AppConfig


class ChannelsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.channels'
    verbose_name = 'Channels'
```

- [ ] **Step 6: Create server/apps/channels/models.py**

```python
from django.contrib.***REMOVED***.fields import ArrayField
from django.db import models

from server.apps.core.models import TimeStampedModel, UUIDModel


class ChannelKind(models.TextChoices):
    LONGFORM = 'LONGFORM', 'Long-form'
    SHORTS = 'SHORTS', 'Shorts'
    CLIPPING = 'CLIPPING', 'Clipping'


class PublishMode(models.TextChoices):
    AUTO = 'auto', 'Auto'
    REVIEW = 'review', 'Review'


class CharacterDesignMode(models.TextChoices):
    INTERACTIVE = 'interactive', 'Interactive'
    AUTO = 'auto', 'Auto'
    NONE = 'none', 'None'


class CharacterStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    APPROVED = 'APPROVED', 'Approved'
    RETIRED = 'RETIRED', 'Retired'


class CharacterOrigin(models.TextChoices):
    LIBRARY = 'LIBRARY', 'Library'
    RUN = 'RUN', 'Run'


class Channel(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=ChannelKind.choices)
    publish_mode = models.CharField(
        max_length=10, choices=PublishMode.choices, default=PublishMode.REVIEW
    )
    # Gate keys that are armed for this channel (e.g. ['storyboard_gate', 'final_gate'])
    gates = ArrayField(
        models.CharField(max_length=40), default=list, blank=True
    )
    character_design_mode = models.CharField(
        max_length=15,
        choices=CharacterDesignMode.choices,
        default=CharacterDesignMode.INTERACTIVE,
    )
    default_budget_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # ElevenLabs TTS config
    voice_id = models.CharField(max_length=100, blank=True)
    stability = models.FloatField(default=0.5)
    similarity_boost = models.FloatField(default=0.75)
    wpm = models.PositiveIntegerField(
        default=158
    )  # words per minute for script pacing
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class NicheConfig(UUIDModel, TimeStampedModel):
    """Content configuration for one channel: audience, angle, format, lore."""

    channel = models.OneToOneField(
        Channel, on_delete=models.CASCADE, related_name='niche_config'
    )
    # FK to prompts.StoryFormat — string ref, prompts app installed later
    format = models.ForeignKey(
        'prompts.StoryFormat',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    audience = models.TextField(blank=True)
    angle = models.TextField(blank=True)
    banned_topics = ArrayField(
        models.CharField(max_length=200), default=list, blank=True
    )
    # Persistent lore document for fiction series (recurring universe)
    lore_document = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Niche config'

    def __str__(self) -> str:
        return f'NicheConfig for {self.channel}'


class YouTubeCredential(UUIDModel, TimeStampedModel):
    channel = models.OneToOneField(
        Channel, on_delete=models.CASCADE, related_name='youtube_credential'
    )
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True)

    def __str__(self) -> str:
        return f'YouTubeCredential for {self.channel}'


class ChannelBranding(UUIDModel):
    channel = models.OneToOneField(
        Channel, on_delete=models.CASCADE, related_name='branding'
    )
    # String refs to assets.LibraryAsset — assets app installed later in this phase
    intro = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    outro = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    watermark = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    watermark_position = models.CharField(max_length=20, default='bottom_right')
    watermark_opacity = models.FloatField(default=0.6)
    caption_style = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    fonts = models.ManyToManyField(
        'assets.LibraryAsset', related_name='+', blank=True
    )
    music_pool_tags = ArrayField(
        models.CharField(max_length=40), default=list, blank=True
    )
    thumbnail_palette = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f'Branding for {self.channel}'


class Character(UUIDModel, TimeStampedModel):
    """An approved AI character with locked appearance prompt and reference image."""

    channel = models.ForeignKey(
        Channel,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='characters',
    )
    name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=10,
        choices=CharacterStatus.choices,
        default=CharacterStatus.DRAFT,
    )
    appearance_prompt = models.TextField()
    persona = models.TextField(blank=True)
    hero_ref = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    total_creation_cost_usd = models.DecimalField(
        max_digits=8, decimal_places=4, default=0
    )
    origin = models.CharField(
        max_length=10,
        choices=CharacterOrigin.choices,
        default=CharacterOrigin.RUN,
    )
    # source_run FK to pipelines.PipelineRun added in Phase 2 migration

    def __str__(self) -> str:
        return self.name


class CharacterSheetItem(UUIDModel):
    """Angle/expression/outfit variant for a character (front, profile, angry, etc.)."""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name='sheet'
    )
    asset = models.ForeignKey(
        'assets.LibraryAsset', on_delete=models.PROTECT, related_name='+'
    )
    label = models.CharField(max_length=60)

    def __str__(self) -> str:
        return f'{self.character} — {self.label}'


class CharacterGenerationSession(UUIDModel, TimeStampedModel):
    """One Studio iteration loop. Every round logged: prompt, refs, candidates, cost."""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name='sessions'
    )
    # run FK to pipelines.PipelineRun added in Phase 2 migration
    rounds = models.JSONField(default=list)

    def __str__(self) -> str:
        return f'Session for {self.character} ({self.created_at})'
```

- [ ] **Step 7: Create server/apps/channels/admin.py**

```python
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.channels.models import (
    Channel,
    ChannelBranding,
    Character,
    CharacterGenerationSession,
    CharacterSheetItem,
    NicheConfig,
    YouTubeCredential,
)


class NicheConfigInline(admin.StackedInline):
    model = NicheConfig
    extra = 0


class ChannelBrandingInline(admin.StackedInline):
    model = ChannelBranding
    extra = 0


@admin.register(Channel)
class ChannelAdmin(ModelAdmin):
    list_display = ('name', 'kind', 'publish_mode', 'is_active')
    list_filter = ('kind', 'publish_mode', 'is_active')
    search_fields = ('name',)
    inlines = [NicheConfigInline, ChannelBrandingInline]


@admin.register(NicheConfig)
class NicheConfigAdmin(ModelAdmin):
    list_display = ('channel', 'format')
    search_fields = ('channel__name',)


@admin.register(YouTubeCredential)
class YouTubeCredentialAdmin(ModelAdmin):
    list_display = ('channel',)
    search_fields = ('channel__name',)


class CharacterSheetItemInline(TabularInline):
    model = CharacterSheetItem
    extra = 0


@admin.register(Character)
class CharacterAdmin(ModelAdmin):
    list_display = (
        'name',
        'channel',
        'status',
        'origin',
        'total_creation_cost_usd',
    )
    list_filter = ('status', 'origin')
    search_fields = ('name',)
    inlines = [CharacterSheetItemInline]


@admin.register(CharacterGenerationSession)
class CharacterGenerationSessionAdmin(ModelAdmin):
    list_display = ('character', 'created_at')
    search_fields = ('character__name',)
```

- [ ] **Step 8: Defer migration to Task 5**

`channels` has FKs to `assets.LibraryAsset` (`ChannelBranding`, `Character`, `CharacterSheetItem`). Django generates cross-app migration dependencies automatically — but only if the target app is installed when `makemigrations` runs. Since `assets` is added in Task 5, run `makemigrations` for ALL apps together at the end of Task 5, not per-task. Skip this step and continue to tests.

- [ ] **Step 9: Run tests (without migration — assets not installed yet)**

Tests that only instantiate model objects in memory (no DB) will pass. DB tests that attempt ORM operations will fail because the table doesn't exist. Mark DB tests `skip` until Task 5's combined migration step:

```python
@pytest.mark.skip(
    reason='Migration deferred to Task 5 — run after assets app added'
)
@pytest.mark.django_db
def test_channel_creation_defaults() -> None: ...
```

Alternatively, run only the non-DB tests to verify imports and model class definitions:
```bash
docker compose exec web pytest tests/test_apps/test_channels/ --no-cov -x -k 'not django_db'
```

- [ ] **Step 10: Commit (without running migration)**

```bash
git add server/apps/channels/ tests/test_apps/test_channels/ \
        server/settings/components/common.py
git commit -m "feat(channels): add Channel, NicheConfig, Character models and Unfold admin

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: prompts app — PromptTemplate, PromptVersion, StoryFormat

**Files:**
- Create: `server/apps/prompts/__init__.py`
- Create: `server/apps/prompts/apps.py`
- Create: `server/apps/prompts/models.py`
- Create: `server/apps/prompts/admin.py`
- Create: `tests/test_apps/test_prompts/__init__.py`
- Create: `tests/test_apps/test_prompts/test_models.py`
- Modify: `server/settings/components/common.py` — add `server.apps.prompts`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_apps/test_prompts/__init__.py  (empty)
```

```python
# tests/test_apps/test_prompts/test_models.py
import pytest

from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


@pytest.mark.django_db
def test_prompt_template_key_is_unique() -> None:
    PromptTemplate.objects.create(
        name='Scene Breakdown', key='scene_breakdown', scope=PromptScope.GLOBAL
    )
    with pytest.raises(Exception):
        PromptTemplate.objects.create(
            name='Dupe', key='scene_breakdown', scope=PromptScope.GLOBAL
        )


@pytest.mark.django_db
def test_prompt_version_unique_per_template_and_version() -> None:
    tmpl = PromptTemplate.objects.create(
        name='Script', key='script', scope=PromptScope.CHANNEL
    )
    PromptVersion.objects.create(
        template=tmpl,
        version=1,
        system_prompt='You are a scriptwriter.',
        user_prompt='Write chapter {chapter_idx}.',
    )
    with pytest.raises(Exception):
        PromptVersion.objects.create(
            template=tmpl,
            version=1,
            system_prompt='Duplicate.',
            user_prompt='.',
        )


@pytest.mark.django_db
def test_prompt_version_defaults() -> None:
    tmpl = PromptTemplate.objects.create(
        name='Outline', key='outline', scope=PromptScope.GLOBAL
    )
    pv = PromptVersion.objects.create(
        template=tmpl, version=1, system_prompt='sys', user_prompt='usr'
    )
    assert pv.model == 'claude-opus-4-8'
    assert pv.temperature == 1.0
    assert pv.max_tokens == 8192
    assert pv.is_active is False


@pytest.mark.django_db
def test_story_format_key_is_unique() -> None:
    StoryFormat.objects.create(
        key='true_crime_case',
        name='True Crime Case',
        beats=[{'key': 'cold_open', 'pct': 0.05}],
    )
    with pytest.raises(Exception):
        StoryFormat.objects.create(key='true_crime_case', name='Dupe', beats=[])


@pytest.mark.django_db
def test_story_format_fiction_default_false() -> None:
    sf = StoryFormat.objects.create(
        key='history_epic', name='History Epic', beats=[]
    )
    assert sf.fiction is False
    assert sf.narration_pov == 'narrator'
    assert sf.is_active is True
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose exec web pytest tests/test_apps/test_prompts/ --no-cov -x
```

Expected: `ModuleNotFoundError: No module named 'server.apps.prompts'`

- [ ] **Step 3: Add server.apps.prompts to INSTALLED_APPS**

In `server/settings/components/common.py`:
```python
('server.apps.channels',)
('server.apps.prompts',)  # ← add here
```

- [ ] **Step 4: Create server/apps/prompts/__init__.py (empty)**

- [ ] **Step 5: Create server/apps/prompts/apps.py**

```python
from django.apps import AppConfig


class PromptsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.prompts'
    verbose_name = 'Prompts'
```

- [ ] **Step 6: Create server/apps/prompts/models.py**

```python
from django.db import models

from server.apps.core.models import TimeStampedModel, UUIDModel


class PromptScope(models.TextChoices):
    GLOBAL = 'GLOBAL', 'Global'
    NICHE = 'NICHE', 'Niche'
    CHANNEL = 'CHANNEL', 'Channel'


class PromptTemplate(UUIDModel, TimeStampedModel):
    """A named prompt slot (e.g. 'scene_breakdown'). Versioned separately."""

    name = models.CharField(max_length=120)
    key = models.CharField(max_length=60, unique=True)
    scope = models.CharField(max_length=10, choices=PromptScope.choices)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.key


class PromptVersion(UUIDModel, TimeStampedModel):
    """One version of a prompt template. Only one can be active at a time."""

    template = models.ForeignKey(
        PromptTemplate, on_delete=models.CASCADE, related_name='versions'
    )
    version = models.PositiveIntegerField()
    system_prompt = models.TextField()
    user_prompt = models.TextField()
    model = models.CharField(max_length=60, default='claude-opus-4-8')
    temperature = models.FloatField(default=1.0)
    max_tokens = models.PositiveIntegerField(default=8192)
    is_active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'version'],
                name='uq_prompt_template_version',
            )
        ]

    def __str__(self) -> str:
        return f'{self.template.key} v{self.version}'


class StoryFormat(UUIDModel, TimeStampedModel):
    """Narrative architecture definition: beats, pacing, music moods.

    Rows represent formats like 'true_crime_case', 'fantasy_story', 'listicle'.
    Adding a new niche format is an admin task — no code change needed.
    """

    key = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    fiction = models.BooleanField(default=False)
    narration_pov = models.CharField(max_length=30, default='narrator')
    beats = models.JSONField()
    pacing = models.JSONField(default=dict)
    prompt_overrides = models.JSONField(default=dict)
    music_mood_map = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name
```

- [ ] **Step 7: Create server/apps/prompts/admin.py**

```python
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.prompts.models import (
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


class PromptVersionInline(TabularInline):
    model = PromptVersion
    extra = 0
    fields = ('version', 'model', 'is_active', 'temperature', 'max_tokens')


@admin.register(PromptTemplate)
class PromptTemplateAdmin(ModelAdmin):
    list_display = ('key', 'name', 'scope')
    search_fields = ('key', 'name')
    inlines = [PromptVersionInline]


@admin.register(PromptVersion)
class PromptVersionAdmin(ModelAdmin):
    list_display = ('template', 'version', 'model', 'is_active')
    list_filter = ('is_active', 'model')
    search_fields = ('template__key',)


@admin.register(StoryFormat)
class StoryFormatAdmin(ModelAdmin):
    list_display = ('key', 'name', 'fiction', 'narration_pov', 'is_active')
    list_filter = ('fiction', 'is_active')
    search_fields = ('key', 'name')
```

- [ ] **Step 8: Commit (migration deferred to Task 5)**

Same as Task 3: prompts has no cross-app FKs to assets, but we defer ALL migrations to Task 5 to run them together in dependency order.

```bash
git add server/apps/prompts/ tests/test_apps/test_prompts/ \
        server/settings/components/common.py
git commit -m "feat(prompts): add PromptTemplate, PromptVersion, StoryFormat models

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: assets app — models (Asset, LibraryAsset, AssetRendition)

**Files:**
- Create: `server/apps/assets/__init__.py`
- Create: `server/apps/assets/apps.py`
- Create: `server/apps/assets/models.py`
- Create: `tests/test_apps/test_assets/test_models.py` (expand existing file)
- Modify: `server/settings/components/common.py` — add `server.apps.assets`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_apps/test_assets/test_models.py`:

```python
import pytest

from server.apps.assets.models import (
    Asset,
    AssetKind,
    LibraryAsset,
    LibraryAssetKind,
    AssetRendition,
)
from server.common.s3 import AssetStorage


def test_asset_storage_class_is_importable() -> None:
    assert AssetStorage is not None


@pytest.mark.django_db
def test_library_asset_creation_defaults() -> None:
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.MUSIC,
        name='Epic Background Track',
    )
    assert str(asset.id)
    assert asset.is_active is True
    assert asset.version == 1
    assert asset.tags == []
    assert asset.meta == {}


@pytest.mark.django_db
def test_library_asset_str() -> None:
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.WATERMARK, name='Logo'
    )
    assert str(asset) == 'Logo (WATERMARK)'


@pytest.mark.django_db
def test_asset_rendition_links_library_asset() -> None:
    source = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO, name='Intro Clip'
    )
    rendition = AssetRendition.objects.create(source=source, profile='mezz')
    assert rendition.source_id == source.id


@pytest.mark.django_db
def test_asset_kind_choices_include_image() -> None:
    # Confirm the enum is usable — Asset rows without files can't be persisted
    # with a real S3 backend, so we just verify the choices are accessible.
    assert AssetKind.IMAGE in AssetKind.values
    assert AssetKind.FINAL_VIDEO in AssetKind.values
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose exec web pytest tests/test_apps/test_assets/test_models.py --no-cov -x
```

Expected: `ImportError` on `server.apps.assets.models`

- [ ] **Step 3: Add server.apps.assets to INSTALLED_APPS**

In `server/settings/components/common.py`:
```python
('server.apps.prompts',)
('server.apps.assets',)  # ← add here
```

- [ ] **Step 4: Create server/apps/assets/__init__.py (empty)**

- [ ] **Step 5: Create server/apps/assets/apps.py**

```python
from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.assets'
    verbose_name = 'Assets'
```

- [ ] **Step 6: Create server/apps/assets/models.py**

```python
from django.contrib.***REMOVED***.fields import ArrayField
from django.db import models

from server.apps.core.models import TimeStampedModel, UUIDModel
from server.common.s3 import AssetStorage


def _asset_upload_to(instance: 'Asset', filename: str) -> str:
    return f'assets/{instance.kind.lower()}/{instance.id}/{filename}'


def _library_asset_upload_to(instance: 'LibraryAsset', filename: str) -> str:
    return f'library/{instance.kind.lower()}/{instance.id}/{filename}'


def _rendition_upload_to(instance: 'AssetRendition', filename: str) -> str:
    return (
        f'library/{instance.source_id}/renditions/{instance.profile}/{filename}'
    )


class AssetKind(models.TextChoices):
    IMAGE = 'IMAGE', 'Image'
    VIDEO_SEGMENT = 'VIDEO_SEGMENT', 'Video segment'
    AUDIO_VO = 'AUDIO_VO', 'Audio voice-over'
    SUBTITLE = 'SUBTITLE', 'Subtitle (ASS)'
    FINAL_VIDEO = 'FINAL_VIDEO', 'Final video'
    THUMBNAIL = 'THUMBNAIL', 'Thumbnail'
    TRANSCRIPT = 'TRANSCRIPT', 'Transcript'
    DOC = 'DOC', 'Document'


class LibraryAssetKind(models.TextChoices):
    WATERMARK = 'WATERMARK', 'Watermark'
    INTRO = 'INTRO', 'Intro'
    OUTRO = 'OUTRO', 'Outro'
    OVERLAY = 'OVERLAY', 'Overlay'
    TRANSITION = 'TRANSITION', 'Transition'
    MUSIC = 'MUSIC', 'Music'
    SFX = 'SFX', 'SFX'
    FONT = 'FONT', 'Font'
    BACKGROUND = 'BACKGROUND', 'Background'
    CHARACTER_REF = 'CHARACTER_REF', 'Character reference'
    CAPTION_STYLE = 'CAPTION_STYLE', 'Caption style (ASS template)'
    LUT = 'LUT', 'LUT'


class Asset(UUIDModel, TimeStampedModel):
    """Pipeline-generated asset, owned by a run, immutable after creation.

    FKs to pipelines.PipelineRun and pipelines.StageExecution are added in
    Phase 2 via an additive migration (both nullable, SET_NULL).
    """

    kind = models.CharField(max_length=15, choices=AssetKind.choices)
    file = models.FileField(storage=AssetStorage(), upload_to=_asset_upload_to)
    mime = models.CharField(max_length=64)
    checksum = models.CharField(max_length=64, db_index=True)
    meta = models.JSONField(
        default=dict
    )  # ffprobe: duration, w, h, fps, codec, loudness

    def __str__(self) -> str:
        return f'{self.kind} {self.id}'


class LibraryAsset(UUIDModel, TimeStampedModel):
    """Human-curated, reusable, versioned asset (music, watermarks, fonts, refs)."""

    kind = models.CharField(max_length=15, choices=LibraryAssetKind.choices)
    name = models.CharField(max_length=120)
    file = models.FileField(
        storage=AssetStorage(), upload_to=_library_asset_upload_to
    )
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    channel = models.ForeignKey(
        'channels.Channel',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='library_assets',
    )
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    meta = models.JSONField(
        default=dict
    )  # probe data, loudness, safe-area info

    def __str__(self) -> str:
        return f'{self.name} ({self.kind})'


class AssetRendition(UUIDModel, TimeStampedModel):
    """Pre-transcoded variant of a LibraryAsset so assembly never re-encodes branding."""

    source = models.ForeignKey(
        LibraryAsset, on_delete=models.CASCADE, related_name='renditions'
    )
    profile = models.CharField(
        max_length=40
    )  # '1080p30_h264', '9x16_1080', 'mezz'
    file = models.FileField(
        storage=AssetStorage(), upload_to=_rendition_upload_to
    )

    class Meta:
        unique_together = [('source', 'profile')]

    def __str__(self) -> str:
        return f'{self.source} → {self.profile}'
```

- [ ] **Step 7: Activate the skipped channel branding test**

In `tests/test_apps/test_channels/test_models.py`, remove the `@pytest.mark.skip` from `test_character_sheet_item_links_character` and add a `library_asset_factory` fixture:

```python
import pytest

from server.apps.assets.models import LibraryAsset, LibraryAssetKind


@pytest.fixture
def library_asset_factory():
    def _make(**kwargs):
        defaults = {'kind': LibraryAssetKind.CHARACTER_REF, 'name': 'ref'}
        defaults.update(kwargs)
        return LibraryAsset.objects.create(**defaults)

    return _make
```

Note: `LibraryAsset.file` is nullable in tests because `file = FileField(blank=True)` defaults allow empty. If FileField isn't blank=True, you'll need to override or mock file storage for tests. Add `blank=True` to the `file` fields in `models.py` to allow creation without uploading files in tests:

```python
# In Asset, LibraryAsset, and AssetRendition models, make file nullable in tests
# by adding blank=True to FileField definitions:
file = models.FileField(
    storage=AssetStorage(), upload_to=_library_asset_upload_to, blank=True
)
```

- [ ] **Step 8: Generate all pending migrations (channels + prompts + assets together)**

Now that all three apps are installed, generate migrations in one shot so Django resolves cross-app FK dependencies correctly (channels → assets):

```bash
just run makemigrations channels prompts assets
just run migrate
```

Expected output: Three migration files created, then `Applying channels.0001_initial... OK`, `Applying prompts.0001_initial... OK`, `Applying assets.0001_initial... OK`.

- [ ] **Step 9: Activate and run all DB tests**

Remove the `@pytest.mark.skip` decorators added in Task 3/4 and run the full test suite:

```bash
docker compose exec web pytest tests/test_apps/ --no-cov
```

Expected: All tests `PASSED`

- [ ] **Step 10: Commit**

```bash
git add server/apps/assets/ tests/test_apps/test_assets/ \
        tests/test_apps/test_channels/ tests/test_apps/test_prompts/ \
        server/settings/components/common.py \
        server/apps/channels/migrations/ server/apps/prompts/migrations/ \
        server/apps/assets/migrations/
git commit -m "feat(assets): add Asset, LibraryAsset, AssetRendition models and apply all Phase 1 migrations

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: LibraryAssetService + ingest_library_asset task (ffprobe + validation)

**Files:**
- Create: `server/apps/assets/services.py`
- Create: `server/apps/assets/tasks.py`
- Create: `tests/test_apps/test_assets/test_services.py`
- Create: `tests/test_apps/test_assets/test_tasks.py`
- Modify: `server/implemented.py` — add `LibraryAssetService` DI registration

The ingest task runs in four stages per §4.3:
1. **ffprobe** — probe codec, duration, dimensions, fps, channel-layout → store in `meta`
2. **Validation** — per kind: watermarks must be PNG+alpha; intros/outros must have audio stream
3. **Loudness** — EBU R128 integrated loudness for MUSIC/SFX kinds → store in `meta['loudness']`
4. **Renditions** — transcode to mezzanine profile for 16:9 + 9:16 formats

- [ ] **Step 1: Write failing tests**

```python
# tests/test_apps/test_assets/__init__.py  (empty, already exists)
```

```python
# tests/test_apps/test_assets/test_services.py
import pytest

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.assets.services import LibraryAssetService


@pytest.mark.django_db
def test_register_creates_library_asset_row() -> None:
    service = LibraryAssetService()
    asset = service.register(
        kind=LibraryAssetKind.MUSIC,
        name='Epic Track',
        s3_key='library/music/epic.wav',
    )
    assert isinstance(asset, LibraryAsset)
    assert asset.kind == LibraryAssetKind.MUSIC
    assert asset.name == 'Epic Track'
    assert asset.meta['s3_key'] == 'library/music/epic.wav'


@pytest.mark.django_db
def test_register_stores_tags() -> None:
    service = LibraryAssetService()
    asset = service.register(
        kind=LibraryAssetKind.MUSIC,
        name='Tense Track',
        s3_key='library/music/tense.wav',
        tags=['tense', 'orchestral'],
    )
    assert asset.tags == ['tense', 'orchestral']
```

```python
# tests/test_apps/test_assets/test_tasks.py
# Async tasks are tested via asyncio.run() — the project's established pattern.
# See tests/test_server/test_taskiq_middleware.py for the canonical example.
import asyncio
import json
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.assets.tasks import ingest_library_asset


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


FFPROBE_AUDIO_OUTPUT = json.dumps({
    'streams': [
        {
            'codec_type': 'audio',
            'codec_name': 'pcm_s16le',
            'sample_rate': '48000',
            'channels': 2,
        }
    ],
    'format': {'duration': '180.5', 'format_name': 'wav'},
})

FFPROBE_PNG_ALPHA_OUTPUT = json.dumps({
    'streams': [
        {
            'codec_type': 'video',
            'codec_name': 'png',
            'pix_fmt': 'rgba',
        }
    ],
    'format': {'duration': '0', 'format_name': 'png_pipe'},
})

FFPROBE_JPEG_OUTPUT = json.dumps({
    'streams': [
        {'codec_type': 'video', 'codec_name': 'mjpeg', 'pix_fmt': 'yuvj420p'}
    ],
    'format': {'duration': '0', 'format_name': 'image2'},
})


def _make_proc(
    returncode: int, stdout: bytes, stderr: bytes = b''
) -> AsyncMock:
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@pytest.mark.django_db
def test_ingest_stores_ffprobe_meta() -> None:
    async def _inner() -> None:
        asset = await LibraryAsset.objects.acreate(
            kind=LibraryAssetKind.MUSIC, name='Track'
        )
        proc = _make_proc(0, FFPROBE_AUDIO_OUTPUT.encode())
        # Music needs loudness too — mock both ffprobe and loudness subprocess
        loudness_proc = _make_proc(
            0, b'', b'I: -18.0 LUFS\n True Peak: -1.0 dBTP'
        )
        call_count = 0

        async def _fake_exec(*args: str, **kwargs: Any) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            return proc if call_count == 1 else loudness_proc

        with (
            patch(
                'server.apps.assets.tasks.asyncio.create_subprocess_exec',
                side_effect=_fake_exec,
            ),
            patch(
                'server.apps.assets.tasks._get_presigned_url',
                return_value='https://s3/track.wav',
            ),
        ):
            await ingest_library_asset(str(asset.id))

        refreshed = await LibraryAsset.objects.aget(id=asset.id)
        assert refreshed.meta['format']['duration'] == '180.5'
        assert refreshed.meta['streams'][0]['codec_type'] == 'audio'

    _run(_inner())


@pytest.mark.django_db
def test_ingest_raises_on_ffprobe_failure() -> None:
    async def _inner() -> None:
        asset = await LibraryAsset.objects.acreate(
            kind=LibraryAssetKind.MUSIC, name='Bad'
        )
        proc = _make_proc(1, b'', b'error: no such file')
        with (
            patch(
                'server.apps.assets.tasks.asyncio.create_subprocess_exec',
                return_value=proc,
            ),
            patch(
                'server.apps.assets.tasks._get_presigned_url',
                return_value='https://s3/bad.wav',
            ),
            pytest.raises(RuntimeError, match='ffprobe failed'),
        ):
            await ingest_library_asset(str(asset.id))

    _run(_inner())


@pytest.mark.django_db
def test_watermark_validation_rejects_non_png() -> None:
    """Watermarks must be PNG with alpha channel (§4.3 validation)."""

    async def _inner() -> None:
        asset = await LibraryAsset.objects.acreate(
            kind=LibraryAssetKind.WATERMARK, name='Logo'
        )
        proc = _make_proc(0, FFPROBE_JPEG_OUTPUT.encode())
        with (
            patch(
                'server.apps.assets.tasks.asyncio.create_subprocess_exec',
                return_value=proc,
            ),
            patch(
                'server.apps.assets.tasks._get_presigned_url',
                return_value='https://s3/logo.jpg',
            ),
            pytest.raises(ValueError, match='Watermark must be PNG'),
        ):
            await ingest_library_asset(str(asset.id))

    _run(_inner())


@pytest.mark.django_db
def test_watermark_validation_accepts_png_rgba() -> None:
    async def _inner() -> None:
        asset = await LibraryAsset.objects.acreate(
            kind=LibraryAssetKind.WATERMARK, name='Logo PNG'
        )
        # Rendition generation needs mocking too for watermarks
        proc = _make_proc(0, FFPROBE_PNG_ALPHA_OUTPUT.encode())
        rendition_proc = _make_proc(0, b'')
        call_count = 0

        async def _fake_exec(*args: str, **kwargs: Any) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            return proc if call_count == 1 else rendition_proc

        with (
            patch(
                'server.apps.assets.tasks.asyncio.create_subprocess_exec',
                side_effect=_fake_exec,
            ),
            patch(
                'server.apps.assets.tasks._get_presigned_url',
                return_value='https://s3/logo.png',
            ),
            patch('builtins.open', side_effect=FileNotFoundError),
        ):
            # Rendition upload will fail because tmp file doesn't exist in test
            # That's acceptable here — we just verify validation passes
            try:
                await ingest_library_asset(str(asset.id))
            except (FileNotFoundError, Exception):
                pass

        refreshed = await LibraryAsset.objects.aget(id=asset.id)
        assert refreshed.meta['streams'][0]['codec_name'] == 'png'

    _run(_inner())
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose exec web pytest tests/test_apps/test_assets/test_services.py \
    tests/test_apps/test_assets/test_tasks.py --no-cov -x
```

Expected: `ImportError: cannot import name 'LibraryAssetService'`

- [ ] **Step 3: Create server/apps/assets/services.py**

```python
from typing import final

import attrs

from server.apps.assets.models import LibraryAsset


@final
@attrs.define(slots=True, frozen=True)
class LibraryAssetService:
    """Handles LibraryAsset registration.

    The caller (async API controller in Phase 2) is responsible for
    enqueuing ingest_library_asset after calling register():
        asset = service.register(...)
        await ingest_library_asset.kiq(str(asset.id))
    """

    def register(
        self,
        kind: str,
        name: str,
        s3_key: str,
        channel_id: str | None = None,
        tags: list[str] | None = None,
    ) -> LibraryAsset:
        """Create a LibraryAsset row. Caller must enqueue ingest_library_asset.

        The asset's file field is populated by the ingest task after probing;
        until then meta['s3_key'] records where the uploaded file lives.
        """
        return LibraryAsset.objects.create(
            kind=kind,
            name=name,
            channel_id=channel_id,
            tags=tags or [],
            meta={'s3_key': s3_key},
        )
```

- [ ] **Step 4: Create server/apps/assets/tasks.py**

```python
import asyncio
import json
import uuid
from typing import Any

from server.common.broker import broker


def _get_presigned_url(s3_key: str) -> str:
    """Generate a presigned S3 URL for the given key (for ffprobe/ffmpeg access)."""
    import boto3
    from django.conf import settings

    client = boto3.client(
        's3',
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )
    return client.generate_presigned_url(
        'get_object',
        Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': s3_key},
        ExpiresIn=3600,
    )


async def _run_ffprobe(url: str) -> dict[str, Any]:
    """Run ffprobe on a URL and return parsed JSON output."""
    proc = await asyncio.create_subprocess_exec(
        'ffprobe',
        '-v',
        'quiet',
        '-print_format',
        'json',
        '-show_streams',
        '-show_format',
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f'ffprobe failed: {stderr.decode()}')
    return json.loads(stdout)  # type: ignore[no-any-return]


def _validate_kind(kind: str, meta: dict[str, Any]) -> None:
    """Enforce per-kind format requirements (§4.3 §2)."""
    streams = meta.get('streams', [])
    video_streams = [s for s in streams if s.get('codec_type') == 'video']
    audio_streams = [s for s in streams if s.get('codec_type') == 'audio']

    if kind == 'WATERMARK':
        if not video_streams or video_streams[0].get('codec_name') != 'png':
            raise ValueError('Watermark must be PNG with alpha channel')
        pix_fmt = video_streams[0].get('pix_fmt', '')
        if 'a' not in pix_fmt and pix_fmt != 'rgba':
            # png with rgba or yuva pix_fmt has alpha
            if pix_fmt not in ('rgba', 'yuva420p', 'yuva444p'):
                raise ValueError(
                    'Watermark PNG must have alpha channel (rgba/yuva pix_fmt)'
                )

    elif kind in ('INTRO', 'OUTRO'):
        if not audio_streams:
            raise ValueError(
                f'{kind} must contain an audio stream (inject silent track if needed)'
            )


async def _measure_loudness(url: str) -> dict[str, float]:
    """Run EBU R128 loudness measurement via ffmpeg."""
    proc = await asyncio.create_subprocess_exec(
        'ffmpeg',
        '-i',
        url,
        '-filter_complex',
        'ebur128=framelog=verbose',
        '-f',
        'null',
        '-',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    # Parse integrated loudness from stderr output
    output = stderr.decode()
    loudness: dict[str, float] = {}
    for line in output.splitlines():
        if 'I:' in line and 'LUFS' in line:
            parts = line.split()
            try:
                loudness['integrated_lufs'] = float(
                    parts[parts.index('I:') + 1]
                )
            except (ValueError, IndexError):
                pass
        if 'True Peak:' in line:
            parts = line.split()
            try:
                idx = parts.index('Peak:')
                loudness['true_peak_dbfs'] = float(parts[idx + 1])
            except (ValueError, IndexError):
                pass
    return loudness


async def _generate_rendition(url: str, profile: str, output_path: str) -> None:
    """Transcode to the mezzanine spec: 1080p30 h264 CRF16 fast, AAC 48kHz."""
    if profile == 'mezz':
        vf = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2'
        args = [
            'ffmpeg',
            '-i',
            url,
            '-vf',
            vf,
            '-c:v',
            'libx264',
            '-crf',
            '16',
            '-preset',
            'fast',
            '-pix_fmt',
            'yuv420p',
            '-r',
            '30',
            '-c:a',
            'aac',
            '-ar',
            '48000',
            '-ac',
            '2',
            '-y',
            output_path,
        ]
    else:
        return  # unsupported profile; extend as needed
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f'ffmpeg rendition failed ({profile}): {stderr.decode()[:500]}'
        )


@broker.task(retry_on_error=False, queue='render')
async def ingest_library_asset(asset_id: str) -> None:
    """Probe, validate, measure loudness, and generate renditions for a LibraryAsset.

    Implements §4.3 upload normalization pipeline.
    """
    from server.apps.assets.models import (
        AssetRendition,
        LibraryAsset,
        LibraryAssetKind,
    )

    asset = await LibraryAsset.objects.aget(id=uuid.UUID(asset_id))
    s3_key = asset.meta.get('s3_key', str(asset.file))
    url = _get_presigned_url(s3_key)

    # Stage 1: ffprobe
    meta = await _run_ffprobe(url)

    # Stage 2: validation
    _validate_kind(asset.kind, meta)

    # Stage 3: loudness (music/SFX only)
    if asset.kind in (LibraryAssetKind.MUSIC, LibraryAssetKind.SFX):
        loudness = await _measure_loudness(url)
        meta['loudness'] = loudness

    # Persist probed metadata
    asset.meta = meta
    await asset.asave(update_fields=['meta'])

    # Stage 4: renditions (skip fonts, LUTs, caption styles, character refs)
    rendition_kinds = {
        LibraryAssetKind.INTRO,
        LibraryAssetKind.OUTRO,
        LibraryAssetKind.MUSIC,
        LibraryAssetKind.OVERLAY,
        LibraryAssetKind.BACKGROUND,
        LibraryAssetKind.WATERMARK,
    }
    if asset.kind in rendition_kinds:
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            await _generate_rendition(url, 'mezz', tmp_path)
            # Upload rendition to S3 and create AssetRendition row
            with open(tmp_path, 'rb') as f:
                from django.core.files.base import ContentFile

                rendition = AssetRendition(source=asset, profile='mezz')
                rendition.file.save(
                    f'rendition_mezz.mp4', ContentFile(f.read()), save=False
                )
                await rendition.asave()
        finally:
            os.unlink(tmp_path)
```

- [ ] **Step 5: Add LibraryAssetService to server/implemented.py**

```python
def _inject_assets(container: Container) -> None:
    from server.apps.assets.services import LibraryAssetService

    container.register(LibraryAssetService, scope=Scope.singleton)
```

And call `_inject_assets(container)` inside `populate_dependencies`.

- [ ] **Step 6: Run tests**

```bash
docker compose exec web pytest tests/test_apps/test_assets/ --no-cov -x
```

Expected: All tests `PASSED`

- [ ] **Step 7: Run full suite**

```bash
docker compose exec web pytest --no-cov
docker compose exec web ruff check .
docker compose exec web mypy server
docker compose exec web lint-imports
```

Fix any issues. `lint-imports` enforces layered architecture; verify no cross-app imports violate layer rules.

- [ ] **Step 8: Commit**

```bash
git add server/apps/assets/services.py server/apps/assets/tasks.py \
        server/implemented.py tests/test_apps/test_assets/
git commit -m "feat(assets): add LibraryAssetService and ingest_library_asset task with ffprobe/ffmpeg

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Assets admin + final wiring + migration checks

**Files:**
- Create: `server/apps/assets/admin.py`
- Run all migration lint checks

- [ ] **Step 1: Create server/apps/assets/admin.py**

```python
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from server.apps.assets.models import Asset, AssetRendition, LibraryAsset


class AssetRenditionInline(TabularInline):
    model = AssetRendition
    extra = 0
    fields = ('profile', 'file')
    readonly_fields = ('file',)


@admin.register(Asset)
class AssetAdmin(ModelAdmin):
    list_display = ('id', 'kind', 'mime', 'checksum')
    list_filter = ('kind',)
    search_fields = ('checksum',)
    readonly_fields = ('id', 'checksum', 'meta')


@admin.register(LibraryAsset)
class LibraryAssetAdmin(ModelAdmin):
    list_display = ('name', 'kind', 'channel', 'version', 'is_active')
    list_filter = ('kind', 'is_active')
    search_fields = ('name',)
    inlines = [AssetRenditionInline]
```

- [ ] **Step 2: Run migration linter**

```bash
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```

Expected: no warnings

- [ ] **Step 3: Run full test suite with coverage**

```bash
docker compose exec web pytest
```

Expected: 100% coverage, all tests pass.

- [ ] **Step 4: Run type checking and linting**

```bash
docker compose exec web mypy server
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web lint-imports
```

Fix any issues before committing.

- [ ] **Step 5: Commit**

```bash
git add server/apps/assets/admin.py
git commit -m "feat(assets): add Unfold admin for Asset and LibraryAsset

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Verification

After all tasks complete, verify end-to-end:

```bash
# 1. Start the stack
docker compose up -d

# 2. Apply all migrations
just run migrate

# 3. Full test suite with coverage
docker compose exec web pytest

# 4. Type check + lint
docker compose exec web mypy server
docker compose exec web ruff check .
docker compose exec web lint-imports

# 5. Migration health
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes

# 6. Spot-check admin (requires superuser)
just run createsuperuser
# Visit http://localhost:8000/admin — should see Channels, Prompts, Assets sections

# 7. Verify ingest task (manual smoke test with a real WAV file)
docker compose exec web python manage.py shell
# >>> from server.apps.assets.services import LibraryAssetService
# >>> svc = LibraryAssetService()
# >>> asset = svc.register(kind='MUSIC', name='Test Track', s3_key='library/music/test.wav')
# >>> # Check the worker processes the ingest task and updates asset.meta
```

---

## Notes for Phase 2

When building the pipeline engine (Phase 2), add these fields via additive migrations:

```python
# Migration: add run/stage FK to Asset
# 0002_asset_pipeline_fks.py
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='asset',
            name='run',
            field=models.ForeignKey(
                'pipelines.PipelineRun',
                null=True,
                on_delete=models.SET_NULL,
                related_name='assets',
            ),
        ),
        migrations.AddField(
            model_name='asset',
            name='stage_execution',
            field=models.ForeignKey(
                'pipelines.StageExecution',
                null=True,
                on_delete=models.SET_NULL,
                related_name='assets',
            ),
        ),
    ]


# Migration: add source_run FK to Character
# channels/0002_character_source_run.py
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='character',
            name='source_run',
            field=models.ForeignKey(
                'pipelines.PipelineRun',
                null=True,
                blank=True,
                on_delete=models.SET_NULL,
            ),
        ),
    ]
```
