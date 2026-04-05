from __future__ import annotations

from unittest.mock import patch

import pytest

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipRender
from django.test import Client
from django.urls import reverse

from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.clipping.tests.factories import ClipRenderFactory
from ***REMOVED***.users.tests.factories import UserFactory


# ── Task 1: model field tests ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_clip_candidate_has_render_gates_field() -> None:
    candidate = ClipCandidateFactory()
    assert candidate.render_gates == []
    candidate.render_gates = [1, 3, 5]
    candidate.save(update_fields=["render_gates"])
    candidate.refresh_from_db()
    assert candidate.render_gates == [1, 3, 5]


def test_clip_render_has_paused_at_gate_status() -> None:
    assert "PAUSED_AT_GATE" in ClipRender.RenderStatus.values


@pytest.mark.django_db
def test_clip_render_has_paused_at_stage_field() -> None:
    render = ClipRenderFactory()
    assert render.paused_at_stage is None
    render.paused_at_stage = 3
    render.save(update_fields=["paused_at_stage"])
    render.refresh_from_db()
    assert render.paused_at_stage == 3


# ── Task 2: pipeline gate pause mechanism ─────────────────────────────────────

def test_pipeline_raises_gate_paused_when_stage_is_in_gates() -> None:
    """Pipeline raises GatePausedException after a stage whose order is in pause_after_stages."""
    from pathlib import Path

    from ***REMOVED***.services.media.clip_render_pipeline import ClipRenderPipeline
    from ***REMOVED***.services.media.clip_render_pipeline import GatePausedException
    from ***REMOVED***.services.media.clip_render_pipeline import PipelineRenderConfig

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


@pytest.mark.django_db
def test_render_clip_task_pauses_at_gate() -> None:
    """render_clip task sets PAUSED_AT_GATE status when candidate has render_gates."""
    from ***REMOVED***.clipping.tasks import render_clip
    from ***REMOVED***.services.media.clip_render_pipeline import GatePausedException

    candidate = ClipCandidateFactory(
        render_gates=[1],
        status=ClipCandidate.CandidateStatus.APPROVED,
    )
    candidate.clipping_job.downloaded_file = "test/file.mp4"
    candidate.clipping_job.save(update_fields=["downloaded_file"])

    with patch("***REMOVED***.clipping.tasks.ClipRenderPipeline") as MockPipeline:
        mock_instance = MockPipeline.return_value
        mock_instance.run.side_effect = GatePausedException(stage_order=1)

        render_clip.apply(args=[str(candidate.pk)])

    render = candidate.renders.get()
    assert render.status == ClipRender.RenderStatus.PAUSED_AT_GATE
    assert render.paused_at_stage == 1


# ── Task 3: candidate detail view ─────────────────────────────────────────────

@pytest.mark.django_db
def test_candidate_detail_view_returns_200(client: Client) -> None:
    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    url = reverse("clipping:candidate_detail", kwargs={"candidate_id": candidate.pk})
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_candidate_detail_requires_staff(client: Client) -> None:
    user = UserFactory(is_staff=False)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    url = reverse("clipping:candidate_detail", kwargs={"candidate_id": candidate.pk})
    response = client.get(url)
    assert response.status_code == 302


# ── Task 4: layout editor views ───────────────────────────────────────────────

@pytest.mark.django_db
def test_update_layout_config_saves_render_mode(client: Client) -> None:
    from ***REMOVED***.clipping.models import ClipLayoutConfig
    from ***REMOVED***.clipping.models import ClipRenderMode

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    url = reverse("clipping:update_layout_config", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {"render_mode": ClipRenderMode.SPATIAL_STACK})
    assert response.status_code == 200
    layout.refresh_from_db()
    assert layout.render_mode == ClipRenderMode.SPATIAL_STACK


@pytest.mark.django_db
def test_update_layout_regions_saves_crop_coords(client: Client) -> None:
    from ***REMOVED***.clipping.models import ClipLayoutConfig

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
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
    from ***REMOVED***.clipping.models import ClipLayoutConfig

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
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


# ── Task 5: style config panels ───────────────────────────────────────────────

@pytest.mark.django_db
def test_update_style_config_saves_caption_fields(client: Client) -> None:
    from ***REMOVED***.clipping.models import ClipStyleConfig

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
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
    from ***REMOVED***.clipping.models import ClipStyleConfig

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    style = ClipStyleConfig.objects.get(candidate=candidate)
    url = reverse("clipping:update_style_config", kwargs={"candidate_id": candidate.pk})
    response = client.post(url, {"caption_enabled": "1", "hook_enabled": "1"})
    assert response.status_code == 200
    style.refresh_from_db()
    assert style.caption_enabled is True
    assert style.hook_enabled is True


# ── Task 6: preview + overlay views ──────────────────────────────────────────

@pytest.mark.django_db
def test_trigger_preview_fires_celery_task(client: Client) -> None:
    from ***REMOVED***.clipping.models import ClipLayoutConfig

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    url = reverse("clipping:trigger_preview", kwargs={"candidate_id": candidate.pk})
    with patch("***REMOVED***.clipping.views.candidates.preview_clip_layout") as mock_task:
        response = client.post(url)
    assert response.status_code == 200
    mock_task.delay.assert_called_once_with(str(layout.pk))


@pytest.mark.django_db
def test_preview_status_returns_image_url_when_ready(client: Client) -> None:
    from ***REMOVED***.clipping.models import ClipLayoutConfig

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    layout.preview_image = "clipping/previews/test.jpg"
    layout.save(update_fields=["preview_image"])
    url = reverse("clipping:preview_status", kwargs={"candidate_id": candidate.pk})
    response = client.get(url)
    assert response.status_code == 200
    assert b"test.jpg" in response.content


@pytest.mark.django_db
def test_add_overlay_creates_record_and_returns_partial(client: Client) -> None:
    from ***REMOVED***.clipping.models import ClipTimedOverlay

    user = UserFactory(is_staff=True)
    client.force_login(user)
    candidate = ClipCandidateFactory()
    url = reverse("clipping:add_overlay", kwargs={"candidate_id": candidate.pk})
    response = client.post(url)
    assert response.status_code == 200
    assert ClipTimedOverlay.objects.filter(candidate=candidate).count() == 1


@pytest.mark.django_db
def test_delete_overlay_removes_record(client: Client) -> None:
    from ***REMOVED***.clipping.models import ClipTimedOverlay
    from ***REMOVED***.clipping.tests.factories import ClipTimedOverlayFactory

    user = UserFactory(is_staff=True)
    client.force_login(user)
    overlay = ClipTimedOverlayFactory()
    url = reverse("clipping:delete_overlay", kwargs={"overlay_id": overlay.pk})
    response = client.post(url)
    assert response.status_code == 200
    assert not ClipTimedOverlay.objects.filter(pk=overlay.pk).exists()


# ── Task 7: render detail view + polled stage list ────────────────────────────

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
