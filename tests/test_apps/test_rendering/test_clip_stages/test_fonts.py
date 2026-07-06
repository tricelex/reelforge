from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server.apps.rendering.clip_stages import fonts as fonts_module
from server.apps.rendering.clip_stages.fonts import (
    CURATED_FONT_SLUGS,
    FONTS_DIR,
    build_fonts_dir,
    curated_font_family,
    curated_font_path,
    resolve_drawtext_font,
)


def test_curated_font_slugs_has_sixteen_entries() -> None:
    assert len(CURATED_FONT_SLUGS) == 16
    assert 'MONTSERRAT_BOLD' in CURATED_FONT_SLUGS
    assert 'PACIFICO' in CURATED_FONT_SLUGS


def test_curated_font_path_resolves_under_fonts_dir() -> None:
    path = curated_font_path('MONTSERRAT_BOLD')
    assert path.parent == FONTS_DIR
    assert path.suffix == '.ttf'


def test_curated_font_path_unknown_slug_raises() -> None:
    with pytest.raises(KeyError):
        curated_font_path('NOT_A_REAL_SLUG')


def test_curated_font_family_extracts_name_from_file(tmp_path: Path) -> None:
    # A real TTF is required for fonttools to parse — skip when not vendored.
    path = curated_font_path('MONTSERRAT_BOLD')
    if not path.exists():
        pytest.skip('Bundled Montserrat-Bold.ttf not present')
    family = curated_font_family('MONTSERRAT_BOLD')
    assert isinstance(family, str)
    assert len(family) > 0


def test_resolve_drawtext_font_curated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        'server.apps.rendering.clip_stages.fonts.curated_font_family',
        lambda slug: 'Montserrat Bold',
    )
    path, family = resolve_drawtext_font('MONTSERRAT_BOLD', None)
    assert path.endswith('Montserrat-Bold.ttf')
    assert family == 'Montserrat Bold'


def test_resolve_drawtext_font_custom_asset() -> None:
    asset = MagicMock()
    asset.file.read.return_value = b'fake-ttf-bytes'
    asset.meta = {'font_family': 'My Custom Font'}
    path, family = resolve_drawtext_font('MONTSERRAT_BOLD', asset)
    assert family == 'My Custom Font'
    assert path != ''


def test_build_fonts_dir_includes_curated_and_custom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fonts_src = tmp_path / 'src_fonts'
    fonts_src.mkdir()
    for filename in fonts_module._CURATED_FONT_FILES.values():
        (fonts_src / filename).write_bytes(b'fake-ttf')
    monkeypatch.setattr(fonts_module, 'FONTS_DIR', fonts_src)
    asset = MagicMock()
    asset.id = 'custom-1'
    asset.file.read.return_value = b'fake-ttf-bytes'
    asset.meta = {'font_family': 'My Custom Font'}
    fonts_dir = build_fonts_dir(tmp_path / 'render', [asset, None])
    files = list(fonts_dir.glob('*.ttf'))
    assert len(files) == 17
