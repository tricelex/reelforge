# Dashboard Phase B — Clip Config + Render Detail + Review Gates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the clip candidate detail page (visual layout editor, style config panels, preview generation) and the render detail page (10-stage progress, per-stage preview, review gates with pause/resume).

**Architecture:** Phase A's foundation (ui app, base template, HTMX polling) is complete. Phase B adds deep config and render observability views. A small model migration adds `render_gates` (list of gate stage numbers) to `ClipCandidate` and `PAUSED_AT_GATE` + `paused_at_stage` to `ClipRender`. The pipeline is extended with a `GatePausedException` that the render task catches, setting status to PAUSED_AT_GATE instead of retrying. All views use HTMX for in-place updates. The Alpine.js region editor handles drag/resize client-side; source video is assumed 1920×1080 (same as the render pipeline's assumed input).

**Tech Stack:** Django 5.2, HTMX 2.0.4, Alpine.js 3.14, Tailwind CSS (standalone), existing `ClipRenderPipeline` + `preview_clip_layout` task, `render_clip` task (modified).

**Depends on:** Phase A complete (`ui` app, base template, clipping job list + detail, candidate approve/reject).

---

## File Map

```
reelforge/clipping/
  models.py                                    ← add render_gates, PAUSED_AT_GATE, paused_at_stage
  migrations/
    0010_render_gates_and_pause_at_gate.py     ← NEW
  views/
    candidates.py                              ← add candidate_detail, layout/style/preview/gates/overlay views
    renders.py                                 ← NEW: render_detail, stage_list_partial, rerun, resume
  urls.py                                      ← add all new Phase B URL patterns
  templates/clipping/
    candidate_detail.html                      ← NEW: split layout (editor left, config right)
    render_detail.html                         ← NEW: stage list left, preview+gates right
    partials/
      layout_editor.html                       ← HTMX swap target: mode selector + editor panel
      smart_crop_editor.html                   ← Alpine drag box for Smart Crop
      spatial_stack_editor.html                ← Alpine dual drag boxes for Spatial Stack
      center_crop_editor.html                  ← static center indicator
      style_panels.html                        ← collapsible style config form (HTMX auto-save)
      overlay_row.html                         ← single timed overlay (HTMX swap target)
      preview_panel.html                       ← preview image / polling panel
      stage_list.html                          ← HTMX-polled stage pills (self-stopping)
      stage_pill.html                          ← single stage pill row
      gates_panel.html                         ← review gate toggle switches
  tests/
    test_views_phase_b.py                      ← NEW: Phase B view tests

reelforge/services/media/clip_render_pipeline.py  ← add GatePausedException + pause_after_stages
reelforge/clipping/tasks.py                        ← read candidate.render_gates, catch GatePausedException
```

---

## Task 1: Model Changes + Migration

**Files:**
- Modify: `reelforge/clipping/models.py`
- Create: `reelforge/clipping/migrations/0010_render_gates_and_pause_at_gate.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# reelforge/clipping/tests/test_views_phase_b.py
import pytest
from reelforge.clipping.models import ClipCandidate, ClipRender
from reelforge.clipping.tests.factories import ClipCandidateFactory, ClipRenderFactory


def test_clip_candidate_has_render_gates_field() -> None:
    candidate = ClipCandidateFactory()
    assert candidate.render_gates == []
    candidate.render_gates = [1, 3, 5]
    candidate.save(update_fields=["render_gates"])
    candidate.refresh_from_db()
    assert candidate.render_gates == [1, 3, 5]


def test_clip_render_has_paused_at_gate_status() -> None:
    assert "PAUSED_AT_GATE" in ClipRender.RenderStatus.values


def test_clip_render_has_paused_at_stage_field() -> None:
    render = ClipRenderFactory()
    assert render.paused_at_stage is None
    render.paused_at_stage = 3
    render.save(update_fields=["paused_at_stage"])
    render.refresh_from_db()
    assert render.paused_at_stage == 3
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py -v
```

Expected: FAIL on `render_gates` AttributeError and `PAUSED_AT_GATE` not in values.

- [ ] **Step 1.3: Add `render_gates` to `ClipCandidate` and `PAUSED_AT_GATE` + `paused_at_stage` to `ClipRender`**

In `reelforge/clipping/models.py`:

After the `rejection_reason = models.TextField(blank=True)` line in `ClipCandidate` (around line 266), add:

```python
    # Review gates — list of stage order numbers at which the render should pause
    # for operator review. e.g. [1, 3, 5, 8]. Empty list = no gates. null = use channel default.
    render_gates = models.JSONField(default=list, blank=True)
```

In `ClipRender.RenderStatus`, add `PAUSED_AT_GATE` after `FAILED`:

```python
    class RenderStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        PAUSED_AT_GATE = "PAUSED_AT_GATE", "Paused at Gate"
```

After `last_error = models.TextField(blank=True)` in `ClipRender` (around line 350), add:

```python
    paused_at_stage = models.PositiveIntegerField(null=True, blank=True)
```

- [ ] **Step 1.4: Create migration**

```bash
uv run python manage.py makemigrations clipping --name render_gates_and_pause_at_gate
```

Verify the generated migration touches exactly three things:
1. `render_gates` added to `ClipCandidate`
2. `PAUSED_AT_GATE` added to `ClipRender.status` choices
3. `paused_at_stage` added to `ClipRender`

- [ ] **Step 1.5: Run migration**

```bash
uv run python manage.py migrate clipping
```

- [ ] **Step 1.6: Run tests to confirm they pass**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_clip_candidate_has_render_gates_field reelforge/clipping/tests/test_views_phase_b.py::test_clip_render_has_paused_at_gate_status reelforge/clipping/tests/test_views_phase_b.py::test_clip_render_has_paused_at_stage_field -v
```

Expected: PASS.

- [ ] **Step 1.7: Commit**

```bash
git add reelforge/clipping/models.py reelforge/clipping/migrations/0010_render_gates_and_pause_at_gate.py reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(clipping): add render_gates, PAUSED_AT_GATE, paused_at_stage"
```

---

## Task 2: Pipeline Gate Pause Mechanism

**Files:**
- Modify: `reelforge/services/media/clip_render_pipeline.py`
- Modify: `reelforge/clipping/tasks.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `reelforge/clipping/tests/test_views_phase_b.py`:

```python
from unittest.mock import MagicMock, patch


def test_pipeline_raises_gate_paused_when_stage_is_in_gates() -> None:
    """Pipeline raises GatePausedException after a stage whose order is in pause_after_stages."""
    from reelforge.services.media.clip_render_pipeline import (
        ClipRenderPipeline,
        GatePausedException,
        PipelineRenderConfig,
    )
    from pathlib import Path

    config = PipelineRenderConfig(
        source_path=Path("/tmp/test.mp4"),
        output_path=Path("/tmp/out.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        hook_text="hook",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id="test-render-id",
    )
    pipeline = ClipRenderPipeline(config)

    # Patch _run_stage to return the input path without actually running FFmpeg
    with patch.object(pipeline, "_run_stage", side_effect=lambda stage, path: path):
        with pytest.raises(GatePausedException) as exc_info:
            pipeline.run(start_from_stage=1, pause_after_stages={1})

    assert exc_info.value.stage_order == 1


def test_render_clip_task_pauses_at_gate(db) -> None:
    """render_clip task sets PAUSED_AT_GATE status when candidate has render_gates."""
    from reelforge.clipping.tasks import render_clip
    from reelforge.clipping.tests.factories import ClipCandidateFactory

    candidate = ClipCandidateFactory(
        render_gates=[1],
        status=ClipCandidate.CandidateStatus.APPROVED,
    )
    candidate.clipping_job.downloaded_file = "test/file.mp4"
    candidate.clipping_job.save(update_fields=["downloaded_file"])

    with (
        patch("reelforge.clipping.tasks.ClipRenderPipeline") as MockPipeline,
    ):
        from reelforge.services.media.clip_render_pipeline import GatePausedException
        mock_instance = MockPipeline.return_value
        mock_instance.run.side_effect = GatePausedException(stage_order=1)

        render_clip.apply(args=[str(candidate.pk)])

    render = candidate.renders.get()
    assert render.status == ClipRender.RenderStatus.PAUSED_AT_GATE
    assert render.paused_at_stage == 1
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_pipeline_raises_gate_paused_when_stage_is_in_gates reelforge/clipping/tests/test_views_phase_b.py::test_render_clip_task_pauses_at_gate -v
```

Expected: FAIL — `GatePausedException` does not exist yet.

- [ ] **Step 2.3: Add `GatePausedException` and modify `ClipRenderPipeline.run()`**

In `reelforge/services/media/clip_render_pipeline.py`:

After the `logger = ...` line at the top, add the exception class:

```python
class GatePausedException(Exception):
    """Raised by ClipRenderPipeline when a gate stage completes and a pause is required."""

    def __init__(self, stage_order: int) -> None:
        self.stage_order = stage_order
        super().__init__(f"Render paused at gate after stage {stage_order}")
```

Modify the `run()` signature and add gate check at the end of the stage loop:

```python
    def run(
        self,
        start_from_stage: int = 1,
        pause_after_stages: set[int] | None = None,
    ) -> Path:
        """Run the pipeline, optionally resuming from a specific stage.

        pause_after_stages: stage order numbers at which to pause after
        the stage completes. Raises GatePausedException instead of continuing.
        Returns config.output_path when fully complete.
        """
        stages = self._build_stages()
        self._stages = stages
        current_path = self.config.source_path

        if start_from_stage > 1:
            try:
                prev_result = ClipRenderStageResult.objects.get(
                    render_id=self.config.render_id,
                    stage_order=start_from_stage - 1,
                )
                if prev_result.output_file:
                    current_path = Path(settings.MEDIA_ROOT) / prev_result.output_file.name
            except ClipRenderStageResult.DoesNotExist:
                logger.warning(
                    "Previous stage result not found — starting from source",
                    extra={
                        "render_id": self.config.render_id,
                        "start_from_stage": start_from_stage,
                    },
                )
            ClipRenderStageResult.objects.filter(
                render_id=self.config.render_id,
                stage_order__gte=start_from_stage,
            ).delete()

        _gates = pause_after_stages or set()

        for stage in stages:
            if stage.order < start_from_stage:
                continue
            current_path = self._run_stage(stage, current_path)
            if stage.order in _gates:
                raise GatePausedException(stage_order=stage.order)

        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(current_path), str(self.config.output_path))
        logger.info(
            "ClipRenderPipeline completed",
            extra={"render_id": self.config.render_id, "output": str(self.config.output_path)},
        )
        return self.config.output_path
```

- [ ] **Step 2.4: Update `render_clip` task to read gates and catch `GatePausedException`**

In `reelforge/clipping/tasks.py`, add the import at the top:

```python
from reelforge.services.media.clip_render_pipeline import GatePausedException
```

In the `render_clip` task, replace the `pipeline.run(start_from_stage=start_from_stage)` call and its surrounding try/except block:

```python
        gate_stages = set(candidate.render_gates or [])

        try:
            pipeline = ClipRenderPipeline(pipeline_config)
            pipeline.run(
                start_from_stage=start_from_stage,
                pause_after_stages=gate_stages,
            )

        except GatePausedException as exc:
            render.status = ClipRender.RenderStatus.PAUSED_AT_GATE
            render.paused_at_stage = exc.stage_order
            render.save(update_fields=["status", "paused_at_stage", "updated_at"])
            logger.info(
                "Render paused at gate",
                extra={
                    "render_id": str(render.id),
                    "candidate_id": str(candidate.id),
                    "paused_at_stage": exc.stage_order,
                },
            )
            return  # Do not retry — this is an intentional pause

        # Write back speaker detection results (existing code unchanged)
        trim_stage = next((s for s in pipeline._stages if s.name == "trim_and_crop"), None)
        if (
            layout_config is not None
            and trim_stage is not None
            and hasattr(trim_stage, "last_speaker_crop_result")
            and trim_stage.last_speaker_crop_result is not None
        ):
            layout_config.face_detected = trim_stage.last_speaker_crop_result.face_detected
            layout_config.detection_confidence = trim_stage.last_speaker_crop_result.confidence
            layout_config.save(update_fields=["face_detected", "detection_confidence", "updated_at"])

        render.video_file = str(output_path.relative_to(settings.MEDIA_ROOT))
        render.file_size_bytes = output_path.stat().st_size
        render.status = ClipRender.RenderStatus.COMPLETED
        render.save(update_fields=["video_file", "file_size_bytes", "status", "updated_at"])

        candidate.status = ClipCandidate.CandidateStatus.RENDERED
        candidate.save(update_fields=["status", "updated_at"])

        for account in job.target_accounts.filter(is_active=True, should_post=True):
            post = ClipPost.objects.create(render=render, social_account=account)
            post_clip.delay(str(post.id))
```

