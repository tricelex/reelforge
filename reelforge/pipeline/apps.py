from django.apps import AppConfig


class PipelineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reelforge.pipeline"

    def ready(self) -> None:
        import reelforge.pipeline.signals  # noqa: F401
