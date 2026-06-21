"""Helpers for surfacing subprocess failure details."""

import subprocess  # noqa: S404
from typing import Final

_STDERR_MAX_LEN: Final = 500


def format_subprocess_failure(
    label: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    """Build a human-readable error from a failed subprocess result."""
    stderr = (result.stderr or '').strip()
    stdout = (result.stdout or '').strip()
    detail = stderr or stdout or f'exit code {result.returncode}'
    if len(detail) > _STDERR_MAX_LEN:
        detail = detail[:_STDERR_MAX_LEN] + '...'
    return f'{label} failed: {detail}'


def raise_subprocess_failure(
    label: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    """Raise RuntimeError with stderr/stdout from a failed subprocess."""
    raise RuntimeError(format_subprocess_failure(label, result))
