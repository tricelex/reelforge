import json
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_stages.probe import sync_ffprobe_duration


@patch('server.apps.rendering.clip_stages.probe.subprocess.run')
def test_sync_ffprobe_duration_parses_format_duration(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({'format': {'duration': '12.345000'}}),
    )
    result = sync_ffprobe_duration('/tmp/clip.mp4')
    assert result == pytest.approx(12.345)


@patch('server.apps.rendering.clip_stages.probe.subprocess.run')
def test_sync_ffprobe_duration_raises_on_failure(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='no such file')
    with pytest.raises(RuntimeError, match='ffprobe failed'):
        sync_ffprobe_duration('/tmp/missing.mp4')
