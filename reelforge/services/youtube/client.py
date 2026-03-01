from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import NoReturn

import googleapiclient.discovery
from google.auth.credentials import AnonymousCredentials
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from reelforge.services.youtube.exceptions import YouTubeAPIError
from reelforge.services.youtube.exceptions import YouTubeAuthError
from reelforge.services.youtube.exceptions import YouTubeQuotaError

if TYPE_CHECKING:
    from reelforge.channels.models import Channel

logger = logging.getLogger("reelforge.youtube.client")


class YouTubeClient:
    """YouTube Data API v3 client — OAuth-only operations (upload, analytics).

    Use `from_channel()` or `from_credential()` to instantiate with OAuth.
    Direct instantiation is provided for completeness but all current methods
    require OAuth via `_require_auth()`.
    """

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self._is_authenticated: bool = False
        self._service: Any = googleapiclient.discovery.build(
            "youtube",
            "v3",
            developerKey=api_key or None,
            credentials=AnonymousCredentials(),
        )

    @classmethod
    def from_credential(cls, credential: dict[str, Any]) -> YouTubeClient:
        """Create a client from OAuth credential dict for authenticated operations."""
        google_creds = Credentials(
            token=credential.get("token", ""),
            refresh_token=credential.get("refresh_token"),
            token_uri=credential.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=credential.get("client_id"),
            client_secret=credential.get("client_secret"),
        )
        instance: YouTubeClient = cls.__new__(cls)
        instance.api_key = ""
        instance._is_authenticated = True
        instance._service = googleapiclient.discovery.build(
            "youtube",
            "v3",
            credentials=google_creds,
        )
        return instance

    @classmethod
    def from_channel(cls, channel: Channel) -> YouTubeClient:
        """Create an authenticated client from a channel's stored OAuth credentials."""
        creds = channel.oauth_credentials
        if not creds or not creds.get("token"):
            msg = f"Channel {channel.slug} has no OAuth credentials stored"
            raise YouTubeAuthError(msg)
        return cls.from_credential(creds)

    def _require_auth(self) -> None:
        """Raise YouTubeAuthError if the client is not authenticated via OAuth."""
        if not self._is_authenticated:
            msg = "This operation requires OAuth authentication. Use YouTubeClient.from_channel()."
            raise YouTubeAuthError(msg)

    def _handle_http_error(self, exc: HttpError) -> NoReturn:
        status = int(exc.resp.status)
        if status == 401:  # noqa: PLR2004
            msg = f"YouTube API authentication failed: {exc}"
            raise YouTubeAuthError(msg) from exc
        if status == 403:  # noqa: PLR2004
            try:
                reason = (exc.error_details or [{}])[0].get("reason", "")
            except (TypeError, KeyError, IndexError):
                reason = ""
            if reason == "quotaExceeded":
                msg = "YouTube API quota exceeded"
                raise YouTubeQuotaError(msg) from exc
            msg = f"YouTube API forbidden: {exc}"
            raise YouTubeAuthError(msg) from exc
        msg = f"YouTube API error: {exc}"
        raise YouTubeAPIError(msg, status_code=status) from exc

    def get_my_channel(self) -> dict[str, Any]:
        """Return the authenticated user's own channel info (requires OAuth)."""
        self._require_auth()
        try:
            response: dict[str, Any] = self._service.channels().list(part="snippet,statistics", mine=True).execute()
        except HttpError as exc:
            self._handle_http_error(exc)
        items: list[dict[str, Any]] = response.get("items", [])
        return items[0] if items else {}

    def get_video_analytics(
        self,
        video_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """Fetch per-video analytics from YouTube Analytics API (requires OAuth).

        TODO: Implement using YouTube Analytics API v2 (different base URL:
        https://youtubeanalytics.googleapis.com/v2). Returns empty dict until implemented.
        """
        self._require_auth()
        logger.warning(
            "get_video_analytics not yet implemented — returning empty dict",
            extra={"video_id": video_id, "start_date": start_date, "end_date": end_date},
        )
        return {}

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str = "private",
    ) -> str:
        """Upload a video to YouTube (requires OAuth). Returns the YouTube video ID.

        TODO: Implement using YouTube Data API v3 resumable upload.
        Returns empty string until implemented.
        """
        self._require_auth()
        logger.warning(
            "upload_video not yet implemented — returning empty string",
            extra={"video_path": video_path, "title": title, "privacy_status": privacy_status},
        )
        return ""

    def upload_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Upload a thumbnail image for a video (requires OAuth).

        TODO: Implement using YouTube Data API v3 thumbnails.set endpoint.
        Returns False until implemented.
        """
        self._require_auth()
        logger.warning(
            "upload_thumbnail not yet implemented — returning False",
            extra={"video_id": video_id, "thumbnail_path": thumbnail_path},
        )
        return False
