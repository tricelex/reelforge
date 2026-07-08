"""Tests for the shared pool-rotation helper."""

from server.apps.pipelines.logic.pool_rotation import pick_cyclic


def test_pick_cyclic_cycles_by_index() -> None:
    pool = ['a', 'b', 'c']
    assert pick_cyclic(pool, 0, 'default') == 'a'
    assert pick_cyclic(pool, 1, 'default') == 'b'
    assert pick_cyclic(pool, 3, 'default') == 'a'


def test_pick_cyclic_empty_pool_returns_default() -> None:
    assert pick_cyclic([], 0, 'default') == 'default'
