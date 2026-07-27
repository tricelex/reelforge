"""Tests for server/common/broker.py."""

from aio_pika import ExchangeType

from server.common.broker import api_broker, render_broker


def test_api_broker_uses_direct_exchange_and_api_routing_key() -> None:
    assert api_broker._exchange_name == 'taskiq-api'  # noqa: SLF001
    assert api_broker._exchange_type is ExchangeType.DIRECT  # noqa: SLF001
    assert api_broker._routing_key == 'api'  # noqa: SLF001
    assert api_broker._queue_name == 'api'  # noqa: SLF001


def test_render_broker_uses_direct_exchange_and_render_routing_key() -> None:
    assert render_broker._exchange_name == 'taskiq-render'  # noqa: SLF001
    assert render_broker._exchange_type is ExchangeType.DIRECT  # noqa: SLF001
    assert render_broker._routing_key == 'render'  # noqa: SLF001
    assert render_broker._queue_name == 'render'  # noqa: SLF001


def test_brokers_use_distinct_exchanges_and_routing_keys() -> None:
    assert api_broker._exchange_name != render_broker._exchange_name  # noqa: SLF001
    assert api_broker._routing_key != render_broker._routing_key  # noqa: SLF001
