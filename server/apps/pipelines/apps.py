from typing import override

from django.apps import AppConfig


class PipelinesConfig(AppConfig):
    """Django app config for the pipelines engine."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.pipelines'
    verbose_name = 'Pipelines'

    @override
    def ready(self) -> None:
        """Register all pipeline stage classes."""
        import server.apps.pipelines.stages.alignment  # noqa: F401
        import server.apps.pipelines.stages.assembly  # noqa: F401
        import server.apps.pipelines.stages.dummy  # noqa: F401
        import server.apps.pipelines.stages.image_gen  # noqa: F401
        import server.apps.pipelines.stages.metadata  # noqa: F401
        import server.apps.pipelines.stages.motion  # noqa: F401
        import server.apps.pipelines.stages.music_plan  # noqa: F401
        import server.apps.pipelines.stages.outline  # noqa: F401
        import server.apps.pipelines.stages.publish  # noqa: F401
        import server.apps.pipelines.stages.qc  # noqa: F401
        import server.apps.pipelines.stages.research  # noqa: F401
        import server.apps.pipelines.stages.review_gate  # noqa: F401
        import server.apps.pipelines.stages.scene_breakdown  # noqa: F401
        import server.apps.pipelines.stages.script  # noqa: F401
        import server.apps.pipelines.stages.thumbnail  # noqa: F401
        import server.apps.pipelines.stages.tts  # noqa: F401
        import server.apps.pipelines.stages.visual_prompts  # noqa: F401
