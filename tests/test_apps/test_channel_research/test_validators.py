"""Tests for ChannelSpec and dossier output validators."""

import pytest

from server.apps.channel_research.logic.schemas import (
    AssemblyStyleBlock,
    BrandingBlock,
    ChannelBlock,
    ChannelResearchAgentOutput,
    ChannelSpecModel,
    CharacterBlock,
    CompetitorRef,
    FootageSourcingBlock,
    FormatProfile,
    NicheBendOpportunity,
    NicheBlock,
    PromptTemplateBlock,
    ResearchReport,
    ResearchSourceRef,
    SeedIdeaBlock,
    SourceChannelStats,
    StoryFormatBeat,
    StoryFormatBlock,
    VideoRef,
    validate_agent_output,
    validate_channel_spec,
    validate_medium_lock,
    validate_research_report,
)
from server.apps.channel_research.logic.value_objects import (
    ChannelSpecAssemblyStylePayload,
    ChannelSpecBrandingPayload,
    ChannelSpecChannelPayload,
    ChannelSpecCharacterPayload,
    ChannelSpecFootageSourcingPayload,
    ChannelSpecNichePayload,
    ChannelSpecPayload,
    ChannelSpecPromptTemplatePayload,
    ChannelSpecSeedIdeaPayload,
    ChannelSpecStoryFormatBeatPayload,
    ChannelSpecStoryFormatPayload,
    CompetitorRefPayload,
    FormatProfilePayload,
    NicheBendOpportunityPayload,
    ResearchReportPayload,
    ResearchSourceRefPayload,
    SourceChannelStatsPayload,
    VideoRefPayload,
)


def lore_document(words: int = 420, medium: str = 'photoreal') -> str:
    label = medium.replace('_', ' ')
    prefix = (
        'FORMAT CONTRACT: every video is a cold-open evidence stack. '
        'Title formula Why X actually Y. Hook is a named case then proof. '
        f'Visual identity: {label} archival maps and stills. '
        'Voice and tone stay dry. Things we never do: break the fourth wall. '
    )
    remaining = max(words - len(prefix.split()), 1)
    return prefix + ' '.join(['word'] * remaining)


def visual_bible_text(words: int = 100, medium: str = 'photoreal') -> str:
    label = medium.replace('_', ' ')
    first = f'{label} establishing stills lock palette line weight and camera. '
    remaining = max(words - len(first.split()), 1)
    return first + ' '.join(['token'] * remaining)


def _channel_overrides(
    hero_ratio: float,
    extra: dict[str, object] | None,
) -> dict[str, object]:
    overrides: dict[str, object] = {'motion': {'hero_ratio': hero_ratio}}
    if extra:
        overrides.update(extra)
    return overrides


