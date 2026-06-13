import pytest

from server.apps.channels.models import Channel, ChannelKind


@pytest.fixture()
def channel(db: None) -> Channel:
    return Channel.objects.create(name='Test Channel', kind=ChannelKind.LONGFORM)
