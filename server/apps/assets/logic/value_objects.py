"""API DTOs for the assets app."""

import msgspec


class PresignUploadPayload(msgspec.Struct, frozen=True):
    """Input for presigned upload URL generation."""

    filename: str
    mime: str


class PresignUploadResultPayload(msgspec.Struct, frozen=True):
    """Presigned PUT URL and storage key."""

    url: str
    key: str


class LibraryAssetPayload(msgspec.Struct, frozen=True):
    """Read representation of a library asset."""

    id: str
    kind: str
    name: str
    tags: list[str]
    channel_id: str | None
    is_active: bool
    version: int
    meta: dict[str, str | int | float | bool | None]


class LibraryAssetCreatePayload(msgspec.Struct, frozen=True):
    """Register an uploaded object as a library asset."""

    kind: str
    name: str
    storage_key: str
    tags: list[str] | None = None
    channel_id: str | None = None


class LibraryAssetListPayload(msgspec.Struct, frozen=True):
    """Filtered library asset list."""

    items: list[LibraryAssetPayload]
    next_cursor: str | None
    total: int
