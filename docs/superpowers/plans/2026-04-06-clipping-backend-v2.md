# Clipping Backend v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the Reelforge Clipping feature from Channel-scoped models to a global/SocialAccount-scoped REST API with JWT auth, SSE real-time updates, and upgraded MediaPipe+PyAnnote speaker detection.

**Architecture:** Phase 1 updates all models (remove Channel FK, add SocialAccount FK), replaces Django template views with DRF ViewSets, and adds an SSE streaming endpoint backed by Redis pub/sub. Phase 2 rewrites the speaker detection service with MediaPipe+PyAnnote and enriches the `analyze_clips` task with diarization, scene detection, and an `analysis_manifest` field.

**Tech Stack:** Django 5.2, Django REST Framework, djangorestframework-simplejwt, Redis (SSE pub/sub), MediaPipe, PyAnnote Audio 3.1, PySceneDetect, Celery

**Spec:** `docs/superpowers/specs/2026-04-06-clipping-backend-v2-design.md`

---

## File Map

### Modified
- `***REMOVED***/clipping/constants.py` — add platform defaults
- `***REMOVED***/clipping/models.py` — remove channel FKs, add social_account FK + new fields
- `***REMOVED***/clipping/apps.py` — remove channel template signal
- `***REMOVED***/clipping/signals.py` — use platform for layout/style defaults
- `***REMOVED***/clipping/admin.py` — remove channel refs
- `***REMOVED***/clipping/tasks.py` — remove auto-approve, add SSE, rewrite analyze_clips
- `***REMOVED***/clipping/services.py` — update ClipAnalysisService
- `***REMOVED***/clipping/views/__init__.py` — re-export all new ViewSets
- `***REMOVED***/clipping/tests/factories.py` — channel → social_account
- `***REMOVED***/clipping/tests/test_models.py` — update fixtures
- `***REMOVED***/clipping/tests/test_signals.py` — platform-based assertions
- `***REMOVED***/clipping/tests/test_tasks.py` — remove auto-approve assertions
- `***REMOVED***/clipping/tests/test_services.py` — remove channel refs
- `***REMOVED***/services/media/speaker_detection.py` — full rewrite
- `***REMOVED***/services/media/render_stages/trim_crop.py` — delegate manual crop to service
- `***REMOVED***/services/media/clip_render_pipeline.py` — remove channel, add social_account_platform
- `config/settings/base.py` — update REST_FRAMEWORK + add SIMPLE_JWT
- `config/urls.py` — add DRF router + JWT, remove clipping template URL
- `pyproject.toml` — add simplejwt, pyannote.audio, scenedetect

### Created
- `***REMOVED***/clipping/migrations/0011_clippingjob_remove_channel_add_social_account.py`
- `***REMOVED***/clipping/migrations/0012_cliprendertemplate_global.py`
- `***REMOVED***/clipping/migrations/0013_clipmediaasset_global.py`
- `***REMOVED***/clipping/migrations/0014_clipmusicasset_global.py`
- `***REMOVED***/clipping/migrations/0015_clipstyleconfig_add_render_template.py`
- `***REMOVED***/clipping/migrations/0016_seed_default_render_template.py`
- `***REMOVED***/clipping/serializers.py`
- `***REMOVED***/clipping/sse.py`
- `***REMOVED***/clipping/analysis_helpers.py`
- `***REMOVED***/clipping/views/jobs.py` (replaces old template-based file)
- `***REMOVED***/clipping/views/candidates.py` (replaces old template-based file)
- `***REMOVED***/clipping/views/renders.py` (replaces old template-based file)
- `***REMOVED***/clipping/views/overlays.py`
- `***REMOVED***/clipping/views/assets.py`
- `***REMOVED***/clipping/tests/test_api.py`

### Deleted
- `***REMOVED***/clipping/urls.py`
- `***REMOVED***/templates/clipping/` (entire directory)
- `***REMOVED***/clipping/tests/test_views_phase_b.py`

---

## Task 1: Update constants.py with platform defaults

**Files:**
- Modify: `***REMOVED***/clipping/constants.py`

- [ ] **Step 1: Add platform defaults to constants.py**

Append to the bottom of `***REMOVED***/clipping/constants.py`:

```python
# Maps SocialAccount.Platform values to clip render mode defaults
PLATFORM_RENDER_MODE_DEFAULTS: dict[str, str] = {
    "TIKTOK": RenderMode.SMART_CROP,
    "YOUTUBE": RenderMode.CENTER_CROP,
    "INSTAGRAM": RenderMode.SMART_CROP,
}

# Maps SocialAccount.Platform values to clip render format defaults
PLATFORM_FORMAT_DEFAULTS: dict[str, str] = {
    "TIKTOK": "VERTICAL_9_16",
    "YOUTUBE": "LANDSCAPE_16_9",
    "INSTAGRAM": "SQUARE_1_1",
}
```

- [ ] **Step 2: Verify constants are importable**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run python -c "from ***REMOVED***.clipping.constants import PLATFORM_RENDER_MODE_DEFAULTS, PLATFORM_FORMAT_DEFAULTS; print('OK', PLATFORM_RENDER_MODE_DEFAULTS)"
```

Expected: `OK {'TIKTOK': 'SMART_CROP', 'YOUTUBE': 'CENTER_CROP', 'INSTAGRAM': 'SMART_CROP'}`

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/constants.py
git commit -m "feat(clipping): add platform render mode and format defaults to constants"
```

---

## Task 2: Update ClippingJob model

**Files:**
- Modify: `***REMOVED***/clipping/models.py`

- [ ] **Step 1: Update ClippingJob class**

In `***REMOVED***/clipping/models.py`, replace the `ClippingJob` model fields. The full replacement:

Remove these fields (lines ~50–59):
```python
channel = models.ForeignKey(
    Channel,
    on_delete=models.CASCADE,
    related_name="clipping_jobs",
)
target_accounts = models.ManyToManyField(
    SocialAccount,
    blank=True,
    related_name="clipping_jobs",
)
```

Add after the `SourceType` class definition:
```python
social_account = models.ForeignKey(
    SocialAccount,
    on_delete=models.PROTECT,
    related_name="clipping_jobs",
)
```

Replace `source_duration_sec = models.PositiveIntegerField(null=True, blank=True)` with:
```python
source_duration_sec = models.FloatField(null=True, blank=True)
```

After the `agent_cost_usd` field and before `celery_task_id`, add:
```python
# Analysis Manifest — structured output from analysis task
analysis_manifest = models.JSONField(null=True, blank=True)

# Derived display assets
thumbnail_strip_file = models.FileField(
    upload_to="clipping/thumbnails/",
    blank=True,
    null=True,
    max_length=500,
)
waveform_data_file = models.FileField(
    upload_to="clipping/waveforms/",
    blank=True,
    null=True,
    max_length=500,
)
```

Update `Meta.indexes` — replace `models.Index(fields=["channel"])` with:
```python
models.Index(fields=["social_account"]),
```

Update `total_cost_usd` property to handle `None` values (fields are now nullable):
```python
@property
def total_cost_usd(self) -> Decimal:
    return (self.transcription_cost_usd or Decimal(0)) + (self.analysis_cost_usd or Decimal(0))
```

Add new FSM transition after `retry_transcription`:
```python
@transition(
    field=status,
    source=[Status.FAILED, Status.ANALYZING],
    target=Status.ANALYZING,
)
def retry_analysis(self) -> None:
    self.last_error = ""
```

Add `platform` property after `total_cost_usd`:
```python
@property
def platform(self) -> str:
    return self.social_account.platform
```

Remove the `from ***REMOVED***.channels.models import Channel` import — `SocialAccount` import stays.

- [ ] **Step 2: Remove Channel import, keep SocialAccount**

At the top of `***REMOVED***/clipping/models.py`, the import block currently has:
```python
from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.models import SocialAccount
```

Remove the `Channel` import line. `SocialAccount` stays.

- [ ] **Step 3: Commit models.py (ClippingJob only)**

```bash
git add ***REMOVED***/clipping/models.py
git commit -m "feat(clipping): replace channel FK with social_account FK on ClippingJob"
```

---

## Task 3: Update remaining models

**Files:**
- Modify: `***REMOVED***/clipping/models.py`

- [ ] **Step 1: Update ClipRenderTemplate**

Replace the `ClipRenderTemplate` class. The new class:

```python
class ClipRenderTemplate(ClipRenderStyleMixin, BaseAbstractModel):
    """Global render style defaults. One can be marked as the system default."""

    name = models.CharField(max_length=100, default="Default Template")
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Clip Render Template"
        verbose_name_plural = "Clip Render Templates"
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="unique_default_render_template",
            )
        ]

    def __str__(self) -> str:
        return f"{'[Default] ' if self.is_default else ''}{self.name}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.is_default:
            ClipRenderTemplate.objects.exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def to_style_defaults(self) -> dict[str, Any]:
        """Return all style fields suitable for seeding a ClipStyleConfig."""
        result: dict[str, Any] = {}
        for name in self.STYLE_FIELD_NAMES:
            value = getattr(self, name)
            if hasattr(value, "name"):
                value = value.name or ""
            result[name] = value
        return result
```

- [ ] **Step 2: Update ClipMediaAsset**

Remove the `channel` FK field from `ClipMediaAsset`. Add `thumbnail` field after `is_active`:
```python
thumbnail = models.ImageField(
    upload_to="clipping/media_assets/thumbs/",
    blank=True,
    null=True,
    max_length=500,
)
```

Update `Meta.indexes` — remove `models.Index(fields=["channel", "asset_type", "is_active"])`, replace with:
```python
models.Index(fields=["asset_type", "is_active"]),
```

- [ ] **Step 3: Update ClipMusicAsset**

Remove the `channel` FK field from `ClipMusicAsset`. Add `waveform_file` after `is_active`:
```python
waveform_file = models.FileField(
    upload_to="clipping/music_assets/waveforms/",
    blank=True,
    null=True,
    max_length=500,
)
```

Update `Meta.indexes` — remove `models.Index(fields=["channel", "is_active"])`, replace with:
```python
models.Index(fields=["is_active"]),
```

- [ ] **Step 4: Update ClipStyleConfig**

Add `render_template` FK to `ClipStyleConfig`. After the `candidate` OneToOneField:
```python
render_template = models.ForeignKey(
    ClipRenderTemplate,
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="seeded_style_configs",
)
```

- [ ] **Step 5: Commit models.py (remaining models)**

```bash
git add ***REMOVED***/clipping/models.py
git commit -m "feat(clipping): globalise ClipRenderTemplate, ClipMediaAsset, ClipMusicAsset; add render_template FK to ClipStyleConfig"
```

---

## Task 4: Generate and apply migrations

**Files:**
- Create: `***REMOVED***/clipping/migrations/0011_*` through `0016_*`

- [ ] **Step 1: Run makemigrations for ClippingJob field changes**

```bash
just manage makemigrations clipping --name clippingjob_remove_channel_add_social_account
```

Django will prompt for a default value for the new non-nullable `social_account` field. Enter `1` to provide a one-off default of `None` — then select option 2 ("Ignore for now") if prompted, OR in the migration file set it to `null=True` temporarily and change to nullable in the model as well until migrate completes. In practice for a dev DB with no existing ClippingJob rows, enter `''` when asked (the migration will still run on an empty table).

If the prompt causes issues, temporarily add `null=True` to `social_account` in `models.py`, run makemigrations, migrate, then remove `null=True` and make a second migration to make it non-nullable. For a fresh dev DB, add the field as NOT NULL directly.

- [ ] **Step 2: Run makemigrations for template/asset changes**

```bash
just manage makemigrations clipping --name cliprendertemplate_global
just manage makemigrations clipping --name clipmediaasset_global
just manage makemigrations clipping --name clipmusicasset_global
just manage makemigrations clipping --name clipstyleconfig_add_render_template
```

- [ ] **Step 3: Write data migration to seed default template**

Create `***REMOVED***/clipping/migrations/0016_seed_default_render_template.py`:

