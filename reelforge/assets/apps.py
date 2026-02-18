from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AssetsConfig(AppConfig):
    name = "***REMOVED***.assets"
    verbose_name = _("Assets")

    def ready(self) -> None:
        """Override this to run code when Django starts."""
