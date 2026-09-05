"""Pydantic schemas for the channel-research agent output."""

import re
from collections.abc import Callable
from typing import Any, Literal

import pydantic

from server.apps.channel_research.logic.types import VisualMediumLiteral

SHARED_FORMAT_KEYS = frozenset({
    'factual_documentary',
    'true_crime_case',
    'educational_explainer',
    'motivational_story',
    'fantasy_lore',
    'documentary_stock',
    'documentary_archival',
})

BLUEPRINT_NAMES = frozenset({
    'longform_v1',
    'longform_documentary_v1',
    'longform_editor_v1',
    'longform_doc_editor_v1',
    'shorts_v1',
    'clipping_v1',
    'clipping_v1_manual',
})

STOCK_BLUEPRINTS = frozenset({
    'longform_documentary_v1',
    'longform_doc_editor_v1',
})

ANIMATED_MEDIA = frozenset({
    '2d_animation',
    '3d_cgi',
    'motion_graphics',
})
PHOTO_MEDIA = frozenset({'photoreal', 'live_action_stock'})
DISTINCTIVE_MEDIA = ANIMATED_MEDIA | frozenset({'mixed'})
VISUAL_MEDIUMS = ANIMATED_MEDIA | PHOTO_MEDIA | frozenset({'mixed'})

_MIN_LORE_WORDS = 400
_NEVER_DO_MARKER = 'never'
_FORMAT_CONTRACT_MARKER = 'format contract'
_MIN_APPEARANCE_WORDS = 80
_MAX_APPEARANCE_WORDS = 160
_MIN_BIBLE_WORDS = 80
_MAX_BIBLE_WORDS = 160
_MIN_TEMPLATE_CHARS = 200
_WIDE_HERO_MIN = 0.15
_WIDE_HERO_MAX = 0.50
_ANIMATED_HERO = (0.35, 0.50)
_PHOTO_HERO = (0.15, 0.25)
_MIXED_HERO = (0.25, 0.45)
_ANIMATED_CUTS = (8, 14)
_SCENE_MIN_SECONDS = (4, 6)
_SCENE_MAX_SECONDS = 8
_STAGE_SCRIPT = 'script'
_STAGE_VISUAL = 'visual_prompts'
_STAGE_SCENES = 'scene_breakdown'


class SourceChannelStats(pydantic.BaseModel):
    """Public stats for the source YouTube channel."""

    channel_id: str = ''
    channel_name: str = ''
    subscriber_count: int | None = None
    video_count: int | None = None
    view_count: int | None = None
    description: str = ''


class FormatProfile(pydantic.BaseModel):
    """Identified storytelling format of the source channel."""

    hook_pattern: str
    title_formulas: list[str]
    pacing: str
    visual_world: str


class VideoRef(pydantic.BaseModel):
    """One notable video from research."""

    video_id: str = ''
    title: str
    url: str = ''
    view_count: int | None = None
    notes: str = ''


class CompetitorRef(pydantic.BaseModel):
    """A competing channel or adjacent format."""

    channel_name: str
    channel_id: str = ''
    url: str = ''
    notes: str = ''


class NicheBendOpportunity(pydantic.BaseModel):
    """One market x format remix that is not a clone."""

    title: str
    market: str
    format_hook: str
    rationale: str


class ResearchSourceRef(pydantic.BaseModel):
    """Provenance for a research claim."""

    url: str
    title: str = ''
    kind: str = ''


class ResearchReport(pydantic.BaseModel):
    """Dossier produced before the ChannelSpec."""

    source_channel: SourceChannelStats
    identified_market: str
    identified_format: FormatProfile
    top_videos: list[VideoRef]
    competitors: list[CompetitorRef]
    what_works: list[str]
    what_not_to_copy: list[str]
    gaps: list[str]
    niche_bend_opportunities: list[NicheBendOpportunity]
    recommended_mode: Literal['same_niche', 'bent']
    sources: list[ResearchSourceRef]
    visual_medium: VisualMediumLiteral
    style_tokens: list[str] = pydantic.Field(default_factory=list)
    style_negatives: list[str] = pydantic.Field(default_factory=list)