```python
from __future__ import annotations

from django.db import migrations


def create_default_template(apps: object, schema_editor: object) -> None:
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    ClipRenderTemplate.objects.get_or_create(
        is_default=True,
        defaults={
            "name": "Default Template",
            "caption_enabled": True,
            "caption_style": "WORD_BY_WORD",
            "caption_font": "Montserrat-Bold",
            "caption_color": "#FFFFFF",
            "caption_stroke_color": "#000000",
            "caption_stroke_width": 3,
            "caption_position": "BOTTOM",
            "caption_animation": "POP",
            "caption_language": "en",
            "hook_enabled": True,
            "hook_style": "TITLE_CARD",
            "hook_duration_sec": 3.0,
            "hook_font": "Montserrat-Bold",
            "hook_size": 60,
            "hook_color": "#FFFFFF",
            "hook_bg_color": "#CC000000",
            "hook_animation": "FADE",
            "intro_transition": "NONE",
            "outro_transition": "NONE",
            "transition_duration_sec": 0.5,
            "watermark_enabled": False,
            "watermark_type": "TEXT",
            "watermark_position": "BOTTOM_RIGHT",
            "watermark_opacity": 0.6,
            "watermark_size": 32,
            "progress_bar_enabled": False,
            "progress_bar_position": "TOP",
            "progress_bar_color": "#FFFFFF",
            "progress_bar_height": 6,
            "music_enabled": False,
            "music_volume_db": -20.0,
            "music_fade_in_sec": 1.0,
            "music_fade_out_sec": 1.0,
        },
    )


def reverse_default_template(apps: object, schema_editor: object) -> None:
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    ClipRenderTemplate.objects.filter(name="Default Template", is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("clipping", "0015_clipstyleconfig_add_render_template"),
    ]

    operations = [
        migrations.RunPython(create_default_template, reverse_default_template),
    ]
```

- [ ] **Step 4: Apply all migrations**

```bash
just manage migrate
```

Expected: All migrations apply without errors.

- [ ] **Step 5: Commit migrations**

```bash
git add ***REMOVED***/clipping/migrations/
git commit -m "feat(clipping): migrations 0011-0016 — globalise models, add social_account FK, seed default template"
```

---

## Task 5: Update apps.py and signals.py

**Files:**
- Modify: `***REMOVED***/clipping/apps.py`
- Modify: `***REMOVED***/clipping/signals.py`

- [ ] **Step 1: Write failing signal tests**

In `***REMOVED***/clipping/tests/test_signals.py`, add (or replace existing signal tests):

```python
import pytest
from ***REMOVED***.channels.tests.factories import SocialAccountFactory
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory, ClippingJobFactory
from ***REMOVED***.clipping.constants import PLATFORM_RENDER_MODE_DEFAULTS


@pytest.mark.django_db
def test_layout_config_uses_tiktok_smart_crop():
    account = SocialAccountFactory(platform="TIKTOK")
    job = ClippingJobFactory(social_account=account)
    candidate = ClipCandidateFactory(clipping_job=job)
    assert candidate.layout_config.render_mode == "SMART_CROP"


@pytest.mark.django_db
def test_layout_config_uses_youtube_center_crop():
    account = SocialAccountFactory(platform="YOUTUBE")
    job = ClippingJobFactory(social_account=account)
    candidate = ClipCandidateFactory(clipping_job=job)
    assert candidate.layout_config.render_mode == "CENTER_CROP"


@pytest.mark.django_db
def test_style_config_seeded_from_default_template():
    """ClipStyleConfig is auto-created and render_template points to default."""
    account = SocialAccountFactory(platform="TIKTOK")
    job = ClippingJobFactory(social_account=account)
    candidate = ClipCandidateFactory(clipping_job=job)
    assert candidate.style_config is not None
    # render_template should be the is_default=True template (seeded by migration 0016)
    from ***REMOVED***.clipping.models import ClipRenderTemplate
    default = ClipRenderTemplate.objects.filter(is_default=True).first()
    assert candidate.style_config.render_template == default
```

Run to confirm they fail:
```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_signals.py -v
```

Expected: FAIL (factories still reference channel at this point — will be fixed in Task 6).

- [ ] **Step 2: Update apps.py — remove channel template signal**

Replace the entire `ready()` method in `***REMOVED***/clipping/apps.py`:

```python
def ready(self) -> None:
    import ***REMOVED***.clipping.signals  # noqa: F401
```

Remove the entire block that imports `Channel` and connects `create_clip_render_template_for_channel`.

- [ ] **Step 3: Update signals.py — remove channel-based function, update layout/style signals**

Replace `***REMOVED***/clipping/signals.py` entirely:

```python
from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver
from django_fsm.signals import post_transition

from ***REMOVED***.clipping.constants import PLATFORM_RENDER_MODE_DEFAULTS
from ***REMOVED***.clipping.constants import RenderMode
from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.clipping")


def on_clipping_job_transition(
    sender: type,
    instance: ClippingJob,
    name: str,
    source: str,
    target: str,
    **kwargs: Any,
) -> None:
    """Log ClippingJob FSM failures."""
    if target == ClippingJob.Status.FAILED:
        logger.error(
            "ClippingJob failed",
            extra={"clipping_job_id": str(instance.id), "last_error": instance.last_error},
        )


post_transition.connect(on_clipping_job_transition, sender=ClippingJob)


@receiver(post_save, sender=ClipCandidate)
def create_layout_config_for_candidate(
    sender: type,
    instance: ClipCandidate,
    created: bool,
    **kwargs: Any,
) -> None:
    """Auto-create a ClipLayoutConfig when a ClipCandidate is first saved.

    Uses the social account's platform to pick the default render mode.
    """
    if not created:
        return
    platform = instance.clipping_job.social_account.platform
    render_mode = PLATFORM_RENDER_MODE_DEFAULTS.get(platform, RenderMode.SMART_CROP)
    ClipLayoutConfig.objects.get_or_create(
        candidate=instance,
        defaults={"render_mode": render_mode},
    )


@receiver(post_save, sender=ClipCandidate)
def create_style_config_for_candidate(
    sender: type,
    instance: ClipCandidate,
    created: bool,
    **kwargs: Any,
) -> None:
    """Auto-create a ClipStyleConfig when a ClipCandidate is first saved.

    Pre-populates from the global default ClipRenderTemplate.
    """
    if not created:
        return
    template = ClipRenderTemplate.objects.filter(is_default=True).first()
    if template is None:
        template = ClipRenderTemplate.objects.first()
    style_defaults = template.to_style_defaults() if template is not None else {}
    ClipStyleConfig.objects.get_or_create(
        candidate=instance,
        defaults={**style_defaults, "render_template": template},
    )


@receiver(post_save, sender=ClipMediaAsset)
def detect_media_asset_duration(
    sender: type,
    instance: ClipMediaAsset,
    **kwargs: Any,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMediaAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        from pathlib import Path

        import ffmpeg
        from django.conf import settings

        file_path = Path(settings.MEDIA_ROOT) / instance.file.name
        if not file_path.exists():
            return
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe["format"]["duration"])
        ClipMediaAsset.objects.filter(pk=instance.pk).update(duration_sec=duration)
        logger.info(
            "Auto-detected media asset duration",
            extra={"asset_id": str(instance.pk), "duration_sec": duration},
        )
    except Exception as exc:
        logger.warning(
            "Could not auto-detect media asset duration",
            extra={"asset_id": str(instance.pk), "error": str(exc)},
        )


@receiver(post_save, sender=ClipMusicAsset)
def detect_music_asset_duration(
    sender: type,
    instance: ClipMusicAsset,
    **kwargs: Any,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMusicAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        from pathlib import Path

        import ffmpeg
        from django.conf import settings

        file_path = Path(settings.MEDIA_ROOT) / instance.file.name
        if not file_path.exists():
            return
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe["format"]["duration"])
        ClipMusicAsset.objects.filter(pk=instance.pk).update(duration_sec=duration)
        logger.info(
            "Auto-detected music asset duration",
            extra={"asset_id": str(instance.pk), "duration_sec": duration},
        )
    except Exception as exc:
        logger.warning(
            "Could not auto-detect music asset duration",
            extra={"asset_id": str(instance.pk), "error": str(exc)},
        )
```

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/apps.py ***REMOVED***/clipping/signals.py
git commit -m "feat(clipping): remove channel signal, update layout/style signals to use platform defaults"
```

---

## Task 6: Update factories and fix existing tests

**Files:**
- Modify: `***REMOVED***/clipping/tests/factories.py`
- Modify: `***REMOVED***/clipping/tests/test_models.py`
- Modify: `***REMOVED***/clipping/tests/test_signals.py`
- Modify: `***REMOVED***/clipping/tests/test_tasks.py`
- Modify: `***REMOVED***/clipping/tests/test_services.py`

- [ ] **Step 1: Update factories.py**

Replace the entire `***REMOVED***/clipping/tests/factories.py`:

```python
from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from ***REMOVED***.channels.tests.factories import SocialAccountFactory
from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClipRenderStageResult
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay


class ClippingJobFactory(DjangoModelFactory[ClippingJob]):
    social_account = factory.SubFactory(SocialAccountFactory)
    source_type = ClippingJob.SourceType.YOUTUBE_URL
    source_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    source_title = factory.Sequence(lambda n: f"Test Video {n}")
    clips_requested = 3

    class Meta:
        model = ClippingJob


class ClipCandidateFactory(DjangoModelFactory[ClipCandidate]):
    clipping_job = factory.SubFactory(ClippingJobFactory)
    start_sec = 60.0
    end_sec = 120.0
    title = "Amazing clip title"
    hook_text = "You won't believe this"
    caption_template = "{title} \U0001f3af"
    relevance_score = 8.5
    reason = "High engagement moment"
    transcript_excerpt = "Sample transcript text here"

    class Meta:
        model = ClipCandidate


class ClipRenderFactory(DjangoModelFactory[ClipRender]):
    candidate = factory.SubFactory(ClipCandidateFactory)
    format = ClipRender.Format.VERTICAL_9_16
    include_captions = True
    include_title_card = True
    include_branding = True

    class Meta:
        model = ClipRender


class ClipPostFactory(DjangoModelFactory[ClipPost]):
    render = factory.SubFactory(ClipRenderFactory)
    social_account = factory.SubFactory(SocialAccountFactory)
    caption = "Test caption #shorts"
    title = "Test Short"

    class Meta:
        model = ClipPost


class ClipLayoutConfigFactory(DjangoModelFactory[ClipLayoutConfig]):
    candidate = factory.SubFactory(ClipCandidateFactory)
    render_mode = ClipLayoutConfig.RenderMode.SMART_CROP

    class Meta:
        model = ClipLayoutConfig

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        candidate = kwargs.get("candidate")
        if candidate is not None:
            obj, _ = model_class.objects.update_or_create(
                candidate=candidate,
                defaults={k: v for k, v in kwargs.items() if k != "candidate"},
            )
            return obj
        return super()._create(model_class, *args, **kwargs)


class ClipRenderTemplateFactory(DjangoModelFactory[ClipRenderTemplate]):
    name = factory.Sequence(lambda n: f"Template {n}")
    is_default = False

    class Meta:
        model = ClipRenderTemplate


class ClipMediaAssetFactory(DjangoModelFactory[ClipMediaAsset]):
    asset_type = "INTRO"
    name = factory.Sequence(lambda n: f"Intro Clip {n}")
    file = factory.django.FileField(filename="intro.mp4", data=b"fake")
    is_active = True

    class Meta:
        model = ClipMediaAsset


class ClipMusicAssetFactory(DjangoModelFactory[ClipMusicAsset]):
    name = factory.Sequence(lambda n: f"Music Track {n}")
    file = factory.django.FileField(filename="track.mp3", data=b"fake")
    genre = "Chill"
    is_active = True

    class Meta:
        model = ClipMusicAsset


class ClipStyleConfigFactory(DjangoModelFactory[ClipStyleConfig]):
    candidate = factory.SubFactory(ClipCandidateFactory)

    class Meta:
        model = ClipStyleConfig

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        candidate = kwargs.get("candidate")
        if candidate is not None:
            obj, _ = model_class.objects.update_or_create(
                candidate=candidate,
                defaults={k: v for k, v in kwargs.items() if k != "candidate"},
            )
            return obj
        return super()._create(model_class, *args, **kwargs)


class ClipTimedOverlayFactory(DjangoModelFactory[ClipTimedOverlay]):
    candidate = factory.SubFactory(ClipCandidateFactory)
    overlay_type = ClipTimedOverlay.OverlayType.TEXT
    text = "Test overlay text"
    start_sec = 5.0
    end_sec = 10.0

    class Meta:
        model = ClipTimedOverlay


class ClipRenderStageResultFactory(DjangoModelFactory[ClipRenderStageResult]):
    render = factory.SubFactory(ClipRenderFactory)
    stage_name = "trim_and_crop"
    stage_order = 1
    status = ClipRenderStageResult.Status.PENDING

    class Meta:
        model = ClipRenderStageResult
