"""Domain events for the assets app."""

import attrs


@attrs.define(frozen=True)
class LibraryAssetIngested:
    """Emitted after a LibraryAsset has been queued for ingest."""

    asset_id: str