class ChannelBlock(pydantic.BaseModel):
    """ChannelSpec.channel."""

    name: str
    kind: Literal['LONGFORM', 'SHORTS', 'CLIPPING']
    publish_mode: str = 'review'
    character_design_mode: str = 'none'
    voice_id: str = ''
    stability: float = 0.5
    similarity_boost: float = 0.75
    wpm: int = 150
    default_budget_usd: str = '15.00'
    max_publishes_per_day: int = 1
    default_blueprint_name: str = 'longform_v1'
    gates: list[str] = pydantic.Field(default_factory=list)
    provider_daily_caps: list[dict[str, Any]] = pydantic.Field(
        default_factory=list,
    )
    config_overrides: dict[str, Any] = pydantic.Field(default_factory=dict)


class NicheBlock(pydantic.BaseModel):
    """ChannelSpec.niche."""

    audience: str = ''
    angle: str
    banned_topics: list[str] = pydantic.Field(default_factory=list)
    lore_document: str = ''
    format_key: str = 'factual_documentary'
    visual_bible: str = ''
    visual_medium: VisualMediumLiteral | None = None
    style_tokens: list[str] = pydantic.Field(default_factory=list)
    style_negatives: list[str] = pydantic.Field(default_factory=list)


class StoryFormatBeat(pydantic.BaseModel):
    """One beat in a story format."""

    name: str
    description: str


class StoryFormatBlock(pydantic.BaseModel):
    """ChannelSpec.story_format."""

    create_if_missing: bool = False
    key: str
    name: str
    fiction: bool = False
    narration_pov: str = 'narrator'
    beats: list[StoryFormatBeat] = pydantic.Field(default_factory=list)
    pacing: dict[str, int] = pydantic.Field(default_factory=dict)
    music_mood_map: dict[str, str] = pydantic.Field(default_factory=dict)
    prompt_overrides: dict[str, str] = pydantic.Field(default_factory=dict)


class PromptTemplateBlock(pydantic.BaseModel):
    """One prompt template to import with the spec."""

    key: str
    name: str
    scope: str = 'GLOBAL'
    description: str = ''
    system_prompt: str = ''
    user_prompt: str = ''
    model: str = 'gpt-5.6-terra'
    temperature: float = 1.0
    max_tokens: int = 8192


class BrandingBlock(pydantic.BaseModel):
    """ChannelSpec.branding."""

    watermark_position: str = 'bottom_right'
    watermark_opacity: float = 0.5
    music_pool_tags: list[str] = pydantic.Field(default_factory=list)
    thumbnail_palette: dict[str, str] = pydantic.Field(default_factory=dict)


class AssemblyStyleBlock(pydantic.BaseModel):
    """ChannelSpec.assembly_style."""

    camera_movements: list[str] = pydantic.Field(default_factory=list)
    transition_styles: list[str] = pydantic.Field(default_factory=list)
    sfx_pool_tags: list[str] = pydantic.Field(default_factory=list)
    min_cuts_per_minute: int = 4
    max_cuts_per_minute: int = 8
    music_bed_gain_db: float = -22
    enable_background_music: bool = True


class FootageSourcingBlock(pydantic.BaseModel):
    """ChannelSpec.footage_sourcing."""

    enabled_providers: list[str] = pydantic.Field(default_factory=list)
    sourcing_mode: str = 'stock_first'
    ai_fallback_enabled: bool = True
    max_ai_fallback_per_run: int = 15
    rerank_mode: str = 'vision'
    candidates_per_scene: int = 8
    min_clip_width: int = 1280
    min_clip_duration_s: float = 3.0
    allowed_licenses: list[str] = pydantic.Field(default_factory=list)
    require_attribution: bool = True


class CharacterBlock(pydantic.BaseModel):
    """ChannelSpec.character."""

    include: bool = False
    name: str = ''
    appearance_prompt: str = ''
    persona: str = ''
    status: str = 'APPROVED'


class SeedIdeaBlock(pydantic.BaseModel):
    """One seed idea for LONGFORM import."""

    title: str
    topic: str
    score: float = 0.8


