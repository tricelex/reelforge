"""Render-check ChannelSpec prompt templates before they are trusted.

A channel-research spec's ``prompt_templates`` become live Jinja2 templates
the very first time a pipeline run renders them — there is no earlier
opportunity to catch a typo'd variable name or a template that forgot to
reference the outline it's supposed to narrate. This module renders every
template against a realistic dummy context (mirroring exactly what
``server.apps.pipelines.services.prompt_variables.build_prompt_variables``
hands each stage at runtime) so those mistakes surface here instead of in a
half-finished production run.

``server.apps.channel_research`` cannot import ``server.apps.pipelines``
(apps are independent - see .importlinter), so the per-stage variable shapes
below are hand-mirrored, not imported. If a stage's real variable set
changes, update its entry here too:
  - base set: server/apps/pipelines/services/prompt_variables.py
    (``build_prompt_variables``)
  - per-stage extras: each stage's ``build_prompt_variables(ctx, extra=...)``
    call site under server/apps/pipelines/stages/
"""

from typing import TYPE_CHECKING, Any

from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

if TYPE_CHECKING:
    from server.apps.channel_research.logic.schemas import (
        ChannelSpecModel,
        PromptTemplateBlock,
    )

_jinja_env = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined)

#: Stage keys whose contract requires one output per outline chapter -
#: templates for these must actually reference the outline, or a model
#: will happily collapse the whole episode into a single summary chapter.
_CHAPTER_STRUCTURE_HINTS: dict[str, tuple[str, ...]] = {
    'script': ('outline.chapters',),
    'scene_breakdown': ('chapter.text', 'chapter.idx'),
}


def _dummy_base_context() -> dict[str, Any]:
    """Mirror build_prompt_variables()'s always-present base keys."""
    return {
        'topic': 'Sample Topic',
        'channel': {
            'name': 'Sample Channel',
            'kind': 'LONGFORM',
            'wpm': 158,
            'publish_mode': 'review',
            'character_design_mode': 'locked',
            'branding': {'thumbnail_palette': {}},
        },
        'niche': {
            'audience': 'Sample audience',
            'angle': 'Sample angle',
            'banned_topics': [],
        },
        'lore': 'Sample lore document.',
        'visual_bible': 'Sample visual bible.',
        'visual_medium': 'photoreal',
        'style_negatives': [],
        'format': {
            'name': 'Sample Format',
            'key': 'sample_format',
            'fiction': False,
            'beats': [],
            'narration_pov': 'narrator',
            'pacing': {},
            'music_mood_map': {},
        },
        'upstream': {
            'research': {'brief': {}, 'sources': []},
            'outline': {
                'chapters': [
                    {
                        'idx': 0,
                        'title': 'Sample chapter',
                        'thesis': 'Sample thesis.',
                        'target_seconds': 60,
                        'device': 'open_loop',
                    },
                ],
                'total_target_seconds': 60,
                'format_key': 'sample_format',
            },
            'script': {'chapters': [], 'total_word_count': 0},
        },
        'config': {},
        'character': {
            'name': 'Sample',
            'appearance_prompt': '',
            'persona': '',
        },
        'footage': {
            'providers': ['pexels'],
            'sourcing_mode': 'stock_first',
            'ai_fallback_enabled': True,
            'min_width': 1280,
            'attribution_required': True,
        },
        'wpm': 158,
        'total_target_seconds': 60,
    }


#: Per-stage keys merged on top of the base context, matching exactly what
#: each stage passes as build_prompt_variables(ctx, extra=...).
_STAGE_EXTRAS: dict[str, dict[str, Any]] = {
    'research': {},
    'outline': {'total_target_seconds': 60, 'soft_spots': []},
    'script': {'wpm': 158},
    'scene_breakdown': {
        'hero_ratio': 0.15,
        'chapter': {
            'idx': 0,
            'title': 'Sample chapter',
            'text': 'Sample chapter narration text.',
        },
        'coverage_note': '',
    },
    'narrative_qc': {},
    'visual_prompts': {
        'style_guide': 'Sample visual bible.',
        'chapter_scenes': [],
    },
    'footage_queries': {'chapter_scenes': []},
    'metadata': {'timestamps': []},
    'thumbnail': {'title': 'Sample Title'},
}

