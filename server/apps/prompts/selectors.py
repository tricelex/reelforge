"""Read-only query helpers for prompts."""

from server.apps.prompts.logic.value_objects import (
    PromptTemplateDetailPayload,
    PromptTemplateListPayload,
    PromptTemplateSummaryPayload,
    PromptVersionListPayload,
    PromptVersionPayload,
    StoryFormatListPayload,
    StoryFormatPayload,
)
from server.apps.prompts.models import (
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)
from server.common.pagination import paginate_queryset


def _active_version_number(template: PromptTemplate) -> int | None:
    return (
        PromptVersion.objects
        .filter(template=template, is_active=True)
        .values_list('version', flat=True)
        .first()
    )


def _to_template_summary(
    template: PromptTemplate,
) -> PromptTemplateSummaryPayload:
    return PromptTemplateSummaryPayload(
        id=str(template.id),
        name=template.name,
        key=template.key,
        scope=template.scope,
        description=template.description,
        active_version=_active_version_number(template),
    )


def list_prompt_templates(
    *,
    scope: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> PromptTemplateListPayload:
    """Return prompt templates with cursor pagination."""
    qs = PromptTemplate.objects.order_by('-created_at', '-id')
    if scope:
        qs = qs.filter(scope=scope)
    rows, next_cursor, total = paginate_queryset(
        qs,
        cursor=cursor,
        limit=limit,
    )
    return PromptTemplateListPayload(
        items=[_to_template_summary(t) for t in rows],
        next_cursor=next_cursor,
        total=total,
    )


def get_prompt_template(template_id: str) -> PromptTemplateDetailPayload:
    """Return one prompt template."""
    template = PromptTemplate.objects.get(id=template_id)
    return PromptTemplateDetailPayload(
        id=str(template.id),
        name=template.name,
        key=template.key,
        scope=template.scope,
        description=template.description,
        active_version=_active_version_number(template),
    )


def _to_version(version: PromptVersion) -> PromptVersionPayload:
    return PromptVersionPayload(
        id=str(version.id),
        template_id=str(version.template_id),
        version=version.version,
        system_prompt=version.system_prompt,
        user_prompt=version.user_prompt,
        model=version.model,
        temperature=version.temperature,
        max_tokens=version.max_tokens,
        is_active=version.is_active,
    )


def list_prompt_versions(template_id: str) -> PromptVersionListPayload:
    """Return versions for a template."""
    items = [
        _to_version(v)
        for v in PromptVersion.objects.filter(
            template_id=template_id,  # type: ignore[misc]
        ).order_by('-version')
    ]
    return PromptVersionListPayload(items=items, total=len(items))


def _to_story_format(fmt: StoryFormat) -> StoryFormatPayload:
    return StoryFormatPayload(
        id=str(fmt.id),
        key=fmt.key,
        name=fmt.name,
        fiction=fmt.fiction,
        narration_pov=fmt.narration_pov,
        beats=_json_beats(fmt.beats),
        pacing=_json_object(fmt.pacing),
        prompt_overrides=_json_object(fmt.prompt_overrides),
        music_mood_map=_json_object(fmt.music_mood_map),
        is_active=fmt.is_active,
    )


JsonMap = dict[str, str | int | float | bool | list[str] | None]


def _scalar_json(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
    ) or isinstance(value, (str, int, float, bool)) or value is None


def _json_object(data: object) -> JsonMap:
    if not isinstance(data, dict):
        return {}
    return {
        key: value
        for key, value in data.items()
        if _scalar_json(value)
    }


def _json_beats(data: object) -> list[JsonMap]:
    if not isinstance(data, list):
        return []
    return [
        _json_object(item)
        for item in data
        if isinstance(item, dict)
    ]


def list_story_formats(
    *,
    active_only: bool = False,
    cursor: str | None = None,
    limit: int = 20,
) -> StoryFormatListPayload:
    """Return story formats with cursor pagination."""
    qs = StoryFormat.objects.order_by('-created_at', '-id')
    if active_only:
        qs = qs.filter(is_active=True)
    rows, next_cursor, total = paginate_queryset(
        qs,
        cursor=cursor,
        limit=limit,
    )
    return StoryFormatListPayload(
        items=[_to_story_format(f) for f in rows],
        next_cursor=next_cursor,
        total=total,
    )


def get_story_format(format_id: str) -> StoryFormatPayload:
    """Return one story format."""
    return _to_story_format(StoryFormat.objects.get(id=format_id))
