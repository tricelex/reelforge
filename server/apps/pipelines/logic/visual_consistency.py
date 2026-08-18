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


class ImageRoute(NamedTuple):
    """Which Flux endpoint to call and which reference URLs to send."""

    model: str
    image_url: str | None
    image_urls: list[str] | None


def build_visual_lock_prefix(
    *,
    lore: str,
    angle: str,
    setting: str,
    appearance: str,
) -> str:
    """Frozen tokens prepended to every Flux prompt in code."""
    parts: list[str] = []
    if lore.strip():
        parts.append(f'Style lock: {lore.strip()}')
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