class ChannelSpecModel(pydantic.BaseModel):
    """Importer-ready ChannelSpec (mirrors channel-onboarding-spec.md)."""

    channel: ChannelBlock
    niche: NicheBlock
    story_format: StoryFormatBlock
    prompt_templates: list[PromptTemplateBlock] = pydantic.Field(
        default_factory=list,
    )
    branding: BrandingBlock = pydantic.Field(default_factory=BrandingBlock)
    assembly_style: AssemblyStyleBlock = pydantic.Field(
        default_factory=AssemblyStyleBlock,
    )
    footage_sourcing: FootageSourcingBlock = pydantic.Field(
        default_factory=FootageSourcingBlock,
    )
    character: CharacterBlock = pydantic.Field(
        default_factory=CharacterBlock,
    )
    seed_ideas: list[SeedIdeaBlock] = pydantic.Field(default_factory=list)
    post_import_notes: list[str] = pydantic.Field(default_factory=list)


class ChannelResearchAgentOutput(pydantic.BaseModel):
    """Structured agent result persisted on the job."""

    research_report: ResearchReport
    channel_spec: ChannelSpecModel


def _word_count(text: str) -> int:
    return len(text.split())


def _run_checks(*checks: Callable[[], None]) -> None:
    """Run every check and raise all failures together, not just the first.

    Stopping at the first failing check - the previous behavior here -
    means a single ModelRetry conveys only one violated rule at a time.
    On a schema this large (15+ independent checks) that reliably
    exhausts the agent's output-retry budget before every rule is
    satisfied, and can even cost a retry re-discovering a rule the model
    regressed while blindly chasing the one it was just told about.
    Reporting every currently-failing rule in one message lets a single
    retry fix them all at once.
    """
    errors: list[str] = []
    for check in checks:
        try:
            check()
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError('; '.join(errors))


def validate_research_report(report: ResearchReport) -> None:
    """Enforce 3-5 Niche Bending opportunities."""
    count = len(report.niche_bend_opportunities)
    if count < 3 or count > 5:
        msg = 'research_report needs 3-5 niche_bend_opportunities'
        raise ValueError(msg)


def _validate_music_overlap(spec: ChannelSpecModel) -> None:
    tags = {tag.lower() for tag in spec.branding.music_pool_tags}
    moods = spec.story_format.music_mood_map.values()
    missing = [mood for mood in moods if mood.lower() not in tags]
    if missing:
        msg = f'music_pool_tags must include mood map values: {missing}'
        raise ValueError(msg)


def _validate_templates(spec: ChannelSpecModel) -> None:
    templates = spec.prompt_templates
    overrides = spec.story_format.prompt_overrides
    if spec.story_format.create_if_missing is False:
        if templates or overrides:
            msg = (
                'create_if_missing=false forbids prompt_templates '
                'and prompt_overrides'
            )
            raise ValueError(msg)
        return
    if not templates:
        return
    fmt_key = spec.story_format.key
    if fmt_key in SHARED_FORMAT_KEYS:
        msg = (
            'new prompt_templates require a new story_format.key, '
            f'not shared seed {fmt_key}'
        )
        raise ValueError(msg)
    override_values = set(overrides.values())
    orphan = [item.key for item in templates if item.key not in override_values]
    if orphan:
        msg = f'orphan prompt_templates not in prompt_overrides: {orphan}'
        raise ValueError(msg)


def _validate_seeds_and_character(spec: ChannelSpecModel) -> None:
    if spec.seed_ideas and spec.channel.kind != 'LONGFORM':
        msg = 'seed_ideas are only allowed for LONGFORM'
        raise ValueError(msg)
    include = spec.character.include
    mode = spec.channel.character_design_mode
    if include and mode == 'none':
        msg = 'character.include must be false when design mode is none'
        raise ValueError(msg)
    if not include and mode != 'none':
        msg = f'character.include must be true when design mode is {mode}'
        raise ValueError(msg)


def _validate_lore(lore: str) -> None:
    if _word_count(lore) < _MIN_LORE_WORDS:
        msg = f'lore_document must be at least {_MIN_LORE_WORDS} words'
        raise ValueError(msg)
    lowered = lore.lower()
    if _NEVER_DO_MARKER not in lowered:
        msg = 'lore_document must include a never-do list'
        raise ValueError(msg)
    if _FORMAT_CONTRACT_MARKER not in lowered:
        msg = 'lore_document must include a FORMAT CONTRACT section'
        raise ValueError(msg)


def _read_hero_ratio(spec: ChannelSpecModel) -> float | None:
    motion = spec.channel.config_overrides.get('motion')
    if not isinstance(motion, dict):
        return None
    raw = motion.get('hero_ratio')
    if isinstance(raw, int | float):
        return float(raw)
    return None


def _validate_hero_ratio(spec: ChannelSpecModel) -> None:
    ratio = _read_hero_ratio(spec)
    if ratio is None:
        msg = 'config_overrides.motion.hero_ratio is required'
        raise ValueError(msg)
    if not (_WIDE_HERO_MIN <= ratio <= _WIDE_HERO_MAX):
        msg = (
            f'hero_ratio must be between {_WIDE_HERO_MIN} and {_WIDE_HERO_MAX}'
        )
        raise ValueError(msg)


def _validate_pacing_and_blueprint(spec: ChannelSpecModel) -> None:
    blueprint = spec.channel.default_blueprint_name
    if blueprint not in BLUEPRINT_NAMES:
        msg = f'unknown default_blueprint_name: {blueprint}'
        raise ValueError(msg)
    beat_names = {beat.name for beat in spec.story_format.beats}
    pacing_keys = set(spec.story_format.pacing)
    extra = pacing_keys - beat_names
    if beat_names and extra:
        msg = f'pacing keys missing from beats: {sorted(extra)}'
        raise ValueError(msg)


def _medium_label(medium: str) -> str:
    return medium.replace('_', ' ')


def _hero_range_for(medium: str) -> tuple[float, float]:
    if medium in ANIMATED_MEDIA:
        return _ANIMATED_HERO
    if medium == 'mixed':
        return _MIXED_HERO
    return _PHOTO_HERO


def _validate_hero_ratio_for_medium(
    spec: ChannelSpecModel,
    medium: str,
) -> None:
    ratio = _read_hero_ratio(spec)
    if ratio is None:
        msg = 'config_overrides.motion.hero_ratio is required'
        raise ValueError(msg)
    low, high = _hero_range_for(medium)
    if not (low <= ratio <= high):
        msg = f'hero_ratio for {medium} must be {low}-{high}'
        raise ValueError(msg)


def _validate_animated_cuts_and_scenes(spec: ChannelSpecModel) -> None:
    assembly = spec.assembly_style
    low, high = _ANIMATED_CUTS
    min_cuts = assembly.min_cuts_per_minute
    max_cuts = assembly.max_cuts_per_minute
    if not (low <= min_cuts <= high and low <= max_cuts <= high):
        msg = f'assembly_style cuts for animation must be {low}-{high}/min'
        raise ValueError(msg)
    if min_cuts > max_cuts:
        msg = 'min_cuts_per_minute must be <= max_cuts_per_minute'
        raise ValueError(msg)
    breakdown = spec.channel.config_overrides.get('scene_breakdown')
    scene = breakdown if isinstance(breakdown, dict) else {}
    min_s = scene.get('min_seconds')
    max_s = scene.get('max_seconds')
    min_low, min_high = _SCENE_MIN_SECONDS
    if not isinstance(min_s, int | float) or not (
        min_low <= float(min_s) <= min_high
    ):
        msg = f'scene_breakdown.min_seconds must be {min_low}-{min_high}'
        raise ValueError(msg)
    max_ok = (
        isinstance(max_s, int | float)
        and abs(float(max_s) - _SCENE_MAX_SECONDS) < 0.01
    )
    if not max_ok:
        msg = f'scene_breakdown.max_seconds must be {_SCENE_MAX_SECONDS}'
        raise ValueError(msg)


def _required_template_keys(format_key: str) -> dict[str, str]:
    return {
        _STAGE_SCRIPT: f'{_STAGE_SCRIPT}_{format_key}',
        _STAGE_VISUAL: f'{_STAGE_VISUAL}_{format_key}',
        _STAGE_SCENES: f'{_STAGE_SCENES}_{format_key}',
    }


