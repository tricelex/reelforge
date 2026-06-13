"""Pydantic value objects for the assets app."""

from typing import Any, final
from uuid import UUID

from pydantic import BaseModel


@final
class LibraryAssetRegisterPayload(BaseModel):
    """Input for registering a new library asset."""

    kind: str
    name: str
    tags: list[str] = []
    channel_id: UUID | None = None


@final
class LibraryAssetPayload(BaseModel):
    """Output representation of a library asset."""

    id: UUID
    kind: str
    name: str
    tags: list[str]
    is_active: bool
    version: int
    meta: dict[str, Any]
