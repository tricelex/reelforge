from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.models import SocialAccount


class ChannelFactory(DjangoModelFactory[Channel]):
    name = factory.Sequence(lambda n: f"Test Channel {n}")
    slug = factory.Sequence(lambda n: f"test-channel-{n}")
    niche_category = "FINANCE"
    target_niches = factory.LazyFunction(list)
    target_location = factory.LazyFunction(list)
    upload_schedule = factory.LazyFunction(list)
    default_tags = factory.LazyFunction(list)
    channel_keywords = factory.LazyFunction(list)

    class Meta:
        model = Channel
        django_get_or_create = ["slug"]


class SocialAccountFactory(DjangoModelFactory[SocialAccount]):
    channel = factory.SubFactory(ChannelFactory)
    platform = SocialAccount.Platform.YOUTUBE
    account_id = factory.Sequence(lambda n: f"UC{n:010d}")
    handle = factory.Sequence(lambda n: f"@testchannel{n}")
    display_name = factory.Sequence(lambda n: f"Test Channel {n}")
    is_active = True

    class Meta:
        model = SocialAccount
