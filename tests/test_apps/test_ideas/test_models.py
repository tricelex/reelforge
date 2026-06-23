"""Tests for ideas ORM models."""

import pytest

from server.apps.channels.models import Channel, ChannelKind, NicheConfig
from server.apps.ideas.logic.constants import IdeaStatus
from server.apps.ideas.models import TopicIdea


@pytest.fixture
def channel(db):  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Model Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def niche(channel):  # type: ignore[no-untyped-def]
    return NicheConfig.objects.create(
        channel=channel,
        audience='readers',
        angle='science',
    )


@pytest.mark.django_db
def test_topic_idea_str(channel, niche) -> None:  # type: ignore[no-untyped-def]
    """TopicIdea.__str__ returns the title (truncated to 60 chars)."""
    idea = TopicIdea.objects.create(
        channel=channel,
        niche=niche,
        title='Quantum computing explained',
        topic='A deep dive into qubits',
        status=IdeaStatus.BACKLOG,
    )
    assert str(idea) == 'Quantum computing explained'
