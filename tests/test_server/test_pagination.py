"""Tests for shared cursor pagination helpers."""

import uuid
from datetime import UTC, datetime

import pytest

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.common.pagination import (
    decode_cursor,
    encode_cursor,
    paginate_queryset,
)


@pytest.mark.django_db
def test_paginate_queryset_returns_next_cursor() -> None:
    """Second page is fetched using the encoded cursor."""
    Channel.objects.create(
        name='Alpha',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    Channel.objects.create(
        name='Beta',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )

    page_one, next_cursor, total = paginate_queryset(
        Channel.objects.order_by('-created_at', '-id'),
        cursor=None,
        limit=1,
    )

    assert total == 2
    assert len(page_one) == 1
    assert next_cursor is not None

    page_two, page_two_cursor, _ = paginate_queryset(
        Channel.objects.order_by('-created_at', '-id'),
        cursor=next_cursor,
        limit=1,
    )

    assert len(page_two) == 1
    assert page_two_cursor is None
    assert page_one[0].id != page_two[0].id


def test_encode_and_decode_cursor_round_trip() -> None:
    """Cursor encoding is reversible."""
    created_at = datetime(2026, 6, 19, 12, 0, 0, tzinfo=UTC)
    row_id = uuid.uuid4()
    cursor = encode_cursor(created_at, row_id)
    decoded_at, decoded_id = decode_cursor(cursor)
    assert decoded_at == created_at
    assert decoded_id == row_id