#: editor_brief renders from a bespoke, non-build_prompt_variables context -
#: see server/apps/pipelines/stages/editor_brief.py.
_EDITOR_BRIEF_CONTEXT: dict[str, Any] = {
    'topic': 'Sample Topic',
    'kind': 'longform',
    'facts_json': '{}',
}


def _context_for_stage(stage_key: str) -> dict[str, Any] | None:
    """Return a dummy render context for stage_key, or None if unknown."""
    if stage_key == 'editor_brief':
        return dict(_EDITOR_BRIEF_CONTEXT)
    extra = _STAGE_EXTRAS.get(stage_key)
    if extra is None:
        return None
    return {**_dummy_base_context(), **extra}


def _render_error(template_str: str, context: dict[str, Any]) -> str | None:
    """Render template_str against context; return an error message, or None."""
    if not template_str.strip():
        return None
    try:
        _jinja_env.from_string(template_str).render(**context)
    except UndefinedError as exc:
        return f'undefined variable: {exc}'
    except TemplateSyntaxError as exc:
        return f'syntax error: {exc}'
    return None


def _stage_by_template_key(spec: 'ChannelSpecModel') -> dict[str, str]:
    overrides = spec.story_format.prompt_overrides
    return {
        template_key: stage_key for stage_key, template_key in overrides.items()
    }


def _template_jinja_errors(
    item: 'PromptTemplateBlock',
    context: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field_name, text in (
        ('system_prompt', item.system_prompt),
        ('user_prompt', item.user_prompt),
    ):
        error = _render_error(text, context)
        if error:
            errors.append(f'{item.key}.{field_name}: {error}')
    return errors


def validate_prompt_template_jinja(spec: 'ChannelSpecModel') -> None:
    """Reject prompt_templates that reference undefined Jinja variables.

    Renders every template's system_prompt/user_prompt with StrictUndefined
    against a realistic dummy context for the stage it overrides. A template
    referencing a variable that doesn't exist at pipeline runtime (a typo, a
    hallucinated name, a variable another stage has but this one doesn't)
    raises here instead of surfacing mid-production as an empty prompt.
    """
    stage_by_key = _stage_by_template_key(spec)
    errors: list[str] = []
    for item in spec.prompt_templates:
        stage_key = stage_by_key.get(item.key)
        if stage_key is None:
            continue  # orphan template - reported by _validate_templates
        context = _context_for_stage(stage_key)
        if context is None:
            continue  # unrecognized stage key - nothing to check against
        errors.extend(_template_jinja_errors(item, context))
    if errors:
        msg = 'prompt template Jinja errors: ' + '; '.join(errors)
        raise ValueError(msg)


def validate_prompt_template_structure(spec: 'ChannelSpecModel') -> None:
    """Reject script/scene_breakdown templates that never reference the outline.

    A template for these two stages that never mentions outline.chapters or
    chapter.text/chapter.idx will (in practice) collapse the whole episode
    into one summary chapter, even though it renders without error - this
    is exactly how a prior production run shipped a 32-word "script" for a
    ~60 minute outline. Substring check, not AST analysis: deliberately
    matches the phrasing the working default templates already use.
    """
    stage_by_key = _stage_by_template_key(spec)
    errors: list[str] = []
    for item in spec.prompt_templates:
        stage_key = stage_by_key.get(item.key)
        hints = _CHAPTER_STRUCTURE_HINTS.get(stage_key or '')
        if not hints:
            continue
        blob = f'{item.system_prompt} {item.user_prompt}'
        if not any(hint in blob for hint in hints):
            options = ' or '.join(hints)
            errors.append(
                f'{item.key}: must reference {options} so the model writes '
                'one output per outline chapter instead of a collapsed '
                'summary',
            )
    if errors:
        raise ValueError('; '.join(errors))
