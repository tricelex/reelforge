from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import RootModel


class OAuthCredentials(BaseModel):
    """OAuth2 credentials for YouTube API access."""

    token: str = ""
    refresh_token: str = ""
    token_uri: str = ""
    client_id: str = ""
    client_secret: str = ""


class UploadSlot(BaseModel):
    """A single weekly upload time slot."""

    day: str = ""  # "Monday" … "Sunday"
    time: str = ""  # "HH:MM" 24-hour
    timezone: str = ""  # IANA name e.g. "America/New_York"


class UploadSchedule(RootModel[list[UploadSlot]]):
    """Ordered list of weekly upload time slots."""

    model_config = ConfigDict(populate_by_name=True)
    root: list[UploadSlot] = []