def _validate_distinctive_templates(spec: ChannelSpecModel) -> None:
    if spec.story_format.create_if_missing is False:
        msg = 'distinctive medium requires create_if_missing=true'
        raise ValueError(msg)
    fmt_key = spec.story_format.key
    if fmt_key in SHARED_FORMAT_KEYS:
        msg = (
            'distinctive medium requires a new story_format.key, '
            f'not shared seed {fmt_key}'
        )
        raise ValueError(msg)
    required = _required_template_keys(fmt_key)
    overrides = spec.story_format.prompt_overrides
    for stage, template_key in required.items():
        if overrides.get(stage) != template_key:
            msg = f'prompt_overrides.{stage} must be {template_key}'
            raise ValueError(msg)
    present = {item.key for item in spec.prompt_templates}
    missing = [key for key in required.values() if key not in present]
    if missing:
        msg = f'distinctive format missing prompt_templates: {missing}'
        raise ValueError(msg)


def _first_sentence(text: str) -> str:
    stripped = text.strip()
    index = stripped.find('.')
    if index == -1:
        return stripped.lower()
    return stripped[:index].lower()


_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')


def _normalize_for_medium_match(text: str) -> str:
    """Collapse case/punctuation so hyphenation doesn't break medium matching.

    Phrasing like 'live-action, stock' or '2D-animated' should still match
    the 'live_action_stock' / '2d_animation' medium label. Requiring the
    literal underscore- or single-space-joined enum value is brittle
    against ordinary hyphenation - it turned "name the medium" into a
    check the model could satisfy in substance yet still fail every
    retry on punctuation alone.
    """
    return _NON_ALNUM_RE.sub(' ', text.lower()).strip()


def _mentions_medium(text: str, medium: str) -> bool:
    label = _normalize_for_medium_match(_medium_label(medium))
    return label in _normalize_for_medium_match(text)


def _validate_visual_bible_length(bible: str) -> None:
    words = _word_count(bible)
    if not (_MIN_BIBLE_WORDS <= words <= _MAX_BIBLE_WORDS):
        msg = (
            f'visual_bible must be {_MIN_BIBLE_WORDS}-{_MAX_BIBLE_WORDS} words'
        )
        raise ValueError(msg)


def _validate_visual_bible_names_medium(bible: str, medium: str) -> None:
    if not _mentions_medium(_first_sentence(bible), medium):
        msg = (
            'visual_bible sentence one must literally say '
            f'"{_medium_label(medium)}"'
        )
        raise ValueError(msg)


def _validate_template_quality(
    spec: ChannelSpecModel,
    medium: str,
) -> None:
    required = set(_required_template_keys(spec.story_format.key).values())
    for item in spec.prompt_templates:
        if item.key not in required:
            continue
        if (
            len(item.system_prompt) < _MIN_TEMPLATE_CHARS
            or len(item.user_prompt) < _MIN_TEMPLATE_CHARS
        ):
            msg = (
                'distinctive templates need '
                f'{_MIN_TEMPLATE_CHARS}+ char prompts'
            )
            raise ValueError(msg)
        blob = f'{item.system_prompt} {item.user_prompt}'.lower()
        if item.key.startswith('visual_prompts_') and not _mentions_medium(
            blob,
            medium,
        ):
            msg = f'{item.key} must literally say "{_medium_label(medium)}"'
            raise ValueError(msg)
        if item.key.startswith('script_'):
            if 'format' not in blob and 'hook' not in blob:
                msg = 'script template must mention format/hook'
                raise ValueError(msg)


