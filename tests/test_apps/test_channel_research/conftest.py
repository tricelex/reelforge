"""Pytest fixtures for channel research tests."""

import pytest
from django.contrib.auth.models import User

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
)
from server.apps.channel_research.logic.schemas import (
    ChannelBlock,
    ChannelResearchAgentOutput,
    ChannelSpecModel,
    FormatProfile,
    NicheBendOpportunity,
    NicheBlock,
    ResearchReport,
    SourceChannelStats,
    StoryFormatBlock,
)
from server.apps.channel_research.models import ChannelResearchJob


def _lore(medium: str = 'photoreal') -> str:
    label = medium.replace('_', ' ')
    prefix = (
        'FORMAT CONTRACT: every video is a cold-open evidence stack. '
        'Title formula Why X actually Y. Hook is a named case then proof. '
        f'Visual identity: {label} archival maps and stills. '
        'Voice and tone stay dry. Things we never do: break the fourth wall. '
    )
    return prefix + ' '.join(['word'] * 410)


def _visual_bible(medium: str = 'photoreal') -> str:
    label = medium.replace('_', ' ')
    first = (
        f'{label} establishing stills lock palette line weight and camera. '
    )
    return first + ' '.join(['token'] * 90)


@pytest.fixture
def agent_output() -> ChannelResearchAgentOutput:
    """Agent output that passes the ChannelSpec quality bar."""
    bends = [
        NicheBendOpportunity(
            title=f'Bend {index}',
            market=f'market {index}',
            format_hook='cold open then evidence',
            rationale='format works; new market',
        )
        for index in range(3)
    ]
    return ChannelResearchAgentOutput(
        research_report=ResearchReport(
            source_channel=SourceChannelStats(
                channel_id='UCabcdefghijklmnopqrstuv',
                channel_name='Source Hub',
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
        ),
        channel_spec=ChannelSpecModel(
            channel=ChannelBlock(
                name='Forge History',
                kind='LONGFORM',
                config_overrides={'motion': {'hero_ratio': 0.2}},
            ),
            niche=NicheBlock(
                angle='documented history with a sharp editorial POV',
                lore_document=_lore(),
                visual_medium='photoreal',
                visual_bible=_visual_bible(),
            ),
            story_format=StoryFormatBlock(
                key='factual_documentary',
                name='Factual Documentary',
            ),
        ),
    )


@pytest.fixture
def research_job(db, api_user: User) -> ChannelResearchJob:  # type: ignore[no-untyped-def]
    """Pending research job owned by the operator fixture user."""
    return ChannelResearchJob.objects.create(
        source_channel_url='https://www.youtube.com/@HistoryHub',
        working_name='Forge History',
        kind=ChannelResearchKind.LONGFORM,
        status=ChannelResearchStatus.PENDING,
        created_by=api_user,
    )
