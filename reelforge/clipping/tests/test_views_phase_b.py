from __future__ import annotations

from unittest.mock import patch

import pytest

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.clipping.tests.factories import ClipRenderFactory


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
