# apps/channels/services.py
import json

from config import settings

from ***REMOVED***.channels.models import Channel


class ChannelSetupService:
    """Guided setup for a new channel."""

    def __init__(self, channel: Channel):
        self.channel = channel

    def setup_youtube_oauth(self, auth_code: str) -> dict:
        """Exchange auth code for OAuth2 tokens, store encrypted."""
        from cryptography.fernet import Fernet
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            client_config=settings.YOUTUBE_OAUTH_CLIENT_CONFIG,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/yt-analytics.readonly",
            ],
        )
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials

        # Encrypt before storing
        fernet = Fernet(settings.CREDENTIAL_ENCRYPTION_KEY)
        encrypted = fernet.encrypt(
            json.dumps(
                {
                    "token": credentials.token,
                    "refresh_token": credentials.refresh_token,
                    "token_uri": credentials.token_uri,
                    "client_id": credentials.client_id,
                    "client_secret": credentials.client_secret,
                }
            ).encode()
        ).decode()

        self.channel.oauth_credentials = {"encrypted": encrypted}
        self.channel.save(update_fields=["oauth_credentials"])

        # Fetch channel ID from API
        self._sync_channel_info()
        return {"success": True}

    def _sync_channel_info(self):
        from ***REMOVED***.services.youtube.client import YouTubeClient

        client = YouTubeClient(self.channel)
        info = client.get_my_channel()
        self.channel.youtube_channel_id = info["id"]
        self.channel.youtube_handle = info.get("snippet", {}).get("customUrl", "")
        self.channel.save()

    def validate_voice(self, voice_id: str, test_text: str = "Hello, this is a test.") -> dict:
        """Test TTS voice before committing."""
        from ***REMOVED***.services.providers.registry import get_tts_provider

        tts = get_tts_provider(self.channel)
        response = tts.synthesize(text=test_text, voice_id=voice_id)
        path = f"storage/temp/voice_test_{self.channel.slug}.mp3"
        with open(path, "wb") as f:
            f.write(response.audio_bytes)
        return {"success": True, "preview_path": path, "duration": response.duration_sec}
