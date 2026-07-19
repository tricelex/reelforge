"""Layout composition validation and legacy fit_mode sync."""

import re

from django.core.exceptions import ValidationError

from server.apps.clips.logic.constants import (
    DEFAULT_BACKGROUND_COLOR,
    DEFAULT_BLUR_STRENGTH,
    MAX_BLUR_STRENGTH,
    MIN_BLUR_STRENGTH,
    BackgroundMode,
    FitMode,
    ForegroundTreatment,
)

_HEX_COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')
_VALID_FOREGROUND = frozenset(ForegroundTreatment.values)
_VALID_BACKGROUND = frozenset(BackgroundMode.values)


def normalize_background_color(value: str) -> str:
    """Validate and normalize a solid background hex color."""
    normalized = value.strip().upper()
    if not _HEX_COLOR_RE.match(normalized):
        msg = f'Invalid background_color: {value}'
        raise ValidationError(msg)
    return normalized


def normalize_blur_strength(value: int) -> int:
    """Validate blur strength is within the allowed inclusive range."""
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f'Invalid blur_strength: {value}'
        raise ValidationError(msg)
    if value < MIN_BLUR_STRENGTH or value > MAX_BLUR_STRENGTH:
        msg = (
            f'blur_strength must be between {MIN_BLUR_STRENGTH} '
            f'and {MAX_BLUR_STRENGTH}, got {value}'
        )
        raise ValidationError(msg)
    return value


def normalize_foreground_treatment(value: str) -> str:
    """Validate a foreground treatment enum value."""
    if value not in _VALID_FOREGROUND:
        msg = f'Invalid foreground_treatment: {value}'
        raise ValidationError(msg)
    return value


def normalize_background_mode(value: str) -> str:
    """Validate a background mode enum value."""
    if value not in _VALID_BACKGROUND:
        msg = f'Invalid background_mode: {value}'
        raise ValidationError(msg)
    return value


def fit_mode_from_composition(
    *,
    foreground_treatment: str,
    background_mode: str,
) -> str:
    """Derive legacy fit_mode from composition fields."""
    if (
        foreground_treatment == ForegroundTreatment.CONTAIN
        and background_mode == BackgroundMode.BLURRED_SOURCE
    ):
        return FitMode.BLUR_FILL
    return FitMode.CROP


def apply_legacy_fit_mode(
    *,
    fit_mode: str,
) -> tuple[str, str, str, int]:
    """Map a legacy fit_mode patch onto composition fields."""
    if fit_mode == FitMode.BLUR_FILL:
        return (
            ForegroundTreatment.CONTAIN,
            BackgroundMode.BLURRED_SOURCE,
            DEFAULT_BACKGROUND_COLOR,
            DEFAULT_BLUR_STRENGTH,
        )
    return (
        ForegroundTreatment.FILL,
        BackgroundMode.SOLID,
        DEFAULT_BACKGROUND_COLOR,
        DEFAULT_BLUR_STRENGTH,
    )


def resolve_composition(
    *,
    foreground_treatment: str | None,
    background_mode: str | None,
    background_color: str | None,
    blur_strength: int | None,
    fit_mode: str | None,
) -> tuple[str, str, str, int]:
    """Resolve effective composition, preferring explicit new fields.

    When only legacy ``fit_mode`` is provided, map it onto composition.
    Explicit composition fields win when both are present.
    """
    if (
        foreground_treatment is None
        and background_mode is None
        and background_color is None
        and blur_strength is None
        and fit_mode is not None
    ):
        return apply_legacy_fit_mode(fit_mode=fit_mode)

    treatment = (
        normalize_foreground_treatment(foreground_treatment)
        if foreground_treatment is not None
        else ForegroundTreatment.FILL
    )
    bg_mode = (
        normalize_background_mode(background_mode)
        if background_mode is not None
        else BackgroundMode.SOLID
    )
    color = (
        normalize_background_color(background_color)
        if background_color is not None
        else DEFAULT_BACKGROUND_COLOR
    )
    blur = (
        normalize_blur_strength(blur_strength)
        if blur_strength is not None
        else DEFAULT_BLUR_STRENGTH
    )
    return treatment, bg_mode, color, blur
