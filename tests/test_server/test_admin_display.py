"""Tests for Unfold admin display helpers."""

from types import SimpleNamespace

from server.common.admin_display import (
    STANDARD_STATUS_COLORS,
    make_badge_method,
    make_boolean_badge_method,
    make_header_method,
    make_money_method,
    merge_color_maps,
)


def test_merge_color_maps_combines_lookups() -> None:
    """Merged color map contains keys from all inputs."""
    left = {'PENDING': 'info'}
    right = {'FAILED': 'danger'}

    merged = merge_color_maps(left, right)

    assert merged == {'PENDING': 'info', 'FAILED': 'danger'}


def test_make_badge_method_reads_field() -> None:
    """Badge helper returns the model field value."""
    method = make_badge_method(
        'status',
        STANDARD_STATUS_COLORS,
        description='Status',
    )
    obj = SimpleNamespace(status='FAILED')

    assert method(None, obj) == 'FAILED'
    assert method.__name__ == 'display_status'


def test_make_boolean_badge_method_reads_field() -> None:
    """Boolean badge helper returns the model field value."""
    method = make_boolean_badge_method('is_active', description='Active')
    obj = SimpleNamespace(is_active=True)

    assert method(None, obj) is True
    assert method.__name__ == 'display_is_active'


def test_make_money_method_formats_decimal() -> None:
    """Money helper formats USD with fixed decimals."""
    method = make_money_method('total_cost_usd', decimals=2)
    obj = SimpleNamespace(total_cost_usd='12.3456')

    assert method(None, obj) == '$12.35'


def test_make_money_method_handles_none() -> None:
    """Money helper renders em dash for missing values."""
    method = make_money_method('total_cost_usd')
    obj = SimpleNamespace(total_cost_usd=None)

    assert method(None, obj) == '—'


def test_make_header_method_builds_lines() -> None:
    """Header helper returns primary, secondary, and initials."""
    method = make_header_method(
        'display_title',
        'Title',
        lambda obj: obj.title,
        lambda obj: obj.subtitle,
        initials=lambda obj: 'AB',
    )
    obj = SimpleNamespace(title='Main', subtitle='Secondary')

    assert method(None, obj) == ['Main', 'Secondary', 'AB']


def test_make_header_method_without_initials() -> None:
    """Header helper omits initials when not configured."""
    method = make_header_method(
        'display_title',
        'Title',
        lambda obj: obj.title,
        lambda obj: obj.subtitle,
    )
    obj = SimpleNamespace(title='Main', subtitle='Secondary')

    assert method(None, obj) == ['Main', 'Secondary']
