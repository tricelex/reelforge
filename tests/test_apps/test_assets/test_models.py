from server.common.s3 import AssetStorage


def test_asset_storage_class_is_importable() -> None:
    assert AssetStorage is not None