```

- [ ] **Step 2: Update test_models.py — remove channel references**

Search `***REMOVED***/clipping/tests/test_models.py` for any reference to `channel` or `ChannelFactory` and replace with `social_account` / `SocialAccountFactory`. Any test that creates a `ClippingJob` via factory will automatically use the updated `ClippingJobFactory`. Any direct `ClippingJob(channel=...)` calls must be changed to `ClippingJob(social_account=...)`.

Also verify: `ClipRenderTemplate` tests no longer use `channel` kwarg.

- [ ] **Step 3: Update test_tasks.py — remove auto-approve assertions**

In `***REMOVED***/clipping/tests/test_tasks.py`:
- Replace any `job.channel` references with `job.social_account`
- Remove any assertions about auto-approve behaviour (e.g. tests that check `candidate.approved == True` after `analyze_clips` runs)
- Add an assertion that `analyze_clips` always calls `job.await_clip_approval()` (status should be `AWAITING_CLIP_APPROVAL` after task runs)
- Replace `ClippingJobFactory(channel=...)` with `ClippingJobFactory(social_account=...)`

- [ ] **Step 4: Update test_services.py**

In `***REMOVED***/clipping/tests/test_services.py`:
- Replace `job.channel` references with `job.social_account`
- `ClipAnalysisService(job)` call stays the same — it's the internals that change

- [ ] **Step 5: Run the full clipping test suite**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/ -v
```

Expected: All tests pass. Fix any remaining channel-reference failures before proceeding.

- [ ] **Step 6: Commit**

```bash
git add ***REMOVED***/clipping/tests/
git commit -m "feat(clipping): update factories and existing tests to use social_account"
```

---

## Task 7: Add simplejwt dependency and update DRF settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `config/settings/base.py`

- [ ] **Step 1: Add djangorestframework-simplejwt**

```bash
uv add djangorestframework-simplejwt
```

- [ ] **Step 2: Add simplejwt to INSTALLED_APPS**

In `config/settings/base.py`, in the `THIRD_PARTY_APPS` list, add after `"rest_framework.authtoken"`:
```python
"rest_framework_simplejwt",
```

- [ ] **Step 3: Update REST_FRAMEWORK settings**

In `config/settings/base.py`, replace the existing `REST_FRAMEWORK` dict (around line 376):

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",  # keep for browsable API / admin
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
```

- [ ] **Step 4: Add SIMPLE_JWT settings**

After the `REST_FRAMEWORK` block in `config/settings/base.py`, add:

```python
# djangorestframework-simplejwt
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}
```

- [ ] **Step 5: Verify JWT import works**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run python -c "from rest_framework_simplejwt.tokens import RefreshToken; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock config/settings/base.py
git commit -m "feat(clipping): add djangorestframework-simplejwt, update REST_FRAMEWORK to JWT+IsAdminUser"
```

---

## Task 8: Write sse.py

**Files:**
- Create: `***REMOVED***/clipping/sse.py`

- [ ] **Step 1: Write failing test**

Create `***REMOVED***/clipping/tests/test_sse.py`:

```python
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def test_emit_job_event_publishes_to_redis():
    with patch("***REMOVED***.clipping.sse._redis_client") as mock_redis:
        from ***REMOVED***.clipping.sse import emit_job_event

        emit_job_event("job-123", "status_changed", {"status": "DOWNLOADING"})

        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == "clipping:job:job-123"
        data = json.loads(payload)
        assert data["type"] == "status_changed"
        assert data["job_id"] == "job-123"
        assert data["status"] == "DOWNLOADING"


def test_job_event_stream_yields_sse_format():
    mock_pubsub = MagicMock()
    mock_pubsub.listen.return_value = [
        {"type": "subscribe", "data": 1},
        {"type": "message", "data": b'{"type":"status_changed","job_id":"j1"}'},
    ]
    with patch("***REMOVED***.clipping.sse._redis_client") as mock_redis:
        mock_redis.pubsub.return_value = mock_pubsub
        from ***REMOVED***.clipping.sse import job_event_stream

        events = list(job_event_stream("j1"))

    assert events[0] == "event: connected\ndata: {}\n\n"
    assert events[1].startswith("data: ")
    assert '"type":"status_changed"' in events[1]
```

Run:
```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_sse.py -v
```

Expected: FAIL (`ModuleNotFoundError: ***REMOVED***.clipping.sse`)

- [ ] **Step 2: Create ***REMOVED***/clipping/sse.py**

```python
from __future__ import annotations

import json
import logging
from collections.abc import Generator

import redis
from django.conf import settings

logger = logging.getLogger("***REMOVED***.clipping.sse")

_redis_client: redis.Redis = redis.from_url(settings.REDIS_URL)


def emit_job_event(job_id: str, event_type: str, data: dict) -> None:
    """Publish a structured event to the Redis pub/sub channel for a clipping job.

    Called from Celery tasks after any state transition. Silently logs on failure
    so a Redis outage never breaks the task itself.
    """
    try:
        payload = json.dumps({"type": event_type, "job_id": job_id, **data})
        _redis_client.publish(f"clipping:job:{job_id}", payload)
    except Exception as exc:
        logger.warning(
            "Failed to emit SSE job event",
            extra={"job_id": job_id, "event_type": event_type, "error": str(exc)},
        )


def job_event_stream(job_id: str) -> Generator[str, None, None]:
    """Subscribe to a job's Redis channel and yield SSE-formatted event strings.

    Intended to be used as the content generator for a StreamingHttpResponse.
    Blocks until the client disconnects or the Redis connection drops.
    """
    pubsub = _redis_client.pubsub()
    pubsub.subscribe(f"clipping:job:{job_id}")
    try:
        yield "event: connected\ndata: {}\n\n"
        for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
    finally:
        pubsub.unsubscribe(f"clipping:job:{job_id}")
        pubsub.close()
```

- [ ] **Step 3: Run tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_sse.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/sse.py ***REMOVED***/clipping/tests/test_sse.py
git commit -m "feat(clipping): add SSE module with emit_job_event and job_event_stream"
```

---

## Task 9: Write serializers.py

**Files:**
- Create: `***REMOVED***/clipping/serializers.py`

- [ ] **Step 1: Create ***REMOVED***/clipping/serializers.py**

```python
from __future__ import annotations

from rest_framework import serializers

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClipRenderStageResult
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay


class ClipRenderStageResultSerializer(serializers.ModelSerializer):
    output_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipRenderStageResult
        fields = [
            "id", "stage_order", "stage_name", "status",
            "started_at", "completed_at", "duration_sec",
            "last_error", "output_file_url",
        ]
        read_only_fields = fields

    def get_output_file_url(self, obj: ClipRenderStageResult) -> str | None:
        if not obj.output_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.output_file.url)
        return obj.output_file.url


class ClipRenderSerializer(serializers.ModelSerializer):
    stage_results = ClipRenderStageResultSerializer(many=True, read_only=True)
    video_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipRender
        fields = [
            "id", "candidate", "format", "status", "paused_at_stage",
            "video_file_url", "file_size_bytes", "render_duration_sec",
            "include_captions", "include_title_card", "include_branding",
            "celery_task_id", "started_at", "completed_at", "last_error",
            "stage_results", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "paused_at_stage", "video_file_url",
            "file_size_bytes", "render_duration_sec", "celery_task_id",
            "started_at", "completed_at", "last_error", "stage_results",
            "created_at", "updated_at",
        ]

    def get_video_file_url(self, obj: ClipRender) -> str | None:
        if not obj.video_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.video_file.url)
        return obj.video_file.url


class ClipTimedOverlaySerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipTimedOverlay
        fields = [
            "id", "candidate", "overlay_type", "text", "image",
            "start_sec", "end_sec", "position_x", "position_y",
            "opacity", "font_size", "font_color", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClipLayoutConfigSerializer(serializers.ModelSerializer):
    preview_image_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipLayoutConfig
        fields = [
            "id", "candidate", "render_mode", "render_format",
            "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h",
            "region_a_label", "region_a_x", "region_a_y", "region_a_w", "region_a_h",
            "region_b_label", "region_b_x", "region_b_y", "region_b_w", "region_b_h",
            "stack_ratio", "face_detected", "detection_confidence",
            "preview_image_url", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "candidate", "face_detected", "detection_confidence",
            "preview_image_url", "created_at", "updated_at",
        ]

    def get_preview_image_url(self, obj: ClipLayoutConfig) -> str | None:
        if not obj.preview_image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.preview_image.url)
        return obj.preview_image.url


class ClipStyleConfigSerializer(serializers.ModelSerializer):
    preview_image_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipStyleConfig
        fields = [
            "id", "candidate", "render_template",
            "intro_asset", "outro_asset", "music_asset",
            # All 36 style fields from ClipRenderStyleMixin:
            "caption_enabled", "caption_style", "caption_font", "caption_size",
            "caption_color", "caption_stroke_color", "caption_stroke_width",
            "caption_bg_color", "caption_position", "caption_animation",
            "caption_language", "caption_translate_to", "emoji_keyword_map",
            "hook_enabled", "hook_style", "hook_duration_sec", "hook_font",
            "hook_size", "hook_color", "hook_bg_color", "hook_animation",
            "intro_transition", "outro_transition", "transition_duration_sec",
            "watermark_enabled", "watermark_type", "watermark_text", "watermark_image",
            "watermark_position", "watermark_opacity", "watermark_size",
            "progress_bar_enabled", "progress_bar_position", "progress_bar_color",
            "progress_bar_height",
            "music_enabled", "music_volume_db", "music_fade_in_sec", "music_fade_out_sec",
            "translated_transcript_json", "preview_image_url",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "candidate", "preview_image_url", "created_at", "updated_at"]

    def get_preview_image_url(self, obj: ClipStyleConfig) -> str | None:
        if not obj.preview_image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.preview_image.url)
        return obj.preview_image.url


class ClipCandidateListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipCandidate
        fields = [
            "id", "clipping_job", "title", "start_sec", "end_sec", "duration_sec",
            "relevance_score", "status", "approved", "approved_at", "render_gates",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "duration_sec", "clipping_job", "created_at", "updated_at"]


class ClipCandidateDetailSerializer(serializers.ModelSerializer):
    layout_config = ClipLayoutConfigSerializer(read_only=True)
    style_config = ClipStyleConfigSerializer(read_only=True)
    timed_overlays = ClipTimedOverlaySerializer(many=True, read_only=True)

    class Meta:
        model = ClipCandidate
        fields = [
            "id", "clipping_job", "title", "hook_text", "caption_template",
            "start_sec", "end_sec", "duration_sec", "relevance_score",
            "reason", "transcript_excerpt", "status", "approved",
            "approved_at", "approved_by", "rejection_reason", "render_gates",
            "layout_config", "style_config", "timed_overlays",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "duration_sec", "clipping_job", "approved", "approved_at",
            "approved_by", "status", "layout_config", "style_config",
            "timed_overlays", "created_at", "updated_at",
        ]


class ClipCandidateSummarySerializer(serializers.ModelSerializer):
    """Minimal nested representation used inside ClippingJobDetailSerializer."""

    class Meta:
        model = ClipCandidate
        fields = [
            "id", "title", "start_sec", "end_sec", "duration_sec",
            "relevance_score", "status", "approved", "render_gates",
        ]
        read_only_fields = fields


class ClippingJobListSerializer(serializers.ModelSerializer):
    total_cost_usd = serializers.DecimalField(max_digits=10, decimal_places=6, read_only=True)

    class Meta:
        model = ClippingJob
        fields = [
            "id", "social_account", "source_type", "source_url", "source_title",
            "source_duration_sec", "clips_requested", "status",
            "started_at", "completed_at", "failed_at", "last_error",
            "total_cost_usd", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "started_at", "completed_at", "failed_at",
            "last_error", "total_cost_usd", "source_title", "source_duration_sec",
            "created_at", "updated_at",
        ]


class ClippingJobDetailSerializer(ClippingJobListSerializer):
    candidates = ClipCandidateSummarySerializer(many=True, read_only=True)
    analysis_manifest = serializers.JSONField(read_only=True)

    class Meta(ClippingJobListSerializer.Meta):
        fields = ClippingJobListSerializer.Meta.fields + [
            "transcript_text", "transcript_json", "analysis_manifest",
            "analysis_provider", "analysis_cost_usd", "agent_run_id",
            "celery_task_id", "candidates",
        ]
        read_only_fields = ClippingJobListSerializer.Meta.read_only_fields + [
            "transcript_text", "transcript_json", "analysis_manifest",
            "analysis_provider", "analysis_cost_usd", "agent_run_id",
            "celery_task_id", "candidates",
        ]


class ClipRenderTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipRenderTemplate
        fields = [
            "id", "name", "is_default",
            "caption_enabled", "caption_style", "caption_font", "caption_size",
            "caption_color", "caption_stroke_color", "caption_stroke_width",
            "caption_bg_color", "caption_position", "caption_animation",
            "caption_language", "caption_translate_to", "emoji_keyword_map",
            "hook_enabled", "hook_style", "hook_duration_sec", "hook_font",
            "hook_size", "hook_color", "hook_bg_color", "hook_animation",
            "intro_transition", "outro_transition", "transition_duration_sec",
            "watermark_enabled", "watermark_type", "watermark_text",
            "watermark_position", "watermark_opacity", "watermark_size",
            "progress_bar_enabled", "progress_bar_position", "progress_bar_color",
            "progress_bar_height",
            "music_enabled", "music_volume_db", "music_fade_in_sec", "music_fade_out_sec",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClipMediaAssetSerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipMediaAsset
        fields = [
            "id", "asset_type", "name", "file", "duration_sec",
            "is_active", "thumbnail_url", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "duration_sec", "thumbnail_url", "created_at", "updated_at"]

    def get_thumbnail_url(self, obj: ClipMediaAsset) -> str | None:
        if not obj.thumbnail:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.thumbnail.url)
        return obj.thumbnail.url


class ClipMusicAssetSerializer(serializers.ModelSerializer):
    waveform_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipMusicAsset
        fields = [
            "id", "name", "file", "duration_sec", "bpm", "genre",
            "is_active", "waveform_file_url", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "duration_sec", "waveform_file_url", "created_at", "updated_at"]

    def get_waveform_file_url(self, obj: ClipMusicAsset) -> str | None:
        if not obj.waveform_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.waveform_file.url)
        return obj.waveform_file.url


class ClipPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipPost
        fields = [
            "id", "render", "social_account", "caption", "title", "hashtags",
            "scheduled_at", "posted_at", "status", "platform_post_id",
            "platform_url", "celery_task_id", "last_error",
            "views", "likes", "comments", "shares", "revenue_est_usd",
            "last_analytics_sync", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "platform_post_id", "platform_url", "celery_task_id",
            "last_error", "views", "likes", "comments", "shares",
            "revenue_est_usd", "last_analytics_sync", "created_at", "updated_at",
        ]
```

- [ ] **Step 2: Verify import**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run python -c "from ***REMOVED***.clipping.serializers import ClippingJobDetailSerializer; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/serializers.py
git commit -m "feat(clipping): add DRF serializers for all clipping models"
```

---

## Task 10: Write ClippingJobViewSet

**Files:**
- Create: `***REMOVED***/clipping/views/jobs.py` (overwrites old template-based file)

- [ ] **Step 1: Create views/jobs.py**

```python
from __future__ import annotations

import logging
from typing import Any

from django.http import StreamingHttpResponse
from django_fsm import can_proceed
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.serializers import ClippingJobDetailSerializer
from ***REMOVED***.clipping.serializers import ClippingJobListSerializer
from ***REMOVED***.clipping.sse import emit_job_event
from ***REMOVED***.clipping.sse import job_event_stream
from ***REMOVED***.clipping.tasks import download_source_video
from ***REMOVED***.clipping.tasks import render_clip
from ***REMOVED***.clipping.tasks import transcribe_video

logger = logging.getLogger("***REMOVED***.clipping.api")


class ClippingJobViewSet(ModelViewSet):
    queryset = ClippingJob.objects.select_related("social_account").order_by("-created_at")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClippingJobDetailSerializer
        return ClippingJobListSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def perform_create(self, serializer) -> None:
        job: ClippingJob = serializer.save()
        if can_proceed(job.begin_download):
            job.begin_download()
            job.save(update_fields=["status", "started_at", "updated_at"])
        download_source_video.delay(str(job.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        logger.info("ClippingJob created", extra={"job_id": str(job.id)})

    @action(detail=True, methods=["post"], url_path="start-render")
    def start_render(self, request: Request, pk: str | None = None) -> Response:
        """Dispatch render_clip for all APPROVED candidates and begin_rendering FSM transition."""
        job: ClippingJob = self.get_object()
        approved = list(
            job.candidates.filter(status=ClipCandidate.CandidateStatus.APPROVED)
        )
        if not approved:
            return Response(
                {"detail": "No approved candidates found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not can_proceed(job.begin_rendering):
            return Response(
                {"detail": f"Cannot begin rendering from state {job.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.begin_rendering()
        job.save(update_fields=["status", "updated_at"])
        for candidate in approved:
            render_clip.delay(str(candidate.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        return Response(
            {
                "dispatched_renders": len(approved),
                "candidate_ids": [str(c.id) for c in approved],
                "job_status": job.status,
            }
        )

    @action(detail=True, methods=["post"], url_path="approve-all")
    def approve_all(self, request: Request, pk: str | None = None) -> Response:
        """Approve all PROPOSED candidates on this job."""
        job: ClippingJob = self.get_object()
        from django.utils import timezone

        updated = job.candidates.filter(
            status=ClipCandidate.CandidateStatus.PROPOSED
        ).update(
            status=ClipCandidate.CandidateStatus.APPROVED,
            approved=True,
            approved_by=request.user,
            approved_at=timezone.now(),
        )
        return Response({"approved_count": updated})

    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request: Request, pk: str | None = None) -> Response:
        """Retry a failed job. Body: {"from_stage": "transcription" | "analysis"}"""
        job: ClippingJob = self.get_object()
        from_stage = request.data.get("from_stage", "transcription")
        if from_stage == "analysis":
            if not can_proceed(job.retry_analysis):
                return Response(
                    {"detail": f"Cannot retry analysis from state {job.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job.retry_analysis()
            job.save(update_fields=["status", "last_error", "updated_at"])
            from ***REMOVED***.clipping.tasks import analyze_clips
            analyze_clips.delay(str(job.id))
        else:
            if not can_proceed(job.retry_transcription):
                return Response(
                    {"detail": f"Cannot retry transcription from state {job.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job.retry_transcription()
            job.save(update_fields=["status", "last_error", "updated_at"])
            transcribe_video.delay(str(job.id))
        emit_job_event(str(job.id), "status_changed", {"status": job.status})
        return Response({"job_status": job.status, "retrying": from_stage})

    @action(detail=True, methods=["get"], url_path="stream")
    def stream(self, request: Request, pk: str | None = None) -> StreamingHttpResponse:
        """SSE endpoint. Streams real-time job events from Redis pub/sub."""
        job: ClippingJob = self.get_object()
        response = StreamingHttpResponse(
            job_event_stream(str(job.id)),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
```

- [ ] **Step 2: Commit**

```bash
git add ***REMOVED***/clipping/views/jobs.py
git commit -m "feat(clipping): add ClippingJobViewSet with DRF + SSE stream action"
```

---

## Task 11: Write ClipCandidateViewSet, ClipLayoutConfigViewSet, ClipStyleConfigViewSet

**Files:**
- Create: `***REMOVED***/clipping/views/candidates.py` (overwrites old file)

- [ ] **Step 1: Create views/candidates.py**

```python
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone
from django_fsm import can_proceed
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework.viewsets import ModelViewSet

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.serializers import ClipCandidateDetailSerializer
from ***REMOVED***.clipping.serializers import ClipCandidateListSerializer
from ***REMOVED***.clipping.serializers import ClipLayoutConfigSerializer
from ***REMOVED***.clipping.serializers import ClipStyleConfigSerializer
from ***REMOVED***.clipping.tasks import preview_clip_layout
from ***REMOVED***.clipping.tasks import preview_clip_style

logger = logging.getLogger("***REMOVED***.clipping.api")


class ClipCandidateViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipCandidate.objects.select_related(
        "clipping_job__social_account",
        "approved_by",
        "layout_config",
        "style_config",
    ).prefetch_related("timed_overlays")
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClipCandidateDetailSerializer
        return ClipCandidateListSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        job_id = self.request.query_params.get("job")
        if job_id:
            qs = qs.filter(clipping_job_id=job_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        candidate.status = ClipCandidate.CandidateStatus.APPROVED
        candidate.approved = True
        candidate.approved_at = timezone.now()
        candidate.approved_by = request.user
        candidate.save(update_fields=["status", "approved", "approved_at", "approved_by", "updated_at"])
        return Response({
            "id": str(candidate.id),
            "status": candidate.status,
            "approved": candidate.approved,
            "approved_at": candidate.approved_at,
        })

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        reason = request.data.get("reason", "")
        candidate.status = ClipCandidate.CandidateStatus.REJECTED
        candidate.approved = False
        candidate.rejection_reason = reason
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

    @action(detail=True, methods=["post"], url_path="undo-reject")
    def undo_reject(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        candidate.status = ClipCandidate.CandidateStatus.PROPOSED
        candidate.approved = None
        candidate.rejection_reason = ""
        candidate.save(update_fields=["status", "approved", "rejection_reason", "updated_at"])
        return Response({"id": str(candidate.id), "status": candidate.status})

    @action(detail=True, methods=["post"], url_path="trigger-preview")
    def trigger_preview(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        if not hasattr(candidate, "layout_config"):
            return Response(
                {"detail": "No layout config found for this candidate."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        preview_clip_layout.delay(str(candidate.layout_config.id))
        return Response({"queued": True, "layout_config_id": str(candidate.layout_config.id)})

    @action(detail=True, methods=["get"], url_path="preview-status")
    def preview_status(self, request: Request, pk: str | None = None) -> Response:
        candidate: ClipCandidate = self.get_object()
        lc = getattr(candidate, "layout_config", None)
        if lc is None:
            return Response({"ready": False, "preview_url": None})
        preview_url = None
        if lc.preview_image:
            preview_url = request.build_absolute_uri(lc.preview_image.url)
        return Response({"ready": bool(lc.preview_image), "preview_url": preview_url})


class ClipLayoutConfigViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipLayoutConfig.objects.select_related("candidate")
    serializer_class = ClipLayoutConfigSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @action(detail=True, methods=["post"], url_path="reset-crop")
    def reset_crop(self, request: Request, pk: str | None = None) -> Response:
        lc: ClipLayoutConfig = self.get_object()
        lc.manual_crop_x = None
        lc.manual_crop_y = None
        lc.manual_crop_w = None
        lc.manual_crop_h = None
        lc.save(update_fields=["manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at"])
        return Response(ClipLayoutConfigSerializer(lc, context={"request": request}).data)


class ClipStyleConfigViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    queryset = ClipStyleConfig.objects.select_related(
        "candidate", "render_template", "intro_asset", "outro_asset", "music_asset"
    )
    serializer_class = ClipStyleConfigSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @action(detail=True, methods=["post"], url_path="apply-template")
    def apply_template(self, request: Request, pk: str | None = None) -> Response:
        """Re-seed all style fields from a given render template."""
        config: ClipStyleConfig = self.get_object()
        template_id = request.data.get("template_id")
        if not template_id:
            return Response(
                {"detail": "template_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            template = ClipRenderTemplate.objects.get(id=template_id)
        except ClipRenderTemplate.DoesNotExist:
            return Response({"detail": "Template not found."}, status=status.HTTP_404_NOT_FOUND)

        style_fields = template.to_style_defaults()
        for field_name, value in style_fields.items():
            setattr(config, field_name, value)
        config.render_template = template
        config.save(update_fields=[*style_fields.keys(), "render_template", "updated_at"])
        return Response(ClipStyleConfigSerializer(config, context={"request": request}).data)
```

- [ ] **Step 2: Commit**

```bash
git add ***REMOVED***/clipping/views/candidates.py
git commit -m "feat(clipping): add ClipCandidateViewSet, ClipLayoutConfigViewSet, ClipStyleConfigViewSet"
```

---

## Task 12: Write ClipRenderViewSet

**Files:**
- Create: `***REMOVED***/clipping/views/renders.py` (overwrites old file)

- [ ] **Step 1: Create views/renders.py**

