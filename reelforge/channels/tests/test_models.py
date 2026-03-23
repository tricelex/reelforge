from __future__ import annotations

import pytest
from django.db import IntegrityError

from ***REMOVED***.channels.models import SocialAccount
from ***REMOVED***.channels.tests.factories import ChannelFactory
from ***REMOVED***.channels.tests.factories import SocialAccountFactory


@pytest.mark.django_db
def test_social_account_str() -> None:
    account = SocialAccountFactory(platform=SocialAccount.Platform.YOUTUBE, handle="@mychannel")
    assert "YouTube" in str(account)
    assert "@mychannel" in str(account)


@pytest.mark.django_db
def test_social_account_unique_together_enforced() -> None:
    channel = ChannelFactory()
    SocialAccountFactory(channel=channel, platform=SocialAccount.Platform.YOUTUBE, account_id="UC123")
    with pytest.raises(IntegrityError):
        SocialAccountFactory(channel=channel, platform=SocialAccount.Platform.YOUTUBE, account_id="UC123")


@pytest.mark.django_db
def test_social_account_multiple_platforms_same_channel() -> None:
    channel = ChannelFactory()
    SocialAccountFactory(channel=channel, platform=SocialAccount.Platform.YOUTUBE, account_id="UC123")
    SocialAccountFactory(channel=channel, platform=SocialAccount.Platform.TIKTOK, account_id="TT456")
    expected_count = 2
    assert channel.social_accounts.count() == expected_count


@pytest.mark.django_db
def test_get_youtube_account_returns_active_account() -> None:
    channel = ChannelFactory()
    yt = SocialAccountFactory(channel=channel, platform=SocialAccount.Platform.YOUTUBE, is_active=True)
    assert channel.get_youtube_account() == yt


@pytest.mark.django_db
def test_get_youtube_account_returns_none_when_not_connected() -> None:
    channel = ChannelFactory()
    assert channel.get_youtube_account() is None
