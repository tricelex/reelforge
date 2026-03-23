# apps/channels/services.py
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings

from reelforge.services.youtube.exceptions import YouTubeAuthError

if TYPE_CHECKING:
    from reelforge.channels.models import Channel
    from reelforge.channels.models import SocialAccount


class ChannelSetupService:
    """Guided setup for a new channel."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    _YOUTUBE_SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    def get_authorization_url(self, redirect_uri: str) -> tuple[str, str]:
        """Build the Google OAuth authorization URL.

        Returns (auth_url, state). The caller is responsible for storing
        `state` in the session for CSRF validation.
        """
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            client_config=settings.YOUTUBE_OAUTH_CLIENT_CONFIG,
            scopes=self._YOUTUBE_SCOPES,
            redirect_uri=redirect_uri,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        return auth_url, state

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange an authorization code for OAuth2 tokens and store on SocialAccount."""
        from google_auth_oauthlib.flow import Flow

        from reelforge.channels.models import SocialAccount

        flow = Flow.from_client_config(
            client_config=settings.YOUTUBE_OAUTH_CLIENT_CONFIG,
            scopes=self._YOUTUBE_SCOPES,
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        oauth_creds = {
            "token": credentials.token or "",
            "refresh_token": credentials.refresh_token or "",
            "token_uri": credentials.token_uri or "",
            "client_id": credentials.client_id or "",
            "client_secret": credentials.client_secret or "",
        }

        # Persist credentials to the channel's YouTube SocialAccount (create if absent)
        account, _ = SocialAccount.objects.get_or_create(
            channel=self.channel,
            platform=SocialAccount.Platform.YOUTUBE,
            defaults={"is_active": True},
        )
        account.oauth_credentials = oauth_creds
        account.save(update_fields=["oauth_credentials", "updated_at"])

        # Fetch channel ID from API
        self._sync_channel_info(account)
        return {"success": True}

    def _sync_channel_info(self, account: SocialAccount | None = None) -> None:
        from reelforge.services.youtube.client import YouTubeClient

        if account is None:
            account = self.channel.get_youtube_account()
        if account is None:
            msg = f"Channel {self.channel.slug} has no active YouTube SocialAccount"
            raise YouTubeAuthError(msg)

        client = YouTubeClient.from_social_account(account)
        info = client.get_my_channel()
        account.account_id = info.get("id", "")
        account.handle = info.get("snippet", {}).get("customUrl", "")
        account.display_name = info.get("snippet", {}).get("title", "")
        account.save(update_fields=["account_id", "handle", "display_name", "updated_at"])

    def validate_voice(self, voice_id: str, test_text: str = "Hello, this is a test.") -> dict:
        """Test TTS voice before committing."""
        from reelforge.services.providers.registry import get_tts_provider

        tts = get_tts_provider(self.channel)
        response = tts.synthesize(text=test_text, voice_id=voice_id)
        temp_dir = Path(settings.MEDIA_ROOT) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        path = temp_dir / f"voice_test_{self.channel.slug}.mp3"
        with path.open("wb") as f:
            f.write(response.audio_bytes)
        return {"success": True, "preview_path": str(path), "duration": response.duration_sec}
