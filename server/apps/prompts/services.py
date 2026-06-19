"""Business logic for prompt templates and story formats."""

import uuid
from typing import final

import attrs
from django.db import transaction

from server.apps.prompts.logic.value_objects import (
    PromptTemplateCreatePayload,
    PromptTemplateDetailPayload,
    PromptTemplatePatchPayload,
    PromptVersionCreatePayload,
    PromptVersionPayload,
    StoryFormatCreatePayload,
    StoryFormatPatchPayload,
    StoryFormatPayload,
)
from server.apps.prompts.models import (
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)
from server.apps.prompts.selectors import (
    get_prompt_template,
    get_story_format,
)


def _apply_patch_fields(
    instance: object,
    payload: object,
    field_names: tuple[str, ...],
) -> list[str]:
    update_fields: list[str] = []
    for name in field_names:
        value = getattr(payload, name)
        if value is not None:
            setattr(instance, name, value)
            update_fields.append(name)
    return update_fields


@final
@attrs.define(slots=True, frozen=True)
class PromptTemplateService:
    """Create and version prompt templates."""

    def create(
        self,
        payload: PromptTemplateCreatePayload,
    ) -> PromptTemplateDetailPayload:
        """Create a prompt template."""
        template = PromptTemplate.objects.create(
            name=payload.name,
            key=payload.key,
            scope=payload.scope,
            description=payload.description,
        )
        return get_prompt_template(str(template.id))

    def patch(
        self,
        template_id: str,
        payload: PromptTemplatePatchPayload,
    ) -> PromptTemplateDetailPayload:
        """Update template metadata."""
        template = PromptTemplate.objects.get(id=uuid.UUID(template_id))
        update_fields = _apply_patch_fields(
            template,
            payload,
            ('name', 'scope', 'description'),
        )
        if update_fields:
            template.save(update_fields=update_fields)
        return get_prompt_template(str(template.id))

    def create_version(
        self,
        template_id: str,
        payload: PromptVersionCreatePayload,
    ) -> PromptVersionPayload:
        """Append a new version row."""
        template = PromptTemplate.objects.get(id=uuid.UUID(template_id))
        latest = (
            PromptVersion.objects
            .filter(template=template)
            .order_by('-version')
            .values_list('version', flat=True)
            .first()
        )
        next_version = (latest or 0) + 1
        version = PromptVersion.objects.create(
            template=template,
            version=next_version,
            system_prompt=payload.system_prompt,
            user_prompt=payload.user_prompt,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
        return PromptVersionPayload(
            id=str(version.id),
            template_id=str(template.id),
            version=version.version,
            system_prompt=version.system_prompt,
            user_prompt=version.user_prompt,
            model=version.model,
            temperature=version.temperature,
            max_tokens=version.max_tokens,
            is_active=version.is_active,
        )

    def activate_version(
        self,
        template_id: str,
        version_number: int,
    ) -> PromptVersionPayload:
        """Activate one version and deactivate siblings."""
        template = PromptTemplate.objects.get(id=uuid.UUID(template_id))
        with transaction.atomic():
            PromptVersion.objects.filter(template=template).update(
                is_active=False,
            )
            version = PromptVersion.objects.get(
                template=template,
                version=version_number,
            )
            version.is_active = True
            version.save(update_fields=['is_active'])
        return PromptVersionPayload(
            id=str(version.id),
            template_id=str(template.id),
            version=version.version,
            system_prompt=version.system_prompt,
            user_prompt=version.user_prompt,
            model=version.model,
            temperature=version.temperature,
            max_tokens=version.max_tokens,
            is_active=version.is_active,
        )


@final
@attrs.define(slots=True, frozen=True)
class StoryFormatService:
    """Create and update story formats."""

    def create(self, payload: StoryFormatCreatePayload) -> StoryFormatPayload:
        """Create a story format."""
        fmt = StoryFormat.objects.create(
            key=payload.key,
            name=payload.name,
            fiction=payload.fiction,
            narration_pov=payload.narration_pov,
            beats=payload.beats or [],
            pacing=dict(payload.pacing or {}),
            prompt_overrides=dict(payload.prompt_overrides or {}),
            music_mood_map=dict(payload.music_mood_map or {}),
        )
        return get_story_format(str(fmt.id))

    def patch(
        self,
        format_id: str,
        payload: StoryFormatPatchPayload,
    ) -> StoryFormatPayload:
        """Update story format fields."""
        fmt = StoryFormat.objects.get(id=uuid.UUID(format_id))
        update_fields = _apply_patch_fields(
            fmt,
            payload,
            ('name', 'fiction', 'narration_pov', 'is_active'),
        )
        if payload.beats is not None:
            fmt.beats = list(payload.beats)
            update_fields.append('beats')
        if payload.pacing is not None:
            fmt.pacing = dict(payload.pacing)
            update_fields.append('pacing')
        if payload.prompt_overrides is not None:
            fmt.prompt_overrides = dict(payload.prompt_overrides)
            update_fields.append('prompt_overrides')
        if payload.music_mood_map is not None:
            fmt.music_mood_map = dict(payload.music_mood_map)
            update_fields.append('music_mood_map')
        if update_fields:
            fmt.save(update_fields=update_fields)
        return get_story_format(str(fmt.id))
