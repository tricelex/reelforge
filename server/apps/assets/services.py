"""Business logic for library assets and presigned uploads."""

import uuid
from typing import final

import attrs

from server.apps.assets.logic.events import LibraryAssetIngested
from server.apps.assets.logic.value_objects import (
    LibraryAssetCreatePayload,
    LibraryAssetListPayload,
    LibraryAssetPayload,
    PresignUploadPayload,
    PresignUploadResultPayload,
)
from server.apps.assets.models import LibraryAsset
from server.common.events import EventBus
from server.common.pagination import paginate_queryset
from server.common.storage import PresignUrlHelper


def _to_payload(asset: LibraryAsset) -> LibraryAssetPayload:
    meta = {
        key: value
        for key, value in dict(asset.meta).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    return LibraryAssetPayload(
        id=str(asset.id),
        kind=asset.kind,
        name=asset.name,
        tags=list(asset.tags),
        channel_id=str(asset.channel_id) if asset.channel_id else None,
        is_active=asset.is_active,
        version=asset.version,
        meta=meta,
    )


@final
@attrs.define(slots=True, frozen=True)
class UploadService:
    """Presigned upload URL generation."""

    _presign: PresignUrlHelper

    def presign_put(
        self,
        payload: PresignUploadPayload,
    ) -> PresignUploadResultPayload:
        """Return a presigned PUT URL and storage key."""
        key = f'uploads/{uuid.uuid4()}/{payload.filename}'
        url = self._presign.presign_put(key, payload.mime)
        return PresignUploadResultPayload(url=url, key=key)


@final
@attrs.define(slots=True, frozen=True)
class LibraryAssetService:
    """Manages library asset registration and metadata."""

    _events: EventBus

    def list_assets(
        self,
        *,
        kind: str | None = None,
        channel_id: str | None = None,
        tag: str | None = None,
        active_only: bool = True,
        cursor: str | None = None,
        limit: int = 20,
    ) -> LibraryAssetListPayload:
        """Return library assets with optional filters."""
        qs = LibraryAsset.objects.order_by('-created_at', '-id')
        if active_only:
            qs = qs.filter(is_active=True)
        if kind:
            qs = qs.filter(kind=kind)
        if channel_id:
            qs = qs.filter(channel_id=uuid.UUID(channel_id))
        if tag:
            qs = qs.filter(tags__contains=[tag])
        rows, next_cursor, total = paginate_queryset(
            qs,
            cursor=cursor,
            limit=limit,
        )
        return LibraryAssetListPayload(
            items=[_to_payload(a) for a in rows],
            next_cursor=next_cursor,
            total=total,
        )

    def get_by_id(self, asset_id: str) -> LibraryAssetPayload:
        """Return one library asset."""
        from server.apps.assets.models import LibraryAsset  # noqa: PLC0415

        return _to_payload(LibraryAsset.objects.get(id=asset_id))

    def register_from_key(
        self,
        payload: LibraryAssetCreatePayload,
    ) -> LibraryAssetPayload:
        """Register a presigned-uploaded object and queue ingest."""
        from server.apps.assets.models import LibraryAsset  # noqa: PLC0415

        asset = LibraryAsset.objects.create(
            kind=payload.kind,
            name=payload.name,
            tags=payload.tags or [],
            channel_id=(
                uuid.UUID(payload.channel_id)
                if payload.channel_id
                else None
            ),
            file=payload.storage_key,
        )
        self._events.emit(LibraryAssetIngested(asset_id=str(asset.id)))
        return _to_payload(asset)