def valid_spec(
    *,
    name: str = 'Forge History',
    kind: str = 'LONGFORM',
    character_design_mode: str = 'none',
    include_character: bool = False,
    lore: str | None = None,
    music_mood_map: dict[str, str] | None = None,
    music_pool_tags: list[str] | None = None,
    create_if_missing: bool = False,
    format_key: str = 'factual_documentary',
    prompt_templates: list[object] | None = None,
    prompt_overrides: dict[str, str] | None = None,
    seed_ideas: list[object] | None = None,
    blueprint: str = 'longform_v1',
    hero_ratio: float = 0.2,
    extra_overrides: dict[str, object] | None = None,
    min_cuts: int = 4,
    max_cuts: int = 8,
    appearance_prompt: str = '',
    visual_medium: str = 'photoreal',
    visual_bible: str | None = None,
    style_tokens: list[str] | None = None,
    style_negatives: list[str] | None = None,
) -> ChannelSpecModel:
    moods = music_mood_map if music_mood_map is not None else {}
    tags = (
        music_pool_tags if music_pool_tags is not None else list(moods.values())
    )
    templates = prompt_templates or []
    overrides = prompt_overrides
    if overrides is None:
        overrides = {'script': 'script_forge_history'} if templates else {}
    return ChannelSpecModel(
        channel=ChannelBlock(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            character_design_mode=character_design_mode,
            default_blueprint_name=blueprint,
            config_overrides=_channel_overrides(hero_ratio, extra_overrides),
        ),
        niche=NicheBlock(
            angle='documented history with a sharp editorial POV',
            lore_document=lore if lore is not None else lore_document(),
            visual_medium=visual_medium,  # type: ignore[arg-type]
            visual_bible=(
                visual_bible
                if visual_bible is not None
                else visual_bible_text(medium=visual_medium)
            ),
            style_tokens=style_tokens or [],
            style_negatives=style_negatives or [],
        ),
        story_format=StoryFormatBlock(
            create_if_missing=create_if_missing,
            key=format_key,
            name='Factual Documentary',
            music_mood_map=moods,
            prompt_overrides=overrides,
        ),
        prompt_templates=templates,  # type: ignore[arg-type]
        branding={'music_pool_tags': tags},  # type: ignore[arg-type]
        assembly_style={  # type: ignore[arg-type]
            'min_cuts_per_minute': min_cuts,
            'max_cuts_per_minute': max_cuts,
        },
        character={  # type: ignore[arg-type]
            'include': include_character,
            'appearance_prompt': appearance_prompt,
        },
        seed_ideas=seed_ideas or [],  # type: ignore[arg-type]
    )


def valid_report(
    *,
    channel_name: str = 'Source Hub',
    bend_count: int = 3,
) -> ResearchReport:
    bends = [
        NicheBendOpportunity(
            title=f'Bend {index}',
            market=f'market {index}',
            format_hook='cold open then evidence',
            rationale='format works; new market',
        )
        for index in range(bend_count)
    ]
    return ResearchReport(
        source_channel=SourceChannelStats(
            channel_id='UCabcdefghijklmnopqrstuv',
            channel_name=channel_name,
        ),
        identified_market='history buffs',
        identified_format=FormatProfile(
            hook_pattern='cold open',
            title_formulas=['Why X actually Y'],
            pacing='slow evidence stack',
            visual_world='archival maps',
        ),
        top_videos=[],
        competitors=[],
        what_works=['evidence-first'],
        what_not_to_copy=['their brand name'],
        gaps=['local history'],
        niche_bend_opportunities=bends,
        recommended_mode='same_niche',
        sources=[],
        visual_medium='photoreal',
    )


def valid_output() -> ChannelResearchAgentOutput:
    return ChannelResearchAgentOutput(
        research_report=valid_report(),
        channel_spec=valid_spec(),
    )


def test_validate_channel_spec_accepts_quality_bar() -> None:
    validate_channel_spec(valid_spec())


def test_validate_channel_spec_rejects_short_lore() -> None:
    spec = valid_spec(lore='Too short. We never do this.')
    with pytest.raises(ValueError, match='at least 400 words'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_lore_without_never_do() -> None:
    spec = valid_spec(lore=' '.join(['word'] * 420))
    with pytest.raises(ValueError, match='never-do'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_music_mismatch() -> None:
    spec = valid_spec(
        music_mood_map={'hook': 'tension'},
        music_pool_tags=['calm'],
    )
    with pytest.raises(ValueError, match='music_pool_tags'):
        validate_channel_spec(spec)


def test_validate_channel_spec_reports_every_failure_in_one_pass() -> None:
    """Multiple independent violations must all land in one raised error.

    Stopping at the first failing check forces one ModelRetry per rule -
    on a schema this large that reliably exhausts the agent's retry
    budget before every rule is satisfied. Every check must run and every
    failure must be reported together so a single retry can fix them all.
    """
    spec = valid_spec(
        lore='Too short. We never do this.',
        music_mood_map={'hook': 'tension'},
        music_pool_tags=['calm'],
    )
    with pytest.raises(ValueError) as exc_info:
        validate_channel_spec(spec)
    message = str(exc_info.value)
    assert 'at least 400 words' in message
    assert 'music_pool_tags' in message


def test_validate_channel_spec_rejects_orphan_templates() -> None:
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt='Write {{ topic }}',
            ),
        ],
    )
    spec.story_format.prompt_overrides = {}
    with pytest.raises(ValueError, match='orphan prompt_templates'):
        validate_channel_spec(spec)