```python
from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.serializers import ClipRenderSerializer
from ***REMOVED***.clipping.tasks import render_clip

logger = logging.getLogger("***REMOVED***.clipping.api")


class ClipRenderViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    queryset = ClipRender.objects.select_related("candidate").prefetch_related("stage_results")
    serializer_class = ClipRenderSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        candidate_id = self.request.query_params.get("candidate")
        if candidate_id:
            qs = qs.filter(candidate_id=candidate_id)
        return qs

    @action(detail=True, methods=["post"])
    def resume(self, request: Request, pk: str | None = None) -> Response:
        """Resume a PAUSED_AT_GATE render from the next stage."""
        render: ClipRender = self.get_object()
        if render.status != ClipRender.RenderStatus.PAUSED_AT_GATE:
            return Response(
                {"detail": f"Render is not paused. Current status: {render.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if render.paused_at_stage is None:
            return Response(
                {"detail": "paused_at_stage is not set."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        next_stage = render.paused_at_stage + 1
        render_clip.delay(
            str(render.candidate_id),
            start_from_stage=next_stage,
            clip_render_id=str(render.id),
        )
        return Response({"resumed": True, "start_from_stage": next_stage})

    @action(detail=True, methods=["post"], url_path=r"rerun/(?P<stage_order>[0-9]+)")
    def rerun(self, request: Request, pk: str | None = None, stage_order: str = "1") -> Response:
        """Re-run a render from a specific stage."""
        render: ClipRender = self.get_object()
        start = int(stage_order)
        if not 1 <= start <= 10:
            return Response(
                {"detail": "stage_order must be between 1 and 10."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        render_clip.delay(
            str(render.candidate_id),
            start_from_stage=start,
            clip_render_id=str(render.id),
        )
        return Response({"rerunning": True, "start_from_stage": start})

    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> Response:
        """Return a URL for downloading the final render file."""
        render: ClipRender = self.get_object()
        if not render.video_file:
            return Response(
                {"detail": "Render has no video file yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        url = request.build_absolute_uri(render.video_file.url)
        return Response({"download_url": url})
```

- [ ] **Step 2: Commit**

```bash
git add ***REMOVED***/clipping/views/renders.py
git commit -m "feat(clipping): add ClipRenderViewSet with resume, rerun, download actions"
```

---

## Task 13: Write ClipTimedOverlayViewSet and asset ViewSets

**Files:**
- Create: `***REMOVED***/clipping/views/overlays.py`
- Create: `***REMOVED***/clipping/views/assets.py`

- [ ] **Step 1: Create views/overlays.py**

```python
from __future__ import annotations

from rest_framework.viewsets import ModelViewSet

from ***REMOVED***.clipping.models import ClipTimedOverlay
from ***REMOVED***.clipping.serializers import ClipTimedOverlaySerializer


class ClipTimedOverlayViewSet(ModelViewSet):
    queryset = ClipTimedOverlay.objects.select_related("candidate")
    serializer_class = ClipTimedOverlaySerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        candidate_id = self.request.query_params.get("candidate")
        if candidate_id:
            qs = qs.filter(candidate_id=candidate_id)
        return qs
```

- [ ] **Step 2: Create views/assets.py**

```python
from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet

from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipPost
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.serializers import ClipMediaAssetSerializer
from ***REMOVED***.clipping.serializers import ClipMusicAssetSerializer
from ***REMOVED***.clipping.serializers import ClipPostSerializer
from ***REMOVED***.clipping.serializers import ClipRenderTemplateSerializer
from ***REMOVED***.clipping.tasks import sync_clip_analytics

logger = logging.getLogger("***REMOVED***.clipping.api")


class ClipMediaAssetViewSet(ModelViewSet):
    queryset = ClipMediaAsset.objects.order_by("asset_type", "name")
    serializer_class = ClipMediaAssetSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        asset_type = self.request.query_params.get("asset_type")
        if asset_type:
            qs = qs.filter(asset_type=asset_type)
        return qs

    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMediaAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


class ClipMusicAssetViewSet(ModelViewSet):
    queryset = ClipMusicAsset.objects.order_by("genre", "name")
    serializer_class = ClipMusicAssetSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @action(detail=True, methods=["get"], url_path="preview-url")
    def preview_url(self, request: Request, pk: str | None = None) -> Response:
        asset: ClipMusicAsset = self.get_object()
        if not asset.file:
            return Response({"detail": "No file."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(asset.file.url)})


class ClipRenderTemplateViewSet(ModelViewSet):
    queryset = ClipRenderTemplate.objects.order_by("-is_default", "name")
    serializer_class = ClipRenderTemplateSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        template: ClipRenderTemplate = self.get_object()
        if template.is_default:
            return Response(
                {"detail": "Cannot delete the default render template."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request: Request, pk: str | None = None) -> Response:
        template: ClipRenderTemplate = self.get_object()
        template.is_default = True
        template.save(update_fields=["is_default", "updated_at"])
        return Response(ClipRenderTemplateSerializer(template).data)


class ClipPostViewSet(ReadOnlyModelViewSet):
    queryset = ClipPost.objects.select_related("render", "social_account")
    serializer_class = ClipPostSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        render_id = self.request.query_params.get("render")
        if render_id:
            qs = qs.filter(render_id=render_id)
        return qs

    @action(detail=True, methods=["post"], url_path="sync-analytics")
    def sync_analytics(self, request: Request, pk: str | None = None) -> Response:
        post: ClipPost = self.get_object()
        sync_clip_analytics.delay(str(post.id))
        return Response({"queued": True})
```

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/views/overlays.py ***REMOVED***/clipping/views/assets.py
git commit -m "feat(clipping): add ClipTimedOverlay, ClipMediaAsset, ClipMusicAsset, ClipRenderTemplate, ClipPost ViewSets"
```

---

## Task 14: Wire up router, remove old files, update admin

**Files:**
- Modify: `***REMOVED***/clipping/views/__init__.py`
- Modify: `config/urls.py`
- Modify: `***REMOVED***/clipping/admin.py`
- Delete: `***REMOVED***/clipping/urls.py`
- Delete: `***REMOVED***/templates/clipping/` (all files)
- Delete: `***REMOVED***/clipping/tests/test_views_phase_b.py`

- [ ] **Step 1: Update views/__init__.py**

Replace `***REMOVED***/clipping/views/__init__.py` entirely:

```python
from __future__ import annotations

from ***REMOVED***.clipping.views.assets import ClipMediaAssetViewSet
from ***REMOVED***.clipping.views.assets import ClipMusicAssetViewSet
from ***REMOVED***.clipping.views.assets import ClipPostViewSet
from ***REMOVED***.clipping.views.assets import ClipRenderTemplateViewSet
from ***REMOVED***.clipping.views.candidates import ClipCandidateViewSet
from ***REMOVED***.clipping.views.candidates import ClipLayoutConfigViewSet
from ***REMOVED***.clipping.views.candidates import ClipStyleConfigViewSet
from ***REMOVED***.clipping.views.jobs import ClippingJobViewSet
from ***REMOVED***.clipping.views.overlays import ClipTimedOverlayViewSet
from ***REMOVED***.clipping.views.renders import ClipRenderViewSet

__all__ = [
    "ClippingJobViewSet",
    "ClipCandidateViewSet",
    "ClipLayoutConfigViewSet",
    "ClipStyleConfigViewSet",
    "ClipRenderViewSet",
    "ClipTimedOverlayViewSet",
    "ClipMediaAssetViewSet",
    "ClipMusicAssetViewSet",
    "ClipRenderTemplateViewSet",
    "ClipPostViewSet",
]
```

- [ ] **Step 2: Update config/urls.py**

Replace the entire `config/urls.py`:

```python
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView

from ***REMOVED***.channels import views as channels_views
from ***REMOVED***.clipping.views import (
    ClipCandidateViewSet,
    ClipLayoutConfigViewSet,
    ClipMediaAssetViewSet,
    ClipMusicAssetViewSet,
    ClipPostViewSet,
    ClipRenderTemplateViewSet,
    ClipRenderViewSet,
    ClipStyleConfigViewSet,
    ClipTimedOverlayViewSet,
    ClippingJobViewSet,
)

# DRF Router
router = DefaultRouter()
router.register(r"clipping/jobs",             ClippingJobViewSet,         basename="clipping-job")
router.register(r"clipping/candidates",       ClipCandidateViewSet,       basename="clip-candidate")
router.register(r"clipping/renders",          ClipRenderViewSet,          basename="clip-render")
router.register(r"clipping/layout-configs",   ClipLayoutConfigViewSet,    basename="clip-layout")
router.register(r"clipping/style-configs",    ClipStyleConfigViewSet,     basename="clip-style")
router.register(r"clipping/overlays",         ClipTimedOverlayViewSet,    basename="clip-overlay")
router.register(r"clipping/media-assets",     ClipMediaAssetViewSet,      basename="clip-media-asset")
router.register(r"clipping/music-assets",     ClipMusicAssetViewSet,      basename="clip-music-asset")
router.register(r"clipping/render-templates", ClipRenderTemplateViewSet,  basename="clip-render-template")
router.register(r"clipping/posts",            ClipPostViewSet,            basename="clip-post")

urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path("about/", TemplateView.as_view(template_name="pages/about.html"), name="about"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("users/", include("***REMOVED***.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    path(
        "oauth/youtube/callback/",
        channels_views.youtube_oauth_callback,
        name="youtube_oauth_callback",
    ),
    path("app/", include("***REMOVED***.ui.urls", namespace="ui")),
    # API v1
    path("api/v1/", include(router.urls)),
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Legacy API router (users)
    path("api/", include("config.api_router")),
    path("api/auth-token/", include("rest_framework.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]

if settings.DEBUG:
    urlpatterns += [
        path("400/", default_views.bad_request, kwargs={"exception": Exception("Bad Request!")}),
        path("403/", default_views.permission_denied, kwargs={"exception": Exception("Permission Denied")}),
        path("404/", default_views.page_not_found, kwargs={"exception": Exception("Page not Found")}),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns = [path("__debug__/", include(debug_toolbar.urls)), *urlpatterns]
```

- [ ] **Step 3: Delete old clipping URL file and templates**

```bash
rm ***REMOVED***/clipping/urls.py
rm -rf ***REMOVED***/templates/clipping/
rm -f ***REMOVED***/clipping/tests/test_views_phase_b.py
```

- [ ] **Step 4: Update admin.py — remove all Channel references**

In `***REMOVED***/clipping/admin.py`, search for all occurrences of `channel` (field references in `list_display`, `list_filter`, `search_fields`, `fieldsets`, `raw_id_fields`) and remove them. Key changes:

- `ClippingJobAdmin`: remove `"channel"` from `list_display` and `list_filter`; in `fieldsets`, replace `"channel"` with `"social_account"`
- `ClipRenderTemplateAdmin` (if exists): remove `channel` from all field lists; add `name` and `is_default` to display/fieldsets
- `ClipMediaAssetAdmin`: remove `"channel"` from `list_display`, `list_filter`, `search_fields`, indexes
- `ClipMusicAssetAdmin`: same as above

Verify no remaining `channel` references in admin.py:
```bash
grep -n "channel" ***REMOVED***/clipping/admin.py
```

Expected: zero matches (or only comments if any).

- [ ] **Step 5: Verify server starts**

```bash
just up
```

Then in another terminal:
```bash
curl -s http://localhost:8000/api/v1/clipping/jobs/ -H "Authorization: Bearer invalid" | python3 -m json.tool
```

Expected: `{"detail": "Given token not valid for any token type", ...}` (401) — confirms JWT is being checked.

- [ ] **Step 6: Commit**

```bash
git add ***REMOVED***/clipping/views/__init__.py config/urls.py ***REMOVED***/clipping/admin.py
git commit -m "feat(clipping): wire DRF router + JWT URLs, remove old template views and clipping URL conf"
```

---

## Task 15: Write test_api.py and update remaining tests

**Files:**
- Create: `***REMOVED***/clipping/tests/test_api.py`

- [ ] **Step 1: Create ***REMOVED***/clipping/tests/test_api.py**

```python
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from ***REMOVED***.channels.tests.factories import SocialAccountFactory
from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.models import ClipRenderTemplate
from ***REMOVED***.clipping.tests.factories import (
    ClipCandidateFactory,
    ClipLayoutConfigFactory,
    ClipMediaAssetFactory,
    ClipMusicAssetFactory,
    ClipRenderFactory,
    ClipRenderTemplateFactory,
    ClippingJobFactory,
    ClipStyleConfigFactory,
    ClipTimedOverlayFactory,
)
from ***REMOVED***.users.tests.factories import UserFactory


@pytest.fixture
def staff_user(db):
    return UserFactory(is_staff=True, is_superuser=True)


@pytest.fixture
def auth_client(db, staff_user):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"username": staff_user.username, "password": "password"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    return client


# ── JWT ───────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_jwt_obtain_token(staff_user):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"username": staff_user.username, "password": "password"},
        format="json",
    )
    assert response.status_code == 200
    assert "access" in response.json()
    assert "refresh" in response.json()


@pytest.mark.django_db
def test_unauthenticated_request_returns_401():
    client = APIClient()
    response = client.get("/api/v1/clipping/jobs/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_non_staff_user_returns_403(db):
    user = UserFactory(is_staff=False)
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"username": user.username, "password": "password"},
        format="json",
    )
    # Token can be obtained but GET returns 403
    token = response.json().get("access")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = client.get("/api/v1/clipping/jobs/")
    assert response.status_code == 403


# ── ClippingJob ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_clipping_jobs(auth_client):
    ClippingJobFactory.create_batch(3)
    response = auth_client.get("/api/v1/clipping/jobs/")
    assert response.status_code == 200
    assert len(response.json()) == 3


@pytest.mark.django_db
def test_create_clipping_job_dispatches_download(auth_client, mocker):
    mock_delay = mocker.patch("***REMOVED***.clipping.views.jobs.download_source_video.delay")
    account = SocialAccountFactory()
    response = auth_client.post(
        "/api/v1/clipping/jobs/",
        {
            "social_account": str(account.id),
            "source_type": "YOUTUBE_URL",
            "source_url": "https://youtube.com/watch?v=test",
            "clips_requested": 3,
        },
        format="json",
    )
    assert response.status_code == 201
    mock_delay.assert_called_once()


@pytest.mark.django_db
def test_retrieve_job_includes_candidates(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job)
    ClipCandidateFactory(clipping_job=job)
    response = auth_client.get(f"/api/v1/clipping/jobs/{job.id}/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["candidates"]) == 2


@pytest.mark.django_db
def test_start_render_requires_approved_candidate(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job, status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(f"/api/v1/clipping/jobs/{job.id}/start-render/")
    assert response.status_code == 400
    assert "No approved candidates" in response.json()["detail"]


@pytest.mark.django_db
def test_approve_all_approves_proposed_candidates(auth_client):
    job = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job, status=ClipCandidate.CandidateStatus.PROPOSED)
    ClipCandidateFactory(clipping_job=job, status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(f"/api/v1/clipping/jobs/{job.id}/approve-all/")
    assert response.status_code == 200
    assert response.json()["approved_count"] == 2


# ── ClipCandidate ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_approve_candidate(auth_client):
    candidate = ClipCandidateFactory(status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(f"/api/v1/clipping/candidates/{candidate.id}/approve/")
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["approved"] is True


@pytest.mark.django_db
def test_reject_candidate(auth_client):
    candidate = ClipCandidateFactory(status=ClipCandidate.CandidateStatus.PROPOSED)
    response = auth_client.post(
        f"/api/v1/clipping/candidates/{candidate.id}/reject/",
        {"reason": "Not relevant"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


@pytest.mark.django_db
def test_undo_reject_resets_to_proposed(auth_client):
    candidate = ClipCandidateFactory(
        status=ClipCandidate.CandidateStatus.REJECTED,
        approved=False,
        rejection_reason="Not relevant",
    )
    response = auth_client.post(f"/api/v1/clipping/candidates/{candidate.id}/undo-reject/")
    assert response.status_code == 200
    assert response.json()["status"] == "PROPOSED"


@pytest.mark.django_db
def test_filter_candidates_by_job(auth_client):
    job1 = ClippingJobFactory()
    job2 = ClippingJobFactory()
    ClipCandidateFactory(clipping_job=job1)
    ClipCandidateFactory(clipping_job=job2)
    response = auth_client.get(f"/api/v1/clipping/candidates/?job={job1.id}")
    assert response.status_code == 200
    assert len(response.json()) == 1


# ── ClipLayoutConfig ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_patch_layout_config(auth_client):
    candidate = ClipCandidateFactory()
    lc = candidate.layout_config
    response = auth_client.patch(
        f"/api/v1/clipping/layout-configs/{lc.id}/",
        {"render_mode": "CENTER_CROP"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["render_mode"] == "CENTER_CROP"


@pytest.mark.django_db
def test_reset_crop_clears_manual_fields(auth_client):
    candidate = ClipCandidateFactory()
    lc = candidate.layout_config
    lc.manual_crop_x = 100
    lc.manual_crop_y = 0
    lc.manual_crop_w = 500
    lc.manual_crop_h = 900
    lc.save()
    response = auth_client.post(f"/api/v1/clipping/layout-configs/{lc.id}/reset-crop/")
    assert response.status_code == 200
    data = response.json()
    assert data["manual_crop_x"] is None
    assert data["manual_crop_w"] is None


# ── ClipRenderTemplate ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_cannot_delete_default_template(auth_client):
    template = ClipRenderTemplateFactory(is_default=True)
    response = auth_client.delete(f"/api/v1/clipping/render-templates/{template.id}/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_set_default_marks_template_as_default(auth_client):
    t1 = ClipRenderTemplateFactory(is_default=True)
    t2 = ClipRenderTemplateFactory(is_default=False)
    response = auth_client.post(f"/api/v1/clipping/render-templates/{t2.id}/set-default/")
    assert response.status_code == 200
    t1.refresh_from_db()
    t2.refresh_from_db()
    assert t2.is_default is True
    assert t1.is_default is False


# ── ClipRender ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_resume_non_paused_render_returns_400(auth_client):
    render = ClipRenderFactory(status=ClipRender.RenderStatus.COMPLETED)
    response = auth_client.post(f"/api/v1/clipping/renders/{render.id}/resume/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_resume_paused_render_dispatches_task(auth_client, mocker):
    mock_delay = mocker.patch("***REMOVED***.clipping.views.renders.render_clip.delay")
    render = ClipRenderFactory(
        status=ClipRender.RenderStatus.PAUSED_AT_GATE,
        paused_at_stage=3,
    )
    response = auth_client.post(f"/api/v1/clipping/renders/{render.id}/resume/")
    assert response.status_code == 200
    mock_delay.assert_called_once_with(
        str(render.candidate_id),
        start_from_stage=4,
        clip_render_id=str(render.id),
    )
```

- [ ] **Step 2: Run the API tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_api.py -v
```

Expected: All pass. Fix any failures before proceeding.

- [ ] **Step 3: Run the full test suite**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/ -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/tests/test_api.py
git commit -m "feat(clipping): add comprehensive DRF API tests covering JWT, ViewSet actions, permissions"
```

---

## Task 16: Add Phase 2 Python dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pyannote.audio and scenedetect**

```bash
uv add "pyannote.audio>=3.1" "scenedetect[opencv]>=0.6"
```

- [ ] **Step 2: Add HUGGINGFACE_TOKEN to settings**

In `config/settings/base.py`, after the `REDIS_URL` block, add:

```python
# PyAnnote speaker diarization model — required for Phase 2 ML analysis
HUGGINGFACE_TOKEN: str = env("HUGGINGFACE_TOKEN", default="")
```

Add `HUGGINGFACE_TOKEN=hf_your_token_here` to `.envs/.local/.django` (do **not** commit this file).

- [ ] **Step 3: Verify import**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run python -c "import scenedetect; print('scenedetect OK'); from pyannote.audio import Pipeline; print('pyannote OK')"
```

Expected: `scenedetect OK` and `pyannote OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock config/settings/base.py
git commit -m "feat(clipping): add pyannote.audio, scenedetect Phase 2 ML dependencies"
```

---

## Task 17: Rewrite speaker_detection.py

**Files:**
- Modify: `***REMOVED***/services/media/speaker_detection.py`

- [ ] **Step 1: Write failing tests**

Create `***REMOVED***/clipping/tests/test_speaker_detection.py` (replaces the existing one or extends it):

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ***REMOVED***.services.media.speaker_detection import (
    DiarizationSegment,
    SpeakerCropResult,
    SpeakerDetectionService,
)


def test_detect_returns_manual_crop_when_all_fields_set():
    service = SpeakerDetectionService()
    with patch("cv2.VideoCapture") as mock_cap:
        mock_instance = MagicMock()
        mock_instance.get.side_effect = [1920, 1080]  # height, width
        mock_cap.return_value = mock_instance
        result = service.detect(
            video_path="fake.mp4",
            start_sec=0.0,
            end_sec=10.0,
            manual_crop_x=200,
            manual_crop_y=0,
            manual_crop_w=400,
            manual_crop_h=800,
        )
    assert result.face_detected is True
    assert result.confidence == 1.0
    assert result.crop_x == 200
    assert result.crop_w == 400


def test_detect_falls_back_to_center_crop_when_no_face():
    service = SpeakerDetectionService()
    with patch.object(service, "detect_faces_for_segment", return_value=[{"timestamp": 0.5, "faces": []}]):
        with patch("cv2.VideoCapture") as mock_cap:
            mock_instance = MagicMock()
            mock_instance.get.side_effect = [1080, 1920]  # width, height
            mock_cap.return_value = mock_instance
            result = service.detect("fake.mp4", 0.0, 10.0)
    assert result.face_detected is False
    assert result.confidence == 0.0


def test_diarization_segment_dataclass():
    seg = DiarizationSegment(speaker_id="SPEAKER_00", start=0.0, end=5.0)
    assert seg.speaker_id == "SPEAKER_00"
    assert seg.start == 0.0


def test_speaker_crop_result_has_speaker_id():
    result = SpeakerCropResult(
        crop_x=0, crop_w=608, crop_h=1080, confidence=0.8, face_detected=True, speaker_id="SPEAKER_00"
    )
    assert result.speaker_id == "SPEAKER_00"
```

Run:
```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_speaker_detection.py -v
```

Expected: FAIL (`DiarizationSegment` not yet defined, `speaker_id` not on `SpeakerCropResult`)

- [ ] **Step 2: Rewrite speaker_detection.py**

Replace `***REMOVED***/services/media/speaker_detection.py` entirely:

```python
from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import numpy as np

logger = logging.getLogger("***REMOVED***.media.speaker_detection")


@dataclass
class SpeakerCropResult:
    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float  # fraction of sampled frames where a face was detected
    face_detected: bool  # False means fell back to center crop
    speaker_id: str | None = None


@dataclass
class DiarizationSegment:
    speaker_id: str
    start: float
    end: float


class SpeakerDetectionService:
    """Speaker detection using MediaPipe face detection + PyAnnote diarization.

    Replaces the legacy OpenCV Haar cascade implementation.
    Lazy-loads models to avoid import-time overhead in workers.
    """

    def __init__(self) -> None:
        self._face_detector = None
        self._diarizer = None

    def _get_face_detector(self):
        if self._face_detector is None:
            import mediapipe as mp
            self._face_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=1,
                min_detection_confidence=0.5,
            )
        return self._face_detector

    def _get_diarizer(self):
        if self._diarizer is None:
            from django.conf import settings
            from pyannote.audio import Pipeline as PyannotePipeline

            self._diarizer = PyannotePipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=settings.HUGGINGFACE_TOKEN,
            )
        return self._diarizer

    def diarize(self, video_path: str | Path) -> list[DiarizationSegment]:
        """Run full speaker diarization on the audio of a video file.

        Extracts audio to a temp WAV, runs PyAnnote, returns segment list.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = tmp.name

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-ac", "1", "-ar", "16000", "-vn", audio_path,
                ],
                check=True,
                capture_output=True,
            )
            diarizer = self._get_diarizer()
            diarization = diarizer(audio_path)
            segments: list[DiarizationSegment] = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(
                    DiarizationSegment(speaker_id=speaker, start=turn.start, end=turn.end)
                )
            return segments
        finally:
            Path(audio_path).unlink(missing_ok=True)

    def detect_faces_for_segment(
        self,
        video_path: str | Path,
        start_sec: float,
        end_sec: float,
        sample_every_n_frames: int = 5,
    ) -> list[dict]:
        """Sample frames in [start_sec, end_sec] and return face bboxes per timestamp."""
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)
        detector = self._get_face_detector()
        results: list[dict] = []

        for frame_num in range(start_frame, end_frame, sample_every_n_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                break
            import cv2 as _cv2
            frame_rgb = _cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB)
            detection = detector.process(frame_rgb)
            timestamp = frame_num / fps
            faces: list[dict] = []
            if detection.detections:
                for d in detection.detections:
                    bbox = d.location_data.relative_bounding_box
                    faces.append(
                        {
                            "x": int(bbox.xmin * frame_width),
                            "y": int(bbox.ymin * frame_height),
                            "w": int(bbox.width * frame_width),
                            "h": int(bbox.height * frame_height),
                            "confidence": float(d.score[0]),
                        }
                    )
            results.append({"timestamp": timestamp, "faces": faces})

        cap.release()
        return results

    def detect(
        self,
        video_path: Path | str,
        start_sec: float,
        end_sec: float,
        manual_crop_x: int | None = None,
        manual_crop_y: int | None = None,
        manual_crop_w: int | None = None,
        manual_crop_h: int | None = None,
    ) -> SpeakerCropResult:
        """Primary method called from TrimAndCropStage for SMART_CROP mode.

        If all manual_crop_* are set, returns those coords directly (operator override).
        Otherwise uses MediaPipe face detection to find the dominant speaker position.
        Falls back to centre crop when no face is detected.
        """
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # Manual crop override — operator sets exact pixel coordinates
        if all(
            v is not None
            for v in [manual_crop_x, manual_crop_y, manual_crop_w, manual_crop_h]
        ):
            return SpeakerCropResult(
                crop_x=int(manual_crop_x),
                crop_w=int(manual_crop_w),
                crop_h=int(manual_crop_h),
                confidence=1.0,
                face_detected=True,
            )

        face_data = self.detect_faces_for_segment(str(video_path), start_sec, end_sec)
        face_centers_x: list[int] = []
        total_samples = len(face_data)
        samples_with_face = 0

        for sample in face_data:
            if sample["faces"]:
                samples_with_face += 1
                best = max(sample["faces"], key=lambda f: f["confidence"])
                face_centers_x.append(best["x"] + best["w"] // 2)

        crop_w = int(frame_height * 9 / 16)

        if not face_centers_x:
            logger.info(
                "No face detected — falling back to center crop",
                extra={"video_path": str(video_path), "total_sampled": total_samples},
            )
            crop_x = max(0, (frame_width - crop_w) // 2)
            return SpeakerCropResult(
                crop_x=crop_x,
                crop_w=crop_w,
                crop_h=frame_height,
                confidence=0.0,
                face_detected=False,
            )

        median_x = int(np.median(face_centers_x))
        crop_x = median_x - crop_w // 2
        crop_x = max(0, min(crop_x, frame_width - crop_w))
        confidence = samples_with_face / total_samples if total_samples > 0 else 0.0

        logger.info(
            "Speaker detected via MediaPipe",
            extra={
                "video_path": str(video_path),
                "median_face_x": median_x,
                "crop_x": crop_x,
                "confidence": confidence,
            },
        )
        return SpeakerCropResult(
            crop_x=crop_x,
            crop_w=crop_w,
            crop_h=frame_height,
            confidence=confidence,
            face_detected=True,
        )
```

- [ ] **Step 3: Run tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_speaker_detection.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/services/media/speaker_detection.py ***REMOVED***/clipping/tests/test_speaker_detection.py
git commit -m "feat(clipping): rewrite SpeakerDetectionService with MediaPipe + PyAnnote"
```

---

## Task 18: Write analysis_helpers.py

**Files:**
- Create: `***REMOVED***/clipping/analysis_helpers.py`

- [ ] **Step 1: Write failing tests**

Create `***REMOVED***/clipping/tests/test_analysis_helpers.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_merge_transcript_with_diarization_assigns_speaker():
    from ***REMOVED***.clipping.analysis_helpers import merge_transcript_with_diarization

    transcript_json = {
        "segments": [
            {
                "words": [
                    {"word": "Hello", "start": 0.1, "end": 0.5, "probability": 0.99},
                    {"word": "world", "start": 0.6, "end": 1.0, "probability": 0.98},
                ]
            }
        ]
    }
    diarization = {
        "segments": [
            {"speaker_id": "SPEAKER_00", "start": 0.0, "end": 2.0}
        ]
    }
    result = merge_transcript_with_diarization(transcript_json, diarization)

    assert len(result) == 2
    assert result[0]["word"] == "Hello"
    assert result[0]["speaker_id"] == "SPEAKER_00"
    assert result[1]["speaker_id"] == "SPEAKER_00"


def test_merge_transcript_unknown_speaker_outside_segments():
    from ***REMOVED***.clipping.analysis_helpers import merge_transcript_with_diarization

    transcript_json = {
        "segments": [
            {"words": [{"word": "Hi", "start": 10.0, "end": 10.5, "probability": 0.9}]}
        ]
    }
    diarization = {"segments": [{"speaker_id": "SPEAKER_00", "start": 0.0, "end": 5.0}]}
    result = merge_transcript_with_diarization(transcript_json, diarization)
    assert result[0]["speaker_id"] == "UNKNOWN"


def test_build_analysis_manifest_schema_version():
    from ***REMOVED***.clipping.analysis_helpers import build_analysis_manifest

    manifest = build_analysis_manifest(
        transcript=[{"word": "test", "start": 0.0, "end": 0.5, "confidence": 1.0, "speaker_id": "SPEAKER_00"}],
        diarization={"segments": [{"speaker_id": "SPEAKER_00", "start": 0.0, "end": 10.0}]},
        face_mappings={},
        scene_cuts=[0.0, 5.0],
        candidates=[],
    )
    assert manifest["schema_version"] == "2.0"
    assert "transcript" in manifest
    assert "speakers" in manifest
    assert "scene_cuts" in manifest
    assert manifest["scene_cuts"] == [0.0, 5.0]


def test_run_scene_detection_returns_list(tmp_path):
    with patch("scenedetect.detect") as mock_detect:
        mock_scene = MagicMock()
        mock_scene.__getitem__ = MagicMock(side_effect=lambda i: MagicMock(get_seconds=lambda: 5.0) if i == 0 else None)
        mock_detect.return_value = [mock_scene]
        from ***REMOVED***.clipping.analysis_helpers import run_scene_detection

        result = run_scene_detection("fake.mp4")
        assert isinstance(result, list)
```

Run:
```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_analysis_helpers.py -v
```

Expected: FAIL

- [ ] **Step 2: Create ***REMOVED***/clipping/analysis_helpers.py**

```python
from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime
from typing import Any

logger = logging.getLogger("***REMOVED***.clipping.analysis")


def run_speaker_diarization(video_path: str) -> dict[str, Any]:
    """Run PyAnnote speaker diarization. Returns dict with 'segments' list."""
    from ***REMOVED***.services.media.speaker_detection import SpeakerDetectionService

    service = SpeakerDetectionService()
    segments = service.diarize(video_path)
    return {
        "segments": [
            {"speaker_id": s.speaker_id, "start": s.start, "end": s.end}
            for s in segments
        ]
    }


def run_scene_detection(video_path: str) -> list[float]:
    """Run PySceneDetect content-aware scene detection.

    Returns a list of scene-cut timestamps in seconds.
    Falls back to empty list if detection fails.
    """
    try:
        from scenedetect import ContentDetector
        from scenedetect import detect

        scenes = detect(video_path, ContentDetector())
        return [scene[0].get_seconds() for scene in scenes]
    except Exception as exc:
        logger.warning(
            "Scene detection failed — continuing without scene cuts",
            extra={"video_path": video_path, "error": str(exc)},
        )
        return []


def run_face_detection_for_speakers(
    video_path: str,
    diarization: dict[str, Any],
) -> dict[str, list[dict]]:
    """Sample faces at key moments per speaker segment.

    Returns {speaker_id: [{"timestamp": float, "bbox": {...}}]} mapping.
    """
    from ***REMOVED***.services.media.speaker_detection import SpeakerDetectionService

    service = SpeakerDetectionService()
    speaker_faces: dict[str, list[dict]] = {}

    for segment in diarization.get("segments", []):
        speaker_id = segment["speaker_id"]
        start = segment["start"]
        end = segment["end"]
        # Sample up to 3 seconds of each segment
        sample_end = min(end, start + 3.0)
        face_data = service.detect_faces_for_segment(video_path, start, sample_end)
        if speaker_id not in speaker_faces:
            speaker_faces[speaker_id] = []
        for frame in face_data:
            if frame["faces"]:
                best = max(frame["faces"], key=lambda f: f["confidence"])
                speaker_faces[speaker_id].append(
                    {
                        "timestamp": frame["timestamp"],
                        "bbox": {
                            "x": best["x"],
                            "y": best["y"],
                            "w": best["w"],
                            "h": best["h"],
                        },
                    }
                )
    return speaker_faces


def _find_speaker_at_time(
    timestamp: float, segments: list[dict[str, Any]]
) -> str:
    """Return the speaker_id whose segment contains timestamp. Returns 'UNKNOWN' if none."""
    for seg in segments:
        if seg["start"] <= timestamp <= seg["end"]:
            return seg["speaker_id"]
    return "UNKNOWN"


def merge_transcript_with_diarization(
    transcript_json: dict[str, Any],
    diarization: dict[str, Any],
) -> list[dict[str, Any]]:
    """Assign speaker_id to each word based on time overlap with diarization segments."""
    words: list[dict[str, Any]] = []
    segments = diarization.get("segments", [])
    for segment in transcript_json.get("segments", []):
        for word_data in segment.get("words", []):
            speaker_id = _find_speaker_at_time(word_data["start"], segments)
            words.append(
                {
                    "word": word_data["word"].strip(),
                    "start": word_data["start"],
                    "end": word_data["end"],
                    "confidence": word_data.get("probability", 1.0),
                    "speaker_id": speaker_id,
                }
            )
    return words


def build_analysis_manifest(
    transcript: list[dict[str, Any]],
    diarization: dict[str, Any],
    face_mappings: dict[str, list[dict]],
    scene_cuts: list[float],
    candidates: list,
) -> dict[str, Any]:
    """Assemble the full analysis_manifest JSON (schema v2.0).

    Args:
        transcript: Word-level transcript with speaker_id from merge_transcript_with_diarization.
        diarization: Raw diarization dict with 'segments' list.
        face_mappings: Speaker → face sample list from run_face_detection_for_speakers.
        scene_cuts: Scene cut timestamps from run_scene_detection.
        candidates: List of ClipCandidate instances from ClipAnalysisService.analyze().
    """
    # Build speaker summaries
    speaker_map: dict[str, dict] = {}
    for seg in diarization.get("segments", []):
        sid = seg["speaker_id"]
        if sid not in speaker_map:
            speaker_map[sid] = {"id": sid, "label": None, "total_talk_time": 0.0, "segments": [], "face_samples": []}
        speaker_map[sid]["total_talk_time"] += seg["end"] - seg["start"]
        speaker_map[sid]["segments"].append({"start": seg["start"], "end": seg["end"]})

    for sid, face_samples in face_mappings.items():
        if sid in speaker_map:
            speaker_map[sid]["face_samples"] = face_samples

    ai_suggestions = []
    for candidate in candidates:
        ai_suggestions.append(
            {
                "start": candidate.start_sec,
                "end": candidate.end_sec,
                "score": candidate.relevance_score,
                "reason": candidate.reason,
                "hook_suggestion": candidate.hook_text,
                "title_suggestion": candidate.title,
                "dominant_speakers": [],
            }
        )

    return {
        "schema_version": "2.0",
        "transcript": transcript,
        "speakers": list(speaker_map.values()),
        "scene_cuts": scene_cuts,
        "ai_clip_suggestions": ai_suggestions,
        "waveform_url": None,
        "thumbnail_strip_url": None,
        "completed_at": datetime.now(UTC).isoformat(),
    }
```

- [ ] **Step 3: Run tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_analysis_helpers.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/analysis_helpers.py ***REMOVED***/clipping/tests/test_analysis_helpers.py
git commit -m "feat(clipping): add analysis_helpers — diarization, scene detection, manifest building"
```

---

## Task 19: Update ClipAnalysisService

**Files:**
- Modify: `***REMOVED***/clipping/services.py`

- [ ] **Step 1: Update ClipAnalysisService.analyze() signature and internals**

In `***REMOVED***/clipping/services.py`, make the following changes:

1. Update `__init__` — no change needed.

2. Replace the `analyze()` method signature and `_system_prompt()` / `_build_prompt()` to accept enriched transcript:

```python
def analyze(
    self,
    enriched_transcript: list[dict] | None = None,
    diarization: dict | None = None,
) -> list[ClipCandidate]:
    transcript = self.job.transcript_text
    prompt = self._build_prompt(transcript, enriched_transcript=enriched_transcript, diarization=diarization)
    llm = get_llm_provider()  # no channel arg — uses DEFAULT_LLM_PROVIDER from settings
    response = llm.complete(prompt=prompt, system=self._system_prompt())
    ...
    # Rest of method unchanged — parsing, candidate creation, cost tracking
```

3. Update `_system_prompt()` to use `social_account` instead of channel:

```python
def _system_prompt(self) -> str:
    platform = self.job.social_account.platform
    account_name = self.job.social_account.username
    return (
        f"You are an expert video editor specialising in short-form content for {platform}. "
        f"You are working on clips for the account @{account_name}. "
        "Identify the most engaging segments that will perform well on this platform. "
        "Return valid JSON only."
    )
```

4. Update `_build_prompt()` to optionally include diarization context:

```python
def _build_prompt(
    self,
    transcript: str,
    enriched_transcript: list[dict] | None = None,
    diarization: dict | None = None,
) -> str:
    lines = [
        f"Source video transcript:\n{transcript}\n",
        f"Number of clips to identify: {self.job.clips_requested}",
    ]
    if diarization and diarization.get("segments"):
        speaker_count = len({s["speaker_id"] for s in diarization["segments"]})
        lines.append(f"\nThis video has {speaker_count} speaker(s).")
    lines.append(
        "\nReturn a JSON array of clip objects with keys: "
        "start_sec, end_sec, title, hook_text, caption_template, relevance_score (1-10), reason."
    )
    return "\n".join(lines)
```

- [ ] **Step 2: Run services tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_services.py -v
```

Expected: All pass (update any `channel` fixtures if needed).

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/services.py
git commit -m "feat(clipping): update ClipAnalysisService to use social_account platform, accept enriched transcript"
```

---

## Task 20: Rewrite analyze_clips task and add SSE to all tasks

**Files:**
- Modify: `***REMOVED***/clipping/tasks.py`

- [ ] **Step 1: Rewrite analyze_clips task**

In `***REMOVED***/clipping/tasks.py`, replace the `analyze_clips` function entirely:

```python
@shared_task(
    bind=True,
    name="***REMOVED***.clipping.analyze_clips",
    max_retries=2,
    default_retry_delay=60,
    queue="clipping",
)
def analyze_clips(self, clipping_job_id: str) -> None:
    try:
        job = ClippingJob.objects.select_related("social_account").get(id=clipping_job_id)
    except ClippingJob.DoesNotExist:
        logger.error("ClippingJob not found for analysis", extra={"id": clipping_job_id})
        return

    try:
        from ***REMOVED***.clipping.analysis_helpers import (
            build_analysis_manifest,
            merge_transcript_with_diarization,
            run_face_detection_for_speakers,
            run_scene_detection,
            run_speaker_diarization,
        )
        from ***REMOVED***.clipping.services import ClipAnalysisService
        from ***REMOVED***.clipping.sse import emit_job_event

        video_path = str(job.downloaded_file.path) if job.downloaded_file else None
        if not video_path:
            raise ValueError("No downloaded file on job")

        # 1. Speaker diarization (may fail gracefully)
        try:
            diarization_result = run_speaker_diarization(video_path)
        except Exception as exc:
            logger.warning(
                "Diarization failed — continuing without speaker data",
                extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            )
            diarization_result = {"segments": []}

        # 2. Scene detection (always graceful)
        scene_cuts = run_scene_detection(video_path)

        # 3. Face detection per speaker segment
        try:
            face_mappings = run_face_detection_for_speakers(video_path, diarization_result)
        except Exception as exc:
            logger.warning(
                "Face detection failed — continuing without face data",
                extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            )
            face_mappings = {}

        # 4. Merge transcript + diarization
        enriched_transcript = merge_transcript_with_diarization(
            job.transcript_json or {}, diarization_result
        )

        # 5. GPT-4o analysis with enriched context
        service = ClipAnalysisService(job)
        candidates = service.analyze(
            enriched_transcript=enriched_transcript,
            diarization=diarization_result,
        )

        # 6. Build and save analysis manifest
        manifest = build_analysis_manifest(
            transcript=enriched_transcript,
            diarization=diarization_result,
            face_mappings=face_mappings,
            scene_cuts=scene_cuts,
            candidates=candidates,
        )
        job.analysis_manifest = manifest

        # 7. Transition — always await approval, no auto-approve
        if can_proceed(job.await_clip_approval):
            job.await_clip_approval()
        job.save(
            update_fields=[
                "status",
                "analysis_manifest",
                "analysis_cost_usd",
                "analysis_provider",
                "updated_at",
            ]
        )

        emit_job_event(
            str(job.id),
            "analysis_complete",
            {"status": job.status, "candidate_count": len(candidates)},
        )

    except Exception as exc:
        logger.error(
            "Clip analysis failed",
            extra={"clipping_job_id": clipping_job_id, "error": str(exc)},
            exc_info=True,
        )
        if self.request.retries >= self.max_retries:
            if can_proceed(job.mark_failed):
                job.mark_failed(error=str(exc))
                job.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
                from ***REMOVED***.clipping.sse import emit_job_event
                emit_job_event(str(job.id), "job_failed", {"error": str(exc), "stage": "analysis"})
            return
        raise self.retry(exc=exc, countdown=2**self.request.retries * 60)
```

- [ ] **Step 2: Add SSE imports and emit calls to all other tasks**

At the top of `tasks.py`, add the SSE import inside each function that transitions state (import inside function avoids circular import at module level):

For **`download_source_video`**, after `job.save(update_fields=["status", "updated_at"])` at the end of the `begin_transcription` block, add:
```python
from ***REMOVED***.clipping.sse import emit_job_event
emit_job_event(str(job.id), "status_changed", {"status": job.status})
```

For **`transcribe_video`**, after `job.save(update_fields=["status", "updated_at"])`, add:
```python
from ***REMOVED***.clipping.sse import emit_job_event
emit_job_event(str(job.id), "status_changed", {"status": job.status})
```

For **`render_clip`**, after the `GatePausedException` catch block, add:
```python
from ***REMOVED***.clipping.sse import emit_job_event
emit_job_event(
    str(candidate.clipping_job_id),
    "render_paused",
    {
        "render_id": str(render.id),
        "candidate_id": str(candidate.id),
        "paused_at_stage": exc.stage_order,
    },
)
```

After `render.save(update_fields=["video_file", "file_size_bytes", "status", "updated_at"])`, add:
```python
from ***REMOVED***.clipping.sse import emit_job_event
emit_job_event(
    str(candidate.clipping_job_id),
    "render_complete",
    {
        "render_id": str(render.id),
        "candidate_id": str(candidate.id),
        "video_url": render.video_file.url if render.video_file else None,
    },
)
```

After the `except Exception` in `render_clip`, add inside the except block before `raise self.retry`:
```python
from ***REMOVED***.clipping.sse import emit_job_event
emit_job_event(
    str(candidate.clipping_job_id),
    "render_failed",
    {"render_id": str(render.id), "candidate_id": str(candidate.id), "error": str(exc)},
)
```

For **`post_clip`**, after `clip_post.save(...)` on success:
```python
from ***REMOVED***.clipping.sse import emit_job_event
emit_job_event(
    str(clip_post.render.candidate.clipping_job_id),
    "post_complete",
    {"post_id": str(clip_post.id), "platform_url": clip_post.platform_url},
)
```

For **`preview_clip_layout`**, after `lc.preview_image.save(...)`:
```python
from ***REMOVED***.clipping.sse import emit_job_event
emit_job_event(
    str(lc.candidate.clipping_job_id),
    "preview_ready",
    {
        "layout_config_id": str(lc.id),
        "preview_url": lc.preview_image.url if lc.preview_image else None,
    },
)
```

Also update the `select_related` calls in tasks that still reference `channel`:
- `transcribe_video`: change `ClippingJob.objects.select_related("channel")` → `ClippingJob.objects.select_related("social_account")`
- `render_clip`: change `ClipCandidate.objects.select_related("clipping_job__channel")` → `ClipCandidate.objects.select_related("clipping_job__social_account")`

In `render_clip`, remove `channel = job.channel` and the `channel=channel` kwarg from `PipelineRenderConfig`. Add `social_account_platform=job.social_account.platform` to `PipelineRenderConfig` instead. Also remove auto-post to `target_accounts`:
```python
# REMOVE this block:
for account in job.target_accounts.filter(is_active=True, should_post=True):
    post = ClipPost.objects.create(render=render, social_account=account)
    post_clip.delay(str(post.id))

# REPLACE with (single social_account on job):
post = ClipPost.objects.create(render=render, social_account=job.social_account)
post_clip.delay(str(post.id))
```

- [ ] **Step 3: Run task tests**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/test_tasks.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/tasks.py
git commit -m "feat(clipping): rewrite analyze_clips with diarization+scene detection, add SSE emit to all tasks"
```

---

## Task 21: Update PipelineRenderConfig and TrimAndCropStage

**Files:**
- Modify: `***REMOVED***/services/media/clip_render_pipeline.py`
- Modify: `***REMOVED***/services/media/render_stages/trim_crop.py`

- [ ] **Step 1: Update PipelineRenderConfig**

In `***REMOVED***/services/media/clip_render_pipeline.py`, update the `PipelineRenderConfig` dataclass:

Remove:
```python
channel: Channel | None = None
```

Add:
```python
social_account_platform: str = "tiktok"
```

Remove the `TYPE_CHECKING` import for `Channel`:
```python
# REMOVE:
if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    ...
```

Keep the `ClipLayoutConfig` and `ClipStyleConfig` type-checking imports.

- [ ] **Step 2: Update TrimAndCropStage._build_smart_crop_command**

In `***REMOVED***/services/media/render_stages/trim_crop.py`, replace `_build_smart_crop_command`:

```python
def _build_smart_crop_command(self, input_path: Path) -> list[str]:
    lc = self.layout_config
    service = SpeakerDetectionService()
    result = service.detect(
        video_path=input_path,
        start_sec=self.start_sec,
        end_sec=self.end_sec,
        manual_crop_x=lc.manual_crop_x if lc is not None else None,
        manual_crop_y=lc.manual_crop_y if lc is not None else None,
        manual_crop_w=lc.manual_crop_w if lc is not None else None,
        manual_crop_h=lc.manual_crop_h if lc is not None else None,
    )
    self.last_speaker_crop_result = result
    crop_x = result.crop_x
    crop_w = result.crop_w
    crop_h = result.crop_h
    vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={self.width}:{self.height},fps={self.fps}"
    return [
        "ffmpeg", "-y",
        "-ss", str(self.start_sec),
        "-to", str(self.end_sec),
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", str(self.crf),
        "-preset", self.preset,
        "-c:a", "aac",
        "-b:a", self.audio_bitrate,
        "-movflags", "faststart",
        str(self.output_path),
    ]
```

The old `if lc is not None and lc.has_manual_smart_crop` guard is no longer needed since `detect()` now handles manual crop internally.

- [ ] **Step 3: Run the full test suite**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/clipping/tests/ -v
```

Expected: All pass.

Also run mypy:
```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run mypy ***REMOVED***/clipping/ ***REMOVED***/services/media/
```

Expected: No new type errors.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/services/media/clip_render_pipeline.py ***REMOVED***/services/media/render_stages/trim_crop.py
git commit -m "feat(clipping): remove channel from PipelineRenderConfig, delegate manual crop to SpeakerDetectionService"
```

---

## Final Verification

- [ ] **Run the complete test suite one last time**

```bash
DATABASE_URL="***REMOVED***://***REMOVED***:***REMOVED***@localhost:5435/***REMOVED***" \
CREDENTIAL_ENCRYPTION_KEY="***REMOVED***" \
uv run pytest ***REMOVED***/ -v --tb=short
```

Expected: All green.

- [ ] **Verify JWT flow end-to-end with the running server**

```bash
# Obtain token
curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@example.com", "password": "yourpassword"}' | python3 -m json.tool

# List jobs with Bearer token
TOKEN="<access token from above>"
curl -s http://localhost:8000/api/v1/clipping/jobs/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: 200 with empty array `[]`.

- [ ] **Verify SSE endpoint responds**

```bash
curl -N http://localhost:8000/api/v1/clipping/jobs/00000000-0000-0000-0000-000000000001/stream/ \
  -H "Authorization: Bearer $TOKEN"
```

Expected: `event: connected\ndata: {}\n\n` then hangs (streaming).
