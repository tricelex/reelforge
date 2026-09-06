"""Atomic ChannelSpec importer (cross-app orchestrator)."""

from typing import final

import attrs
import msgspec
import pydantic
from django.core.exceptions import ValidationError
from django.db import transaction

try:
    # zeal is a development-only dependency (django-zeal's N+1 raiser is
    # only wired up in server.settings.environments.development). Fall back
    # to a no-op so this production module stays importable without it.
    from zeal import zeal_ignore
except ModuleNotFoundError:
    from contextlib import nullcontext as zeal_ignore

from server.apps.channel_research.logic.schemas import (
    ChannelSpecModel,
    validate_channel_spec,
    validate_medium_lock,
)
from server.apps.channel_research.logic.value_objects import (
    ChannelSpecImportResultPayload,
    ChannelSpecImportStepPayload,
    ChannelSpecPayload,
    ChannelSpecPromptTemplatePayload,
)
from server.apps.channels.character_studio import CharacterStudioService
from server.apps.channels.logic.value_objects import (
    AssemblyStyleConfigPatchPayload,
    ChannelBrandingPatchPayload,
    ChannelCreatePayload,
    ChannelPatchPayload,
    CharacterCreatePayload,
    FootageSourcingPatchPayload,
    NicheCreatePayload,
    ProviderDailyCapPayload,
)
from server.apps.channels.models import CharacterStatus, NicheConfig
from server.apps.channels.services import ChannelService
from server.apps.ideas.logic.constants import IdeaStatus
from server.apps.ideas.models import TopicIdea
from server.apps.prompts.logic.value_objects import (
    JsonObject,
    PromptTemplateCreatePayload,
    PromptVersionCreatePayload,
    StoryFormatCreatePayload,
)
from server.apps.prompts.models import PromptTemplate, StoryFormat
from server.apps.prompts.services import (
    PromptTemplateService,
    StoryFormatService,
)
from server.common.transition_styles import HARD_CUT

MAX_PROMPT_TEMPLATES = 40
MAX_SEED_IDEAS = 50


def _normalize_transition_style(style: str) -> str:
    """Map non-canonical spellings to ***REMOVED***'s snake_case vocabulary.

    Import specs come from external tooling that doesn't always follow
    server.common.transition_styles' naming (e.g. hyphens instead of
    underscores, or 'cut' instead of 'hard_cut').
    """
    normalized = style.replace('-', '_')
    return HARD_CUT if normalized == 'cut' else normalized


def _normalized_payload(payload: ChannelSpecPayload) -> ChannelSpecPayload:
    """Normalize transition style names before schema validation runs.

    Must happen before _validate_before_write, not merely before the
    write itself - validate_channel_spec rejects unknown transition
    styles outright, so a hyphenated/shorthand name needs to already be
    canonical by the time that check sees it.
    """
    assembly = payload.assembly_style
    normalized_styles = [
        _normalize_transition_style(style)
        for style in assembly.transition_styles
    ]
    if normalized_styles == list(assembly.transition_styles):
        return payload
    return msgspec.structs.replace(
        payload,
        assembly_style=msgspec.structs.replace(
            assembly,
            transition_styles=normalized_styles,
        ),
    )


def _step(
    name: str,
    detail: str,
    *,
    ok: bool = True,
) -> ChannelSpecImportStepPayload:
    return ChannelSpecImportStepPayload(name=name, ok=ok, detail=detail)


def _spec_model(payload: ChannelSpecPayload) -> ChannelSpecModel:
    try:
        return ChannelSpecModel.model_validate(
            msgspec.to_builtins(payload),
        )
    except pydantic.ValidationError as exc:
        raise ValidationError(str(exc)) from exc


