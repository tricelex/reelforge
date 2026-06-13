from typing import final
from uuid import UUID

from pydantic import BaseModel


@final
class LibraryAssetRegisterPayload(BaseModel):
    kind: str
    name: str
    tags: list[str] = []
    channel_id: UUID | None = None


@final
class LibraryAssetPayload(BaseModel):
    id: UUID
    kind: str
    name: str
    tags: list[str]
    is_active: bool
    version: int
    meta: dict
