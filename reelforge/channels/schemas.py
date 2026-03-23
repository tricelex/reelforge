from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import RootModel


class YouTubeOAuthCredentials(BaseModel):
    """OAuth2 credentials for YouTube API access."""

    token: str = ""
    refresh_token: str = ""
    token_uri: str = ""
    client_id: str = ""
    client_secret: str = ""


# Backward-compat alias — existing imports of OAuthCredentials continue to work
OAuthCredentials = YouTubeOAuthCredentials


class TikTokOAuthCredentials(BaseModel):
    """OAuth2 credentials for TikTok API access."""

    access_token: str
    refresh_token: str
    open_id: str
    expires_in: int
    refresh_expires_in: int


class InstagramOAuthCredentials(BaseModel):
    """OAuth2 credentials for Instagram API access."""

    access_token: str
    user_id: str
    token_type: str


class UploadSlot(BaseModel):
    """A single weekly upload time slot."""

    day: str = ""  # "Monday" … "Sunday"
    time: str = ""  # "HH:MM" 24-hour
    timezone: str = ""  # IANA name e.g. "America/New_York"


class UploadSchedule(RootModel[list[UploadSlot]]):
    """Ordered list of weekly upload time slots."""

    model_config = ConfigDict(populate_by_name=True)
    root: list[UploadSlot] = []
