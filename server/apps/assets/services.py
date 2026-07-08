"""Business logic for library assets and presigned uploads."""

import mimetypes
import uuid
from typing import final

import attrs

from server.apps.assets.logic.events import LibraryAssetIngested
from server.apps.assets.logic.value_objects import (
    LibraryAssetCreatePayload,
    LibraryAssetListPayload,
    LibraryAssetPatchPayload,
    LibraryAssetPayload,
    PresignUploadPayload,
    PresignUploadResultPayload,
)
from server.apps.assets.models import LibraryAsset
from server.common.events import EventBus
from server.common.pagination import paginate_queryset
from server.common.storage import PresignUrlHelper


def _guess_mime(filename: str) -> str:
    """Return a MIME type guess for a storage key or filename."""
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or ''


def _to_payload(
    asset: LibraryAsset,
    presign: PresignUrlHelper,
) -> LibraryAssetPayload:
    meta = {
        key: value
        for key, value in dict(asset.meta).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    url = ''
    if asset.file:
        url = presign.presign_get(asset.file.name or '')
    return LibraryAssetPayload(
        id=str(asset.id),
        kind=asset.kind,
        name=asset.name,
        url=url,
        mime=asset.mime or _guess_mime(asset.file.name or ''),
        tags=list(asset.tags),
        channel_id=str(asset.channel_id) if asset.channel_id else None,
        is_active=asset.is_active,
        version=asset.version,
        meta=meta,
        license_type=asset.license_type,
        license_note=asset.license_note,
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
        key = f'library/{uuid.uuid4()}/{payload.filename}'
        url = self._presign.presign_put(key, payload.mime)
        return PresignUploadResultPayload(url=url, key=key)


@final
@attrs.define(slots=True, frozen=True)
class LibraryAssetService:
    """Manages library asset registration and metadata."""

    _events: EventBus
    _presign: PresignUrlHelper

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
            items=[_to_payload(a, self._presign) for a in rows],
            next_cursor=next_cursor,
            total=total,
        )

    def get_by_id(self, asset_id: str) -> LibraryAssetPayload:
        """Return one library asset."""
        from server.apps.assets.models import LibraryAsset  # noqa: PLC0415

        return _to_payload(
            LibraryAsset.objects.get(id=asset_id),
            self._presign,
        )

    def register_from_key(
        self,
        payload: LibraryAssetCreatePayload,
    ) -> LibraryAssetPayload:
        """Register a presigned-uploaded object and queue ingest."""
        from server.apps.assets.models import (  # noqa: PLC0415
            LibraryAsset,
            LibraryAssetLicense,
        )

        asset = LibraryAsset.objects.create(
            kind=payload.kind,
            name=payload.name,
            tags=payload.tags or [],
            channel_id=(
                uuid.UUID(payload.channel_id) if payload.channel_id else None
            ),
            file=payload.storage_key,
            mime=payload.mime or _guess_mime(payload.storage_key),
            license_type=(
                payload.license_type or LibraryAssetLicense.UNSPECIFIED
            ),
            license_note=payload.license_note or '',
        )
        self._events.emit(LibraryAssetIngested(asset_id=str(asset.id)))
        return _to_payload(asset, self._presign)

    def patch(
        self,
        asset_id: str,
        payload: LibraryAssetPatchPayload,
    ) -> LibraryAssetPayload:
        """Update a library asset's licensing fields."""
        from server.apps.assets.models import LibraryAsset  # noqa: PLC0415

        asset = LibraryAsset.objects.get(id=uuid.UUID(asset_id))
        update_fields: list[str] = []
        if payload.license_type is not None:
            asset.license_type = payload.license_type
            update_fields.append('license_type')
        if payload.license_note is not None:
            asset.license_note = payload.license_note
            update_fields.append('license_note')
        if update_fields:
            asset.save(update_fields=update_fields)
        return _to_payload(asset, self._presign)