def test_validate_channel_spec_create_if_missing_without_templates() -> None:
    spec = valid_spec(create_if_missing=True, format_key='forge_history')
    validate_channel_spec(spec)


def test_validate_channel_spec_accepts_templates_on_new_format_key() -> None:
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt=(
                    'Write {{ topic }}. Chapters: '
                    '{{ upstream.outline.chapters }}'
                ),
            ),
        ],
    )
    validate_channel_spec(spec)


def test_validate_channel_spec_rejects_templates_on_shared_key() -> None:
    spec = valid_spec(
        create_if_missing=True,
        format_key='factual_documentary',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt='Write {{ topic }}',
            ),
        ],
    )
    with pytest.raises(ValueError, match='shared seed'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_templates_when_reusing_format() -> None:
    spec = valid_spec(
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt='Write {{ topic }}',
            ),
        ],
    )
    with pytest.raises(ValueError, match='create_if_missing=false'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_seed_ideas_for_shorts() -> None:
    spec = valid_spec(
        kind='SHORTS',
        seed_ideas=[
            SeedIdeaBlock(title='A title', topic='Named person, stakes.'),
        ],
    )
    with pytest.raises(ValueError, match='LONGFORM'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_character_mismatch() -> None:
    spec = valid_spec(
        character_design_mode='none',
        include_character=True,
    )
    with pytest.raises(ValueError, match='include must be false'):
        validate_channel_spec(spec)
    spec = valid_spec(
        character_design_mode='interactive',
        include_character=False,
    )
    with pytest.raises(ValueError, match='include must be true'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_blueprint() -> None:
    spec = valid_spec(blueprint='invented_v1')
    with pytest.raises(ValueError, match='unknown default_blueprint_name'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_transition_style() -> None:
    spec = valid_spec()
    spec.assembly_style.transition_styles = ['cut', 'cross_dissolve']
    with pytest.raises(ValueError, match='unknown transition style'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_sourcing_mode() -> None:
    spec = valid_spec()
    spec.footage_sourcing.sourcing_mode = 'ai_first'
    with pytest.raises(ValueError, match='unknown sourcing_mode'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_rerank_mode() -> None:
    spec = valid_spec()
    spec.footage_sourcing.rerank_mode = 'best'
    with pytest.raises(ValueError, match='unknown rerank_mode'):
        validate_channel_spec(spec)


def test_validate_channel_spec_accepts_valid_assembly_and_sourcing() -> None:
    spec = valid_spec()
    spec.assembly_style.transition_styles = [
        'hard_cut',
        'slow_pan',
        'wipe_left',
    ]
    spec.footage_sourcing.sourcing_mode = 'ai_only'
    spec.footage_sourcing.rerank_mode = 'metadata'
    validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_publish_mode() -> None:
    spec = valid_spec()
    spec.channel.publish_mode = 'manual'
    with pytest.raises(ValueError, match='unknown publish_mode'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_character_design_mode() -> None:
    spec = valid_spec(character_design_mode='auto', include_character=True)
    spec.channel.character_design_mode = 'automatic'
    with pytest.raises(ValueError, match='unknown character_design_mode'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_character_status() -> None:
    spec = valid_spec()
    spec.character.status = 'PENDING'
    with pytest.raises(ValueError, match='unknown character status'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_enabled_provider() -> None:
    spec = valid_spec()
    spec.footage_sourcing.enabled_providers = ['pexels', 'shutterstock']
    with pytest.raises(ValueError, match='unknown footage provider'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_unknown_prompt_template_scope() -> None:
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt='Write {{ topic }}',
                scope='REGIONAL',
            ),
        ],
    )
    with pytest.raises(ValueError, match='unknown prompt template scope'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_undefined_jinja_variable() -> None:
    """Reproduces the Dreamless Abbot bug: an undefined template variable."""
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt=(
                    'Title idea: {{ title }}\n'
                    'Chapters: {{ upstream.outline.chapters }}'
                ),
            ),
        ],
    )
    with pytest.raises(ValueError, match='undefined variable'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_template_syntax_error() -> None:
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt='{% if topic %}unterminated',
            ),
        ],
    )
    with pytest.raises(ValueError, match='syntax error'):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_script_template_missing_outline() -> (
    None
):
    """A script template with valid variables but no outline reference."""
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt='Write a full episode for {{ topic }}.',
            ),
        ],
    )
    with pytest.raises(
        ValueError,
        match=r'must reference outline\.chapters',
    ):
        validate_channel_spec(spec)


