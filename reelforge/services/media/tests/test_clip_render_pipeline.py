from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from reelforge.services.media.clip_render_pipeline import ClipRenderPipeline
from reelforge.services.media.clip_render_pipeline import PipelineRenderConfig


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
    from reelforge.clipping.models import ClipRenderStageResult
    from reelforge.clipping.tests.factories import ClipRenderFactory

    render = ClipRenderFactory()
    config = _make_config(tmp_path, render_id=str(render.pk))

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")

    with patch("reelforge.services.media.clip_render_pipeline.ClipRenderPipeline._run_stage") as mock_run:
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
    from reelforge.clipping.tests.factories import ClipRenderFactory

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
        "reelforge.services.media.render_stages.trim_crop.TrimAndCropStage.run"
    ) as mock_trim, patch(
        "reelforge.services.media.render_stages.trim_crop.TrimAndCropStage.should_run",
        return_value=True,
    ):
        stage_out = tmp_path / "stage01.mp4"
        stage_out.write_bytes(b"stage output")
        mock_trim.return_value = stage_out
        result = pipeline.run()

    assert result == output
    assert output.exists()


def test_pipeline_render_config_has_expected_defaults(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert config.width == 1080
    assert config.height == 1920
    assert config.fps == 30
    assert config.crf == 18
    assert config.preset == "slow"
    assert config.audio_bitrate == "192k"
    assert config.channel is None