def _validate_character_lock(
    spec: ChannelSpecModel,
    medium: str,
) -> None:
    if not spec.character.include:
        return
    words = _word_count(spec.character.appearance_prompt)
    if not (_MIN_APPEARANCE_WORDS <= words <= _MAX_APPEARANCE_WORDS):
        msg = (
            'character.appearance_prompt must be '
            f'{_MIN_APPEARANCE_WORDS}-{_MAX_APPEARANCE_WORDS} words'
        )
        raise ValueError(msg)
    if medium not in ANIMATED_MEDIA:
        return
    image_gen = spec.channel.config_overrides.get('image_gen')
    use_ref = (
        image_gen.get('use_character_ref')
        if isinstance(image_gen, dict)
        else None
    )
    if use_ref is not True:
        msg = 'image_gen.use_character_ref must be true for animated character'
        raise ValueError(msg)


def _validate_lore_names_medium(spec: ChannelSpecModel, medium: str) -> None:
    if not _mentions_medium(spec.niche.lore_document, medium):
        msg = f'lore_document must literally say "{_medium_label(medium)}"'
        raise ValueError(msg)


def _validate_blueprint_for_medium(
    spec: ChannelSpecModel,
    medium: str,
) -> None:
    blueprint = spec.channel.default_blueprint_name
    if medium in ANIMATED_MEDIA and blueprint in STOCK_BLUEPRINTS:
        msg = 'stock documentary blueprint is not for animated media'
        raise ValueError(msg)


def _validate_style_negatives_required(
    style_negatives: list[str] | None,
) -> None:
    if not style_negatives:
        msg = 'style_negatives required for distinctive media'
        raise ValueError(msg)


def validate_medium_lock(
    spec: ChannelSpecModel,
    *,
    visual_medium: str | None = None,
    style_negatives: list[str] | None = None,
) -> None:
    """Enforce hero_ratio, templates, and cuts for the classified medium."""
    medium = (
        visual_medium
        if visual_medium is not None
        else (spec.niche.visual_medium or '')
    )
    negatives = (
        style_negatives
        if style_negatives is not None
        else list(spec.niche.style_negatives)
    )
    if not medium:
        msg = 'visual_medium is required'
        raise ValueError(msg)
    if medium not in VISUAL_MEDIUMS:
        msg = f'unknown visual_medium: {medium}'
        raise ValueError(msg)

    checks: list[Callable[[], None]] = [
        lambda: _validate_visual_bible_length(spec.niche.visual_bible),
        lambda: _validate_visual_bible_names_medium(
            spec.niche.visual_bible,
            medium,
        ),
        lambda: _validate_hero_ratio_for_medium(spec, medium),
        lambda: _validate_lore_names_medium(spec, medium),
        lambda: _validate_blueprint_for_medium(spec, medium),
        lambda: _validate_character_lock(spec, medium),
    ]
    if medium in ANIMATED_MEDIA:
        checks.append(lambda: _validate_animated_cuts_and_scenes(spec))
    if medium in DISTINCTIVE_MEDIA:
        checks.extend((
            lambda: _validate_distinctive_templates(spec),
            lambda: _validate_template_quality(spec, medium),
            lambda: _validate_style_negatives_required(negatives),
        ))
    _run_checks(*checks)


def validate_channel_spec(spec: ChannelSpecModel) -> None:
    """Onboarding self-check. Raises ValueError (all failures) at once."""
    _run_checks(
        lambda: _validate_lore(spec.niche.lore_document),
        lambda: _validate_music_overlap(spec),
        lambda: _validate_templates(spec),
        lambda: _validate_seeds_and_character(spec),
        lambda: _validate_pacing_and_blueprint(spec),
        lambda: _validate_hero_ratio(spec),
    )


def _validate_distinct_brand_name(output: ChannelResearchAgentOutput) -> None:
    source_name = output.research_report.source_channel.channel_name
    spec_name = output.channel_spec.channel.name
    if (
        source_name
        and spec_name
        and source_name.strip().lower() == spec_name.strip().lower()
    ):
        msg = 'Do not copy the source channel brand name'
        raise ValueError(msg)


def validate_agent_output(output: ChannelResearchAgentOutput) -> None:
    """Run dossier + ChannelSpec quality-bar checks, all failures at once."""
    _run_checks(
        lambda: validate_research_report(output.research_report),
        lambda: validate_channel_spec(output.channel_spec),
        lambda: _validate_distinct_brand_name(output),
        lambda: validate_medium_lock(output.channel_spec),
    )