def test_validate_channel_spec_rejects_scene_breakdown_missing_chapter() -> (
    None
):
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='scene_breakdown_forge_history',
                name='Forge scenes',
                user_prompt='Break "{{ topic }}" into scenes.',
            ),
        ],
        prompt_overrides={'scene_breakdown': 'scene_breakdown_forge_history'},
    )
    with pytest.raises(
        ValueError,
        match=r'must reference chapter\.text or chapter\.idx',
    ):
        validate_channel_spec(spec)


def test_validate_channel_spec_accepts_well_formed_script_template() -> None:
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt=(
                    'Write {{ topic }}. '
                    'Chapters: {{ upstream.outline.chapters }}'
                ),
            ),
        ],
    )
    validate_channel_spec(spec)


def test_validate_channel_spec_skips_unrecognized_stage_templates() -> None:
    """A template overriding a stage with no known dummy context passes.

    e.g. clip_analyze uses a different variable-building path entirely, so
    there's nothing to render-check it against.
    """
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='clip_analyze_forge_history',
                name='Forge clip analyze',
                user_prompt='{{ totally_undefined_variable }}',
            ),
        ],
        prompt_overrides={'clip_analyze': 'clip_analyze_forge_history'},
    )
    validate_channel_spec(spec)


def test_validate_channel_spec_ignores_orphan_template_variables() -> None:
    """An orphan template (not in prompt_overrides) isn't Jinja-checked here.

    _validate_templates already rejects it for being orphaned; the Jinja/
    structure checks must not also crash trying to resolve its stage.
    """
    spec = valid_spec(
        create_if_missing=True,
        format_key='forge_history',
        prompt_templates=[
            PromptTemplateBlock(
                key='script_forge_history',
                name='Forge script',
                user_prompt='{{ totally_undefined_variable }}',
            ),
        ],
    )
    spec.story_format.prompt_overrides = {}
    with pytest.raises(ValueError, match='orphan prompt_templates'):
        validate_channel_spec(spec)


def test_validate_channel_spec_accepts_valid_channel_and_character_fields() -> (
    None
):
    spec = valid_spec(character_design_mode='auto', include_character=True)
    spec.channel.publish_mode = 'auto'
    spec.character.status = 'APPROVED'
    spec.footage_sourcing.enabled_providers = ['pexels', 'archive_org']
    validate_channel_spec(spec)


def test_validate_channel_spec_rejects_pacing_without_beats() -> None:
    spec = valid_spec()
    spec.story_format.beats = [
        StoryFormatBeat(name='hook', description='open'),
    ]
    spec.story_format.pacing = {'hook': 12, 'missing': 8}
    with pytest.raises(ValueError, match='pacing keys'):
        validate_channel_spec(spec)


def test_validate_channel_spec_accepts_matching_music_tags() -> None:
    spec = valid_spec(
        music_mood_map={'hook': 'tension'},
        music_pool_tags=['tension', 'resolve'],
    )
    validate_channel_spec(spec)


def test_validate_research_report_requires_three_to_five_bends() -> None:
    with pytest.raises(ValueError, match='3-5'):
        validate_research_report(valid_report(bend_count=2))
    validate_research_report(valid_report(bend_count=5))
    with pytest.raises(ValueError, match='3-5'):
        validate_research_report(valid_report(bend_count=6))


