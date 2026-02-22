from django.apps import AppConfig


class PipelineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "***REMOVED***.pipeline"

    def ready(self) -> None:
        import ***REMOVED***.pipeline.signals  # noqa: F401
