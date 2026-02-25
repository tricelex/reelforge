from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "***REMOVED***.research"

    def ready(self) -> None:
        import ***REMOVED***.research.signals  # noqa: F401
