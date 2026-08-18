"""Tests for visual lock prefixes and Flux Kontext routing."""

from server.apps.pipelines.logic.visual_consistency import (
    DRIFT_NEGATIVE,
    FLUX_DEV,
    KONTEXT,
    KONTEXT_MULTI,
    apply_visual_lock,
    build_visual_lock_prefix,
    is_kontext_model,
    resolve_image_route,
)


def test_build_visual_lock_prefix_includes_lore_setting_appearance() -> None:
    """Lock text is assembled from channel lore, setting, and appearance."""
    prefix = build_visual_lock_prefix(
        lore='desaturated documentary, 16:9',
        angle='fall of empires',
        setting='Roman forum at dusk',
        appearance='Marcus, grey beard, crimson toga',
    )
    assert 'desaturated documentary' in prefix
    assert 'fall of empires' in prefix
    assert 'Roman forum at dusk' in prefix
    assert 'Marcus, grey beard, crimson toga' in prefix


def test_build_visual_lock_prefix_skips_empty_parts() -> None:
    """Zero-character runs omit appearance without leaving blanks."""
    prefix = build_visual_lock_prefix(
        lore='cinematic',
        angle='',
        setting='open sea',
        appearance='',
    )
    assert 'cinematic' in prefix
    assert 'open sea' in prefix
    assert 'Character lock' not in prefix


def test_build_visual_lock_prefix_all_empty_uses_generic_lock() -> None:
    """Zero lore/angle/setting/appearance still emits a camera-only lock."""
    prefix = build_visual_lock_prefix(
        lore='',
        angle='',
        setting='',
        appearance='',
    )
    assert 'Keep locked visual traits identical' in prefix
    assert 'Character lock' not in prefix


def test_apply_visual_lock_empty_prefix_keeps_prompt() -> None:
    """A blank prefix does not insert a leading newline."""
    prompt, negative = apply_visual_lock(
        'wide aerial',
        prefix='',
        negative='',
    )
    assert prompt == 'wide aerial'
    assert DRIFT_NEGATIVE in negative


def test_apply_visual_lock_does_not_duplicate_drift_negative() -> None:
    """Re-applying the lock does not stack the same negative twice."""
    prompt, negative = apply_visual_lock(
        'shot',
        prefix='x',
        negative=DRIFT_NEGATIVE,
    )
    assert negative.count('appearance drift') == 1
    assert prompt.startswith('x')


def test_apply_visual_lock_prepends_prefix_and_drift_negative() -> None:
    """Every prompt gets the lock prefix and a shared anti-drift negative."""
    prompt, negative = apply_visual_lock(
        'wide aerial of the forum',
        prefix='Setting lock: Roman forum',
        negative='modern cars',
    )
    assert prompt.startswith('Setting lock: Roman forum')
    assert 'wide aerial of the forum' in prompt
    assert 'modern cars' in negative
    assert DRIFT_NEGATIVE in negative


def test_resolve_image_route_plain_flux_without_refs() -> None:
    """Zero-cast, no establishing shot → flux/dev and no image_url."""
    route = resolve_image_route(
        character_url=None,
        setting_url=None,
        use_character_ref=True,
        default_model=FLUX_DEV,
    )
    assert route.model == FLUX_DEV
    assert route.image_url is None
    assert route.image_urls is None


def test_resolve_image_route_setting_only_uses_kontext() -> None:
    """A setting establishing shot is enough to call Kontext."""
    route = resolve_image_route(
        character_url=None,
        setting_url='https://cdn/forum.jpg',
        use_character_ref=True,
        default_model=FLUX_DEV,
    )
    assert route.model == KONTEXT
    assert route.image_url == 'https://cdn/forum.jpg'
    assert route.image_urls is None


def test_resolve_image_route_character_only_uses_kontext() -> None:
    """An approved hero sheet routes to single-image Kontext."""
    route = resolve_image_route(
        character_url='https://cdn/hero.jpg',
        setting_url=None,
        use_character_ref=True,
        default_model=FLUX_DEV,
    )
    assert route.model == KONTEXT
    assert route.image_url == 'https://cdn/hero.jpg'


def test_resolve_image_route_both_uses_kontext_multi() -> None:
    """Character sheet + setting anchor use the multi-ref endpoint."""
    route = resolve_image_route(
        character_url='https://cdn/hero.jpg',
        setting_url='https://cdn/forum.jpg',
        use_character_ref=True,
        default_model=FLUX_DEV,
    )
    assert route.model == KONTEXT_MULTI
    assert route.image_url is None
    assert route.image_urls == [
        'https://cdn/hero.jpg',
        'https://cdn/forum.jpg',
    ]


def test_resolve_image_route_ignores_character_when_flag_off() -> None:
    """use_character_ref false never sends a hero sheet."""
    route = resolve_image_route(
        character_url='https://cdn/hero.jpg',
        setting_url='https://cdn/forum.jpg',
        use_character_ref=False,
        default_model=FLUX_DEV,
    )
    assert route.model == KONTEXT
    assert route.image_url == 'https://cdn/forum.jpg'


def test_is_kontext_model_detects_both_endpoints() -> None:
    """Kontext single and multi models share the kontext argument shape."""
    assert is_kontext_model(KONTEXT) is True
    assert is_kontext_model(KONTEXT_MULTI) is True
    assert is_kontext_model(FLUX_DEV) is False


def test_resolve_image_route_blank_default_falls_back_to_flux_dev() -> None:
    """Empty default_model with no refs still uses flux/dev."""
    route = resolve_image_route(
        character_url=None,
        setting_url=None,
        use_character_ref=True,
        default_model='',
    )
    assert route.model == FLUX_DEV