def _validate_before_write(payload: ChannelSpecPayload) -> None:
    spec = _spec_model(payload)
    try:
        validate_channel_spec(spec)
        validate_medium_lock(spec)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _ensure_format(
    spec: ChannelSpecPayload,
) -> tuple[str | None, ChannelSpecImportStepPayload]:
    key = spec.story_format.key or spec.niche.format_key
    if not key:
        return None, _step('story_format', 'Skipped')
    existing = StoryFormat.objects.filter(key=key).first()
    if existing is not None:
        return str(existing.id), _step(
            'story_format',
            f'Reused format {existing.id}',
        )
    if spec.story_format.create_if_missing is False:
        return None, _step('story_format', 'Reused or skipped')
    beats: list[JsonObject] = [
        {'name': beat.name, 'description': beat.description}
        for beat in spec.story_format.beats
    ]
    created = StoryFormatService().create(
        StoryFormatCreatePayload(
            key=spec.story_format.key,
            name=spec.story_format.name,
            fiction=spec.story_format.fiction,
            narration_pov=spec.story_format.narration_pov,
            beats=beats,
            pacing=dict(spec.story_format.pacing),
            prompt_overrides=dict(spec.story_format.prompt_overrides),
            music_mood_map=dict(spec.story_format.music_mood_map),
        ),
    )
    return created.id, _step('story_format', f'Attached format {created.id}')


def _create_one_template(
    template: ChannelSpecPromptTemplatePayload,
    existing_keys: set[str],
    prompts: PromptTemplateService,
) -> bool:
    if template.key in existing_keys:
        return False
    created = prompts.create(
        PromptTemplateCreatePayload(
            name=template.name,
            key=template.key,
            scope=template.scope,
            description=template.description,
        ),
    )
    version = prompts.create_version(
        created.id,
        PromptVersionCreatePayload(
            system_prompt=template.system_prompt,
            user_prompt=template.user_prompt,
            model=template.model,
            temperature=template.temperature,
            max_tokens=template.max_tokens,
        ),
    )
    prompts.activate_version(created.id, version.version)
    existing_keys.add(template.key)
    return True


def _ensure_prompt_templates(
    spec: ChannelSpecPayload,
) -> ChannelSpecImportStepPayload:
    templates = spec.prompt_templates[:MAX_PROMPT_TEMPLATES]
    if not templates:
        return _step('prompt_templates', 'Created 0 templates')
    existing_keys = set(
        PromptTemplate.objects.filter(
            key__in=[item.key for item in templates],
        ).values_list('key', flat=True),
    )
    prompts = PromptTemplateService()
    created_count = 0
    for template in templates:
        if _create_one_template(template, existing_keys, prompts):
            created_count += 1
    return _step(
        'prompt_templates',
        f'Created {created_count} templates',
    )


def _niche_create(
    spec: ChannelSpecPayload,
    format_id: str | None,
) -> NicheCreatePayload:
    return NicheCreatePayload(
        format_id=format_id,
        audience=spec.niche.audience,
        angle=spec.niche.angle,
        banned_topics=list(spec.niche.banned_topics),
        lore_document=spec.niche.lore_document,
        visual_bible=spec.niche.visual_bible,
        visual_medium=spec.niche.visual_medium or '',
        style_tokens=list(spec.niche.style_tokens),
        style_negatives=list(spec.niche.style_negatives),
    )


def _create_channel(
    spec: ChannelSpecPayload,
    format_id: str | None,
) -> tuple[str, str | None, ChannelSpecImportStepPayload]:
    channel = spec.channel
    caps = [
        ProviderDailyCapPayload(
            provider=cap.provider,
            daily_cap_usd=str(cap.daily_cap_usd),
        )
        for cap in channel.provider_daily_caps
    ]
    detail = ChannelService().create(
        ChannelCreatePayload(
            name=channel.name,
            kind=channel.kind,
            publish_mode=channel.publish_mode,
            gates=list(channel.gates),
            character_design_mode=channel.character_design_mode,
            default_budget_usd=channel.default_budget_usd,
            voice_id=channel.voice_id,
            stability=channel.stability,
            similarity_boost=channel.similarity_boost,
            wpm=channel.wpm,
            default_blueprint_name=channel.default_blueprint_name,
            provider_daily_caps=caps,
            config_overrides=dict(channel.config_overrides),
            niche=_niche_create(spec, format_id),
            max_publishes_per_day=channel.max_publishes_per_day,
        ),
    )
    niche = NicheConfig.objects.filter(channel_id=detail.id).first()
    niche_id = str(niche.id) if niche is not None else None
    return (
        detail.id,
        niche_id,
        _step('channel', channel.name),
    )


