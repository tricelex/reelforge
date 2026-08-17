"""Dependency injection wiring — registers all concrete implementations."""

from punq import Container, Scope


def _inject_django(container: Container) -> None:
    from django.conf import LazySettings, settings

    container.register(
        LazySettings,
        instance=settings,
        scope=Scope.singleton,
    )


def _inject_main(container: Container) -> None:
    from server.apps.main.services import BlogPostService
    from server.common.events import EventBus, InProcessEventBus

    container.register(EventBus, instance=InProcessEventBus())
    container.register(BlogPostService, scope=Scope.singleton)


def _inject_clips(container: Container) -> None:
    from server.apps.clips.services import ClipsService
    from server.apps.clips.source_services import ClipSourceService

    container.register(ClipsService, scope=Scope.singleton)
    container.register(ClipSourceService, scope=Scope.singleton)


def _inject_pipelines(container: Container) -> None:
    from server.apps.pipelines.services import PipelineRunService
    from server.apps.pipelines.services.blueprint import BlueprintService
    from server.apps.pipelines.services.editor_package import (
        EditorPackageService,
    )
    from server.apps.pipelines.services.run_cast import RunCastService
    from server.apps.pipelines.services.run_review import RunReviewService

    container.register(PipelineRunService, scope=Scope.singleton)
    container.register(BlueprintService, scope=Scope.singleton)
    container.register(RunCastService, scope=Scope.singleton)
    container.register(RunReviewService, scope=Scope.singleton)
    container.register(EditorPackageService, scope=Scope.singleton)


def _inject_channels(container: Container) -> None:
    from server.apps.channels.character_studio import CharacterStudioService
    from server.apps.channels.services import ChannelService

    container.register(ChannelService, scope=Scope.singleton)
    container.register(CharacterStudioService, scope=Scope.singleton)


def _inject_assets(container: Container) -> None:
    from server.apps.assets.services import UploadService
    from server.common.storage import PresignUrlHelper

    container.register(PresignUrlHelper, scope=Scope.singleton)
    container.register(UploadService, scope=Scope.singleton)


def _inject_prompts(container: Container) -> None:
    from server.apps.prompts.services import (
        PromptTemplateService,
        StoryFormatService,
    )

    container.register(PromptTemplateService, scope=Scope.singleton)
    container.register(StoryFormatService, scope=Scope.singleton)


def _inject_ideas(container: Container) -> None:
    from server.apps.ideas.services import IdeationService

    container.register(IdeationService, scope=Scope.singleton)


def _inject_campaigns(container: Container) -> None:
    from server.apps.clips.brand_template_services import (
        ClipBrandTemplateService,
    )
    from server.apps.clips.campaign_services import ClipCampaignService

    container.register(ClipCampaignService, scope=Scope.singleton)
    container.register(ClipBrandTemplateService, scope=Scope.singleton)


def populate_dependencies(container: Container) -> Container:
    """Populate the container with all application dependencies."""
    _inject_django(container)
    _inject_main(container)
    _inject_clips(container)
    _inject_pipelines(container)
    _inject_channels(container)
    _inject_assets(container)
    _inject_prompts(container)
    _inject_ideas(container)
    _inject_campaigns(container)
    return container
