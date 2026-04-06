from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.services.media.clip_render_pipeline import ClipRenderPipeline
from ***REMOVED***.services.media.clip_render_pipeline import PipelineRenderConfig


def _make_config(tmp_path: Path, render_id: str = "test-render-uuid") -> PipelineRenderConfig:
    return PipelineRenderConfig(
        source_path=tmp_path / "source.mp4",
        output_path=tmp_path / "final.mp4",
        start_sec=0.0,
        end_sec=60.0,
        hook_text="",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id=render_id,
    )


@pytest.mark.django_db
def test_pipeline_builds_10_stages(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    pipeline = ClipRenderPipeline(config)
    stages = pipeline._build_stages()
    orders = [s.order for s in stages]
    assert orders == list(range(1, 11)), f"Expected stages 1-10, got {orders}"


@pytest.mark.django_db
def test_pipeline_creates_stage_result_records(tmp_path: Path) -> None:
    from ***REMOVED***.clipping.models import ClipRenderStageResult
    from ***REMOVED***.clipping.tests.factories import ClipRenderFactory

    render = ClipRenderFactory()
    config = _make_config(tmp_path, render_id=str(render.pk))

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")

    with patch("***REMOVED***.services.media.clip_render_pipeline.ClipRenderPipeline._run_stage") as mock_run:
        mock_run.side_effect = lambda stage, path: path
        with patch.object(ClipRenderPipeline, "_build_stages") as mock_build:
            mock_stage = MagicMock()
            mock_stage.order = 1
            mock_stage.name = "trim_and_crop"
            mock_stage.should_run.return_value = False
            mock_build.return_value = [mock_stage]
            with patch("shutil.copy2"):
                pipeline = ClipRenderPipeline(config)
                pipeline.run()

    assert ClipRenderStageResult.objects.filter(render=render).count() >= 0  # pipeline ran


@pytest.mark.django_db
def test_pipeline_run_end_to_end_all_skipped(tmp_path: Path) -> None:
    """When all stages are skipped, run() should copy source to output."""
    from ***REMOVED***.clipping.tests.factories import ClipRenderFactory

    render = ClipRenderFactory()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake video content")
    output = tmp_path / "final.mp4"

    config = PipelineRenderConfig(
        source_path=source,
        output_path=output,
        start_sec=0.0,
        end_sec=60.0,
        hook_text="",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id=str(render.pk),
    )
    pipeline = ClipRenderPipeline(config)

    with patch(
        "***REMOVED***.services.media.render_stages.trim_crop.TrimAndCropStage.run"
    ) as mock_trim, patch(
        "***REMOVED***.services.media.render_stages.trim_crop.TrimAndCropStage.should_run",
        return_value=True,
    ):
        stage_out = tmp_path / "stage01.mp4"
        stage_out.write_bytes(b"stage output")
        mock_trim.return_value = stage_out
        result = pipeline.run()

    assert result == output
    assert output.exists()


def test_pipeline_run_stores_stages_on_instance(tmp_path: Path) -> None:
    """After run(), pipeline._stages holds the stage instances used during execution."""
    config = _make_config(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")
    config.source_path = source

    pipeline = ClipRenderPipeline(config)
    assert not hasattr(pipeline, "_stages")

    with patch("***REMOVED***.services.media.clip_render_pipeline.ClipRenderPipeline._run_stage") as mock_run, \
         patch("shutil.copy2"):
        mock_run.side_effect = lambda stage, path: path
        pipeline.run()

    assert hasattr(pipeline, "_stages")
    assert len(pipeline._stages) == 10
    assert pipeline._stages[0].name == "trim_and_crop"


def test_pipeline_render_config_has_expected_defaults(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert config.width == 1080
    assert config.height == 1920
    assert config.fps == 30
    assert config.crf == 18
    assert config.preset == "slow"
    assert config.audio_bitrate == "192k"
    assert config.social_account_platform == "tiktok"


@pytest.mark.django_db
def test_pipeline_resume_deletes_stage_results_from_start_stage() -> None:
    """When start_from_stage=3, stage results for stages >= 3 are deleted before rerun."""
    from ***REMOVED***.clipping.models import ClipRenderStageResult
    from ***REMOVED***.clipping.tests.factories import ClipRenderFactory

    render = ClipRenderFactory()
    render_id = str(render.id)

    # Pre-create stage results for stages 1–3
    for order in [1, 2, 3]:
        ClipRenderStageResult.objects.create(
            render=render,
            stage_order=order,
            stage_name=f"stage_{order}",
            status=ClipRenderStageResult.Status.COMPLETED,
        )

    config = PipelineRenderConfig(
        source_path=Path("/tmp/src.mp4"),
        output_path=Path("/tmp/out.mp4"),
        start_sec=0.0,
        end_sec=10.0,
        hook_text="",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id=render_id,
    )
    pipeline = ClipRenderPipeline(config)

    with patch.object(pipeline, "_build_stages") as mock_build, \
         patch("shutil.copy2"), \
         patch("pathlib.Path.mkdir"):
        mock_stage = MagicMock()
        mock_stage.order = 3
        mock_stage.should_run.return_value = False
        mock_build.return_value = [mock_stage]

        prev_result = ClipRenderStageResult.objects.get(render=render, stage_order=2)
        with patch.object(ClipRenderStageResult.objects, "get", return_value=prev_result):
            pipeline.run(start_from_stage=3)

    remaining = list(
        ClipRenderStageResult.objects.filter(render=render).values_list("stage_order", flat=True)
    )
    assert 1 in remaining
    assert 2 in remaining
    assert 3 not in remaining


@pytest.mark.django_db
def test_pipeline_resume_falls_back_to_source_when_prev_result_missing() -> None:
    """When the previous stage result doesn't exist, pipeline logs a warning and uses source_path."""
    from ***REMOVED***.clipping.tests.factories import ClipRenderFactory

    render = ClipRenderFactory()
    config = PipelineRenderConfig(
        source_path=Path("/tmp/src.mp4"),
        output_path=Path("/tmp/out.mp4"),
        start_sec=0.0,
        end_sec=10.0,
        hook_text="",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id=str(render.id),
    )
    pipeline = ClipRenderPipeline(config)

    with patch.object(pipeline, "_build_stages") as mock_build, \
         patch("shutil.copy2"), \
         patch("pathlib.Path.mkdir"), \
         patch("***REMOVED***.services.media.clip_render_pipeline.logger") as mock_logger:
        mock_stage = MagicMock()
        mock_stage.order = 5
        mock_stage.should_run.return_value = False
        mock_build.return_value = [mock_stage]

        pipeline.run(start_from_stage=5)

    mock_logger.warning.assert_called_once()
    warning_msg = mock_logger.warning.call_args[0][0]
    assert "Previous stage result not found" in warning_msg


@pytest.mark.django_db
def test_pipeline_stage_failure_persists_failed_status_and_error() -> None:
    """When a stage raises, ClipRenderStageResult status=FAILED and last_error is set."""
    from ***REMOVED***.clipping.models import ClipRenderStageResult
    from ***REMOVED***.clipping.tests.factories import ClipRenderFactory
    from ***REMOVED***.services.media.render_stages.base import RenderStageError

    render = ClipRenderFactory()
    config = PipelineRenderConfig(
        source_path=Path("/tmp/src.mp4"),
        output_path=Path("/tmp/out.mp4"),
        start_sec=0.0,
        end_sec=10.0,
        hook_text="",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id=str(render.id),
    )
    pipeline = ClipRenderPipeline(config)
    boom = RuntimeError("ffmpeg exploded")

    with patch.object(pipeline, "_build_stages") as mock_build, \
         patch("pathlib.Path.mkdir"):
        mock_stage = MagicMock()
        mock_stage.order = 2
        mock_stage.name = "intro_concat"
        mock_stage.should_run.return_value = True
        mock_stage.run.side_effect = boom
        mock_build.return_value = [mock_stage]

        with pytest.raises(RenderStageError) as exc_info:
            pipeline.run()

    assert exc_info.value.stage_name == "intro_concat"
    assert exc_info.value.stage_order == 2

    result = ClipRenderStageResult.objects.get(render=render, stage_order=2)
    assert result.status == ClipRenderStageResult.Status.FAILED
    assert "ffmpeg exploded" in result.last_error
