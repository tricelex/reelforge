"""Scene-count, coverage, and setting-anchor helpers for longform density."""

from typing import Any, Final

DEFAULT_MIN_WORDS: Final = 10
DEFAULT_MAX_WORDS: Final = 35
DEFAULT_MIN_SECONDS: Final = 6.0
DEFAULT_MAX_SECONDS: Final = 12.0
COVERAGE_RATIO_MIN: Final = 0.95
COVERAGE_RATIO_MAX: Final = 1.10
DEFAULT_MAX_HERO_SCENES: Final = 6
MAX_SETTING_ANCHORS: Final = 8
SCHEMA_MIN_WORDS: Final = 5
SCHEMA_MAX_WORDS: Final = 40


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def density_bounds(
    config: dict[str, Any],
) -> tuple[int, int, float, float]:
    """Return min/max words and seconds from stage config."""
    min_words = _as_int(config.get('min_words'), DEFAULT_MIN_WORDS)
    max_words = _as_int(config.get('max_words'), DEFAULT_MAX_WORDS)
    min_seconds = _as_float(config.get('min_seconds'), DEFAULT_MIN_SECONDS)
    max_seconds = _as_float(config.get('max_seconds'), DEFAULT_MAX_SECONDS)
    return min_words, max_words, min_seconds, max_seconds


def coverage_limits(config: dict[str, Any]) -> tuple[float, float]:
    """Return allowed scene-word / chapter-word coverage band."""
    low = _as_float(
        config.get('coverage_ratio_min'),
        COVERAGE_RATIO_MIN,
    )
    high = _as_float(
        config.get('coverage_ratio_max'),
        COVERAGE_RATIO_MAX,
    )
    return low, high


def max_hero_scenes(config: dict[str, Any]) -> int | None:
    """Cap Kling hero flags when configured; None means do not clamp."""
    if 'max_hero_scenes' not in config:
        return None
    return max(
        0,
        _as_int(config.get('max_hero_scenes'), DEFAULT_MAX_HERO_SCENES),
    )


def chapter_word_count(text: str) -> int:
    """Count words the same way alignment quotas do."""
    return len(text.split())


def coverage_ok(
    scene_word_sum: int,
    chapter_words: int,
    ratio_min: float = COVERAGE_RATIO_MIN,
    ratio_max: float = COVERAGE_RATIO_MAX,
) -> bool:
    """True when scene narration covers the chapter within the ratio band."""
    if chapter_words <= 0:
        return scene_word_sum == 0
    ratio = scene_word_sum / chapter_words
    return ratio_min <= ratio <= ratio_max


def stitch_global_idx(
    chapter_scene_lists: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Renumber scene idx globally while preserving chapter_idx."""
    stitched: list[dict[str, Any]] = []
    next_idx = 0
    for chapter_scenes in chapter_scene_lists:
        for scene in chapter_scenes:
            row = dict(scene)
            row['idx'] = next_idx
            stitched.append(row)
            next_idx += 1
    return stitched


def clamp_hero_flags(
    scenes: list[dict[str, Any]],
    max_hero_scenes: int,
) -> list[dict[str, Any]]:
    """Keep the first N is_hero flags; clear the rest."""
    kept = 0
    out: list[dict[str, Any]] = []
    for scene in scenes:
        row = dict(scene)
        if bool(row.get('is_hero')):
            if kept >= max_hero_scenes:
                row['is_hero'] = False
            else:
                kept += 1
        out.append(row)
    return out


def normalize_setting(raw: str) -> str:
    """Canonical setting key: lowercase, collapsed whitespace."""
    return ' '.join(raw.casefold().split())


def select_anchor_settings(
    scenes: list[dict[str, Any]],
    max_anchors: int = MAX_SETTING_ANCHORS,
) -> list[str]:
    """First-seen unique settings, capped for establishing-shot budget."""
    keys: list[str] = []
    seen: set[str] = set()
    cap = max(0, max_anchors)
    for scene in scenes:
        if len(keys) >= cap:
            break
        key = normalize_setting(str(scene.get('setting') or ''))
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys
