from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from reelforge.clipping.tests.factories import ClipCandidateFactory
from reelforge.clipping.tests.factories import ClipRenderFactory
from reelforge.clipping.tests.factories import ClipStyleConfigFactory


@pytest.mark.django_db
def test_render_clip_creates_new_clip_render_when_no_render_id() -> None:
    from reelforge.clipping.models import ClipRender
    from reelforge.clipping.tasks import render_clip

    candidate = ClipCandidateFactory()
    ClipStyleConfigFactory(candidate=candidate)

    with patch("reelforge.clipping.tasks.ClipRenderPipeline") as mock_pipeline_cls, patch(
        "reelforge.clipping.tasks.get_clip_render_path"
    ) as mock_path, patch("reelforge.clipping.tasks.Path") as mock_path_cls:
        mock_path.return_value = Path("/media/test.mp4")
        mock_path_cls.return_value = Path("/media/source.mp4")
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = Path("/media/test.mp4")
        mock_pipeline._build_stages.return_value = []
        mock_pipeline_cls.return_value = mock_pipeline

        render_clip.apply(args=[str(candidate.pk)])

    assert ClipRender.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_render_clip_uses_existing_render_when_clip_render_id_provided() -> None:
    from reelforge.clipping.models import ClipRender
    from reelforge.clipping.tasks import render_clip

    candidate = ClipCandidateFactory()
    render = ClipRenderFactory(candidate=candidate)
    ClipStyleConfigFactory(candidate=candidate)

    with patch("reelforge.clipping.tasks.ClipRenderPipeline") as mock_pipeline_cls, patch(
        "reelforge.clipping.tasks.get_clip_render_path"
    ) as mock_path:
        mock_path.return_value = Path("/media/test.mp4")
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = Path("/media/test.mp4")
        mock_pipeline._build_stages.return_value = []
        mock_pipeline_cls.return_value = mock_pipeline

        render_clip.apply(
            args=[str(candidate.pk)],
            kwargs={
                "clip_render_id": str(render.pk),
                "start_from_stage": 3,
            },
        )

    # Should still be the same render, not a new one
    assert ClipRender.objects.filter(candidate=candidate).count() == 1