def _apply_optional_config(
    channel_id: str,
    spec: ChannelSpecPayload,
) -> ChannelSpecImportStepPayload:
    channels = ChannelService()
    branding = spec.branding
    channels.patch_branding(
        channel_id,
        ChannelBrandingPatchPayload(
            watermark_position=branding.watermark_position,
            watermark_opacity=branding.watermark_opacity,
            music_pool_tags=list(branding.music_pool_tags),
            thumbnail_palette=dict(branding.thumbnail_palette),
        ),
    )
    assembly = spec.assembly_style
    channels.patch_assembly_style(
        channel_id,
        AssemblyStyleConfigPatchPayload(
            camera_movements=list(assembly.camera_movements),
            transition_styles=list(assembly.transition_styles),
            sfx_pool_tags=list(assembly.sfx_pool_tags),
            min_cuts_per_minute=assembly.min_cuts_per_minute,
            max_cuts_per_minute=assembly.max_cuts_per_minute,
            music_bed_gain_db=assembly.music_bed_gain_db,
            enable_background_music=assembly.enable_background_music,
        ),
    )
    footage = spec.footage_sourcing
    channels.patch(
        channel_id,
        ChannelPatchPayload(
            footage_sourcing=FootageSourcingPatchPayload(
                enabled_providers=list(footage.enabled_providers),
                sourcing_mode=footage.sourcing_mode,
                ai_fallback_enabled=footage.ai_fallback_enabled,
                max_ai_fallback_per_run=footage.max_ai_fallback_per_run,
                rerank_mode=footage.rerank_mode,
                candidates_per_scene=footage.candidates_per_scene,
                min_clip_width=footage.min_clip_width,
                min_clip_duration_s=footage.min_clip_duration_s,
                allowed_licenses=list(footage.allowed_licenses),
                require_attribution=footage.require_attribution,
            ),
        ),
    )
    return _step('config', 'Branding, assembly, footage, niche')


def _seed_character_and_ideas(
    channel_id: str,
    niche_id: str | None,
    spec: ChannelSpecPayload,
) -> ChannelSpecImportStepPayload:
    character = spec.character
    if character.include and character.name.strip():
        status = character.status or CharacterStatus.APPROVED
        CharacterStudioService().create(
            CharacterCreatePayload(
                name=character.name,
                channel_id=channel_id,
                appearance_prompt=character.appearance_prompt,
                persona=character.persona,
                status=status,
            ),
        )
    seeds = spec.seed_ideas[:MAX_SEED_IDEAS]
    for idea in seeds:
        TopicIdea.objects.create(
            channel_id=channel_id,
            niche_id=niche_id,
            title=idea.title[:200],
            topic=idea.topic,
            score=idea.score,
            status=IdeaStatus.BACKLOG,
            metadata={'source_type': 'channel_spec'},
        )
    return _step('seeds', f'{len(seeds)} ideas')


@final
@attrs.define(slots=True, frozen=True)
class ChannelSpecImporter:
    """Import a ChannelSpec in one atomic transaction. Does not call fal."""

    def import_spec(
        self,
        payload: ChannelSpecPayload,
    ) -> ChannelSpecImportResultPayload:
        """Validate then write format, templates, channel, config, seeds."""
        payload = _normalized_payload(payload)
        _validate_before_write(payload)
        # Sequential ChannelService create/patch reloads are intentional,
        # not a loop N+1 — suppress zeal for this orchestrator only.
        with transaction.atomic(), zeal_ignore():
            format_id, format_step = _ensure_format(payload)
            template_step = _ensure_prompt_templates(payload)
            channel_id, niche_id, channel_step = _create_channel(
                payload,
                format_id,
            )
            config_step = _apply_optional_config(channel_id, payload)
            seed_step = _seed_character_and_ideas(
                channel_id,
                niche_id,
                payload,
            )
        return ChannelSpecImportResultPayload(
            channel_id=channel_id,
            steps=[
                format_step,
                template_step,
                channel_step,
                config_step,
                seed_step,
            ],
        )


def import_channel_spec(
    payload: ChannelSpecPayload,
) -> ChannelSpecImportResultPayload:
    """Module-level entry used by the channel-research import controller."""
    return ChannelSpecImporter().import_spec(payload)