def test_validate_agent_output_rejects_copied_brand_name() -> None:
    output = ChannelResearchAgentOutput(
        research_report=valid_report(channel_name='History Hub'),
        channel_spec=valid_spec(name='History Hub'),
    )
    with pytest.raises(ValueError, match='brand name'):
        validate_agent_output(output)


def test_validate_agent_output_accepts_distinct_brand() -> None:
    validate_agent_output(valid_output())


def test_validate_agent_output_reports_every_failure_in_one_pass() -> None:
    """A dossier failure and a ChannelSpec failure must both surface at once."""
    output = ChannelResearchAgentOutput(
        research_report=valid_report(bend_count=1),
        channel_spec=valid_spec(hero_ratio=0.05),
    )
    with pytest.raises(ValueError) as exc_info:
        validate_agent_output(output)
    message = str(exc_info.value)
    assert 'niche_bend_opportunities' in message
    assert 'hero_ratio' in message


def test_lore_document_helper_meets_word_count() -> None:
    assert len(lore_document().split()) >= 400


def test_validate_channel_spec_rejects_lore_without_format_contract() -> None:
    spec = valid_spec(
        lore='Things we never do: slang. ' + ' '.join(['word'] * 420),
    )
    with pytest.raises(ValueError, match='FORMAT CONTRACT'):
        validate_channel_spec(spec)


def test_validate_channel_spec_requires_hero_ratio() -> None:
    spec = valid_spec()
    spec.channel.config_overrides = {}
    with pytest.raises(ValueError, match='hero_ratio'):
        validate_channel_spec(spec)


