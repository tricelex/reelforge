from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from typing import Any

from reelforge.services.fal.exceptions import FalAiAuthError
from reelforge.services.fal.exceptions import FalAiError
from reelforge.services.fal.exceptions import FalAiRateLimitError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("reelforge.providers.fal_ai")


def _classify_error(exc: Exception) -> FalAiError:
    """Map a raw exception to a typed FalAiError subclass."""
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return FalAiRateLimitError(str(exc))
    if "401" in msg or "403" in msg or "invalid api" in msg or "unauthorized" in msg:
        return FalAiAuthError(str(exc))
    return FalAiError(str(exc))


class FalAiClient:
    """Thin wrapper around the fal-client library.

    Sets FAL_KEY in the environment on construction and provides typed
    async wrappers around fal_client.run_async() and
    fal_client.upload_file_async(). All public methods raise FalAiError
    (or subclasses) on failure.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        os.environ["FAL_KEY"] = api_key

    def run(self, model: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run a fal.ai model synchronously and return the result dict."""
        import fal_client

        try:
            result: dict[str, Any] = fal_client.run(model, arguments=arguments)
        except Exception as exc:
            raise _classify_error(exc) from exc
        return result

    async def run_async(self, model: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run a fal.ai model asynchronously and return the result dict."""
        import fal_client

        try:
            result: dict[str, Any] = await fal_client.run_async(model, arguments=arguments)
        except Exception as exc:
            raise _classify_error(exc) from exc
        return result

    async def upload_file_async(self, path: Path) -> str:
        """Upload a local file to the fal.ai CDN and return the CDN URL."""
        import fal_client

        try:
            url: str = await fal_client.upload_file_async(path)
        except Exception as exc:
            raise _classify_error(exc) from exc
        return url
