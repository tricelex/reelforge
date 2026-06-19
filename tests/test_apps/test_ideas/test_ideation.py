"""Unit tests for ideation helpers and post-processing."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    NicheConfig,
    PublishMode,
)
from server.apps.ideas.ideation import _agent, _build_prompt, run_ideation_agent
from server.apps.ideas.logic.filters import (
    filter_ideation_candidates,
    touches_banned,
)
from server.apps.ideas.logic.schemas import (
    IdeationOutput,
    SourceRef,
    SourceSnapshot,
    TopicCandidate,
)
from server.apps.ideas.logic.value_objects import IdeaGeneratePayload
from server.apps.ideas.selectors import IdeationContext, build_ideation_context
from server.apps.ideas.services import IdeationService
from server.apps.ideas.source_ingest import ingest_youtube
from server.apps.pipelines.services.pipeline_run import PipelineRunService


def test_touches_banned_ignores_blank_terms() -> None:
    """Blank banned terms do not match everything."""
    assert not touches_banned('Rome logistics', ['', '   '])


def test_filter_rejects_banned_title() -> None:
    """Banned words in the title reject the candidate."""
    candidates = [
        TopicCandidate(
            title='crypto secrets',
            topic='Valid topic about Rome',
            score=0.9,
            remix_strategy='a',
            hook_pattern='h1',
            differentiation='d1',
        ),
    ]
    accepted = filter_ideation_candidates(
        candidates,
        count=1,
        existing=set(),
        banned_topics=['crypto'],
    )
    assert accepted == []


def test_build_prompt_includes_niche_and_remix_fields() -> None:
    """Prompt builder injects niche config and source snapshot."""
    context = IdeationContext(
        audience='history buffs',
        angle='ancient empires',
        lore_document='Lore doc',
        banned_topics=['crypto'],
        format_name='epic_doc',
        existing_topics={'old topic'},
    )
    source = SourceSnapshot(
        url='https://youtu.be/abc',
        video_id='abc',
        title='Viral',
        description='desc',
        channel='Hub',
        duration_sec=90.0,
        view_count=None,
        caption_text='captions',
    )

    niche_prompt = _build_prompt(context, None, count=3)
    assert 'NICHE-ONLY MODE' in niche_prompt
    assert 'epic_doc' in niche_prompt
    assert 'Lore doc' in niche_prompt

    remix_prompt = _build_prompt(context, source, count=3)
    assert 'REMIX MODE' in remix_prompt
    assert 'unknown' in remix_prompt


def test_run_ideation_agent_delegates_to_cached_agent() -> None:
    """run_ideation_agent returns structured output from the agent."""
    context = IdeationContext(
        audience='a',
        angle='b',
        lore_document='',
        banned_topics=[],
        format_name='',
        existing_topics=set(),
    )
    expected = IdeationOutput(ideas=[])
    mock_agent = MagicMock()
    mock_agent.run_sync.return_value = MagicMock(output=expected)

    with patch('server.apps.ideas.ideation._agent', return_value=mock_agent):
        result = run_ideation_agent(context, source=None, count=2)

    assert result == expected
    mock_agent.run_sync.assert_called_once()


@pytest.mark.django_db
def test_build_ideation_context_reads_niche(niche: NicheConfig) -> None:
    """Selector bundles niche fields and existing topics."""
    context = build_ideation_context(niche)
    assert context.audience == 'history buffs'
    assert 'crypto' in context.banned_topics


@pytest.mark.django_db
def test_get_idea_returns_empty_metadata_default(
    niche: NicheConfig,
) -> None:
    """Ideas without metadata expose an empty dict in the payload."""
    from server.apps.ideas.models import TopicIdea
    from server.apps.ideas.selectors import get_idea

    idea = TopicIdea.objects.create(
        channel=niche.channel,
        niche=niche,
        title='No metadata',
        topic='Topic',
        metadata={},
    )
    payload = get_idea(str(idea.id))
    assert payload.metadata == {}


@pytest.mark.django_db
def test_get_idea_returns_stored_metadata(niche: NicheConfig) -> None:
    """Non-empty metadata is exposed on the payload."""
    from server.apps.ideas.models import TopicIdea
    from server.apps.ideas.selectors import get_idea

    idea = TopicIdea.objects.create(
        channel=niche.channel,
        niche=niche,
        title='With metadata',
        topic='Topic',
        metadata={'source_type': 'niche_only'},
    )
    payload = get_idea(str(idea.id))
    assert payload.metadata['source_type'] == 'niche_only'
    """Selector bundles niche fields and existing topics."""
    context = build_ideation_context(niche)
    assert context.audience == 'history buffs'
    assert 'crypto' in context.banned_topics


@pytest.fixture
def niche(db) -> NicheConfig:  # type: ignore[no-untyped-def]
    """Longform niche for ideation unit tests."""
    channel = Channel.objects.create(
        name='Unit Ideation',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )
    return NicheConfig.objects.create(
        channel=channel,
        audience='history buffs',
        angle='ancient empires',
        banned_topics=['crypto'],
    )


def test_cached_agent_is_created() -> None:
    """Agent factory returns a configured PydanticAI agent."""
    _agent.cache_clear()
    agent = _agent()
    assert agent is _agent()


def test_filter_skips_empty_topic() -> None:
    """Blank topic strings are ignored."""
    candidates = [
        TopicCandidate(
            title='Empty',
            topic='   ',
            score=0.9,
            remix_strategy='a',
            hook_pattern='h1',
            differentiation='d1',
        ),
    ]
    assert filter_ideation_candidates(
        candidates,
        count=1,
        existing=set(),
        banned_topics=[],
    ) == []


def test_filter_candidates_dedupes_and_sorts() -> None:
    candidates = [
        TopicCandidate(
            title='Low',
            topic='Same topic',
            score=0.4,
            remix_strategy='a',
            hook_pattern='h1',
            differentiation='d1',
        ),
        TopicCandidate(
            title='High',
            topic='Unique alpha',
            score=0.95,
            remix_strategy='b',
            hook_pattern='h2',
            differentiation='d2',
        ),
        TopicCandidate(
            title='Dup',
            topic='Same topic',
            score=0.99,
            remix_strategy='c',
            hook_pattern='h3',
            differentiation='d3',
        ),
    ]
    accepted = filter_ideation_candidates(
        candidates,
        count=2,
        existing={'existing topic'},
        banned_topics=[],
    )
    assert len(accepted) == 2
    assert accepted[0].topic == 'Same topic'
    assert accepted[0].score == pytest.approx(0.99)
    assert accepted[1].topic == 'Unique alpha'


def test_filter_candidates_respects_banned_topics() -> None:
    """Ideas touching banned terms are removed."""
    candidates = [
        TopicCandidate(
            title='Bad',
            topic='Why crypto will moon',
            score=0.9,
            remix_strategy='a',
            hook_pattern='h1',
            differentiation='d1',
        ),
        TopicCandidate(
            title='Good',
            topic='Fall of Rome logistics',
            score=0.8,
            remix_strategy='b',
            hook_pattern='h2',
            differentiation='d2',
        ),
    ]
    accepted = filter_ideation_candidates(
        candidates,
        count=5,
        existing=set(),
        banned_topics=['crypto'],
    )
    assert len(accepted) == 1
    assert accepted[0].title == 'Good'


def test_ingest_youtube_rejects_non_youtube_url() -> None:
    """Non-YouTube URLs raise ValidationError."""
    with pytest.raises(ValidationError, match='YouTube'):
        ingest_youtube('https://example.com/video')


@pytest.mark.django_db
def test_generate_uses_agent_and_persists_metadata(
    niche: NicheConfig,
) -> None:
    """Service wires agent output into TopicIdea rows with metadata."""
    service = IdeationService(runs=MagicMock(spec=PipelineRunService))
    mock_output = IdeationOutput(
        ideas=[
            TopicCandidate(
                title='Rome supply lines',
                topic='How Roman logistics caused collapse',
                score=0.91,
                remix_strategy='deeper_dive',
                hook_pattern='counterintuitive_fact',
                differentiation='Maps and grain routes',
                source_refs=[
                    SourceRef(
                        url='https://youtu.be/abc',
                        title='Viral Rome',
                        video_id='abc',
                    ),
                ],
            ),
        ],
    )
    mock_source = SourceSnapshot(
        url='https://youtu.be/abc',
        video_id='abc',
        title='Viral Rome',
        description='desc',
        channel='History Hub',
        duration_sec=600.0,
        view_count=1_000_000,
        caption_text='transcript excerpt',
    )

    with (
        patch(
            'server.apps.ideas.services.run_ideation_agent',
            return_value=mock_output,
        ),
        patch(
            'server.apps.ideas.services.ingest_youtube',
            return_value=mock_source,
        ),
    ):
        result = service.generate(
            str(niche.id),
            IdeaGeneratePayload(
                count=1,
                source_url='https://youtu.be/abc',
            ),
        )

    assert result.total == 1
    item = result.items[0]
    assert item.metadata['source_type'] == 'youtube_remix'
    assert item.metadata['remix_strategy'] == 'deeper_dive'
    assert item.metadata['source_snapshot']['video_id'] == 'abc'


@pytest.mark.django_db
def test_generate_raises_when_all_filtered(
    niche: NicheConfig,
) -> None:
    """ValidationError when post-filter removes every candidate."""
    service = IdeationService(runs=MagicMock(spec=PipelineRunService))
    mock_output = IdeationOutput(
        ideas=[
            TopicCandidate(
                title='Bad',
                topic='crypto scams in Rome',
                score=0.9,
                remix_strategy='a',
                hook_pattern='h1',
                differentiation='d1',
            ),
        ],
    )

    with patch(
        'server.apps.ideas.services.run_ideation_agent',
        return_value=mock_output,
    ), pytest.raises(ValidationError, match='No unique ideas'):
        service.generate(
            str(niche.id),
            IdeaGeneratePayload(count=1),
        )
