import attrs


@attrs.define(frozen=True)
class LibraryAssetIngested:
    asset_id: str
