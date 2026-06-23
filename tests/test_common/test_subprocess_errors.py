"""Tests for subprocess error formatting helpers."""

import subprocess
from unittest.mock import MagicMock

from server.common.subprocess_errors import (
    format_subprocess_failure,
    raise_subprocess_failure,
)


def test_format_subprocess_failure_prefers_stderr() -> None:
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = 1
    result.stderr = 'ModuleNotFoundError: No module named whisperx'
    result.stdout = ''
    assert 'whisperx' in format_subprocess_failure('whisperx', result)


def test_raise_subprocess_failure_raises_runtime_error() -> None:
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = 1
    result.stderr = 'ffmpeg error'
    result.stdout = ''
    try:
        raise_subprocess_failure('ffmpeg', result)
    except RuntimeError as exc:
        assert 'ffmpeg failed' in str(exc)
        assert 'ffmpeg error' in str(exc)
    else:
        raise AssertionError('expected RuntimeError')
