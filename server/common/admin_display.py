"""Unfold @display helpers for ReelForge admin changelists."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

from django_stubs_ext import StrOrPromise
from unfold.decorators import display

# Shared semantic colors for lifecycle statuses across apps.
COLOR_INFO = 'info'
COLOR_SUCCESS = 'success'
COLOR_WARNING = 'warning'
COLOR_DANGER = 'danger'

ACTIVE_COLORS: dict[str, str] = {
    'ACTIVE': COLOR_SUCCESS,
    'APPROVED': COLOR_SUCCESS,
    'COMPLETED': COLOR_SUCCESS,
    'DISTRIBUTED': COLOR_SUCCESS,
    'POSTED': COLOR_SUCCESS,
    'PROMOTED': COLOR_SUCCESS,
    'READY': COLOR_SUCCESS,
    'RENDERED': COLOR_SUCCESS,
    'SUCCEEDED': COLOR_SUCCESS,
}

PENDING_COLORS: dict[str, str] = {
    'BACKLOG': COLOR_INFO,
    'DRAFT': COLOR_INFO,
    'INGESTING': COLOR_INFO,
    'PENDING': COLOR_INFO,
    'PROPOSED': COLOR_INFO,
    'QUEUED': COLOR_INFO,
    'RUNNING': COLOR_INFO,
    'UPLOADING': COLOR_INFO,
    'POSTING': COLOR_INFO,
    'RENDERING': COLOR_INFO,
    'DISTRIBUTING': COLOR_INFO,
}

WARNING_COLORS: dict[str, str] = {
    'AWAITING_REVIEW': COLOR_WARNING,
    'BUDGET_HOLD': COLOR_WARNING,
    'PUBLISH_HOLD': COLOR_WARNING,
    'NEEDS_INPUT': COLOR_WARNING,
    'SKIPPED': COLOR_WARNING,
    'STALE': COLOR_WARNING,
}

DANGER_COLORS: dict[str, str] = {
    'CANCELLED': COLOR_DANGER,
    'DEMOTED': COLOR_DANGER,
    'FAILED': COLOR_DANGER,
    'INACTIVE': COLOR_DANGER,
    'REJECTED': COLOR_DANGER,
    'RETIRED': COLOR_DANGER,
}


def merge_color_maps(*maps: dict[str, str]) -> dict[str, str]:
    """Merge status color maps into one lookup."""
    merged: dict[str, str] = {}
    for color_map in maps:
        merged.update(color_map)
    return merged


STANDARD_STATUS_COLORS = merge_color_maps(
    ACTIVE_COLORS,
    PENDING_COLORS,
    WARNING_COLORS,
    DANGER_COLORS,
)


def make_badge_method(
    field: str,
    color_map: dict[Any, str],
    *,
    description: StrOrPromise | None = None,
) -> Callable[..., Any]:
    """Build a changelist column with Unfold colored status badges."""
    label = description or field.replace('_', ' ').title()

    @display(description=label, ordering=field, label=color_map)  # type: ignore[untyped-decorator]
    def method(_self: object, obj: Any) -> Any:
        return getattr(obj, field)

    method.__name__ = f'display_{field}'
    return cast('Callable[..., Any]', method)


def make_boolean_badge_method(
    field: str,
    *,
    description: StrOrPromise | None = None,
    true_label: str = COLOR_SUCCESS,
    false_label: str = COLOR_DANGER,
) -> Callable[..., bool]:
    """Build a changelist column with boolean success/danger badges."""
    label = description or field.replace('_', ' ').title()

    @display(
        description=label,
        ordering=field,
        label={True: true_label, False: false_label},
    )  # type: ignore[untyped-decorator]
    def method(_self: object, obj: Any) -> bool:
        return bool(getattr(obj, field))

    method.__name__ = f'display_{field}'
    return cast('Callable[..., bool]', method)


def make_money_method(
    field: str,
    *,
    description: StrOrPromise | None = None,
    decimals: int = 4,
) -> Callable[..., str]:
    """Build a changelist column with formatted USD amounts."""
    label = description or field.replace('_', ' ').title()

    @display(description=label, ordering=field)  # type: ignore[untyped-decorator]
    def method(_self: object, obj: Any) -> str:
        value = getattr(obj, field)
        if value is None:
            return '—'
        amount = Decimal(str(value))
        return f'${amount:.{decimals}f}'

    method.__name__ = f'display_{field}'
    return cast('Callable[..., str]', method)


def make_header_method(
    method_name: str,
    description: StrOrPromise,
    primary: Callable[[Any], str],
    secondary: Callable[[Any], str | None],
    *,
    initials: Callable[[Any], str | None] | None = None,
) -> Callable[..., list[str | None]]:
    """Build a two-line changelist column with optional initials badge."""

    @display(header=True, description=description)  # type: ignore[untyped-decorator]
    def method(_self: object, obj: Any) -> list[str | None]:
        lines: list[str | None] = [primary(obj), secondary(obj)]
        if initials is not None:
            lines.append(initials(obj))
        return lines

    method.__name__ = method_name
    return cast('Callable[..., list[str | None]]', method)
