from typing import override

from django.apps import AppConfig


class AssetsConfig(AppConfig):
    """AppConfig for the assets app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.assets'
    verbose_name = 'Assets'

    @override
    def ready(self) -> None:
        """Register assets DI bindings and subscribe event handlers."""
        from punq import Scope

        from server.apps.assets.logic.events import LibraryAssetIngested
        from server.apps.assets.services import LibraryAssetService
        from server.apps.assets.tasks import handle_library_asset_ingested
        from server.common import container as container_module
        from server.common.events import EventBus

        container_module.container.register(
            LibraryAssetService,
            scope=Scope.singleton,
        )
        bus = container_module.container.resolve(EventBus)
        bus.subscribe(LibraryAssetIngested, handle_library_asset_ingested)
