from __future__ import annotations

from unittest.mock import patch

from reelforge.core.storage import get_clip_ass_path
from reelforge.core.storage import get_stage_output_path


def test_get_stage_output_path_format() -> None:
    with patch("reelforge.core.storage.settings") as mock_settings:
        mock_settings.MEDIA_ROOT = "/media"
        with patch("pathlib.Path.mkdir"):
            path = get_stage_output_path("abc-123", 3, "captions")
    assert str(path) == "/media/clipping/stage_outputs/abc-123/03_captions.mp4"


def test_get_clip_ass_path_format() -> None:
    with patch("reelforge.core.storage.settings") as mock_settings:
        mock_settings.MEDIA_ROOT = "/media"
        with patch("pathlib.Path.mkdir"):
            path = get_clip_ass_path("abc-123")
    assert str(path) == "/media/clipping/ass/abc-123.ass"
