from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.apps.assets.models import Asset
    from server.apps.pipelines.models import StageExecution


class AssetWriter:
    """Persists pipeline-generated files to S3 and creates Asset rows."""

    def __init__(self, execution: 'StageExecution') -> None:
        """Initialise with the StageExecution that will own generated assets."""
        self._execution = execution

    async def save(
        self,
        kind: str,
        content: bytes,
        filename: str,
        mime: str,
    ) -> 'Asset':
        """Upload content bytes to S3 and return a saved Asset row."""
        import hashlib  # noqa: PLC0415

        from django.core.files.base import ContentFile  # noqa: PLC0415

        from server.apps.assets.models import Asset  # noqa: PLC0415

        checksum = hashlib.sha256(content).hexdigest()
        asset = Asset(
            kind=kind,
            mime=mime,
            checksum=checksum,
            run=self._execution.run,
            stage_execution=self._execution,
        )
        asset.file.save(filename, ContentFile(content), save=False)
        await asset.asave()
        return asset
