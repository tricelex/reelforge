"""Curated font registry — bundled .ttf files + custom LibraryAsset fonts."""

from __future__ import annotations

import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.apps.assets.models import LibraryAsset

FONTS_DIR = Path(__file__).parent.parent / 'fonts'

# slug -> bundled filename. Slugs are our own stable identifiers (used as
# CaptionFont TextChoices values); filenames are the vendored Google Fonts
# static-weight files. The actual font family name libass needs is extracted
# from each file's name table, not hardcoded here — see curated_font_family.
_CURATED_FONT_FILES: dict[str, str] = {
    'MONTSERRAT_BOLD': 'Montserrat-Bold.ttf',
    'POPPINS_BOLD': 'Poppins-Bold.ttf',
    'INTER_BOLD': 'Inter-Bold.ttf',
    'ROBOTO_BOLD': 'Roboto-Bold.ttf',
    'OSWALD_BOLD': 'Oswald-Bold.ttf',
    'BEBAS_NEUE': 'BebasNeue-Regular.ttf',
    'ANTON': 'Anton-Regular.ttf',
    'ARCHIVO_BLACK': 'ArchivoBlack-Regular.ttf',
    'BANGERS': 'Bangers-Regular.ttf',
    'PERMANENT_MARKER': 'PermanentMarker-Regular.ttf',
    'CAVEAT_BOLD': 'Caveat-Bold.ttf',
    'LOBSTER': 'Lobster-Regular.ttf',
    'PLAYFAIR_DISPLAY_BOLD': 'PlayfairDisplay-Bold.ttf',
    'RIGHTEOUS': 'Righteous-Regular.ttf',
    'LUCKIEST_GUY': 'LuckiestGuy-Regular.ttf',
    'PACIFICO': 'Pacifico-Regular.ttf',
}

CURATED_FONT_SLUGS: tuple[str, ...] = tuple(_CURATED_FONT_FILES.keys())


def curated_font_path(slug: str) -> Path:
    """Return the bundled file path for a curated font slug.

    Raises:
        KeyError: If slug is not a known curated font.
    """
    return FONTS_DIR / _CURATED_FONT_FILES[slug]


@lru_cache(maxsize=32)
def _extract_family_name(path: str) -> str:
    from fontTools.ttLib import TTFont  # noqa: PLC0415

    with TTFont(path, lazy=True) as font:
        name_table = font['name']
        # Prefer the full name (ID 4); fall back to family name (ID 1).
        full_name = name_table.getDebugName(4)
        if full_name:
            return full_name
        family_name = name_table.getDebugName(1)
        return family_name or path


def curated_font_family(slug: str) -> str:
    """Return the font's real embedded family/full name, for ASS Fontname.

    Raises:
        KeyError: If slug is not a known curated font.
    """
    path = curated_font_path(slug)
    return _extract_family_name(str(path))


def resolve_drawtext_font(
    font_choice: str,
    font_asset: LibraryAsset | None,
) -> tuple[str, str]:
    """Return (fontfile_path, family_name) for a drawtext-based stage.

    A custom `font_asset` always overrides the curated `font_choice`. The
    asset's bytes are written to a temp file (mirroring the existing
    watermark_image/intro_asset pattern) and its family name is read from
    `meta['font_family']`, populated at ingest time (see Task 14).
    """
    if font_asset is not None:
        font_bytes: bytes = font_asset.file.read()
        with tempfile.NamedTemporaryFile(
            suffix='.ttf',
            delete=False,
        ) as tmp:
            tmp.write(font_bytes)
            path = tmp.name
        family = font_asset.meta.get('font_family', 'Custom Font')
        return path, family
    return str(curated_font_path(font_choice)), curated_font_family(
        font_choice,
    )


def build_fonts_dir(
    render_tmp_dir: Path,
    extra_assets: list[LibraryAsset | None],
) -> Path:
    """Assemble a per-render fonts directory for the `subtitles` filter's
    `fontsdir` option: bundled curated fonts + any custom font assets
    referenced by this render's style config.
    """
    fonts_dir = render_tmp_dir / 'fonts'
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for filename in _CURATED_FONT_FILES.values():
        src = FONTS_DIR / filename
        dest = fonts_dir / filename
        if not dest.exists() and src.exists():
            shutil.copy2(src, dest)
    for asset in extra_assets:
        if asset is None:
            continue
        font_bytes: bytes = asset.file.read()
        dest = fonts_dir / f'{asset.id}.ttf'
        dest.write_bytes(font_bytes)
    return fonts_dir
