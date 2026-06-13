from typing import Any, final

import attrs

from server.apps.assets.logic.events import LibraryAssetIngested
from server.apps.assets.logic.value_objects import (
    LibraryAssetPayload,
    LibraryAssetRegisterPayload,
)
from server.apps.assets.models import LibraryAsset
from server.common.events import EventBus


@final
@attrs.define(slots=True, frozen=True)
class LibraryAssetService:
    """Manages library asset registration and metadata."""

    _events: EventBus

    def register(
        self,
        payload: LibraryAssetRegisterPayload,
        file: Any,
    ) -> LibraryAssetPayload:
        """Persist a new library asset and queue the ingest pipeline."""
        asset = LibraryAsset.objects.create(
            kind=payload.kind,
            name=payload.name,
            tags=payload.tags,
            channel_id=payload.channel_id,
            file=file,
        )
        self._events.emit(LibraryAssetIngested(asset_id=str(asset.id)))
        return LibraryAssetPayload(
            id=asset.id,
            kind=asset.kind,
            name=asset.name,
            tags=asset.tags,
            is_active=asset.is_active,
            version=asset.version,
            meta=asset.meta,
        )
