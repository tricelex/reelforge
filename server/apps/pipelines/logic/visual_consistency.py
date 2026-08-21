"""Visual-bible prefixes and Flux Kontext vs flux/dev routing."""

from typing import Final, NamedTuple

DRIFT_NEGATIVE: Final = (
    'appearance drift, wardrobe change, age change, hairstyle change, '
    'setting morph, anachronism, style shift, different person, '
    'different location identity'
)

FLUX_DEV: Final = 'fal-ai/flux/dev'
KONTEXT: Final = 'fal-ai/flux-pro/kontext'
KONTEXT_MULTI: Final = 'fal-ai/flux-pro/kontext/multi'

_ESTABLISHING_BY_MEDIUM: Final[dict[str, str]] = {
    '2d_animation': 'flat-color 2D animation still, locked lighting',
    '3d_cgi': '3D CGI still, locked lighting',
    'motion_graphics': 'motion-graphics still, locked lighting',
    'photoreal': 'photorealistic documentary still, locked lighting',
    'live_action_stock': (
        'photorealistic documentary still, locked lighting'
    ),
    'mixed': 'mixed-media still, locked lighting',
}


class ImageRoute(NamedTuple):
    """Which Flux endpoint to call and which reference URLs to send."""

    model: str
    image_url: str | None
    image_urls: list[str] | None


def build_visual_lock_prefix(
    *,
    lore: str = '',
    visual_bible: str = '',
    angle: str,
    setting: str,
    appearance: str,
) -> str:
    """Frozen tokens prepended to every Flux prompt in code."""
    parts: list[str] = []
    style = visual_bible.strip() or lore.strip()
    if style:
        parts.append(f'Style lock: {style}')
    if angle.strip():
        parts.append(f'Channel angle: {angle.strip()}')
    if setting.strip():
        parts.append(f'Setting lock: {setting.strip()}')
    if appearance.strip():
        parts.append(f'Character lock: {appearance.strip()}')
    if not parts:
        return (
            'Keep locked visual traits identical; change only camera, '
            'lens, and subject action.'
        )
    parts.append(
        'Keep locked traits identical; change only camera, lens, '
        'and subject action.',
    )
    return '\n'.join(parts)


def establishing_shot_prompt(setting: str, visual_medium: str) -> str:
    """Medium-specific wide establishing still prompt."""
    style = _ESTABLISHING_BY_MEDIUM.get(
        visual_medium,
        'cinematic still, locked lighting',
    )
    return (
        f'Wide establishing shot of {setting}, cinematic 16:9, {style}'
    )


def merge_style_negatives(
    negative: str,
    style_negatives: list[str],
) -> str:
    """Append niche style negatives without duplicating tokens."""
    extras = [item.strip() for item in style_negatives if item.strip()]
    if not extras:
        return negative
    extra = ', '.join(extras)
    if extra in negative:
        return negative
    if negative.strip():
        return f'{negative}, {extra}'
    return extra


def _as_text(value: object) -> str:
    return value if isinstance(value, str) else ''


def niche_style_fields(
    niche: object | None,
) -> tuple[str, str, str, list[str]]:
    """Return style lock, angle, visual_medium, style_negatives.

    Style lock prefers visual_bible and falls back to lore_document.
    """
    if niche is None:
        return '', '', '', []
    bible = _as_text(getattr(niche, 'visual_bible', ''))
    lore = _as_text(getattr(niche, 'lore_document', ''))
    angle = _as_text(getattr(niche, 'angle', ''))
    medium = _as_text(getattr(niche, 'visual_medium', ''))
    raw = getattr(niche, 'style_negatives', None)
    negatives = (
        [str(item) for item in raw if isinstance(item, str)]
        if isinstance(raw, list)
        else []
    )
    return bible.strip() or lore.strip(), angle, medium, negatives


def apply_visual_lock(
    prompt: str,
    *,
    prefix: str,
    negative: str,
) -> tuple[str, str]:
    """Prepend the visual bible and append anti-drift negatives."""
    locked = f'{prefix}\n{prompt}' if prefix.strip() else prompt
    if DRIFT_NEGATIVE in negative:
        merged = negative
    elif negative.strip():
        merged = f'{negative}, {DRIFT_NEGATIVE}'
    else:
        merged = DRIFT_NEGATIVE
    return locked, merged


def is_kontext_model(model: str) -> bool:
    """True for Flux Kontext single- and multi-image endpoints."""
    return 'kontext' in model


def resolve_image_route(
    *,
    character_url: str | None,
    setting_url: str | None,
    use_character_ref: bool,
    default_model: str,
) -> ImageRoute:
    """Pick flux/dev, Kontext, or Kontext multi from available refs.

    Never chain the previous scene. Character URLs are ignored when
    ``use_character_ref`` is false. Empty-cast runs stay on flux/dev
    unless a setting establishing shot exists.
    """
    char = character_url if use_character_ref else None
    setting = setting_url
    if char and setting:
        return ImageRoute(KONTEXT_MULTI, None, [char, setting])
    if char:
        return ImageRoute(KONTEXT, char, None)
    if setting:
        return ImageRoute(KONTEXT, setting, None)
    return ImageRoute(default_model or FLUX_DEV, None, None)