def _padded_template(seed: str) -> str:
    filler = (
        ' Keep the locked contract. Repeat the show grammar. '
        'Do not invent a new show. Stay inside the visual medium. '
    )
    needed = max(200 - len(seed), 0)
    copies = (needed // len(filler)) + 1 if needed else 0
    return seed + (filler * copies)


def _distinctive_templates(key: str) -> list[PromptTemplateBlock]:
    script = _padded_template(
        'FORMAT CONTRACT and hook: every video is a cold-open. '
        'Chapters: {{ upstream.outline.chapters }} ',
    )
    visual = _padded_template(
        '2d animation stills. Flat color, no photoreal. {{ visual_bible }} ',
    )
    scenes = _padded_template(
        'Shorter scenes so cuts stay dense for animation. '
        'Chapter {{ chapter.idx }}: {{ chapter.text }} ',
    )
    return [
        PromptTemplateBlock(
            key=f'script_{key}',
            name='s',
            system_prompt=script,
            user_prompt=script,
        ),
        PromptTemplateBlock(
            key=f'visual_prompts_{key}',
            name='v',
            system_prompt=visual,
            user_prompt=visual,
        ),
        PromptTemplateBlock(
            key=f'scene_breakdown_{key}',
            name='b',
            system_prompt=scenes,
            user_prompt=scenes,
        ),
    ]


def _distinctive_overrides(key: str) -> dict[str, str]:
    return {
        'script': f'script_{key}',
        'visual_prompts': f'visual_prompts_{key}',
        'scene_breakdown': f'scene_breakdown_{key}',
    }


def animated_spec() -> ChannelSpecModel:
    key = 'whiteboard_explainer'
    return valid_spec(
        lore=lore_document(medium='2d_animation'),
        create_if_missing=True,
        format_key=key,
        prompt_templates=_distinctive_templates(key),
        prompt_overrides=_distinctive_overrides(key),
        hero_ratio=0.4,
        extra_overrides={
            'scene_breakdown': {'min_seconds': 5, 'max_seconds': 8},
        },
        min_cuts=10,
        max_cuts=12,
        visual_medium='2d_animation',
        visual_bible=visual_bible_text(medium='2d_animation'),
        style_negatives=['photorealistic', 'live action'],
    )


def test_validate_medium_lock_accepts_animated_spec() -> None:
    spec = animated_spec()
    validate_channel_spec(spec)
    validate_medium_lock(
        spec,
        visual_medium='2d_animation',
        style_negatives=['photorealistic', 'live action'],
    )


def test_validate_medium_lock_rejects_shared_format_for_2d() -> None:
    spec = valid_spec(
        lore=lore_document(medium='2d_animation'),
        hero_ratio=0.4,
        visual_medium='2d_animation',
        visual_bible=visual_bible_text(medium='2d_animation'),
        style_negatives=['photorealistic'],
    )
    with pytest.raises(ValueError, match='create_if_missing'):
        validate_medium_lock(
            spec,
            visual_medium='2d_animation',
            style_negatives=['photorealistic'],
        )


def test_validate_medium_lock_rejects_wrong_hero_ratio() -> None:
    spec = valid_spec(hero_ratio=0.4)
    with pytest.raises(ValueError, match='hero_ratio for photoreal'):
        validate_medium_lock(spec, visual_medium='photoreal')


def test_validate_medium_lock_rejects_missing_template_stage() -> None:
    spec = animated_spec()
    spec.story_format.prompt_overrides['visual_prompts'] = 'wrong_key'
    with pytest.raises(
        ValueError,
        match=r'prompt_overrides\.visual_prompts',
    ):
        validate_medium_lock(
            spec,
            visual_medium='2d_animation',
            style_negatives=['photorealistic'],
        )


def test_validate_medium_lock_requires_style_negatives() -> None:
    spec = animated_spec()
    with pytest.raises(ValueError, match='style_negatives'):
        validate_medium_lock(
            spec,
            visual_medium='2d_animation',
            style_negatives=[],
        )


def test_validate_medium_lock_rejects_unknown_medium() -> None:
    with pytest.raises(ValueError, match='unknown visual_medium'):
        validate_medium_lock(valid_spec(), visual_medium='oil_painting')


def test_validate_medium_lock_rejects_stock_blueprint_for_2d() -> None:
    spec = animated_spec()
    spec.channel.default_blueprint_name = 'longform_documentary_v1'
    with pytest.raises(ValueError, match='stock documentary'):
        validate_medium_lock(
            spec,
            visual_medium='2d_animation',
            style_negatives=['photorealistic'],
        )


def test_validate_medium_lock_rejects_slow_cuts_for_2d() -> None:
    spec = animated_spec()
    spec.assembly_style.min_cuts_per_minute = 4
    spec.assembly_style.max_cuts_per_minute = 8
    with pytest.raises(ValueError, match='cuts for animation'):
        validate_medium_lock(
            spec,
            visual_medium='2d_animation',
            style_negatives=['photorealistic'],
        )


def test_validate_medium_lock_rejects_short_appearance() -> None:
    spec = animated_spec()
    spec.character.include = True
    spec.channel.character_design_mode = 'auto'
    spec.character.appearance_prompt = 'a red hat'
    with pytest.raises(ValueError, match='appearance_prompt'):
        validate_medium_lock(
            spec,
            visual_medium='2d_animation',
            style_negatives=['photorealistic'],
        )
    named_pairs: tuple[tuple[type, type], ...] = (
        (ChannelSpecModel, ChannelSpecPayload),
        (ChannelBlock, ChannelSpecChannelPayload),
        (NicheBlock, ChannelSpecNichePayload),
        (StoryFormatBlock, ChannelSpecStoryFormatPayload),
        (StoryFormatBeat, ChannelSpecStoryFormatBeatPayload),
        (PromptTemplateBlock, ChannelSpecPromptTemplatePayload),
        (BrandingBlock, ChannelSpecBrandingPayload),
        (AssemblyStyleBlock, ChannelSpecAssemblyStylePayload),
        (FootageSourcingBlock, ChannelSpecFootageSourcingPayload),
        (CharacterBlock, ChannelSpecCharacterPayload),
        (SeedIdeaBlock, ChannelSpecSeedIdeaPayload),
        (ResearchReport, ResearchReportPayload),
        (SourceChannelStats, SourceChannelStatsPayload),
        (FormatProfile, FormatProfilePayload),
        (VideoRef, VideoRefPayload),
        (CompetitorRef, CompetitorRefPayload),
        (NicheBendOpportunity, NicheBendOpportunityPayload),
        (ResearchSourceRef, ResearchSourceRefPayload),
    )
    for pydantic_cls, struct_cls in named_pairs:
        pydantic_fields = set(pydantic_cls.model_fields)
        struct_fields = set(struct_cls.__struct_fields__)
        assert pydantic_fields == struct_fields, pydantic_cls.__name__


def test_validate_medium_lock_requires_visual_medium() -> None:
    spec = valid_spec()
    spec.niche.visual_medium = None
    with pytest.raises(ValueError, match='visual_medium is required'):
        validate_medium_lock(spec)


def test_validate_medium_lock_rejects_short_visual_bible() -> None:
    spec = valid_spec(visual_bible='photoreal stills only.')
    with pytest.raises(ValueError, match='visual_bible must be'):
        validate_medium_lock(spec)


def test_validate_medium_lock_rejects_bible_missing_medium() -> None:
    bible = 'Oil on canvas stills lock palette and line. ' + ' '.join(
        ['token'] * 90,
    )
    spec = valid_spec(visual_bible=bible)
    with pytest.raises(ValueError, match='sentence one'):
        validate_medium_lock(spec)


def test_validate_medium_lock_accepts_hyphenated_medium_mention() -> None:
    """Natural hyphenation of a multi-word medium must not fail the check.

    Requiring the literal underscore- or single-space-joined enum value
    ("2d animation") is brittle against ordinary phrasing like
    "2D-animated" - that turned "name the medium" into a rule the agent
    kept failing every retry on punctuation alone, never on substance.
    """
    spec = animated_spec()
    spec.niche.visual_bible = (
        'This 2D-animation series locks a flat color palette and '
        'consistent line weight throughout every scene. '
        + ' '.join(['token'] * 90)
    )
    validate_medium_lock(spec, visual_medium='2d_animation')


def test_validate_medium_lock_reports_every_failure_in_one_pass() -> None:
    """A too-short bible missing the medium mention, plus a bad hero_ratio.

    Both kinds of failure must surface together, not one rule per retry.
    This mirrors a real failure: the agent kept losing its whole
    output-retry budget re-discovering visual_bible's two independent
    checks (length, then medium mention) and hero_ratio one at a time
    across separate turns, never reaching a valid final answer.
    """
    spec = valid_spec(
        visual_bible='Too short and never names the medium.',
        hero_ratio=0.05,
    )
    with pytest.raises(ValueError) as exc_info:
        validate_medium_lock(spec)
    message = str(exc_info.value)
    assert 'visual_bible must be' in message
    assert 'sentence one' in message
    assert 'hero_ratio' in message


def test_validate_medium_lock_rejects_short_distinctive_templates() -> None:
    spec = animated_spec()
    spec.prompt_templates[0].user_prompt = 'x'
    with pytest.raises(ValueError, match='200'):
        validate_medium_lock(spec)


def test_validate_medium_lock_rejects_visual_template_without_medium() -> None:
    spec = animated_spec()
    padded = _padded_template(
        'FORMAT CONTRACT locked. Camera and palette stay frozen. ',
    )
    spec.prompt_templates[1].system_prompt = padded
    spec.prompt_templates[1].user_prompt = padded
    with pytest.raises(ValueError, match='must literally say'):
        validate_medium_lock(spec)


def test_validate_medium_lock_rejects_script_without_format_hook() -> None:
    spec = animated_spec()
    padded = _padded_template(
        'Write narration in this voice and stay in world. ',
    )
    spec.prompt_templates[0].system_prompt = padded
    spec.prompt_templates[0].user_prompt = padded
    with pytest.raises(ValueError, match='format/hook'):
        validate_medium_lock(spec)