Note: the outer `except Exception as exc` block that retries must remain after the above — move it to wrap only the post-pipeline cleanup code. The full try structure becomes:

```python
    try:
        # ... pipeline setup (existing) ...

        gate_stages = set(candidate.render_gates or [])

        try:
            pipeline = ClipRenderPipeline(pipeline_config)
            pipeline.run(start_from_stage=start_from_stage, pause_after_stages=gate_stages)
        except GatePausedException as exc:
            render.status = ClipRender.RenderStatus.PAUSED_AT_GATE
            render.paused_at_stage = exc.stage_order
            render.save(update_fields=["status", "paused_at_stage", "updated_at"])
            logger.info("Render paused at gate", extra={"render_id": str(render.id), "paused_at_stage": exc.stage_order})
            return

        # Write-back detection results (existing code)
        trim_stage = next((s for s in pipeline._stages if s.name == "trim_and_crop"), None)
        if layout_config is not None and trim_stage is not None and hasattr(trim_stage, "last_speaker_crop_result") and trim_stage.last_speaker_crop_result is not None:
            layout_config.face_detected = trim_stage.last_speaker_crop_result.face_detected
            layout_config.detection_confidence = trim_stage.last_speaker_crop_result.confidence
            layout_config.save(update_fields=["face_detected", "detection_confidence", "updated_at"])

        render.video_file = str(output_path.relative_to(settings.MEDIA_ROOT))
        render.file_size_bytes = output_path.stat().st_size
        render.status = ClipRender.RenderStatus.COMPLETED
        render.save(update_fields=["video_file", "file_size_bytes", "status", "updated_at"])

        candidate.status = ClipCandidate.CandidateStatus.RENDERED
        candidate.save(update_fields=["status", "updated_at"])

        for account in job.target_accounts.filter(is_active=True, should_post=True):
            post = ClipPost.objects.create(render=render, social_account=account)
            post_clip.delay(str(post.id))

    except Exception as exc:
        render.status = ClipRender.RenderStatus.FAILED
        render.last_error = str(exc)
        render.save(update_fields=["status", "last_error", "updated_at"])
        raise self.retry(exc=exc, countdown=2**self.request.retries * 300)
```

