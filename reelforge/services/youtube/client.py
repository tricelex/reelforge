from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from typing import Any

import httpx

from ***REMOVED***.services.youtube.exceptions import YouTubeAPIError
from ***REMOVED***.services.youtube.exceptions import YouTubeAuthError
from ***REMOVED***.services.youtube.exceptions import YouTubeQuotaError

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel

logger = logging.getLogger("***REMOVED***.youtube.client")

_YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeClient:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self._is_authenticated: bool = False
        self._client = httpx.Client(
            base_url=_YOUTUBE_API_BASE,
            timeout=30.0,
        )

    @classmethod
    def from_credential(cls, credential: dict[str, Any]) -> YouTubeClient:
        """Create a client from OAuth credential for authenticated operations."""
        instance = cls(api_key="")
        instance._is_authenticated = True
        instance._client = httpx.Client(
            base_url=_YOUTUBE_API_BASE,
            headers={"Authorization": f"Bearer {credential.get('access_token', '')}"},
            timeout=30.0,
        )
        return instance

    @classmethod
    def from_channel(cls, channel: Channel) -> YouTubeClient:
        """Create an authenticated client by decrypting a channel's stored OAuth blob."""
        from django.conf import settings

        from cryptography.fernet import Fernet

        from ***REMOVED***.channels.schemas import OAuthCredentials

        raw_blob = channel.oauth_credentials
        if not raw_blob:
            raise YouTubeAuthError(f"Channel {channel.slug} has no OAuth credentials stored")

        creds = OAuthCredentials.model_validate(raw_blob)
        fernet = Fernet(settings.CREDENTIAL_ENCRYPTION_KEY)
        decrypted = json.loads(fernet.decrypt(creds.encrypted.encode()).decode())

        # Normalize key: google-auth uses "token", we store "token" but from_credential expects "access_token"
        if "token" in decrypted and "access_token" not in decrypted:
            decrypted["access_token"] = decrypted.pop("token")

        return cls.from_credential(decrypted)

    def _require_auth(self) -> None:
        """Raise YouTubeAuthError if the client is not authenticated via OAuth."""
        if not self._is_authenticated:
            raise YouTubeAuthError("This operation requires OAuth authentication. Use YouTubeClient.from_channel().")

    def _handle_errors(self, response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code == 401:
            raise YouTubeAuthError(f"YouTube API authentication failed: {response.text}")
        if response.status_code == 403:
            try:
                data = response.json()
                reason = data.get("error", {}).get("errors", [{}])[0].get("reason", "")
            except Exception:
                reason = ""
            if reason == "quotaExceeded":
                raise YouTubeQuotaError("YouTube API quota exceeded")
            raise YouTubeAuthError(f"YouTube API forbidden: {response.text}")
        raise YouTubeAPIError(
            f"YouTube API error: {response.text}",
            status_code=response.status_code,
        )

    def search_videos(
        self,
        query: str,
        max_results: int = 25,
        order: str = "relevance",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": order,
            "key": self.api_key,
        }
        response = self._client.get("/search", params=params)
        self._handle_errors(response)
        return response.json().get("items", [])

    def get_trending_videos(
        self,
        region: str = "US",
        category_id: str = "",
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region,
            "maxResults": max_results,
            "key": self.api_key,
        }
        if category_id:
            params["videoCategoryId"] = category_id
        response = self._client.get("/videos", params=params)
        self._handle_errors(response)
        return response.json().get("items", [])

    def get_channel_videos(
        self,
        channel_id: str,
        max_results: int = 25,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": max_results,
            "key": self.api_key,
        }
        response = self._client.get("/search", params=params)
        self._handle_errors(response)
        return response.json().get("items", [])

    def get_channel_stats(self, channel_id: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "part": "statistics,snippet",
            "id": channel_id,
            "key": self.api_key,
        }
        response = self._client.get("/channels", params=params)
        self._handle_errors(response)
        items = response.json().get("items", [])
        return items[0] if items else {}

    def get_video_details(self, video_id: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
            "key": self.api_key,
        }
        response = self._client.get("/videos", params=params)
        self._handle_errors(response)
        items = response.json().get("items", [])
        return items[0] if items else {}

    def get_my_channel(self) -> dict[str, Any]:
        """Return the authenticated user's own channel info (requires OAuth)."""
        self._require_auth()
        params: dict[str, Any] = {"part": "snippet,statistics", "mine": "true"}
        response = self._client.get("/channels", params=params)
        self._handle_errors(response)
        items = response.json().get("items", [])
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
