"""Pure helpers for portrait/landscape canvas composition filters."""

from dataclasses import dataclass

from server.apps.clips.logic.constants import (
    DEFAULT_BACKGROUND_COLOR,
    DEFAULT_BLUR_STRENGTH,
    MAX_BLUR_STRENGTH,
    MIN_BLUR_STRENGTH,
    BackgroundMode,
    FitMode,
    ForegroundTreatment,
)

_MAX_CANVAS_EDGE = 7680


@dataclass(frozen=True, slots=True)
class MiddleZone:
    """Centered square zone inside the output canvas."""

    size: int
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class ResolvedComposition:
    """Effective composition settings for one render."""

    foreground_treatment: str
    background_mode: str
    background_color: str
    blur_strength: int


def middle_zone(width: int, height: int) -> MiddleZone:
    """Return the largest centered square that fits in the canvas."""
    if width <= 0 or height <= 0:
        msg = f'Canvas dimensions must be positive, got {width}x{height}'
        raise ValueError(msg)
    if width > _MAX_CANVAS_EDGE or height > _MAX_CANVAS_EDGE:
        msg = f'Canvas dimensions too large: {width}x{height}'
        raise ValueError(msg)
    size = min(width, height)
    return MiddleZone(
        size=size,
        x=(width - size) // 2,
        y=(height - size) // 2,
    )


def resolve_layout_composition(layout: object | None) -> ResolvedComposition:
    """Resolve composition from layout, including legacy fit_mode."""
    if layout is None:
        return ResolvedComposition(
            foreground_treatment=ForegroundTreatment.FILL,
            background_mode=BackgroundMode.SOLID,
            background_color=DEFAULT_BACKGROUND_COLOR,
            blur_strength=DEFAULT_BLUR_STRENGTH,
        )

    treatment = getattr(
        layout,
        'foreground_treatment',
        ForegroundTreatment.FILL,
    )
    bg_mode = getattr(layout, 'background_mode', BackgroundMode.SOLID)
    color = getattr(layout, 'background_color', DEFAULT_BACKGROUND_COLOR)
    blur = getattr(layout, 'blur_strength', DEFAULT_BLUR_STRENGTH)
    fit_mode = getattr(layout, 'fit_mode', FitMode.CROP)

    # Legacy rows / mocks that only set BLUR_FILL.
    if (
        treatment == ForegroundTreatment.FILL
        and bg_mode == BackgroundMode.SOLID
        and fit_mode == FitMode.BLUR_FILL
    ):
        return ResolvedComposition(
            foreground_treatment=ForegroundTreatment.CONTAIN,
            background_mode=BackgroundMode.BLURRED_SOURCE,
            background_color=color,
            blur_strength=blur,
        )

    blur_int = int(blur)
    if blur_int < MIN_BLUR_STRENGTH or blur_int > MAX_BLUR_STRENGTH:
        msg = f'Invalid blur_strength: {blur_int}'
        raise ValueError(msg)

    return ResolvedComposition(
        foreground_treatment=str(treatment),
        background_mode=str(bg_mode),
        background_color=str(color),
        blur_strength=blur_int,
    )


def needs_composed_background(composition: ResolvedComposition) -> bool:
    """Return True when the canvas needs a background behind the foreground."""
    return composition.foreground_treatment in {
        ForegroundTreatment.CONTAIN,
        ForegroundTreatment.SQUARE_CROP,
    }


def solid_background_filter(
    *,
    width: int,
    height: int,
    color: str,
    duration_sec: float,
) -> str:
    """Build an FFmpeg color source filter for a solid canvas background."""
    if width <= 0 or height <= 0:
        msg = f'Invalid solid background size: {width}x{height}'
        raise ValueError(msg)
    if duration_sec <= 0:
        msg = f'duration must be positive: {duration_sec}'
        raise ValueError(msg)
    safe_color = color if color.startswith('#') else f'#{color}'
    return (
        f'color=c={safe_color}:s={width}x{height}:d={duration_sec:.6f},'
        f'format=yuv420p[bg]'
    )


def blurred_background_filter(
    *,
    width: int,
    height: int,
    blur_strength: int,
    input_label: str = '0:v',
) -> str:
    """Build a scale/crop/blur chain that fills the canvas from the source."""
    if width <= 0 or height <= 0:
        msg = f'Invalid blur background size: {width}x{height}'
        raise ValueError(msg)
    if blur_strength < MIN_BLUR_STRENGTH or blur_strength > MAX_BLUR_STRENGTH:
        msg = f'Invalid blur_strength: {blur_strength}'
        raise ValueError(msg)
    return (
        f'[{input_label}]scale={width}:{height}:'
        f'force_original_aspect_ratio=increase,'
        f'crop={width}:{height},'
        f'boxblur={blur_strength}:5[bg]'
    )


def contain_foreground_filter(
    *,
    zone: MiddleZone,
    input_label: str = '0:v',
) -> str:
    """Scale source to fit inside the middle zone without cropping."""
    return (
        f'[{input_label}]scale={zone.size}:{zone.size}:'
        f'force_original_aspect_ratio=decrease[fg]'
    )


def square_crop_foreground_filter(
    *,
    zone: MiddleZone,
    crop_x: int | None,
    crop_y: int | None,
    crop_w: int | None,
    crop_h: int | None,
    input_label: str = '0:v',
) -> str:
    """Crop source to a square, then scale to the middle zone."""
    if (
        crop_x is not None
        and crop_y is not None
        and crop_w is not None
        and crop_h is not None
    ):
        side = min(crop_w, crop_h)
        return (
            f'[{input_label}]crop={side}:{side}:{crop_x}:{crop_y},'
            f'scale={zone.size}:{zone.size}[fg]'
        )
    return (
        f"[{input_label}]crop='min(iw,ih)':'min(iw,ih)',"
        f'scale={zone.size}:{zone.size}[fg]'
    )


def fill_crop_filter(*, width: int, height: int) -> str:
    """Aspect-aware center crop that fills the full canvas."""
    return (
        f"crop='min(iw,ih*{width}/{height})'"
        f":'min(ih,iw*{height}/{width})',"
        f'scale={width}:{height}'
    )


def compose_overlay_filter(
    *,
    zone: MiddleZone,
    video_suffix: str,
    fps: int,
) -> str:
    """Overlay a prepared [fg] onto [bg], centered in the middle zone."""
    return (
        f'[bg][fg]overlay='
        f'{zone.x}+({zone.size}-w)/2:'
        f'{zone.y}+({zone.size}-h)/2,'
        f'fps={fps}{video_suffix}[vout]'
    )
