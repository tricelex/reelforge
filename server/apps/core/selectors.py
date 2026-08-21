"""Read-only selectors for the core app."""

from django.db import models

from server.apps.core.logic.value_objects import EnumOptionPayload, EnumsPayload


def _choices_to_options(
    choices: type[models.Choices],
) -> list[EnumOptionPayload]:
    return [
        EnumOptionPayload(value=str(value), label=str(label))
        for value, label in choices.choices
    ]


def collect_enums() -> EnumsPayload:
    """Collect TextChoices enums exposed to the frontend."""
    from server.apps.channel_research.logic.constants import (  # noqa: PLC0415
        ChannelResearchKind,
        ChannelResearchStatus,
        VisualMedium,
    )
    from server.apps.channels.models import (  # noqa: PLC0415
        ChannelKind,
        CharacterDesignMode,
        CharacterOrigin,
        CharacterStatus,
        PublishMode,
    )
    from server.apps.clips.logic.constants import (  # noqa: PLC0415
        CandidateStatus,
        CaptionAnimation,
        CaptionPosition,
        CaptionStyle,
        ClipSourceStatus,
        ClipSourceType,
        HookStyle,
        OverlayType,
        PostStatus,
        ProgressBarPosition,
        RenderFormat,
        RenderMode,
        TransitionStyle,
        WatermarkPosition,
        WatermarkType,
    )
    from server.apps.core.logic.constants import UserRole  # noqa: PLC0415
    from server.apps.pipelines.models import (  # noqa: PLC0415
        CastDesignStatus,
        PipelineKind,
        RunStatus,
        StageStatus,
    )
    from server.apps.publishing.models import PublishStatus  # noqa: PLC0415

    registry: dict[str, type[models.Choices]] = {
        'UserRole': UserRole,
        'ChannelKind': ChannelKind,
        'PublishMode': PublishMode,
        'CharacterDesignMode': CharacterDesignMode,
        'CharacterStatus': CharacterStatus,
        'CharacterOrigin': CharacterOrigin,
        'ChannelResearchStatus': ChannelResearchStatus,
        'ChannelResearchKind': ChannelResearchKind,
        'VisualMedium': VisualMedium,
        'PipelineKind': PipelineKind,
        'RunStatus': RunStatus,
        'StageStatus': StageStatus,
        'CastDesignStatus': CastDesignStatus,
        'PublishStatus': PublishStatus,
        'CandidateStatus': CandidateStatus,
        'ClipSourceStatus': ClipSourceStatus,
        'ClipSourceType': ClipSourceType,
        'PostStatus': PostStatus,
        'RenderMode': RenderMode,
        'RenderFormat': RenderFormat,
        'CaptionStyle': CaptionStyle,
        'CaptionPosition': CaptionPosition,
        'CaptionAnimation': CaptionAnimation,
        'HookStyle': HookStyle,
        'TransitionStyle': TransitionStyle,
        'WatermarkType': WatermarkType,
        'WatermarkPosition': WatermarkPosition,
        'ProgressBarPosition': ProgressBarPosition,
        'OverlayType': OverlayType,
    }
    return EnumsPayload(
        enums={
            name: _choices_to_options(choices)
            for name, choices in registry.items()
        },
    )