- [ ] **Step 2.5: Run tests**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_pipeline_raises_gate_paused_when_stage_is_in_gates reelforge/clipping/tests/test_views_phase_b.py::test_render_clip_task_pauses_at_gate -v
```

Expected: PASS.

- [ ] **Step 2.6: Run the full clipping test suite to check for regressions**

```bash
uv run pytest reelforge/clipping/tests/ -v
```

Expected: All existing tests still pass.

- [ ] **Step 2.7: Commit**

```bash
git add reelforge/services/media/clip_render_pipeline.py reelforge/clipping/tasks.py reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(clipping): add render gate pause mechanism to pipeline + task"
```

---

## Task 3: Candidate Detail View + Template

**Files:**
- Modify: `reelforge/clipping/views/candidates.py`
- Modify: `reelforge/clipping/urls.py`
- Create: `reelforge/clipping/templates/clipping/candidate_detail.html`

- [ ] **Step 3.1: Write the failing test**

Append to `reelforge/clipping/tests/test_views_phase_b.py`:

```python
from django.test import Client
from django.urls import reverse
from reelforge.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_candidate_detail_view_returns_200(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    url = reverse("clipping:candidate_detail", kwargs={"candidate_id": candidate.pk})
    response = client.get(url)
    assert response.status_code == 200
    assert b"candidate_detail" in response.content or response.template_name is not None


@pytest.mark.django_db
def test_candidate_detail_requires_staff(client: Client) -> None:
    user = UserFactory(is_staff=False)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    url = reverse("clipping:candidate_detail", kwargs={"candidate_id": candidate.pk})
    response = client.get(url)
    assert response.status_code == 302  # redirected to login
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_candidate_detail_view_returns_200 reelforge/clipping/tests/test_views_phase_b.py::test_candidate_detail_requires_staff -v
```

Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 3.3: Add `candidate_detail` view to `candidates.py`**

In `reelforge/clipping/views/candidates.py`, add this view (after existing views):

```python
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from reelforge.clipping.models import (
    ClipCandidate,
    ClipLayoutConfig,
    ClipRenderStyleMixin,
    ClipStyleConfig,
    ClipTimedOverlay,
)


@staff_member_required
def candidate_detail(request: HttpRequest, candidate_id: str) -> HttpResponse:
    candidate = get_object_or_404(
        ClipCandidate.objects.select_related(
            "clipping_job__channel__clip_render_template",
            "layout_config",
            "style_config",
        ).prefetch_related("timed_overlays"),
        pk=candidate_id,
    )
    layout = getattr(candidate, "layout_config", None)
    style = getattr(candidate, "style_config", None)
    channel_template = getattr(candidate.clipping_job.channel, "clip_render_template", None)

    renders = candidate.renders.prefetch_related("stage_results").order_by("-created_at")

    return render(
        request,
        "clipping/candidate_detail.html",
        {
            "candidate": candidate,
            "job": candidate.clipping_job,
            "layout": layout,
            "style": style,
            "channel_template": channel_template,
            "renders": renders,
            "timed_overlays": list(candidate.timed_overlays.all()),
        },
    )
```

- [ ] **Step 3.4: Register the URL**

In `reelforge/clipping/urls.py`, add to `urlpatterns`:

```python
path("clips/<uuid:candidate_id>/", views_candidates.candidate_detail, name="candidate_detail"),
```

- [ ] **Step 3.5: Create `candidate_detail.html`**

Create `reelforge/clipping/templates/clipping/candidate_detail.html`:

```html
{% extends "ui/base.html" %}
{% load static %}

{% block title %}{{ candidate.title }} — Clip Config{% endblock %}

{% block content %}
<div class="flex items-center gap-3 mb-6">
  <a href="{% url 'clipping:job_detail' candidate.clipping_job.pk %}"
     class="text-slate-400 hover:text-white text-sm">← {{ job.title|truncatechars:40 }}</a>
  <span class="text-slate-600">/</span>
  <h1 class="text-lg font-semibold text-white truncate">{{ candidate.title }}</h1>
</div>

<div class="grid grid-cols-2 gap-6">

  {# ── Left column: layout editor ── #}
  <div class="space-y-4">
    <div id="layout-editor-panel">
      {% include "clipping/partials/layout_editor.html" %}
    </div>
  </div>

  {# ── Right column: style config + overlays + gates ── #}
  <div class="space-y-4">

    {# Renders list + link to render detail #}
    {% if renders %}
    <div class="bg-slate-800 rounded-lg p-4">
      <h3 class="text-sm font-semibold text-slate-300 mb-3">Renders</h3>
      {% for render in renders %}
      <div class="flex items-center justify-between py-2 border-b border-slate-700 last:border-0">
        <div class="flex items-center gap-2">
          <span class="text-xs px-2 py-0.5 rounded
            {% if render.status == 'COMPLETED' %}bg-green-900 text-green-300
            {% elif render.status == 'RUNNING' %}bg-indigo-900 text-indigo-300
            {% elif render.status == 'PAUSED_AT_GATE' %}bg-amber-900 text-amber-300
            {% elif render.status == 'FAILED' %}bg-red-900 text-red-300
            {% else %}bg-slate-700 text-slate-400{% endif %}">
            {{ render.get_status_display }}
          </span>
          <span class="text-xs text-slate-400">{{ render.get_format_display }}</span>
          {% if render.render_duration_sec %}
          <span class="text-xs text-slate-500">{{ render.render_duration_sec|floatformat:0 }}s</span>
          {% endif %}
        </div>
        <a href="{% url 'clipping:render_detail' render.pk %}"
           class="text-xs text-indigo-400 hover:text-indigo-300">View stages →</a>
      </div>
      {% endfor %}
    </div>
    {% endif %}

    {# Style config panels #}
    <div id="style-config-panel">
      {% include "clipping/partials/style_panels.html" %}
    </div>

    {# Timed overlays #}
    <div class="bg-slate-800 rounded-lg p-4">
      <h3 class="text-sm font-semibold text-slate-300 mb-3">Timed Overlays</h3>
      <div id="overlays-list" class="space-y-2">
        {% for overlay in timed_overlays %}
          {% include "clipping/partials/overlay_row.html" with overlay=overlay %}
        {% empty %}
          <p class="text-xs text-slate-500">No timed overlays.</p>
        {% endfor %}
      </div>
      <button class="mt-3 text-xs text-indigo-400 hover:text-indigo-300"
              hx-post="{% url 'clipping:add_overlay' candidate.pk %}"
              hx-target="#overlays-list"
              hx-swap="beforeend">
        + Add Overlay
      </button>
    </div>

    {# Review gates #}
    <div id="gates-panel">
      {% include "clipping/partials/gates_panel.html" %}
    </div>

  </div>
</div>
{% endblock %}
```

- [ ] **Step 3.6: Run tests**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_candidate_detail_view_returns_200 reelforge/clipping/tests/test_views_phase_b.py::test_candidate_detail_requires_staff -v
```

Expected: PASS.

- [ ] **Step 3.7: Commit**

```bash
git add reelforge/clipping/views/candidates.py reelforge/clipping/urls.py reelforge/clipping/templates/clipping/candidate_detail.html reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(dashboard): add candidate detail view and base template"
```

---

## Task 4: Visual Layout Editor (Alpine.js Drag+Resize)

**Files:**
- Modify: `reelforge/clipping/views/candidates.py`
- Modify: `reelforge/clipping/urls.py`
- Create: `reelforge/clipping/templates/clipping/partials/layout_editor.html`
- Create: `reelforge/clipping/templates/clipping/partials/smart_crop_editor.html`
- Create: `reelforge/clipping/templates/clipping/partials/spatial_stack_editor.html`
- Create: `reelforge/clipping/templates/clipping/partials/center_crop_editor.html`

- [ ] **Step 4.1: Write failing tests**

Append to `reelforge/clipping/tests/test_views_phase_b.py`:

```python
@pytest.mark.django_db
def test_update_layout_config_saves_render_mode(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    from reelforge.clipping.models import ClipLayoutConfig, ClipRenderMode
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    url = reverse("clipping:update_layout_config", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {"render_mode": ClipRenderMode.SPATIAL_STACK})
    assert response.status_code == 200
    layout.refresh_from_db()
    assert layout.render_mode == ClipRenderMode.SPATIAL_STACK


@pytest.mark.django_db
def test_update_layout_regions_saves_crop_coords(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    from reelforge.clipping.models import ClipLayoutConfig
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    url = reverse("clipping:update_layout_regions", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {
        "manual_crop_x": "100", "manual_crop_y": "50",
        "manual_crop_w": "900", "manual_crop_h": "1600",
    })
    assert response.status_code == 200
    layout.refresh_from_db()
    assert layout.manual_crop_x == 100
    assert layout.manual_crop_y == 50


@pytest.mark.django_db
def test_reset_smart_crop_clears_manual_coords(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    from reelforge.clipping.models import ClipLayoutConfig
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    layout.manual_crop_x = 100
    layout.manual_crop_y = 100
    layout.manual_crop_w = 500
    layout.manual_crop_h = 900
    layout.save(update_fields=["manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h"])
    url = reverse("clipping:reset_smart_crop", kwargs={"candidate_id": candidate.pk})
    response = client.post(url)
    assert response.status_code == 200
    layout.refresh_from_db()
    assert layout.manual_crop_x is None
    assert layout.manual_crop_w is None
```

- [ ] **Step 4.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_update_layout_config_saves_render_mode reelforge/clipping/tests/test_views_phase_b.py::test_update_layout_regions_saves_crop_coords reelforge/clipping/tests/test_views_phase_b.py::test_reset_smart_crop_clears_manual_coords -v
```

Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 4.3: Add layout views to `candidates.py`**

```python
from django.views.decorators.http import require_POST
from reelforge.clipping.models import ClipLayoutConfig, ClipRenderMode


@staff_member_required
@require_POST
def update_layout_config(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Save render_mode and/or render_format; return the swapped layout editor partial."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    layout, _ = ClipLayoutConfig.objects.get_or_create(candidate=candidate)

    update_fields: list[str] = ["updated_at"]

    if "render_mode" in request.POST:
        layout.render_mode = request.POST["render_mode"]
        update_fields.append("render_mode")

    if "render_format" in request.POST:
        layout.render_format = request.POST["render_format"]
        update_fields.append("render_format")

    layout.save(update_fields=update_fields)

    return render(
        request,
        "clipping/partials/layout_editor.html",
        {"candidate": candidate, "layout": layout},
    )


@staff_member_required
@require_POST
def update_layout_regions(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Save drag-editor coordinate fields. Returns 200 with no body (hx-swap='none')."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    layout, _ = ClipLayoutConfig.objects.get_or_create(candidate=candidate)

    coord_fields = [
        "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h",
        "region_a_x", "region_a_y", "region_a_w", "region_a_h",
        "region_b_x", "region_b_y", "region_b_w", "region_b_h",
    ]
    update_fields: list[str] = ["updated_at"]

    for field in coord_fields:
        if field in request.POST and request.POST[field] != "":
            try:
                setattr(layout, field, int(request.POST[field]))
                update_fields.append(field)
            except (ValueError, TypeError):
                pass

    if "stack_ratio" in request.POST:
        try:
            val = float(request.POST["stack_ratio"])
            if 0.3 <= val <= 0.8:
                layout.stack_ratio = val
                update_fields.append("stack_ratio")
        except (ValueError, TypeError):
            pass

    layout.save(update_fields=update_fields)
    return HttpResponse(status=200)


@staff_member_required
@require_POST
def reset_smart_crop(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Clear manual Smart Crop coordinates; return refreshed layout editor partial."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    layout = get_object_or_404(ClipLayoutConfig, candidate=candidate)
    layout.manual_crop_x = None
    layout.manual_crop_y = None
    layout.manual_crop_w = None
    layout.manual_crop_h = None
    layout.save(update_fields=["manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at"])
    return render(
        request,
        "clipping/partials/layout_editor.html",
        {"candidate": candidate, "layout": layout},
    )
```

- [ ] **Step 4.4: Register the new URLs**

In `reelforge/clipping/urls.py`, add:

```python
path("clips/<uuid:candidate_id>/layout/", views_candidates.update_layout_config, name="update_layout_config"),
path("clips/<uuid:candidate_id>/layout/regions/", views_candidates.update_layout_regions, name="update_layout_regions"),
path("clips/<uuid:candidate_id>/layout/reset-crop/", views_candidates.reset_smart_crop, name="reset_smart_crop"),
```

- [ ] **Step 4.5: Create `layout_editor.html`**

Create `reelforge/clipping/templates/clipping/partials/layout_editor.html`:

```html
{# Swap target: id="layout-editor-panel" on candidate_detail.html #}
<div id="layout-editor-panel">

  {# Render mode + format selectors #}
  <div class="bg-slate-800 rounded-lg p-4 mb-4">
    <h3 class="text-sm font-semibold text-slate-300 mb-3">Render Mode</h3>
    <div class="grid grid-cols-3 gap-2 mb-4">
      {% for mode_value, mode_label in layout.RenderMode.choices %}
      <button
        hx-post="{% url 'clipping:update_layout_config' candidate.pk %}"
        hx-vals='{"render_mode": "{{ mode_value }}"}'
        hx-target="#layout-editor-panel"
        hx-swap="outerHTML"
        class="py-2 px-3 rounded text-sm border transition
          {% if layout.render_mode == mode_value %}
            border-indigo-500 bg-indigo-900/40 text-indigo-300
          {% else %}
            border-slate-600 bg-slate-700 text-slate-400 hover:border-slate-500
          {% endif %}">
        {{ mode_label }}
      </button>
      {% endfor %}
    </div>

    <div class="flex items-center gap-3">
      <label class="text-xs text-slate-400">Output Format</label>
      <select name="render_format"
              hx-post="{% url 'clipping:update_layout_config' candidate.pk %}"
              hx-include="[name='render_format']"
              hx-target="#layout-editor-panel"
              hx-swap="outerHTML"
              class="bg-slate-700 border border-slate-600 text-slate-200 text-xs rounded px-2 py-1">
        {% for fmt_value, fmt_label in layout.render_format|field_choices:"render_format" %}
        <option value="{{ fmt_value }}" {% if layout.render_format == fmt_value %}selected{% endif %}>
          {{ fmt_label }}
        </option>
        {% endfor %}
      </select>
    </div>
  </div>

  {# Visual editor — swapped based on render mode #}
  <div class="bg-slate-800 rounded-lg p-4">
    {% if layout.render_mode == 'SMART_CROP' %}
      {% include "clipping/partials/smart_crop_editor.html" %}
    {% elif layout.render_mode == 'SPATIAL_STACK' %}
      {% include "clipping/partials/spatial_stack_editor.html" %}
    {% else %}
      {% include "clipping/partials/center_crop_editor.html" %}
    {% endif %}
  </div>

  {# Preview panel #}
  <div class="bg-slate-800 rounded-lg p-4 mt-4">
    <h3 class="text-sm font-semibold text-slate-300 mb-3">9:16 Output Preview</h3>
    <div id="preview-panel">
      {% include "clipping/partials/preview_panel.html" %}
    </div>
  </div>

</div>
```

Note: The `field_choices` template tag doesn't exist. Replace the format dropdown with a hardcoded approach:

```html
      <select name="render_format"
              hx-post="{% url 'clipping:update_layout_config' candidate.pk %}"
              hx-target="#layout-editor-panel"
              hx-swap="outerHTML"
              class="bg-slate-700 border border-slate-600 text-slate-200 text-xs rounded px-2 py-1">
        <option value="VERTICAL_9_16" {% if layout.render_format == 'VERTICAL_9_16' %}selected{% endif %}>Vertical 9:16</option>
        <option value="LANDSCAPE_16_9" {% if layout.render_format == 'LANDSCAPE_16_9' %}selected{% endif %}>Landscape 16:9</option>
        <option value="SQUARE_1_1" {% if layout.render_format == 'SQUARE_1_1' %}selected{% endif %}>Square 1:1</option>
      </select>
```

- [ ] **Step 4.6: Create `smart_crop_editor.html`**

Create `reelforge/clipping/templates/clipping/partials/smart_crop_editor.html`:

```html
{% comment %}Alpine.js drag editor for Smart Crop mode. Source assumed 1920×1080.{% endcomment %}
<div
  x-data="regionEditor({
    mode: 'smart',
    cx: {{ layout.manual_crop_x|default:'null' }},
    cy: {{ layout.manual_crop_y|default:'null' }},
    cw: {{ layout.manual_crop_w|default:'null' }},
    ch: {{ layout.manual_crop_h|default:'null' }}
  })"
  @mousemove.window="onMouseMove($event)"
  @mouseup.window="stopDrag()"
  class="relative select-none"
>
  <h3 class="text-sm font-semibold text-slate-300 mb-2">Smart Crop Region</h3>
  {% if layout.face_detected is not None %}
  <p class="text-xs text-slate-400 mb-2">
    Face detection:
    {% if layout.face_detected %}
      <span class="text-green-400">detected</span>
      {% if layout.detection_confidence %}({{ layout.detection_confidence|floatformat:2 }}){% endif %}
    {% else %}
      <span class="text-amber-400">not detected</span>
    {% endif %}
  </p>
  {% endif %}

  {# 16:9 source frame container #}
  <div class="relative w-full bg-slate-900 rounded overflow-hidden" style="padding-top: 56.25%">
    {# Absolute container for overlay boxes #}
    <div class="absolute inset-0">
      {# Crop region box — shown only when manual crop is set or being dragged #}
      <template x-if="crop.x !== null">
        <div
          class="absolute border-2 border-indigo-500 cursor-move"
          :style="cropBoxStyle"
          @mousedown.prevent="startDrag($event, 'crop', 'move')"
        >
          {# Resize handle bottom-right #}
          <div
            class="absolute bottom-0 right-0 w-3 h-3 bg-indigo-500 cursor-se-resize"
            @mousedown.prevent.stop="startDrag($event, 'crop', 'resize')"
          ></div>
          {# Label #}
          <span class="absolute top-1 left-1 text-xs bg-indigo-500/80 px-1 rounded text-white leading-none">Crop</span>
        </div>
      </template>
      {# "Click to set" hint when no crop is set #}
      <template x-if="crop.x === null">
        <div class="absolute inset-0 flex items-center justify-center">
          <button
            class="text-xs text-slate-400 border border-dashed border-slate-600 px-3 py-2 rounded hover:border-indigo-500 hover:text-indigo-400"
            @click="initCrop()"
          >Click to set crop region</button>
        </div>
      </template>
    </div>
  </div>

  {# Coordinate inputs for manual entry #}
  <div x-show="crop.x !== null" class="grid grid-cols-4 gap-2 mt-3 text-xs">
    <div><label class="text-slate-400 block mb-1">X</label>
      <input type="number" x-model.number="crop.x" @change="saveRegions()"
             class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
    <div><label class="text-slate-400 block mb-1">Y</label>
      <input type="number" x-model.number="crop.y" @change="saveRegions()"
             class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
    <div><label class="text-slate-400 block mb-1">W</label>
      <input type="number" x-model.number="crop.w" @change="saveRegions()"
             class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
    <div><label class="text-slate-400 block mb-1">H</label>
      <input type="number" x-model.number="crop.h" @change="saveRegions()"
             class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
  </div>

  <button x-show="crop.x !== null"
          class="mt-2 text-xs text-slate-400 hover:text-red-400"
          hx-post="{% url 'clipping:reset_smart_crop' candidate.pk %}"
          hx-target="#layout-editor-panel"
          hx-swap="outerHTML">
    ↺ Reset to auto-detect
  </button>

  {# Hidden form for saving coords via HTMX #}
  <form x-ref="saveForm"
        hx-post="{% url 'clipping:update_layout_regions' candidate.pk %}"
        hx-swap="none"
        class="hidden">
    {% csrf_token %}
    <input type="hidden" name="manual_crop_x" :value="crop.x ?? ''">
    <input type="hidden" name="manual_crop_y" :value="crop.y ?? ''">
    <input type="hidden" name="manual_crop_w" :value="crop.w ?? ''">
    <input type="hidden" name="manual_crop_h" :value="crop.h ?? ''">
  </form>
</div>

<script>
{% if not regionEditorDefined %}
function regionEditor(config) {
  const SOURCE_W = 1920;
  const SOURCE_H = 1080;

  function clamp(val, min, max) { return Math.max(min, Math.min(max, val)); }

  function toPct(val, total) { return (val / total * 100).toFixed(4) + '%'; }

  function toVideoX(pct, containerW) { return Math.round(pct * SOURCE_W); }
  function toVideoY(pct, containerH) { return Math.round(pct * SOURCE_H); }

  return {
    SOURCE_W, SOURCE_H,

    crop: {
      x: config.cx,
      y: config.cy,
      w: config.cw ?? 540,
      h: config.ch ?? 960,
    },

    regions: {
      a: { x: 240, y: 0, w: 1440, h: 540 },
      b: { x: 240, y: 540, w: 1440, h: 540 },
    },

    stackRatio: config.stackRatio ?? 0.6,

    dragging: null,
    _saveTimer: null,

    get cropBoxStyle() {
      if (this.crop.x === null) return '';
      return [
        `left:${toPct(this.crop.x, SOURCE_W)}`,
        `top:${toPct(this.crop.y, SOURCE_H)}`,
        `width:${toPct(this.crop.w, SOURCE_W)}`,
        `height:${toPct(this.crop.h, SOURCE_H)}`,
      ].join(';');
    },

    get regionAStyle() {
      const r = this.regions.a;
      return `left:${toPct(r.x,SOURCE_W)};top:${toPct(r.y,SOURCE_H)};width:${toPct(r.w,SOURCE_W)};height:${toPct(r.h,SOURCE_H)}`;
    },

    get regionBStyle() {
      const r = this.regions.b;
      return `left:${toPct(r.x,SOURCE_W)};top:${toPct(r.y,SOURCE_H)};width:${toPct(r.w,SOURCE_W)};height:${toPct(r.h,SOURCE_H)}`;
    },

    initCrop() {
      this.crop = { x: 240, y: 0, w: 540, h: 960 };
    },

    startDrag(event, region, type) {
      const container = this.$el.querySelector('[style*="padding-top"]');
      const rect = container.getBoundingClientRect();
      const target = region === 'crop' ? this.crop : this.regions[region];
      this.dragging = {
        region, type,
        startX: event.clientX, startY: event.clientY,
        containerW: rect.width, containerH: rect.height,
        origX: target.x, origY: target.y,
        origW: target.w, origH: target.h,
      };
    },

    onMouseMove(event) {
      if (!this.dragging) return;
      const d = this.dragging;
      const dx = (event.clientX - d.startX) / d.containerW * SOURCE_W;
      const dy = (event.clientY - d.startY) / d.containerH * SOURCE_H;
      const target = d.region === 'crop' ? this.crop : this.regions[d.region];

      if (d.type === 'move') {
        target.x = Math.round(clamp(d.origX + dx, 0, SOURCE_W - d.origW));
        target.y = Math.round(clamp(d.origY + dy, 0, SOURCE_H - d.origH));
      } else if (d.type === 'resize') {
        target.w = Math.round(clamp(d.origW + dx, 80, SOURCE_W - d.origX));
        target.h = Math.round(clamp(d.origH + dy, 80, SOURCE_H - d.origY));
      }
    },

    stopDrag() {
      if (!this.dragging) return;
      this.dragging = null;
      this.saveRegions();
    },

    saveRegions() {
      clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => {
        const form = this.$refs.saveForm;
        if (form) htmx.trigger(form, 'submit');
      }, 300);
    },
  };
}
{% endif %}
</script>
```

Note: The `{% if not regionEditorDefined %}` guard won't work as-is in Django templates. Remove the conditional and just include the script once — if multiple editors could appear on one page, move the JS to a static file instead. For this page, only one editor is shown at a time.

Replace with a simple `<script>` block without the guard.

- [ ] **Step 4.7: Create `spatial_stack_editor.html`**

Create `reelforge/clipping/templates/clipping/partials/spatial_stack_editor.html`:

```html
{% comment %}Alpine.js dual drag editor for Spatial Stack mode.{% endcomment %}
<div
  x-data="regionEditor({
    mode: 'stack',
    ax: {{ layout.region_a_x|default:'240' }},
    ay: {{ layout.region_a_y|default:'0' }},
    aw: {{ layout.region_a_w|default:'1440' }},
    ah: {{ layout.region_a_h|default:'540' }},
    bx: {{ layout.region_b_x|default:'240' }},
    by: {{ layout.region_b_y|default:'540' }},
    bw: {{ layout.region_b_w|default:'1440' }},
    bh: {{ layout.region_b_h|default:'540' }},
    stackRatio: {{ layout.stack_ratio|default:'0.6' }}
  })"
  @mousemove.window="onMouseMove($event)"
  @mouseup.window="stopDrag()"
  class="relative select-none"
>
  <h3 class="text-sm font-semibold text-slate-300 mb-2">Spatial Stack Regions</h3>

  {# 16:9 source frame #}
  <div class="relative w-full bg-slate-900 rounded overflow-hidden" style="padding-top: 56.25%">
    <div class="absolute inset-0">
      {# Region A (indigo) #}
      <div class="absolute border-2 border-indigo-500 cursor-move"
           :style="regionAStyle"
           @mousedown.prevent="startDrag($event, 'a', 'move')">
        <div class="absolute bottom-0 right-0 w-3 h-3 bg-indigo-500 cursor-se-resize"
             @mousedown.prevent.stop="startDrag($event, 'a', 'resize')"></div>
        <span class="absolute top-1 left-1 text-xs bg-indigo-500/80 px-1 rounded text-white leading-none">A</span>
      </div>
      {# Region B (cyan) #}
      <div class="absolute border-2 border-cyan-500 cursor-move"
           :style="regionBStyle"
           @mousedown.prevent="startDrag($event, 'b', 'move')">
        <div class="absolute bottom-0 right-0 w-3 h-3 bg-cyan-500 cursor-se-resize"
             @mousedown.prevent.stop="startDrag($event, 'b', 'resize')"></div>
        <span class="absolute top-1 left-1 text-xs bg-cyan-500/80 px-1 rounded text-white leading-none">B</span>
      </div>
    </div>
  </div>

  {# Stack ratio slider #}
  <div class="mt-3">
    <label class="text-xs text-slate-400 flex justify-between">
      <span>Stack ratio (A:B)</span>
      <span x-text="stackRatio.toFixed(2)"></span>
    </label>
    <input type="range" min="0.3" max="0.8" step="0.05"
           x-model.number="stackRatio"
           @change="saveRegions()"
           class="w-full mt-1">
  </div>

  {# Region A coords #}
  <div class="mt-3">
    <p class="text-xs text-indigo-400 mb-1 font-medium">Region A</p>
    <div class="grid grid-cols-4 gap-2 text-xs">
      <div><label class="text-slate-400 block mb-1">X</label>
        <input type="number" x-model.number="regions.a.x" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
      <div><label class="text-slate-400 block mb-1">Y</label>
        <input type="number" x-model.number="regions.a.y" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
      <div><label class="text-slate-400 block mb-1">W</label>
        <input type="number" x-model.number="regions.a.w" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
      <div><label class="text-slate-400 block mb-1">H</label>
        <input type="number" x-model.number="regions.a.h" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
    </div>
  </div>

  {# Region B coords #}
  <div class="mt-2">
    <p class="text-xs text-cyan-400 mb-1 font-medium">Region B</p>
    <div class="grid grid-cols-4 gap-2 text-xs">
      <div><label class="text-slate-400 block mb-1">X</label>
        <input type="number" x-model.number="regions.b.x" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
      <div><label class="text-slate-400 block mb-1">Y</label>
        <input type="number" x-model.number="regions.b.y" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
      <div><label class="text-slate-400 block mb-1">W</label>
        <input type="number" x-model.number="regions.b.w" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
      <div><label class="text-slate-400 block mb-1">H</label>
        <input type="number" x-model.number="regions.b.h" @change="saveRegions()"
               class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1"></div>
    </div>
  </div>

  <form x-ref="saveForm"
        hx-post="{% url 'clipping:update_layout_regions' candidate.pk %}"
        hx-swap="none" class="hidden">
    {% csrf_token %}
    <input type="hidden" name="region_a_x" :value="regions.a.x">
    <input type="hidden" name="region_a_y" :value="regions.a.y">
    <input type="hidden" name="region_a_w" :value="regions.a.w">
    <input type="hidden" name="region_a_h" :value="regions.a.h">
    <input type="hidden" name="region_b_x" :value="regions.b.x">
    <input type="hidden" name="region_b_y" :value="regions.b.y">
    <input type="hidden" name="region_b_w" :value="regions.b.w">
    <input type="hidden" name="region_b_h" :value="regions.b.h">
    <input type="hidden" name="stack_ratio" :value="stackRatio">
  </form>
</div>

<script>
{# regionEditor() function is defined in smart_crop_editor.html — must be included first,
   or extracted to a shared static JS file when both editors can coexist on one page.
   Since only one editor is rendered at a time (based on render_mode), no duplication occurs. #}
</script>
```

- [ ] **Step 4.8: Create `center_crop_editor.html`**

Create `reelforge/clipping/templates/clipping/partials/center_crop_editor.html`:

```html
<div>
  <h3 class="text-sm font-semibold text-slate-300 mb-2">Center Crop</h3>
  <div class="relative w-full bg-slate-900 rounded overflow-hidden" style="padding-top: 56.25%">
    <div class="absolute inset-0 flex items-center justify-center">
      {# Center crop indicator: a 9:16 box centered in the 16:9 frame #}
      {# 9:16 = 0.5625 aspect. In a 16:9 container, width = height×(9/16). If container = 100% wide,
         then the crop zone is (100% * 9/16) / (16/9) = ~31.6% wide and 56.25% of container height. #}
      <div class="absolute border-2 border-dashed border-slate-500"
           style="width: 31.6%; height: 100%; left: 50%; transform: translateX(-50%);">
        <span class="absolute top-1 left-1/2 -translate-x-1/2 text-xs text-slate-400 bg-slate-900/80 px-1 rounded">9:16</span>
      </div>
    </div>
  </div>
  <p class="mt-2 text-xs text-slate-500">Center crop uses the center column of the source frame. No manual adjustment.</p>
</div>
```

- [ ] **Step 4.9: Run tests**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_update_layout_config_saves_render_mode reelforge/clipping/tests/test_views_phase_b.py::test_update_layout_regions_saves_crop_coords reelforge/clipping/tests/test_views_phase_b.py::test_reset_smart_crop_clears_manual_coords -v
```

Expected: PASS.

- [ ] **Step 4.10: Commit**

```bash
git add reelforge/clipping/views/candidates.py reelforge/clipping/urls.py \
  reelforge/clipping/templates/clipping/partials/layout_editor.html \
  reelforge/clipping/templates/clipping/partials/smart_crop_editor.html \
  reelforge/clipping/templates/clipping/partials/spatial_stack_editor.html \
  reelforge/clipping/templates/clipping/partials/center_crop_editor.html \
  reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(dashboard): add visual layout editor (Smart Crop + Spatial Stack + Center Crop)"
```

---

## Task 5: Style Config Panels (HTMX Auto-Save)

**Files:**
- Modify: `reelforge/clipping/views/candidates.py`
- Modify: `reelforge/clipping/urls.py`
- Create: `reelforge/clipping/templates/clipping/partials/style_panels.html`

- [ ] **Step 5.1: Write failing test**

Append to `test_views_phase_b.py`:

```python
@pytest.mark.django_db
def test_update_style_config_saves_caption_fields(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    from reelforge.clipping.models import ClipStyleConfig
    style = ClipStyleConfig.objects.get(candidate=candidate)
    url = reverse("clipping:update_style_config", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {
        "caption_font": "Arial",
        "caption_size": "48",
        "caption_color": "#FF0000",
        # caption_enabled omitted = False
    })
    assert response.status_code == 200
    style.refresh_from_db()
    assert style.caption_font == "Arial"
    assert style.caption_size == 48
    assert style.caption_color == "#FF0000"
    assert style.caption_enabled is False


@pytest.mark.django_db
def test_update_style_config_saves_boolean_fields(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    from reelforge.clipping.models import ClipStyleConfig
    style = ClipStyleConfig.objects.get(candidate=candidate)
    url = reverse("clipping:update_style_config", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {"caption_enabled": "1", "hook_enabled": "1"})
    assert response.status_code == 200
    style.refresh_from_db()
    assert style.caption_enabled is True
    assert style.hook_enabled is True
```

- [ ] **Step 5.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_update_style_config_saves_caption_fields reelforge/clipping/tests/test_views_phase_b.py::test_update_style_config_saves_boolean_fields -v
```

Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 5.3: Add `update_style_config` view**

In `reelforge/clipping/views/candidates.py`, add:

```python
from reelforge.clipping.models import ClipStyleConfig

_BOOLEAN_STYLE_FIELDS = frozenset({
    "caption_enabled",
    "hook_enabled",
    "watermark_enabled",
    "progress_bar_enabled",
    "music_enabled",
})

_INT_STYLE_FIELDS = frozenset({
    "caption_size", "caption_stroke_width", "watermark_size",
    "progress_bar_height", "hook_size",
})

_FLOAT_STYLE_FIELDS = frozenset({
    "hook_duration_sec", "transition_duration_sec", "watermark_opacity",
    "music_volume_db", "music_fade_in_sec", "music_fade_out_sec",
})

_STYLE_FIELD_SET = frozenset(ClipRenderStyleMixin.STYLE_FIELD_NAMES)


@staff_member_required
@require_POST
def update_style_config(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Save any style config fields sent in POST. Called on blur/change from style panels."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    style, _ = ClipStyleConfig.objects.get_or_create(candidate=candidate)

    update_fields: list[str] = ["updated_at"]

    for field_name in _STYLE_FIELD_SET - {"emoji_keyword_map"}:
        if field_name in _BOOLEAN_STYLE_FIELDS:
            val = field_name in request.POST
            setattr(style, field_name, val)
            update_fields.append(field_name)
        elif field_name in request.POST:
            raw = request.POST[field_name]
            try:
                if field_name in _INT_STYLE_FIELDS:
                    setattr(style, field_name, int(raw))
                elif field_name in _FLOAT_STYLE_FIELDS:
                    setattr(style, field_name, float(raw))
                else:
                    setattr(style, field_name, raw)
                update_fields.append(field_name)
            except (ValueError, TypeError):
                pass

    style.save(update_fields=update_fields)
    return HttpResponse(status=200)
```

- [ ] **Step 5.4: Register URL**

In `reelforge/clipping/urls.py`, add:

```python
path("clips/<uuid:candidate_id>/style/", views_candidates.update_style_config, name="update_style_config"),
```

- [ ] **Step 5.5: Create `style_panels.html`**

Create `reelforge/clipping/templates/clipping/partials/style_panels.html`:

```html
{% comment %}
  Collapsible style config panels. The entire form auto-saves on any change or blur.
  Boolean fields (enabled toggles) use checkboxes; their absence in POST = False.
{% endcomment %}
<div x-data="{ openPanel: 'captions' }">

  {# Form wraps all panels — any change/blur triggers a POST #}
  <form id="style-form"
        hx-post="{% url 'clipping:update_style_config' candidate.pk %}"
        hx-trigger="change delay:200ms, blur delay:200ms"
        hx-swap="none">
    {% csrf_token %}

    {# ── Captions panel ── #}
    <div class="bg-slate-800 rounded-lg mb-2">
      <button type="button"
              @click="openPanel = openPanel === 'captions' ? null : 'captions'"
              class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-200">
        <span class="flex items-center gap-2">
          <input type="checkbox" name="caption_enabled" value="1"
                 {% if style.caption_enabled %}checked{% endif %}
                 @click.stop
                 class="mr-1">
          Captions
        </span>
        <span x-text="openPanel === 'captions' ? '▲' : '▼'" class="text-slate-400 text-xs"></span>
      </button>
      <div x-show="openPanel === 'captions'" class="px-4 pb-4 space-y-3">
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div>
            <label class="text-slate-400 block mb-1">Style</label>
            <select name="caption_style" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              {% for val, lbl in style.caption_style|field_choices_from_model:"caption_style" %}
              {% empty %}
              <option value="CHUNKED" {% if style.caption_style == 'CHUNKED' %}selected{% endif %}>Chunked</option>
              <option value="WORD" {% if style.caption_style == 'WORD' %}selected{% endif %}>Word by Word</option>
              <option value="KARAOKE" {% if style.caption_style == 'KARAOKE' %}selected{% endif %}>Karaoke</option>
              <option value="FULL" {% if style.caption_style == 'FULL' %}selected{% endif %}>Full</option>
              {% endfor %}
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Position</label>
            <select name="caption_position" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="TOP" {% if style.caption_position == 'TOP' %}selected{% endif %}>Top</option>
              <option value="MIDDLE" {% if style.caption_position == 'MIDDLE' %}selected{% endif %}>Middle</option>
              <option value="BOTTOM" {% if style.caption_position == 'BOTTOM' %}selected{% endif %}>Bottom</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Animation</label>
            <select name="caption_animation" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="NONE" {% if style.caption_animation == 'NONE' %}selected{% endif %}>None</option>
              <option value="POP" {% if style.caption_animation == 'POP' %}selected{% endif %}>Pop</option>
              <option value="FADE" {% if style.caption_animation == 'FADE' %}selected{% endif %}>Fade</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Font Size</label>
            <input type="number" name="caption_size" value="{{ style.caption_size }}"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Color</label>
            <input type="color" name="caption_color" value="{{ style.caption_color }}"
                   class="w-full h-8 bg-slate-700 border border-slate-600 rounded">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Stroke Color</label>
            <input type="color" name="caption_stroke_color" value="{{ style.caption_stroke_color }}"
                   class="w-full h-8 bg-slate-700 border border-slate-600 rounded">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Stroke Width</label>
            <input type="number" name="caption_stroke_width" value="{{ style.caption_stroke_width }}"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Font</label>
            <input type="text" name="caption_font" value="{{ style.caption_font }}"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
        </div>
      </div>
    </div>

    {# ── Hook panel ── #}
    <div class="bg-slate-800 rounded-lg mb-2">
      <button type="button"
              @click="openPanel = openPanel === 'hook' ? null : 'hook'"
              class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-200">
        <span class="flex items-center gap-2">
          <input type="checkbox" name="hook_enabled" value="1"
                 {% if style.hook_enabled %}checked{% endif %}
                 @click.stop class="mr-1">
          Hook
        </span>
        <span x-text="openPanel === 'hook' ? '▲' : '▼'" class="text-slate-400 text-xs"></span>
      </button>
      <div x-show="openPanel === 'hook'" class="px-4 pb-4 space-y-3">
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div>
            <label class="text-slate-400 block mb-1">Style</label>
            <select name="hook_style" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="OVERLAY_TOP" {% if style.hook_style == 'OVERLAY_TOP' %}selected{% endif %}>Overlay Top</option>
              <option value="OVERLAY_BOTTOM" {% if style.hook_style == 'OVERLAY_BOTTOM' %}selected{% endif %}>Overlay Bottom</option>
              <option value="FULL_SCREEN" {% if style.hook_style == 'FULL_SCREEN' %}selected{% endif %}>Full Screen</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Duration (sec)</label>
            <input type="number" name="hook_duration_sec" value="{{ style.hook_duration_sec }}" step="0.5"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Animation</label>
            <select name="hook_animation" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="NONE" {% if style.hook_animation == 'NONE' %}selected{% endif %}>None</option>
              <option value="POP" {% if style.hook_animation == 'POP' %}selected{% endif %}>Pop</option>
              <option value="FADE" {% if style.hook_animation == 'FADE' %}selected{% endif %}>Fade</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Font Size</label>
            <input type="number" name="hook_size" value="{{ style.hook_size }}"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Text Color</label>
            <input type="color" name="hook_color" value="{{ style.hook_color }}"
                   class="w-full h-8 bg-slate-700 border border-slate-600 rounded">
          </div>
        </div>
      </div>
    </div>

    {# ── Watermark panel ── #}
    <div class="bg-slate-800 rounded-lg mb-2">
      <button type="button"
              @click="openPanel = openPanel === 'watermark' ? null : 'watermark'"
              class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-200">
        <span class="flex items-center gap-2">
          <input type="checkbox" name="watermark_enabled" value="1"
                 {% if style.watermark_enabled %}checked{% endif %}
                 @click.stop class="mr-1">
          Watermark
        </span>
        <span x-text="openPanel === 'watermark' ? '▲' : '▼'" class="text-slate-400 text-xs"></span>
      </button>
      <div x-show="openPanel === 'watermark'" class="px-4 pb-4">
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div>
            <label class="text-slate-400 block mb-1">Type</label>
            <select name="watermark_type" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="TEXT" {% if style.watermark_type == 'TEXT' %}selected{% endif %}>Text</option>
              <option value="IMAGE" {% if style.watermark_type == 'IMAGE' %}selected{% endif %}>Image</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Text</label>
            <input type="text" name="watermark_text" value="{{ style.watermark_text }}"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Position</label>
            <select name="watermark_position" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="TOP_LEFT" {% if style.watermark_position == 'TOP_LEFT' %}selected{% endif %}>Top Left</option>
              <option value="TOP_RIGHT" {% if style.watermark_position == 'TOP_RIGHT' %}selected{% endif %}>Top Right</option>
              <option value="BOTTOM_LEFT" {% if style.watermark_position == 'BOTTOM_LEFT' %}selected{% endif %}>Bottom Left</option>
              <option value="BOTTOM_RIGHT" {% if style.watermark_position == 'BOTTOM_RIGHT' %}selected{% endif %}>Bottom Right</option>
              <option value="CENTER" {% if style.watermark_position == 'CENTER' %}selected{% endif %}>Center</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Opacity (0-1)</label>
            <input type="number" name="watermark_opacity" value="{{ style.watermark_opacity }}" step="0.1" min="0" max="1"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Size (px)</label>
            <input type="number" name="watermark_size" value="{{ style.watermark_size }}"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
        </div>
      </div>
    </div>

    {# ── Background Music panel ── #}
    <div class="bg-slate-800 rounded-lg mb-2">
      <button type="button"
              @click="openPanel = openPanel === 'music' ? null : 'music'"
              class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-200">
        <span class="flex items-center gap-2">
          <input type="checkbox" name="music_enabled" value="1"
                 {% if style.music_enabled %}checked{% endif %}
                 @click.stop class="mr-1">
          Background Music
        </span>
        <span x-text="openPanel === 'music' ? '▲' : '▼'" class="text-slate-400 text-xs"></span>
      </button>
      <div x-show="openPanel === 'music'" class="px-4 pb-4">
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div>
            <label class="text-slate-400 block mb-1">Volume (dB)</label>
            <input type="number" name="music_volume_db" value="{{ style.music_volume_db }}" step="1"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Fade In (sec)</label>
            <input type="number" name="music_fade_in_sec" value="{{ style.music_fade_in_sec }}" step="0.5"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Fade Out (sec)</label>
            <input type="number" name="music_fade_out_sec" value="{{ style.music_fade_out_sec }}" step="0.5"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
        </div>
      </div>
    </div>

    {# ── Transitions panel ── #}
    <div class="bg-slate-800 rounded-lg mb-2">
      <button type="button"
              @click="openPanel = openPanel === 'transitions' ? null : 'transitions'"
              class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-200">
        Transitions
        <span x-text="openPanel === 'transitions' ? '▲' : '▼'" class="text-slate-400 text-xs"></span>
      </button>
      <div x-show="openPanel === 'transitions'" class="px-4 pb-4">
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div>
            <label class="text-slate-400 block mb-1">Intro</label>
            <select name="intro_transition" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="NONE" {% if style.intro_transition == 'NONE' %}selected{% endif %}>None</option>
              <option value="FADE" {% if style.intro_transition == 'FADE' %}selected{% endif %}>Fade</option>
              <option value="SLIDE" {% if style.intro_transition == 'SLIDE' %}selected{% endif %}>Slide</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Outro</label>
            <select name="outro_transition" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="NONE" {% if style.outro_transition == 'NONE' %}selected{% endif %}>None</option>
              <option value="FADE" {% if style.outro_transition == 'FADE' %}selected{% endif %}>Fade</option>
              <option value="SLIDE" {% if style.outro_transition == 'SLIDE' %}selected{% endif %}>Slide</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Duration (sec)</label>
            <input type="number" name="transition_duration_sec" value="{{ style.transition_duration_sec }}" step="0.1"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
        </div>
      </div>
    </div>

    {# Progress bar — no toggle but still collapsible #}
    <div class="bg-slate-800 rounded-lg mb-2">
      <button type="button"
              @click="openPanel = openPanel === 'progressbar' ? null : 'progressbar'"
              class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-200">
        <span class="flex items-center gap-2">
          <input type="checkbox" name="progress_bar_enabled" value="1"
                 {% if style.progress_bar_enabled %}checked{% endif %}
                 @click.stop class="mr-1">
          Progress Bar
        </span>
        <span x-text="openPanel === 'progressbar' ? '▲' : '▼'" class="text-slate-400 text-xs"></span>
      </button>
      <div x-show="openPanel === 'progressbar'" class="px-4 pb-4">
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div>
            <label class="text-slate-400 block mb-1">Position</label>
            <select name="progress_bar_position" class="w-full bg-slate-700 border border-slate-600 text-slate-200 rounded px-2 py-1">
              <option value="TOP" {% if style.progress_bar_position == 'TOP' %}selected{% endif %}>Top</option>
              <option value="BOTTOM" {% if style.progress_bar_position == 'BOTTOM' %}selected{% endif %}>Bottom</option>
            </select>
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Height (px)</label>
            <input type="number" name="progress_bar_height" value="{{ style.progress_bar_height }}"
                   class="w-full bg-slate-700 border border-slate-600 text-white rounded px-2 py-1">
          </div>
          <div>
            <label class="text-slate-400 block mb-1">Color</label>
            <input type="color" name="progress_bar_color" value="{{ style.progress_bar_color }}"
                   class="w-full h-8 bg-slate-700 border border-slate-600 rounded">
          </div>
        </div>
      </div>
    </div>

    {% if channel_template %}
    <p class="text-xs text-slate-500 mt-2">
      These are per-clip overrides.
      <a href="#" class="text-indigo-400 hover:text-indigo-300">Reset to channel defaults</a>
      (channel: {{ channel_template.channel.name }})
    </p>
    {% endif %}

  </form>
</div>
```

- [ ] **Step 5.6: Run tests**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py::test_update_style_config_saves_caption_fields reelforge/clipping/tests/test_views_phase_b.py::test_update_style_config_saves_boolean_fields -v
```

Expected: PASS.

- [ ] **Step 5.7: Commit**

```bash
git add reelforge/clipping/views/candidates.py reelforge/clipping/urls.py \
  reelforge/clipping/templates/clipping/partials/style_panels.html \
  reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(dashboard): add style config panels with HTMX auto-save"
```

---

## Task 6: Preview Generation + Timed Overlays

**Files:**
- Modify: `reelforge/clipping/views/candidates.py`
- Modify: `reelforge/clipping/urls.py`
- Create: `reelforge/clipping/templates/clipping/partials/preview_panel.html`
- Create: `reelforge/clipping/templates/clipping/partials/overlay_row.html`

- [ ] **Step 6.1: Write failing tests**

Append to `test_views_phase_b.py`:

```python
@pytest.mark.django_db
def test_trigger_preview_fires_celery_task(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    from reelforge.clipping.models import ClipLayoutConfig
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    url = reverse("clipping:trigger_preview", kwargs={"candidate_id": candidate.pk})
    with patch("reelforge.clipping.views.candidates.preview_clip_layout") as mock_task:
        response = client.post(url)
    assert response.status_code == 200
    mock_task.delay.assert_called_once_with(str(layout.pk))


@pytest.mark.django_db
def test_preview_status_returns_image_url_when_ready(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    from reelforge.clipping.models import ClipLayoutConfig
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    layout.preview_image = "clipping/previews/test.jpg"
    layout.save(update_fields=["preview_image"])
    url = reverse("clipping:preview_status", kwargs={"candidate_id": candidate.pk})
    response = client.get(url)
    assert response.status_code == 200
    assert b"test.jpg" in response.content


@pytest.mark.django_db
def test_add_overlay_creates_record_and_returns_partial(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    url = reverse("clipping:add_overlay", kwargs={"candidate_id": candidate.pk})
    response = client.post(url)
    assert response.status_code == 200
    from reelforge.clipping.models import ClipTimedOverlay
    assert ClipTimedOverlay.objects.filter(candidate=candidate).count() == 1


@pytest.mark.django_db
def test_delete_overlay_removes_record(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    from reelforge.clipping.tests.factories import ClipTimedOverlayFactory
    overlay = ClipTimedOverlayFactory()
    url = reverse("clipping:delete_overlay", kwargs={"overlay_id": overlay.pk})
    response = client.post(url)
    assert response.status_code == 200
    from reelforge.clipping.models import ClipTimedOverlay
    assert not ClipTimedOverlay.objects.filter(pk=overlay.pk).exists()
```

- [ ] **Step 6.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py -k "preview or overlay" -v
```

Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 6.3: Add preview + overlay views**

In `reelforge/clipping/views/candidates.py`, add:

```python
from reelforge.clipping.tasks import preview_clip_layout


@staff_member_required
@require_POST
def trigger_preview(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Fire the preview_clip_layout Celery task. Returns the polling preview panel."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    layout = get_object_or_404(ClipLayoutConfig, candidate=candidate)
    preview_clip_layout.delay(str(layout.pk))
    return render(
        request,
        "clipping/partials/preview_panel.html",
        {"candidate": candidate, "layout": layout, "polling": True},
    )


@staff_member_required
def preview_status(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """HTMX polling endpoint: returns preview panel partial.
    Sets data-terminal when preview_image is populated."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    layout = getattr(candidate, "layout_config", None)
    is_ready = layout is not None and bool(layout.preview_image)
    return render(
        request,
        "clipping/partials/preview_panel.html",
        {"candidate": candidate, "layout": layout, "polling": not is_ready},
    )


@staff_member_required
@require_POST
def add_overlay(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Create a new timed overlay with defaults; return the new overlay row partial."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        text="New overlay",
        start_sec=0.0,
        end_sec=5.0,
    )
    return render(
        request,
        "clipping/partials/overlay_row.html",
        {"overlay": overlay, "candidate": candidate},
    )


@staff_member_required
@require_POST
def update_overlay(request: HttpRequest, overlay_id: str) -> HttpResponse:
    """Save text/time fields for a timed overlay."""
    overlay = get_object_or_404(ClipTimedOverlay, pk=overlay_id)
    update_fields: list[str] = ["updated_at"]
    if "text" in request.POST:
        overlay.text = request.POST["text"]
        update_fields.append("text")
    for field in ("start_sec", "end_sec", "position_x", "position_y", "font_size"):
        if field in request.POST:
            try:
                setattr(overlay, field, float(request.POST[field]) if "sec" in field else int(request.POST[field]))
                update_fields.append(field)
            except (ValueError, TypeError):
                pass
    overlay.save(update_fields=update_fields)
    return HttpResponse(status=200)


@staff_member_required
@require_POST
def delete_overlay(request: HttpRequest, overlay_id: str) -> HttpResponse:
    """Delete a timed overlay; return empty 200 (HTMX outerHTML swap removes the row)."""
    overlay = get_object_or_404(ClipTimedOverlay, pk=overlay_id)
    overlay.delete()
    return HttpResponse(status=200)
```

- [ ] **Step 6.4: Register URLs**

In `reelforge/clipping/urls.py`, add:

```python
path("clips/<uuid:candidate_id>/preview/trigger/", views_candidates.trigger_preview, name="trigger_preview"),
path("clips/<uuid:candidate_id>/preview/status/", views_candidates.preview_status, name="preview_status"),
path("clips/<uuid:candidate_id>/overlays/add/", views_candidates.add_overlay, name="add_overlay"),
path("overlays/<uuid:overlay_id>/update/", views_candidates.update_overlay, name="update_overlay"),
path("overlays/<uuid:overlay_id>/delete/", views_candidates.delete_overlay, name="delete_overlay"),
```

- [ ] **Step 6.5: Create `preview_panel.html`**

Create `reelforge/clipping/templates/clipping/partials/preview_panel.html`:

```html
{# Self-stopping polling panel. Sets data-terminal when image is ready. #}
<div id="preview-panel"
     {% if polling %}
     hx-get="{% url 'clipping:preview_status' candidate.pk %}"
     hx-trigger="every 2s"
     hx-swap="outerHTML"
     {% else %}
     data-terminal="true"
     {% endif %}>

  {% if layout and layout.preview_image %}
    {# Preview ready: show 9:16 image #}
    <div class="flex justify-center">
      <img src="{{ layout.preview_image.url }}"
           alt="Layout preview"
           class="max-h-96 rounded shadow-lg">
    </div>
    <button class="mt-2 w-full text-xs text-slate-400 hover:text-white border border-slate-600 rounded py-1"
            hx-post="{% url 'clipping:trigger_preview' candidate.pk %}"
            hx-target="#preview-panel"
            hx-swap="outerHTML">
      ↺ Regenerate Preview
    </button>
  {% elif polling %}
    {# Generating... #}
    <div class="flex flex-col items-center gap-2 py-8">
      <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
      <p class="text-xs text-slate-400">Generating preview…</p>
    </div>
  {% else %}
    {# Not yet generated #}
    <div class="flex flex-col items-center gap-3 py-6">
      <p class="text-xs text-slate-500">No preview generated yet.</p>
      <button class="text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-2"
              hx-post="{% url 'clipping:trigger_preview' candidate.pk %}"
              hx-target="#preview-panel"
              hx-swap="outerHTML">
        Generate Preview
      </button>
    </div>
  {% endif %}

</div>
```

- [ ] **Step 6.6: Create `overlay_row.html`**

Create `reelforge/clipping/templates/clipping/partials/overlay_row.html`:

```html
<div id="overlay-{{ overlay.pk }}" class="bg-slate-700 rounded p-3 text-xs">
  <div class="grid grid-cols-3 gap-2 mb-2">
    <div class="col-span-3">
      <label class="text-slate-400 block mb-1">Text</label>
      <input type="text" value="{{ overlay.text }}"
             hx-post="{% url 'clipping:update_overlay' overlay.pk %}"
             hx-vals='{"text": event.target.value}'
             hx-trigger="blur"
             hx-swap="none"
             class="w-full bg-slate-600 border border-slate-500 text-white rounded px-2 py-1">
    </div>
    <div>
      <label class="text-slate-400 block mb-1">Start (sec)</label>
      <input type="number" value="{{ overlay.start_sec }}" step="0.1"
             hx-post="{% url 'clipping:update_overlay' overlay.pk %}"
             hx-vals='{"start_sec": event.target.value}'
             hx-trigger="blur"
             hx-swap="none"
             class="w-full bg-slate-600 border border-slate-500 text-white rounded px-2 py-1">
    </div>
    <div>
      <label class="text-slate-400 block mb-1">End (sec)</label>
      <input type="number" value="{{ overlay.end_sec }}" step="0.1"
             hx-post="{% url 'clipping:update_overlay' overlay.pk %}"
             hx-vals='{"end_sec": event.target.value}'
             hx-trigger="blur"
             hx-swap="none"
             class="w-full bg-slate-600 border border-slate-500 text-white rounded px-2 py-1">
    </div>
    <div>
      <label class="text-slate-400 block mb-1">Font Size</label>
      <input type="number" value="{{ overlay.font_size }}"
             hx-post="{% url 'clipping:update_overlay' overlay.pk %}"
             hx-vals='{"font_size": event.target.value}'
             hx-trigger="blur"
             hx-swap="none"
             class="w-full bg-slate-600 border border-slate-500 text-white rounded px-2 py-1">
    </div>
  </div>
  <button class="text-red-400 hover:text-red-300 text-xs"
          hx-post="{% url 'clipping:delete_overlay' overlay.pk %}"
          hx-target="#overlay-{{ overlay.pk }}"
          hx-swap="outerHTML"
          hx-confirm="Delete this overlay?">
    ✕ Delete
  </button>
</div>
```

- [ ] **Step 6.7: Run tests**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py -k "preview or overlay" -v
```

Expected: PASS.

- [ ] **Step 6.8: Commit**

```bash
git add reelforge/clipping/views/candidates.py reelforge/clipping/urls.py \
  reelforge/clipping/templates/clipping/partials/preview_panel.html \
  reelforge/clipping/templates/clipping/partials/overlay_row.html \
  reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(dashboard): add preview generation + timed overlay inline editing"
```

---

## Task 7: Render Detail View + Polled Stage List

**Files:**
- Create: `reelforge/clipping/views/renders.py`
- Modify: `reelforge/clipping/urls.py`
- Create: `reelforge/clipping/templates/clipping/render_detail.html`
- Create: `reelforge/clipping/templates/clipping/partials/stage_list.html`
- Create: `reelforge/clipping/templates/clipping/partials/stage_pill.html`

- [ ] **Step 7.1: Write failing tests**

Append to `test_views_phase_b.py`:

```python
@pytest.mark.django_db
def test_render_detail_view_returns_200(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    render = ClipRenderFactory()
    url = reverse("clipping:render_detail", kwargs={"render_id": render.pk})
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_stage_list_partial_returns_200(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    render = ClipRenderFactory()
    url = reverse("clipping:stage_list_partial", kwargs={"render_id": render.pk})
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_stage_list_partial_is_terminal_when_render_completed(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    render = ClipRenderFactory(status=ClipRender.RenderStatus.COMPLETED)
    url = reverse("clipping:stage_list_partial", kwargs={"render_id": render.pk})
    response = client.get(url)
    assert response.status_code == 200
    assert b"data-terminal" in response.content
```

- [ ] **Step 7.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py -k "render_detail or stage_list" -v
```

Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 7.3: Create `reelforge/clipping/views/renders.py`**

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from reelforge.clipping.models import ClipCandidate, ClipRender, ClipRenderStageResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger("reelforge.clipping.views")

_TERMINAL_RENDER_STATUSES = frozenset({
    ClipRender.RenderStatus.COMPLETED,
    ClipRender.RenderStatus.FAILED,
    ClipRender.RenderStatus.PAUSED_AT_GATE,
})


@staff_member_required
def render_detail(request: HttpRequest, render_id: str) -> HttpResponse:
    clip_render = get_object_or_404(
        ClipRender.objects.select_related(
            "candidate__clipping_job__channel",
            "candidate__layout_config",
        ).prefetch_related("stage_results"),
        pk=render_id,
    )
    candidate = clip_render.candidate
    layout = getattr(candidate, "layout_config", None)
    is_terminal = clip_render.status in _TERMINAL_RENDER_STATUSES
    stages = list(clip_render.stage_results.order_by("stage_order"))

    return render(
        request,
        "clipping/render_detail.html",
        {
            "render": clip_render,
            "candidate": candidate,
            "layout": layout,
            "stages": stages,
            "is_terminal": is_terminal,
        },
    )


@staff_member_required
def stage_list_partial(request: HttpRequest, render_id: str) -> HttpResponse:
    """HTMX polling target: refreshes the stage list. Self-stopping when render is terminal."""
    clip_render = get_object_or_404(
        ClipRender.objects.prefetch_related("stage_results"),
        pk=render_id,
    )
    is_terminal = clip_render.status in _TERMINAL_RENDER_STATUSES
    stages = list(clip_render.stage_results.order_by("stage_order"))

    return render(
        request,
        "clipping/partials/stage_list.html",
        {
            "render": clip_render,
            "stages": stages,
            "is_terminal": is_terminal,
        },
    )
```

- [ ] **Step 7.4: Register URLs**

In `reelforge/clipping/urls.py`, add at the top of the views imports:

```python
from reelforge.clipping.views import renders as views_renders
```

Add to `urlpatterns`:

```python
path("renders/<uuid:render_id>/", views_renders.render_detail, name="render_detail"),
path("renders/<uuid:render_id>/stages/", views_renders.stage_list_partial, name="stage_list_partial"),
```

- [ ] **Step 7.5: Create `render_detail.html`**

Create `reelforge/clipping/templates/clipping/render_detail.html`:

```html
{% extends "ui/base.html" %}

{% block title %}Render — {{ candidate.title|truncatechars:40 }}{% endblock %}

{% block content %}
<div class="flex items-center gap-3 mb-6">
  <a href="{% url 'clipping:candidate_detail' candidate.pk %}"
     class="text-slate-400 hover:text-white text-sm">← {{ candidate.title|truncatechars:40 }}</a>
  <span class="text-slate-600">/</span>
  <h1 class="text-lg font-semibold text-white">
    Render
    <span class="text-sm font-normal ml-2
      {% if render.status == 'COMPLETED' %}text-green-400
      {% elif render.status == 'RUNNING' %}text-indigo-400
      {% elif render.status == 'PAUSED_AT_GATE' %}text-amber-400
      {% elif render.status == 'FAILED' %}text-red-400
      {% else %}text-slate-400{% endif %}">
      {{ render.get_status_display }}
    </span>
  </h1>
</div>

<div class="grid grid-cols-5 gap-6">

  {# ── Left: stage list (2/5 width) ── #}
  <div class="col-span-2">
    <div id="stage-list-container">
      {% include "clipping/partials/stage_list.html" %}
    </div>
  </div>

  {# ── Right: preview + gates (3/5 width) ── #}
  <div class="col-span-3 space-y-4">

    {# Video preview panel — shown when a stage with output is selected #}
    <div id="stage-preview" class="bg-slate-800 rounded-lg p-4">
      {% if render.status == 'COMPLETED' and render.video_file %}
        <h3 class="text-sm font-semibold text-slate-300 mb-3">Final Output</h3>
        <video src="{{ render.video_file.url }}" controls
               class="w-full rounded max-h-96 bg-black"></video>
      {% elif render.status == 'PAUSED_AT_GATE' %}
        {% for stage in stages %}
          {% if stage.stage_order == render.paused_at_stage and stage.output_file %}
          <h3 class="text-sm font-semibold text-amber-400 mb-3">
            Paused at Gate — Stage {{ stage.stage_order }}: {{ stage.stage_name|title }}
          </h3>
          <video src="{{ stage.output_file.url }}" controls
                 class="w-full rounded max-h-96 bg-black"></video>
          {% endif %}
        {% endfor %}
      {% else %}
        <p class="text-xs text-slate-500 text-center py-8">
          Click a completed stage to preview its output.
        </p>
      {% endif %}
    </div>

    {# Review gates panel #}
    <div id="gates-panel">
      {% include "clipping/partials/gates_panel.html" with candidate=candidate render=render %}
    </div>

    {# Resume / re-run actions when paused #}
    {% if render.status == 'PAUSED_AT_GATE' %}
    <div class="bg-amber-900/30 border border-amber-700 rounded-lg p-4">
      <p class="text-sm text-amber-300 mb-3">
        Render paused after Stage {{ render.paused_at_stage }}.
        Review the preview above, then continue or adjust config.
      </p>
      <div class="flex gap-3">
        <button class="text-sm bg-green-700 hover:bg-green-600 text-white rounded px-4 py-2"
                hx-post="{% url 'clipping:resume_render' render.pk %}"
                hx-target="body"
                hx-push-url="true">
          ✓ Continue Pipeline
        </button>
        <a href="{% url 'clipping:candidate_detail' candidate.pk %}"
           class="text-sm border border-slate-600 hover:border-slate-500 text-slate-300 rounded px-4 py-2">
          ← Edit Config
        </a>
      </div>
    </div>
    {% endif %}

  </div>
</div>
{% endblock %}
```

- [ ] **Step 7.6: Create `stage_list.html`**

Create `reelforge/clipping/templates/clipping/partials/stage_list.html`:

```html
{# Self-stopping polling. Swaps when render is not terminal. #}
<div id="stage-list-container"
     {% if not is_terminal %}
     hx-get="{% url 'clipping:stage_list_partial' render.pk %}"
     hx-trigger="every 2s"
     hx-swap="outerHTML"
     {% else %}
     data-terminal="true"
     {% endif %}>

  <h3 class="text-sm font-semibold text-slate-300 mb-3">Pipeline Stages</h3>

  <div class="space-y-1">
    {% for stage in stages %}
      {% include "clipping/partials/stage_pill.html" %}
    {% empty %}
      <p class="text-xs text-slate-500 py-4 text-center">
        {% if render.status == 'PENDING' %}Waiting to start…
        {% else %}No stage results yet.{% endif %}
      </p>
    {% endfor %}
  </div>

</div>
```

- [ ] **Step 7.7: Create `stage_pill.html`**

Create `reelforge/clipping/templates/clipping/partials/stage_pill.html`:

```html
<div class="flex items-start gap-3 px-3 py-2 rounded
  {% if stage.status == 'COMPLETED' %}bg-slate-800 hover:bg-slate-750
  {% elif stage.status == 'RUNNING' %}bg-indigo-900/40 border border-indigo-700
  {% elif stage.status == 'FAILED' %}bg-red-900/30 border border-red-800
  {% elif stage.status == 'SKIPPED' %}bg-slate-850 opacity-50
  {% else %}bg-slate-850{% endif %}">

  {# Status indicator #}
  <div class="flex-shrink-0 mt-0.5">
    {% if stage.status == 'COMPLETED' %}
      <span class="text-green-400 text-sm">✓</span>
    {% elif stage.status == 'RUNNING' %}
      <span class="text-indigo-400 text-sm animate-pulse">●</span>
    {% elif stage.status == 'FAILED' %}
      <span class="text-red-400 text-sm">✕</span>
    {% elif stage.status == 'SKIPPED' %}
      <span class="text-slate-600 text-sm">—</span>
    {% else %}
      <span class="text-slate-700 text-sm">○</span>
    {% endif %}
  </div>

  {# Stage info #}
  <div class="flex-1 min-w-0">
    <div class="flex items-center justify-between">
      <p class="text-sm text-slate-200">
        <span class="text-slate-500 mr-1">{{ stage.stage_order }}.</span>
        {{ stage.stage_name|replace:"_":" "|title }}
      </p>
      {% if stage.duration_sec %}
        <span class="text-xs text-slate-500 flex-shrink-0 ml-2">{{ stage.duration_sec|floatformat:1 }}s</span>
      {% endif %}
    </div>

    {# Error message for failed stages #}
    {% if stage.status == 'FAILED' and stage.last_error %}
    <div x-data="{ open: false }">
      <button @click="open = !open" class="text-xs text-red-400 hover:text-red-300 mt-1">
        <span x-text="open ? '▲ Hide error' : '▼ Show error'"></span>
      </button>
      <pre x-show="open" class="text-xs text-red-300 bg-red-900/20 rounded p-2 mt-1 whitespace-pre-wrap break-all max-h-32 overflow-y-auto">{{ stage.last_error }}</pre>
    </div>
    {% endif %}

    {# Actions for completed stages #}
    {% if stage.status == 'COMPLETED' %}
    <div class="flex gap-2 mt-1">
      {% if stage.output_file %}
      <a href="{{ stage.output_file.url }}"
         class="text-xs text-indigo-400 hover:text-indigo-300"
         hx-get="{{ stage.output_file.url }}"
         hx-target="#stage-preview"
         hx-swap="innerHTML"
         onclick="document.getElementById('stage-preview').innerHTML='<video src=\'{{ stage.output_file.url }}\' controls class=\'w-full rounded max-h-96 bg-black\'></video>'; return false;">
        ▶ Preview
      </a>
      {% endif %}
      <button class="text-xs text-slate-400 hover:text-white"
              hx-post="{% url 'clipping:rerun_from_stage' render.pk stage.stage_order %}"
              hx-confirm="Re-run from stage {{ stage.stage_order }}? This will delete results for stages {{ stage.stage_order }}+."
              hx-target="body"
              hx-push-url="true">
        ↺ Re-run from here
      </button>
    </div>
    {% endif %}

    {# Action for failed stages #}
    {% if stage.status == 'FAILED' %}
    <button class="text-xs text-amber-400 hover:text-amber-300 mt-1"
            hx-post="{% url 'clipping:rerun_from_stage' render.pk stage.stage_order %}"
            hx-target="body"
            hx-push-url="true">
      ↺ Retry from this stage
    </button>
    {% endif %}

  </div>
</div>
```

Note: The `{% url 'clipping:rerun_from_stage' ... %}` URL requires integers; Django URL resolvers will handle UUID → int conversion. Make sure the URL pattern uses `int` converter for `stage_order`.

The Alpine `onclick` preview hack in `stage_pill.html` is rough — use a proper HTMX approach: a separate `stage_preview_partial` endpoint that returns just a `<video>` tag for the given stage output file.

Simplify the preview link:

```html
      {% if stage.output_file %}
      <a href="{{ stage.output_file.url }}" target="_blank"
         class="text-xs text-indigo-400 hover:text-indigo-300">▶ Open preview</a>
      {% endif %}
```

Opening in a new tab is sufficient for operator review.

- [ ] **Step 7.8: Run tests**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py -k "render_detail or stage_list" -v
```

Expected: PASS.

- [ ] **Step 7.9: Commit**

```bash
git add reelforge/clipping/views/renders.py reelforge/clipping/urls.py \
  reelforge/clipping/templates/clipping/render_detail.html \
  reelforge/clipping/templates/clipping/partials/stage_list.html \
  reelforge/clipping/templates/clipping/partials/stage_pill.html \
  reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(dashboard): add render detail view with polled stage list"
```

---

## Task 8: Stage Actions + Review Gates Panel

**Files:**
- Modify: `reelforge/clipping/views/renders.py`
- Modify: `reelforge/clipping/views/candidates.py`
- Modify: `reelforge/clipping/urls.py`
- Create: `reelforge/clipping/templates/clipping/partials/gates_panel.html`

- [ ] **Step 8.1: Write failing tests**

Append to `test_views_phase_b.py`:

```python
@pytest.mark.django_db
def test_rerun_from_stage_fires_task_and_redirects(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    render = ClipRenderFactory(status=ClipRender.RenderStatus.PAUSED_AT_GATE, paused_at_stage=3)
    from reelforge.clipping.tests.factories import ClipRenderStageResultFactory
    ClipRenderStageResultFactory(render=render, stage_order=1, status=ClipRenderStageResult.Status.COMPLETED)
    ClipRenderStageResultFactory(render=render, stage_order=2, status=ClipRenderStageResult.Status.COMPLETED)
    ClipRenderStageResultFactory(render=render, stage_order=3, status=ClipRenderStageResult.Status.COMPLETED)
    url = reverse("clipping:rerun_from_stage", kwargs={"render_id": render.pk, "stage_order": 2})
    with patch("reelforge.clipping.views.renders.render_clip") as mock_task:
        response = client.post(url)
    assert response.status_code in (200, 302, 204)
    mock_task.delay.assert_called_once()
    render.refresh_from_db()
    assert render.status == ClipRender.RenderStatus.RUNNING
    assert render.paused_at_stage is None


@pytest.mark.django_db
def test_resume_render_fires_task_from_next_stage(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    render = ClipRenderFactory(status=ClipRender.RenderStatus.PAUSED_AT_GATE, paused_at_stage=1)
    url = reverse("clipping:resume_render", kwargs={"render_id": render.pk})
    with patch("reelforge.clipping.views.renders.render_clip") as mock_task:
        response = client.post(url)
    assert response.status_code in (200, 302, 204)
    mock_task.delay.assert_called_once_with(
        str(render.candidate_id),
        clip_render_id=str(render.pk),
        start_from_stage=2,
    )
    render.refresh_from_db()
    assert render.status == ClipRender.RenderStatus.RUNNING
    assert render.paused_at_stage is None


@pytest.mark.django_db
def test_update_render_gates_saves_list(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    url = reverse("clipping:update_render_gates", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {"gates": "1,3,5"})
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.render_gates == [1, 3, 5]


@pytest.mark.django_db
def test_update_render_gates_handles_empty(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory(render_gates=[1, 3])
    url = reverse("clipping:update_render_gates", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {"gates": ""})
    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.render_gates == []
```

- [ ] **Step 8.2: Run tests to confirm they fail**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py -k "rerun or resume or gates" -v
```

Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 8.3: Add rerun/resume views to `renders.py`**

In `reelforge/clipping/views/renders.py`, add:

```python
from reelforge.clipping.tasks import render_clip


@staff_member_required
@require_POST
def rerun_from_stage(request: HttpRequest, render_id: str, stage_order: int) -> HttpResponse:
    """Re-run the render pipeline from the given stage order."""
    clip_render = get_object_or_404(ClipRender, pk=render_id)
    clip_render.status = ClipRender.RenderStatus.RUNNING
    clip_render.paused_at_stage = None
    clip_render.last_error = ""
    clip_render.save(update_fields=["status", "paused_at_stage", "last_error", "updated_at"])

    render_clip.delay(
        str(clip_render.candidate_id),
        clip_render_id=str(clip_render.pk),
        start_from_stage=stage_order,
    )

    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"/app/clipping/renders/{render_id}/"
    return response


@staff_member_required
@require_POST
def resume_render(request: HttpRequest, render_id: str) -> HttpResponse:
    """Continue the pipeline from the stage after the current gate pause."""
    clip_render = get_object_or_404(ClipRender, pk=render_id)
    if clip_render.status != ClipRender.RenderStatus.PAUSED_AT_GATE or clip_render.paused_at_stage is None:
        return HttpResponse("Render is not paused at a gate", status=400)

    next_stage = clip_render.paused_at_stage + 1
    clip_render.status = ClipRender.RenderStatus.RUNNING
    clip_render.paused_at_stage = None
    clip_render.save(update_fields=["status", "paused_at_stage", "updated_at"])

    render_clip.delay(
        str(clip_render.candidate_id),
        clip_render_id=str(clip_render.pk),
        start_from_stage=next_stage,
    )

    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"/app/clipping/renders/{render_id}/"
    return response
```

- [ ] **Step 8.4: Add `update_render_gates` view to `candidates.py`**

In `reelforge/clipping/views/candidates.py`, add:

```python
@staff_member_required
@require_POST
def update_render_gates(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Save the render_gates list for a candidate. POST body: gates=1,3,5 (comma-separated)."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    raw_gates = request.POST.get("gates", "").strip()

    gates: list[int] = []
    if raw_gates:
        for part in raw_gates.split(","):
            try:
                val = int(part.strip())
                if 1 <= val <= 10:
                    gates.append(val)
            except (ValueError, TypeError):
                pass

    candidate.render_gates = sorted(set(gates))
    candidate.save(update_fields=["render_gates", "updated_at"])

    return render(
        request,
        "clipping/partials/gates_panel.html",
        {"candidate": candidate},
    )
```

- [ ] **Step 8.5: Register URLs**

In `reelforge/clipping/urls.py`, add:

```python
path("renders/<uuid:render_id>/rerun/<int:stage_order>/", views_renders.rerun_from_stage, name="rerun_from_stage"),
path("renders/<uuid:render_id>/resume/", views_renders.resume_render, name="resume_render"),
path("clips/<uuid:candidate_id>/gates/", views_candidates.update_render_gates, name="update_render_gates"),
```

- [ ] **Step 8.6: Create `gates_panel.html`**

Create `reelforge/clipping/templates/clipping/partials/gates_panel.html`:

```html
{# Review gates configuration panel. render_gates is a list of stage order ints. #}
<div id="gates-panel" class="bg-slate-800 rounded-lg p-4">
  <h3 class="text-sm font-semibold text-slate-300 mb-1">Review Gates</h3>
  <p class="text-xs text-slate-500 mb-3">
    Pause the render after selected stages for review before continuing.
  </p>

  {% comment %}
    Gate toggles: 4 natural checkpoints. Each checkbox adds/removes its stage number.
    On any change, serialize checked boxes to comma-separated string and POST.
  {% endcomment %}
  <div x-data="{
    gates: {{ candidate.render_gates|default:'[]'|safe }},
    toggle(n) {
      const idx = this.gates.indexOf(n);
      if (idx === -1) this.gates.push(n);
      else this.gates.splice(idx, 1);
      this.gates.sort((a,b) => a - b);
    },
    hasGate(n) { return this.gates.includes(n); }
  }"
  @change="
    const form = $refs.gatesForm;
    form.querySelector('[name=gates]').value = gates.join(',');
    htmx.trigger(form, 'submit');
  ">

    <div class="space-y-2">
      {% for stage_order, stage_label in gate_options %}
      <label class="flex items-center gap-3 cursor-pointer">
        <input type="checkbox"
               :checked="hasGate({{ stage_order }})"
               @change="toggle({{ stage_order }})"
               class="rounded border-slate-500 bg-slate-700 text-indigo-500">
        <span class="text-sm text-slate-200">After Stage {{ stage_order }}</span>
        <span class="text-xs text-slate-500">{{ stage_label }}</span>
      </label>
      {% empty %}
      {# Hardcoded gate options since context var may not always be passed #}
      <label class="flex items-center gap-3 cursor-pointer">
        <input type="checkbox" :checked="hasGate(1)" @change="toggle(1)"
               class="rounded border-slate-500 bg-slate-700 text-indigo-500">
        <span class="text-sm text-slate-200">After Stage 1</span>
        <span class="text-xs text-slate-500">Trim + Crop — verify raw crop</span>
      </label>
      <label class="flex items-center gap-3 cursor-pointer">
        <input type="checkbox" :checked="hasGate(3)" @change="toggle(3)"
               class="rounded border-slate-500 bg-slate-700 text-indigo-500">
        <span class="text-sm text-slate-200">After Stage 3</span>
        <span class="text-xs text-slate-500">Hook — verify hook text + animation</span>
      </label>
      <label class="flex items-center gap-3 cursor-pointer">
        <input type="checkbox" :checked="hasGate(5)" @change="toggle(5)"
               class="rounded border-slate-500 bg-slate-700 text-indigo-500">
        <span class="text-sm text-slate-200">After Stage 5</span>
        <span class="text-xs text-slate-500">Captions — verify caption style</span>
      </label>
      <label class="flex items-center gap-3 cursor-pointer">
        <input type="checkbox" :checked="hasGate(8)" @change="toggle(8)"
               class="rounded border-slate-500 bg-slate-700 text-indigo-500">
        <span class="text-sm text-slate-200">After Stage 8</span>
        <span class="text-xs text-slate-500">Progress Bar — final check before music</span>
      </label>
      {% endfor %}
    </div>

    {# Hidden form — submitted by Alpine on change #}
    <form x-ref="gatesForm"
          hx-post="{% url 'clipping:update_render_gates' candidate.pk %}"
          hx-target="#gates-panel"
          hx-swap="outerHTML"
          class="hidden">
      {% csrf_token %}
      <input type="hidden" name="gates" :value="gates.join(',')">
    </form>

  </div>

  {% if candidate.render_gates %}
  <p class="text-xs text-amber-400 mt-3">
    {{ candidate.render_gates|length }} gate{{ candidate.render_gates|length|pluralize }} active.
    Render will pause for review at {{ candidate.render_gates|join:", " }}.
  </p>
  {% endif %}
</div>
```

Pass `gate_options` from views that include this partial. For `candidate_detail`, add to context:

```python
"gate_options": [],  # empty list causes hardcoded fallback in template to render
```

- [ ] **Step 8.7: Run tests**

```bash
uv run pytest reelforge/clipping/tests/test_views_phase_b.py -k "rerun or resume or gates" -v
```

Expected: PASS.

- [ ] **Step 8.8: Run full test suite**

```bash
uv run pytest reelforge/clipping/tests/ -v
```

Expected: All tests pass.

- [ ] **Step 8.9: Commit**

```bash
git add reelforge/clipping/views/renders.py reelforge/clipping/views/candidates.py \
  reelforge/clipping/urls.py \
  reelforge/clipping/templates/clipping/partials/gates_panel.html \
  reelforge/clipping/tests/test_views_phase_b.py
git commit -m "feat(dashboard): add stage rerun/resume actions + review gates panel"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Clip candidate detail page (`/app/clipping/clips/<id>/`) — Task 3
- [x] Render mode selector (Smart Crop / Spatial Stack / Center Crop) — Task 4
- [x] Visual drag editor for Smart Crop and Spatial Stack — Task 4
- [x] "Reset to auto" for Smart Crop — Task 4
- [x] Stack ratio slider for Spatial Stack — Task 4
- [x] Output format dropdown — Task 4
- [x] Style config panels (captions, hook, watermark, music, transitions, progress bar) — Task 5
- [x] HTMX auto-save on blur/change — Task 5
- [x] 9:16 preview generation + polling — Task 6
- [x] Timed overlays inline add/remove/edit — Task 6
- [x] Render detail page (`/app/clipping/renders/<id>/`) — Task 7
- [x] 10-stage progress list with polled updates — Task 7
- [x] Self-stopping polling when terminal — Task 7
- [x] Per-stage preview (open in new tab) — Task 7
- [x] PAUSED_AT_GATE status display on render detail — Task 7 + Task 8
- [x] "Re-run from stage N" action — Task 8
- [x] "Continue pipeline" (resume) action — Task 8
- [x] Review gate toggle controls — Task 8
- [x] Model changes (render_gates, PAUSED_AT_GATE, paused_at_stage) — Task 1
- [x] Pipeline gate pause mechanism — Task 2

**Not covered (out of Phase B scope):**
- "Channel defaults note" reset-to-defaults link (placeholder text added in style_panels.html)
- Background music asset picker (ClipMusicAsset FK) — complex UI, defer

**Type consistency checks:**
- `candidate_id` and `render_id` are UUIDs — URL patterns use `<uuid:...>`, views accept `str`
- `stage_order` is an integer — URL pattern uses `<int:stage_order>`
- `render_gates` is a `list[int]` — stored as JSON, parsed from comma-separated POST param
- `GatePausedException.stage_order` matches `ClipRender.paused_at_stage` (both `int`)
- `_TERMINAL_RENDER_STATUSES` in `renders.py` includes `PAUSED_AT_GATE` — correct, polling stops
