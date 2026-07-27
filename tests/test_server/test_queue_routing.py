"""Tests for server/common/queue_routing.py."""

from server.common.queue_routing import physical_queue


def test_physical_queue_render() -> None:
    assert physical_queue('render') == 'render'


def test_physical_queue_api() -> None:
    assert physical_queue('api') == 'api'


def test_physical_queue_gpu_maps_to_api() -> None:
    assert physical_queue('gpu') == 'api'


def test_physical_queue_orchestrator_maps_to_api() -> None:
    assert physical_queue('orchestrator') == 'api'
