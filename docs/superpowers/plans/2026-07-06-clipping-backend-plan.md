# Clipping Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the clipping render pipeline into a fully-featured, CapCut-parity
style/effects layer on one clip candidate — fixing the transition/image-overlay/
caption-animation no-ops and adding fonts, color grading, speed ramp, video/PIP
overlays, custom transitions, and an SFX library.

**Architecture:** Extend the existing `ClipStyleConfig`/`ClipLayoutConfig`/
`ClipTimedOverlay` models and the 10-stage `ClipRenderPipeline`
(`server/apps/rendering/clip_stages/`) in place. No new apps, no DAG changes —
everything lives inside the existing `clip_render` pipeline node.

**Tech Stack:** Django 6.0, msgspec (value objects), django-modern-rest (DMR)
controllers, ffmpeg/ffprobe via `subprocess`, pytest, `fonttools` (new).

**Spec:** `docs/superpowers/specs/2026-07-06-clipping-fully-featured-design.md`

## Global Constraints

- Python 3.13.x, Django 6.0.x. `ruff` single quotes, 80-char lines. `mypy`
  strict — all public functions need type annotations.
- 100% test coverage required (`--cov-fail-under=100`) — every new branch
  needs a test.
- Migrations must be zero-downtime/backward-compatible — every new field
  needs a default or must be nullable. Migration linter enforces this
  (`just run makemigrations` then `python manage.py lintmigrations` and
  `check_migrations --exclude-apps=axes`).
- `@final` on every concrete class. `@attrs.define(slots=True, frozen=True)`
  for service objects. `msgspec.Struct` for value objects.
- Never add `from __future__ import annotations` to files registered with
  punq (not relevant here — no new DI singletons).
- All commands run via `docker compose exec web ...` or `just run ...`
  (sources `.env.local`, no Docker needed for `manage.py` subcommands).

---

## Task 1: Font registry module + `fonttools` dependency

**Files:**
- Modify: `pyproject.toml` (add `fonttools` to main dependency group)
- Create: `server/apps/rendering/fonts/` (directory for bundled `.ttf` files)
- Create: `server/apps/rendering/fonts/download_fonts.sh`
- Create: `server/apps/rendering/clip_stages/fonts.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_fonts.py`

**Interfaces:**
- Produces: `CURATED_FONT_SLUGS: tuple[str, ...]` (16 fixed identifiers, used
  by Task 3's `CaptionFont` TextChoices), `FONTS_DIR: Path`,
  `curated_font_path(slug: str) -> Path`,
  `curated_font_family(slug: str) -> str` (lazily extracts the real embedded
  family name via `fonttools.ttLib.TTFont` — see rationale below).

**Rationale:** rather than hand-typing each bundled font's internal family
name (risky — libass matches ASS `Fontname` against the font's own name
table, and guessing it wrong silently breaks captions), we extract it
directly from the bundled file with `fonttools` at first access and cache it.
This also gives us one code path shared with the custom-upload font
extraction in Task 9.

- [ ] **Step 1: Add `fonttools` to `pyproject.toml`**

Add to the `[tool.poetry.dependencies]` (main group, not `ml` or `dev`):

```toml
fonttools = "^4.55.0"
```

Run: `docker compose exec web poetry lock --no-update`
Expected: `poetry.lock` updates with `fonttools` and its transitive deps
(none — it's dependency-free).

Run: `docker compose exec web poetry sync --without ml --no-interaction`
Expected: installs `fonttools` into the container's venv.

- [ ] **Step 2: Write the failing test for the registry**

```python
# tests/test_apps/test_rendering/test_clip_stages/test_fonts.py
from pathlib import Path

import pytest

from server.apps.rendering.clip_stages.fonts import (
    CURATED_FONT_SLUGS,
    FONTS_DIR,
    curated_font_family,
    curated_font_path,
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
    # A real TTF is required for fonttools to parse — this test runs against
    # the actual bundled file, so it doubles as a "did we vendor the file
    # correctly" check.
    family = curated_font_family('MONTSERRAT_BOLD')
    assert isinstance(family, str)
    assert len(family) > 0
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_fonts.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named
'server.apps.rendering.clip_stages.fonts'`

- [ ] **Step 3: Write the registry module**

```python
# server/apps/rendering/clip_stages/fonts.py
"""Curated font registry — bundled .ttf files + custom LibraryAsset fonts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    font = TTFont(path, lazy=True)
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
```

- [ ] **Step 4: Run test to verify path/slug tests pass, family test still fails (no file yet)**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_fonts.py -v --no-cov`
Expected: `test_curated_font_slugs_has_sixteen_entries` and
`test_curated_font_path_resolves_under_fonts_dir` and
`test_curated_font_path_unknown_slug_raises` PASS.
`test_curated_font_family_extracts_name_from_file` FAILS —
`FileNotFoundError` (no `.ttf` vendored yet). This is expected at this step.

- [ ] **Step 5: Write the download helper script**

```bash
# server/apps/rendering/fonts/download_fonts.sh
#!/usr/bin/env bash
# Downloads the 16 curated fonts from the google/fonts GitHub repo (OFL
# licensed) into this directory. Run once during implementation; the
# resulting .ttf files are committed to git like any other static asset.
#
# NOTE: verify each path against https://github.com/google/fonts before
# running — the repo occasionally moves to variable-only fonts for a family,
# in which case use `fonttools varLib.instancer` to cut a static instance,
# e.g.:
#   fonttools varLib.instancer Inter[opsz,wght].ttf wght=700 -o Inter-Bold.ttf
set -euo pipefail
cd "$(dirname "$0")"

BASE="https://github.com/google/fonts/raw/main/ofl"

declare -A FONTS=(
  ["montserrat/Montserrat-Bold.ttf"]="Montserrat-Bold.ttf"
  ["poppins/Poppins-Bold.ttf"]="Poppins-Bold.ttf"
  ["inter/Inter-Bold.ttf"]="Inter-Bold.ttf"
  ["roboto/Roboto-Bold.ttf"]="Roboto-Bold.ttf"
  ["oswald/Oswald-Bold.ttf"]="Oswald-Bold.ttf"
  ["bebasneue/BebasNeue-Regular.ttf"]="BebasNeue-Regular.ttf"
  ["anton/Anton-Regular.ttf"]="Anton-Regular.ttf"
  ["archivoblack/ArchivoBlack-Regular.ttf"]="ArchivoBlack-Regular.ttf"
  ["bangers/Bangers-Regular.ttf"]="Bangers-Regular.ttf"
  ["permanentmarker/PermanentMarker-Regular.ttf"]="PermanentMarker-Regular.ttf"
  ["caveat/Caveat-Bold.ttf"]="Caveat-Bold.ttf"
  ["lobster/Lobster-Regular.ttf"]="Lobster-Regular.ttf"
  ["playfairdisplay/PlayfairDisplay-Bold.ttf"]="PlayfairDisplay-Bold.ttf"
  ["righteous/Righteous-Regular.ttf"]="Righteous-Regular.ttf"
  ["luckiestguy/LuckiestGuy-Regular.ttf"]="LuckiestGuy-Regular.ttf"
  ["pacifico/Pacifico-Regular.ttf"]="Pacifico-Regular.ttf"
)

for src in "${!FONTS[@]}"; do
  dest="${FONTS[$src]}"
  echo "Fetching $src -> $dest"
  curl -sSL -f "${BASE}/${src}" -o "${dest}" || {
    echo "FAILED: $src not found at expected path — check google/fonts repo layout for this family and update this script." >&2
    exit 1
  }
done

echo "Done. Run 'fc-scan' or the test suite to verify each file parses."
```

Run: `chmod +x server/apps/rendering/fonts/download_fonts.sh`
Run: `docker compose exec web bash server/apps/rendering/fonts/download_fonts.sh`
Expected: 16 `.ttf` files land in `server/apps/rendering/fonts/`. If any URL
404s, fix that font's path (check the live repo) or substitute an
equally-styled alternative before continuing — do not skip a font silently.

- [ ] **Step 6: Run the full test file to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_fonts.py -v --no-cov`
Expected: all 4 tests PASS.

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_fonts.py --cov=server.apps.rendering.clip_stages.fonts --cov-report=term-missing`
Expected: 100% coverage on `fonts.py`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml poetry.lock server/apps/rendering/fonts/ \
  server/apps/rendering/clip_stages/fonts.py \
  tests/test_apps/test_rendering/test_clip_stages/test_fonts.py
git commit -m "feat(clipping): add curated font registry + fonttools dependency"
```

---

## Task 2: Sync ffprobe helper

**Files:**
- Create: `server/apps/rendering/clip_stages/probe.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_probe.py`

**Interfaces:**
- Produces: `sync_ffprobe_duration(path: str) -> float` — used by Task 16
  (transition offset calculation).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_rendering/test_clip_stages/test_probe.py
import json
from unittest.mock import MagicMock, patch

import pytest

from server.apps.rendering.clip_stages.probe import sync_ffprobe_duration


@patch('server.apps.rendering.clip_stages.probe.subprocess.run')
def test_sync_ffprobe_duration_parses_format_duration(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({'format': {'duration': '12.345000'}}),
    )
    result = sync_ffprobe_duration('/tmp/clip.mp4')
    assert result == pytest.approx(12.345)


@patch('server.apps.rendering.clip_stages.probe.subprocess.run')
def test_sync_ffprobe_duration_raises_on_failure(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='no such file')
    with pytest.raises(RuntimeError, match='ffprobe failed'):
        sync_ffprobe_duration('/tmp/missing.mp4')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_probe.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# server/apps/rendering/clip_stages/probe.py
"""Sync ffprobe helper for render stages (they run via subprocess, not asyncio)."""

import json
import subprocess  # noqa: S404


def sync_ffprobe_duration(path: str) -> float:
    """Return the media duration in seconds via ffprobe.

    Raises:
        RuntimeError: If ffprobe exits non-zero.
    """
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-show_format',
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f'ffprobe failed for {path}: {result.stderr}')
    data = json.loads(result.stdout)
    return float(data['format']['duration'])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_probe.py -v --cov=server.apps.rendering.clip_stages.probe --cov-report=term-missing`
Expected: both tests PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/probe.py \
  tests/test_apps/test_rendering/test_clip_stages/test_probe.py
git commit -m "feat(clipping): add sync ffprobe duration helper for transitions"
```

---

## Task 3: New TextChoices enums

**Files:**
- Modify: `server/apps/clips/logic/constants.py`
- Test: `tests/test_apps/test_clips/test_logic/test_constants.py` (create if
  it doesn't already exist — check first with
  `find tests/test_apps/test_clips -iname "*constants*"`)

**Interfaces:**
- Produces: `CaptionFont` (16 values matching Task 1's `CURATED_FONT_SLUGS`
  exactly), `OverlayAnimation` (`NONE`, `FADE`, `POP`, `SLIDE_LEFT`,
  `SLIDE_RIGHT`, `SLIDE_UP`, `SLIDE_DOWN`), `ColorFilterPreset` (`NONE`,
  `VIVID`, `MOODY`, `WARM`, `COOL`, `BLACK_WHITE`, `VINTAGE`), `FitMode`
  (`CROP`, `BLUR_FILL`), `OverlayShape` (`RECTANGLE`, `CIRCLE`, `ROUNDED`).
  Extends `TransitionStyle` with `FADE_WHITE`, `SLIDE_LEFT`, `SLIDE_RIGHT`,
  `SLIDE_UP`, `SLIDE_DOWN`, `WIPE_LEFT`, `WIPE_RIGHT`, `ZOOM_IN`,
  `CUSTOM_ASSET`. Extends `WatermarkPosition` with `CENTER`, `TILED`. Extends
  `CaptionStyle` with `KARAOKE_HIGHLIGHT`. Extends `OverlayType` with `VIDEO`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_clips/test_logic/test_constants.py
from server.apps.clips.logic.constants import (
    CaptionFont,
    CaptionStyle,
    ColorFilterPreset,
    FitMode,
    OverlayAnimation,
    OverlayShape,
    OverlayType,
    TransitionStyle,
    WatermarkPosition,
)


def test_caption_font_has_sixteen_curated_values() -> None:
    assert len(CaptionFont.values) == 16
    assert 'MONTSERRAT_BOLD' in CaptionFont.values
    assert 'PACIFICO' in CaptionFont.values


def test_transition_style_has_full_capcut_palette() -> None:
    expected = {
        'NONE', 'CROSSFADE', 'FADE_BLACK', 'FADE_WHITE',
        'SLIDE_LEFT', 'SLIDE_RIGHT', 'SLIDE_UP', 'SLIDE_DOWN',
        'WIPE_LEFT', 'WIPE_RIGHT', 'ZOOM_IN', 'CUSTOM_ASSET',
    }
    assert set(TransitionStyle.values) == expected


def test_watermark_position_has_center_and_tiled() -> None:
    assert 'CENTER' in WatermarkPosition.values
    assert 'TILED' in WatermarkPosition.values


def test_caption_style_has_karaoke_highlight() -> None:
    assert 'KARAOKE_HIGHLIGHT' in CaptionStyle.values


def test_overlay_type_has_video() -> None:
    assert 'VIDEO' in OverlayType.values


def test_overlay_animation_values() -> None:
    assert set(OverlayAnimation.values) == {
        'NONE', 'FADE', 'POP',
        'SLIDE_LEFT', 'SLIDE_RIGHT', 'SLIDE_UP', 'SLIDE_DOWN',
    }


def test_color_filter_preset_values() -> None:
    assert set(ColorFilterPreset.values) == {
        'NONE', 'VIVID', 'MOODY', 'WARM', 'COOL', 'BLACK_WHITE', 'VINTAGE',
    }


def test_fit_mode_values() -> None:
    assert set(FitMode.values) == {'CROP', 'BLUR_FILL'}


def test_overlay_shape_values() -> None:
    assert set(OverlayShape.values) == {'RECTANGLE', 'CIRCLE', 'ROUNDED'}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_logic/test_constants.py -v --no-cov`
Expected: FAIL — `ImportError` (new names don't exist yet).

- [ ] **Step 3: Extend `constants.py`**

Modify `TransitionStyle` (replace the existing class body):

```python
class TransitionStyle(models.TextChoices):
    """Transition applied between clip segments."""

    NONE = 'NONE', 'None (hard cut)'
    CROSSFADE = 'CROSSFADE', 'Crossfade'
    FADE_BLACK = 'FADE_BLACK', 'Fade to Black'
    FADE_WHITE = 'FADE_WHITE', 'Fade to White'
    SLIDE_LEFT = 'SLIDE_LEFT', 'Slide Left'
    SLIDE_RIGHT = 'SLIDE_RIGHT', 'Slide Right'
    SLIDE_UP = 'SLIDE_UP', 'Slide Up'
    SLIDE_DOWN = 'SLIDE_DOWN', 'Slide Down'
    WIPE_LEFT = 'WIPE_LEFT', 'Wipe Left'
    WIPE_RIGHT = 'WIPE_RIGHT', 'Wipe Right'
    ZOOM_IN = 'ZOOM_IN', 'Zoom In'
    CUSTOM_ASSET = 'CUSTOM_ASSET', 'Custom Transition Video'
```

Modify `WatermarkPosition`:

```python
class WatermarkPosition(models.TextChoices):
    """Corner position of the watermark."""

    TOP_LEFT = 'TOP_LEFT', 'Top Left'
    TOP_RIGHT = 'TOP_RIGHT', 'Top Right'
    BOTTOM_LEFT = 'BOTTOM_LEFT', 'Bottom Left'
    BOTTOM_RIGHT = 'BOTTOM_RIGHT', 'Bottom Right'
    CENTER = 'CENTER', 'Center'
    TILED = 'TILED', 'Tiled'
```

Modify `CaptionStyle`:

```python
class CaptionStyle(models.TextChoices):
    """Visual style used for rendering captions."""

    WORD_BY_WORD = 'WORD_BY_WORD', 'Word by Word (karaoke)'
    CHUNKED = 'CHUNKED', 'Chunked Phrases (3-4 words)'
    LOWER_THIRD = 'LOWER_THIRD', 'Lower Third (full segment)'
    EMOJI_ACCENT = 'EMOJI_ACCENT', 'Emoji Accent (chunked + emoji)'
    KARAOKE_HIGHLIGHT = 'KARAOKE_HIGHLIGHT', 'Karaoke Highlight'
```

Modify `OverlayType`:

```python
class OverlayType(models.TextChoices):
    """Type of a timed overlay on a clip."""

    TEXT = 'TEXT', 'Text'
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'
```

Add four new classes (append to the file):

```python
class CaptionFont(models.TextChoices):
    """Curated font palette, shared by captions, hook, watermark, overlays."""

    MONTSERRAT_BOLD = 'MONTSERRAT_BOLD', 'Montserrat Bold'
    POPPINS_BOLD = 'POPPINS_BOLD', 'Poppins Bold'
    INTER_BOLD = 'INTER_BOLD', 'Inter Bold'
    ROBOTO_BOLD = 'ROBOTO_BOLD', 'Roboto Bold'
    OSWALD_BOLD = 'OSWALD_BOLD', 'Oswald Bold'
    BEBAS_NEUE = 'BEBAS_NEUE', 'Bebas Neue'
    ANTON = 'ANTON', 'Anton'
    ARCHIVO_BLACK = 'ARCHIVO_BLACK', 'Archivo Black'
    BANGERS = 'BANGERS', 'Bangers'
    PERMANENT_MARKER = 'PERMANENT_MARKER', 'Permanent Marker'
    CAVEAT_BOLD = 'CAVEAT_BOLD', 'Caveat Bold'
    LOBSTER = 'LOBSTER', 'Lobster'
    PLAYFAIR_DISPLAY_BOLD = 'PLAYFAIR_DISPLAY_BOLD', 'Playfair Display Bold'
    RIGHTEOUS = 'RIGHTEOUS', 'Righteous'
    LUCKIEST_GUY = 'LUCKIEST_GUY', 'Luckiest Guy'
    PACIFICO = 'PACIFICO', 'Pacifico'


class OverlayAnimation(models.TextChoices):
    """Entrance/exit animation for a timed overlay or the hook."""

    NONE = 'NONE', 'None'
    FADE = 'FADE', 'Fade'
    POP = 'POP', 'Pop'
    SLIDE_LEFT = 'SLIDE_LEFT', 'Slide Left'
    SLIDE_RIGHT = 'SLIDE_RIGHT', 'Slide Right'
    SLIDE_UP = 'SLIDE_UP', 'Slide Up'
    SLIDE_DOWN = 'SLIDE_DOWN', 'Slide Down'


class ColorFilterPreset(models.TextChoices):
    """Preset color-grade look applied before manual adjustments."""

    NONE = 'NONE', 'None'
    VIVID = 'VIVID', 'Vivid'
    MOODY = 'MOODY', 'Moody'
    WARM = 'WARM', 'Warm'
    COOL = 'COOL', 'Cool'
    BLACK_WHITE = 'BLACK_WHITE', 'Black & White'
    VINTAGE = 'VINTAGE', 'Vintage'


class FitMode(models.TextChoices):
    """How the source video fills a mismatched target aspect ratio."""

    CROP = 'CROP', 'Crop'
    BLUR_FILL = 'BLUR_FILL', 'Blurred Background Fill'


class OverlayShape(models.TextChoices):
    """Mask shape for image/video overlays."""

    RECTANGLE = 'RECTANGLE', 'Rectangle'
    CIRCLE = 'CIRCLE', 'Circle'
    ROUNDED = 'ROUNDED', 'Rounded Rectangle'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_logic/test_constants.py -v --cov=server.apps.clips.logic.constants --cov-report=term-missing`
Expected: all 8 tests PASS, 100% coverage (TextChoices classes are fully
covered just by being imported/enumerated — no branches to miss).

- [ ] **Step 5: Commit**

```bash
git add server/apps/clips/logic/constants.py \
  tests/test_apps/test_clips/test_logic/test_constants.py
git commit -m "feat(clipping): add font/animation/color-filter/fit-mode/overlay-shape enums"
```

---

## Task 4: Extend `ClipStyleConfig` model

**Files:**
- Modify: `server/apps/clips/models.py`
- Create: migration via `makemigrations` (do not hand-author)
- Test: `tests/test_apps/test_clips/test_models.py` (add to existing file —
  check with `find tests/test_apps/test_clips -iname "test_models.py"`; if it
  doesn't exist, create it following the existing model-test conventions in
  `tests/test_apps/test_clips/`)

**Interfaces:**
- Consumes: `CaptionFont`, `OverlayAnimation`, `ColorFilterPreset`,
  `TransitionStyle`, `WatermarkPosition` from Task 3.
- Produces: the following new fields on `ClipStyleConfig`, all nullable or
  defaulted (zero-downtime): `watermark_color` (`CharField`, default
  `'#FFFFFF'`), `watermark_font` (`CaptionFont` choice, default
  `MONTSERRAT_BOLD`), `watermark_font_asset` (FK to `LibraryAsset`, null),
  `caption_font_asset` (FK, null), `hook_font_asset` (FK, null),
  `intro_transition_duration_sec` (`FloatField`, default `0.5`),
  `outro_transition_duration_sec` (`FloatField`, default `0.5`),
  `intro_transition_asset` (FK, null), `outro_transition_asset` (FK, null),
  `hook_animation` (`OverlayAnimation` choice, default `NONE`),
  `caption_highlight_color` (`CharField`, default `'#FFD400'`),
  `caption_uppercase` (`BooleanField`, default `False`), `color_filter`
  (`ColorFilterPreset` choice, default `NONE`), `brightness` (`FloatField`,
  default `0.0`), `contrast` (`FloatField`, default `0.0`), `saturation`
  (`FloatField`, default `0.0`), `lut_asset` (FK, null), `playback_speed`
  (`FloatField`, default `1.0`). Also changes `caption_font`/`hook_font` from
  freeform `CharField` to `CaptionFont` choice fields (default
  `MONTSERRAT_BOLD`, replacing the old `'Montserrat-Bold'` string default —
  see the data-migration note in Step 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_clips/test_models.py (add to existing file, or create)
import pytest

pytestmark = pytest.mark.django_db


def test_clip_style_config_new_field_defaults(clip_candidate_factory) -> None:
    from server.apps.clips.models import ClipStyleConfig

    candidate = clip_candidate_factory()
    config = ClipStyleConfig.objects.get(candidate=candidate)

    assert config.watermark_color == '#FFFFFF'
    assert config.watermark_font == 'MONTSERRAT_BOLD'
    assert config.watermark_font_asset is None
    assert config.caption_font_asset is None
    assert config.hook_font_asset is None
    assert config.intro_transition_duration_sec == 0.5
    assert config.outro_transition_duration_sec == 0.5
    assert config.intro_transition_asset is None
    assert config.outro_transition_asset is None
    assert config.hook_animation == 'NONE'
    assert config.caption_highlight_color == '#FFD400'
    assert config.caption_uppercase is False
    assert config.color_filter == 'NONE'
    assert config.brightness == 0.0
    assert config.contrast == 0.0
    assert config.saturation == 0.0
    assert config.lut_asset is None
    assert config.playback_speed == 1.0
    assert config.caption_font == 'MONTSERRAT_BOLD'
    assert config.hook_font == 'MONTSERRAT_BOLD'
```

Check `tests/test_apps/test_clips/conftest.py` (or the project-wide
`tests/plugins/`) for an existing `clip_candidate_factory` fixture before
writing a new one — `ClipStyleConfig` rows are auto-created by a signal per
the model docstring ("Auto-created by signal"), so creating a `ClipCandidate`
via the existing factory should be enough to get a `ClipStyleConfig` for free.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k new_field_defaults`
Expected: FAIL — `AttributeError` (fields don't exist on the model yet).

- [ ] **Step 3: Extend the model**

In `server/apps/clips/models.py`, change the imports at the top to include
the new enums:

```python
from server.apps.clips.logic.constants import (
    CampaignStatus,
    CandidateStatus,
    CaptionAnimation,
    CaptionFont,
    CaptionPosition,
    CaptionStyle,
    ClipSourceStatus,
    ClipSourceType,
    ColorFilterPreset,
    HookStyle,
    OverlayAnimation,
    OverlayType,
    PostStatus,
    ProgressBarPosition,
    RenderFormat,
    RenderMode,
    TransitionStyle,
    WatermarkPosition,
    WatermarkType,
)
```

(Keep whatever's already imported — this is the full merged list; adjust to
match what's actually present rather than duplicating.)

Change `caption_font` and `hook_font` from freeform `CharField` to choice
fields:

```python
    caption_font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
```

```python
    hook_font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
```

Add the new fields to `ClipStyleConfig` (insert after `outro_transition`,
before `watermark_enabled`):

```python
    intro_transition_duration_sec = models.FloatField(default=0.5)
    outro_transition_duration_sec = models.FloatField(default=0.5)
    intro_transition_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    outro_transition_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
```

Insert after `watermark_size`, before `progress_bar_enabled`:

```python
    watermark_color = models.CharField(max_length=9, default='#FFFFFF')
    watermark_font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
    watermark_font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
```

Insert after `hook_bg_color`, before `intro_transition`:

```python
    hook_animation = models.CharField(
        max_length=15,
        choices=OverlayAnimation.choices,
        default=OverlayAnimation.NONE,
    )
    hook_font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
```

Insert after `caption_translate_to`, before `emoji_keyword_map`:

```python
    caption_font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    caption_highlight_color = models.CharField(
        max_length=9,
        default='#FFD400',
    )
    caption_uppercase = models.BooleanField(default=False)
```

Insert after `music_fade_out_sec` (end of the field list, before `class Meta`):

```python
    color_filter = models.CharField(
        max_length=15,
        choices=ColorFilterPreset.choices,
        default=ColorFilterPreset.NONE,
    )
    brightness = models.FloatField(default=0.0)
    contrast = models.FloatField(default=0.0)
    saturation = models.FloatField(default=0.0)
    lut_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    playback_speed = models.FloatField(default=1.0)
```

Add two `CheckConstraint`s to `class Meta.constraints` (alongside the
existing `intro_transition_valid`/`outro_transition_valid` ones — those don't
need changes since they already validate against `TransitionStyle.values`,
which Task 3 already extended):

```python
            models.CheckConstraint(
                name='clips_clipstyleconfig_hook_animation_valid',
                condition=models.Q(hook_animation__in=OverlayAnimation.values),
            ),
            models.CheckConstraint(
                name='clips_clipstyleconfig_color_filter_valid',
                condition=models.Q(color_filter__in=ColorFilterPreset.values),
            ),
```

Note: the existing `caption_style_valid` constraint already checks against
`CaptionStyle.values`, which Task 3 extended with `KARAOKE_HIGHLIGHT` — no
change needed there either.

- [ ] **Step 4: Generate and apply the migration**

Run: `docker compose exec web python manage.py makemigrations clips`
Expected: creates a new migration file (e.g.
`server/apps/clips/migrations/0006_<name>.py`) with `AddField`/`AlterField`
operations for every field above. Read the generated migration and confirm
every new field has a `default=` (Django will prompt interactively for
`caption_font`/`hook_font` `AlterField` if it can't infer a safe default —
answer with the `CaptionFont.MONTSERRAT_BOLD` value).

Run: `docker compose exec web python manage.py migrate clips`
Expected: migration applies cleanly.

Run: `docker compose exec web python manage.py lintmigrations`
Expected: no zero-downtime violations reported.

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k new_field_defaults`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/apps/clips/models.py server/apps/clips/migrations/ \
  tests/test_apps/test_clips/test_models.py
git commit -m "feat(clipping): extend ClipStyleConfig with font/transition/watermark/color/speed fields"
```

---

## Task 5: Extend `ClipLayoutConfig` with `fit_mode`

**Files:**
- Modify: `server/apps/clips/models.py`
- Create: migration via `makemigrations`
- Test: `tests/test_apps/test_clips/test_models.py`

**Interfaces:**
- Consumes: `FitMode` from Task 3.
- Produces: `ClipLayoutConfig.fit_mode` (`FitMode` choice, default `CROP`).

- [ ] **Step 1: Write the failing test**

```python
def test_clip_layout_config_fit_mode_default(clip_candidate_factory) -> None:
    from server.apps.clips.models import ClipLayoutConfig

    candidate = clip_candidate_factory()
    layout = ClipLayoutConfig.objects.get(candidate=candidate)
    assert layout.fit_mode == 'CROP'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k fit_mode_default`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Extend the model**

Add `FitMode` to the constants import block (same import statement edited in
Task 4). Add the field to `ClipLayoutConfig` (insert after `stack_ratio`,
before `face_detected`):

```python
    fit_mode = models.CharField(
        max_length=10,
        choices=FitMode.choices,
        default=FitMode.CROP,
    )
```

Add a `CheckConstraint` to `ClipLayoutConfig.Meta.constraints`:

```python
            models.CheckConstraint(
                name='clips_cliplayoutconfig_fit_mode_valid',
                condition=models.Q(fit_mode__in=FitMode.values),
            ),
```

- [ ] **Step 4: Generate and apply the migration**

Run: `docker compose exec web python manage.py makemigrations clips`
Run: `docker compose exec web python manage.py migrate clips`
Expected: clean migration, one `AddField` for `fit_mode` plus the
`CheckConstraint`.

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k fit_mode_default`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/apps/clips/models.py server/apps/clips/migrations/ \
  tests/test_apps/test_clips/test_models.py
git commit -m "feat(clipping): add fit_mode to ClipLayoutConfig for blurred-background fill"
```

---

## Task 6: Extend `ClipTimedOverlay`

**Files:**
- Modify: `server/apps/clips/models.py`
- Create: migration via `makemigrations`
- Test: `tests/test_apps/test_clips/test_models.py`

**Interfaces:**
- Consumes: `CaptionFont`, `OverlayAnimation`, `OverlayShape` from Task 3.
- Produces: `ClipTimedOverlay.font` (`CaptionFont` choice, default
  `MONTSERRAT_BOLD`), `.font_asset` (FK, null), `.width` (nullable
  `PositiveIntegerField`, for IMAGE/VIDEO overlays), `.animation`
  (`OverlayAnimation` choice, default `NONE`), `.video_asset` (FK, null),
  `.shape` (`OverlayShape` choice, default `RECTANGLE`).

- [ ] **Step 1: Write the failing test**

```python
def test_clip_timed_overlay_new_field_defaults(clip_candidate_factory) -> None:
    from server.apps.clips.models import ClipTimedOverlay

    candidate = clip_candidate_factory()
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate,
        start_sec=0.0,
        end_sec=1.0,
    )
    assert overlay.font == 'MONTSERRAT_BOLD'
    assert overlay.font_asset is None
    assert overlay.width is None
    assert overlay.animation == 'NONE'
    assert overlay.video_asset is None
    assert overlay.shape == 'RECTANGLE'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k timed_overlay_new_field`
Expected: FAIL — `TypeError` (unexpected keyword or attribute error on
default fields).

- [ ] **Step 3: Extend the model**

Add `OverlayShape` to the constants import block. Add fields to
`ClipTimedOverlay` (insert after `image_asset`, before `start_sec`):

```python
    video_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    shape = models.CharField(
        max_length=10,
        choices=OverlayShape.choices,
        default=OverlayShape.RECTANGLE,
    )
```

Insert after `opacity` (end of field list, before `class Meta`):

```python
    font = models.CharField(
        max_length=30,
        choices=CaptionFont.choices,
        default=CaptionFont.MONTSERRAT_BOLD,
    )
    font_asset = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    width = models.PositiveIntegerField(null=True, blank=True)
    animation = models.CharField(
        max_length=15,
        choices=OverlayAnimation.choices,
        default=OverlayAnimation.NONE,
    )
```

Add a `CheckConstraint` to `ClipTimedOverlay.Meta.constraints` (alongside the
existing `overlay_type_valid` one, which already covers the new `VIDEO`
value from Task 3):

```python
            models.CheckConstraint(
                name='clips_cliptimedoverlay_shape_valid',
                condition=models.Q(shape__in=OverlayShape.values),
            ),
            models.CheckConstraint(
                name='clips_cliptimedoverlay_animation_valid',
                condition=models.Q(animation__in=OverlayAnimation.values),
            ),
```

- [ ] **Step 4: Generate and apply the migration**

Run: `docker compose exec web python manage.py makemigrations clips`
Run: `docker compose exec web python manage.py migrate clips`

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k timed_overlay_new_field`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/apps/clips/models.py server/apps/clips/migrations/ \
  tests/test_apps/test_clips/test_models.py
git commit -m "feat(clipping): add font/animation/video/shape fields to ClipTimedOverlay"
```

---

## Task 7: New `ClipTimedSfx` model

**Files:**
- Modify: `server/apps/clips/models.py`
- Create: migration via `makemigrations`
- Test: `tests/test_apps/test_clips/test_models.py`

**Interfaces:**
- Produces: `ClipTimedSfx` model — `id` (UUID, via `UUIDModel`), `candidate`
  (FK to `ClipCandidate`, `related_name='timed_sfx'`), `sfx_asset` (FK to
  `LibraryAsset`, required — an SFX overlay with no asset is meaningless, so
  unlike the optional intro/outro/watermark assets this one is NOT nullable),
  `start_sec` (`FloatField`), `volume_db` (`FloatField`, default `0.0`).
  Mirrors `ClipTimedOverlay`'s shape (`UUIDModel, TimeStampedModel`, `__str__`
  override).

- [ ] **Step 1: Write the failing test**

```python
def test_clip_timed_sfx_creation(clip_candidate_factory, library_asset_factory) -> None:
    from server.apps.clips.models import ClipTimedSfx

    candidate = clip_candidate_factory()
    sfx_asset = library_asset_factory(kind='SFX')
    sfx = ClipTimedSfx.objects.create(
        candidate=candidate,
        sfx_asset=sfx_asset,
        start_sec=5.0,
    )
    assert sfx.volume_db == 0.0
    assert str(sfx) == f'SFX {sfx_asset.name} @5.0s'
```

Check for an existing `library_asset_factory` fixture in
`tests/plugins/` or `tests/test_apps/test_assets/conftest.py` before writing
a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k timed_sfx_creation`
Expected: FAIL — `ImportError` (`ClipTimedSfx` doesn't exist).

- [ ] **Step 3: Add the model**

Append to `server/apps/clips/models.py`, near `ClipTimedOverlay`:

```python
class ClipTimedSfx(UUIDModel, TimeStampedModel):
    """A one-shot sound effect dropped at a timestamp on a clip."""

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name='timed_sfx',
    )
    sfx_asset = models.ForeignKey(
        'assets.LibraryAsset',
        on_delete=models.CASCADE,
        related_name='+',
    )
    start_sec = models.FloatField()
    volume_db = models.FloatField(default=0.0)

    @override
    def __str__(self) -> str:
        return f'SFX {self.sfx_asset.name} @{self.start_sec}s'
```

- [ ] **Step 4: Generate and apply the migration**

Run: `docker compose exec web python manage.py makemigrations clips`
Run: `docker compose exec web python manage.py migrate clips`

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_models.py -v --no-cov -k timed_sfx_creation`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/apps/clips/models.py server/apps/clips/migrations/ \
  tests/test_apps/test_clips/test_models.py
git commit -m "feat(clipping): add ClipTimedSfx model for one-shot sound effects"
```

---

## Task 8: Update `logic/types.py` Literal types

**Files:**
- Modify: `server/apps/clips/logic/types.py`
- Test: `tests/test_apps/test_clips/test_logic/test_types.py` (create if
  missing)

**Interfaces:**
- Produces: `CaptionFontLiteral`, `OverlayAnimationLiteral`,
  `ColorFilterPresetLiteral`, `FitModeLiteral`, `OverlayShapeLiteral`.
  Updates `TransitionStyleLiteral`, `WatermarkPositionLiteral`,
  `CaptionStyleLiteral`, `OverlayTypeLiteral` to match Task 3's expanded
  enums exactly (this file's own docstring says "Wire values must match
  Django TextChoices in constants.py — enforced in tests").

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_clips/test_logic/test_types.py
"""Verify every *Literal type's values match its Django TextChoices exactly."""

from typing import get_args

from server.apps.clips.logic import types
from server.apps.clips.logic.constants import (
    CaptionFont,
    CaptionStyle,
    ColorFilterPreset,
    FitMode,
    OverlayAnimation,
    OverlayShape,
    OverlayType,
    TransitionStyle,
    WatermarkPosition,
)


def test_transition_style_literal_matches_enum() -> None:
    assert set(get_args(types.TransitionStyleLiteral)) == set(
        TransitionStyle.values,
    )


def test_watermark_position_literal_matches_enum() -> None:
    assert set(get_args(types.WatermarkPositionLiteral)) == set(
        WatermarkPosition.values,
    )


def test_caption_style_literal_matches_enum() -> None:
    assert set(get_args(types.CaptionStyleLiteral)) == set(CaptionStyle.values)


def test_overlay_type_literal_matches_enum() -> None:
    assert set(get_args(types.OverlayTypeLiteral)) == set(OverlayType.values)


def test_caption_font_literal_matches_enum() -> None:
    assert set(get_args(types.CaptionFontLiteral)) == set(CaptionFont.values)


def test_overlay_animation_literal_matches_enum() -> None:
    assert set(get_args(types.OverlayAnimationLiteral)) == set(
        OverlayAnimation.values,
    )


def test_color_filter_preset_literal_matches_enum() -> None:
    assert set(get_args(types.ColorFilterPresetLiteral)) == set(
        ColorFilterPreset.values,
    )


def test_fit_mode_literal_matches_enum() -> None:
    assert set(get_args(types.FitModeLiteral)) == set(FitMode.values)


def test_overlay_shape_literal_matches_enum() -> None:
    assert set(get_args(types.OverlayShapeLiteral)) == set(OverlayShape.values)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_logic/test_types.py -v --no-cov`
Expected: FAIL — `AttributeError` (new `*Literal` names don't exist;
existing ones don't yet match the expanded enums).

- [ ] **Step 3: Update `types.py`**

Replace `TransitionStyleLiteral`:

```python
# TransitionStyle.values
TransitionStyleLiteral = Literal[
    'NONE', 'CROSSFADE', 'FADE_BLACK', 'FADE_WHITE',
    'SLIDE_LEFT', 'SLIDE_RIGHT', 'SLIDE_UP', 'SLIDE_DOWN',
    'WIPE_LEFT', 'WIPE_RIGHT', 'ZOOM_IN', 'CUSTOM_ASSET',
]
```

Replace `WatermarkPositionLiteral`:

```python
# WatermarkPosition.values
WatermarkPositionLiteral = Literal[
    'TOP_LEFT', 'TOP_RIGHT', 'BOTTOM_LEFT', 'BOTTOM_RIGHT',
    'CENTER', 'TILED',
]
```

Replace `CaptionStyleLiteral`:

```python
# CaptionStyle.values
CaptionStyleLiteral = Literal[
    'WORD_BY_WORD', 'CHUNKED', 'LOWER_THIRD', 'EMOJI_ACCENT',
    'KARAOKE_HIGHLIGHT',
]
```

Replace `OverlayTypeLiteral`:

```python
# OverlayType.values
OverlayTypeLiteral = Literal['TEXT', 'IMAGE', 'VIDEO']
```

Append four new Literal types at the end of the file:

```python
# CaptionFont.values
CaptionFontLiteral = Literal[
    'MONTSERRAT_BOLD', 'POPPINS_BOLD', 'INTER_BOLD', 'ROBOTO_BOLD',
    'OSWALD_BOLD', 'BEBAS_NEUE', 'ANTON', 'ARCHIVO_BLACK', 'BANGERS',
    'PERMANENT_MARKER', 'CAVEAT_BOLD', 'LOBSTER', 'PLAYFAIR_DISPLAY_BOLD',
    'RIGHTEOUS', 'LUCKIEST_GUY', 'PACIFICO',
]

# OverlayAnimation.values
OverlayAnimationLiteral = Literal[
    'NONE', 'FADE', 'POP',
    'SLIDE_LEFT', 'SLIDE_RIGHT', 'SLIDE_UP', 'SLIDE_DOWN',
]

# ColorFilterPreset.values
ColorFilterPresetLiteral = Literal[
    'NONE', 'VIVID', 'MOODY', 'WARM', 'COOL', 'BLACK_WHITE', 'VINTAGE',
]

# FitMode.values
FitModeLiteral = Literal['CROP', 'BLUR_FILL']

# OverlayShape.values
OverlayShapeLiteral = Literal['RECTANGLE', 'CIRCLE', 'ROUNDED']
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_logic/test_types.py -v --cov=server.apps.clips.logic.types --cov-report=term-missing`
Expected: all 9 tests PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/clips/logic/types.py \
  tests/test_apps/test_clips/test_logic/test_types.py
git commit -m "feat(clipping): sync Literal types with expanded clip style enums"
```

---

## Task 9: Update `value_objects.py`

**Files:**
- Modify: `server/apps/clips/logic/value_objects.py`
- Test: covered indirectly by Task 10/12's API tests — no standalone test
  file needed for pure msgspec.Struct definitions (matches existing
  convention — `value_objects.py` has no dedicated test file today).

**Interfaces:**
- Consumes: the new `*Literal` types from Task 8.
- Produces: extended `ClipStyleConfigPayload`/`ClipStyleConfigPatchPayload`,
  extended `ClipLayoutConfigPayload`/`ClipLayoutConfigPatchPayload`, extended
  `ClipTimedOverlayPayload`/`ClipTimedOverlayCreatePayload`/
  `ClipTimedOverlayPatchPayload`, new `ClipTimedSfxPayload`,
  `ClipTimedSfxCreatePayload`, `ClipTimedSfxPatchPayload`,
  `ClipSfxListPayload`.

- [ ] **Step 1: Update the import block**

```python
from server.apps.clips.logic.types import (
    _CROP_COORD_DESC,
    CandidateStatusLiteral,
    CaptionAnimationLiteral,
    CaptionFontLiteral,
    CaptionPositionLiteral,
    CaptionStyleLiteral,
    ColorFilterPresetLiteral,
    FitModeLiteral,
    HookStyleLiteral,
    OverlayAnimationLiteral,
    OverlayShapeLiteral,
    OverlayTypeLiteral,
    ProgressBarPositionLiteral,
    RenderFormatLiteral,
    RenderModeLiteral,
    TransitionStyleLiteral,
    WatermarkPositionLiteral,
    WatermarkTypeLiteral,
)
```

- [ ] **Step 2: Extend `ClipLayoutConfigPayload`/`PatchPayload`**

Add `fit_mode: FitModeLiteral` to `ClipLayoutConfigPayload` (find its
definition — it wasn't shown in the excerpt read during design, but follows
the same pattern as `ClipLayoutConfigPatchPayload` shown below; add the field
in the same position as `stack_ratio`). Add to `ClipLayoutConfigPatchPayload`:

```python
    fit_mode: FitModeLiteral | None = None
```
(insert after `stack_ratio: float | None = None`)

- [ ] **Step 3: Extend `ClipStyleConfigPayload`**

Change field types (in place, same position):

```python
    caption_font: CaptionFontLiteral
    ...
    hook_font: CaptionFontLiteral
```

Add fields (insert after `caption_translate_to`, before `emoji_keyword_map`):

```python
    caption_font_asset_id: str | None
    caption_highlight_color: str
    caption_uppercase: bool
```

Insert after `hook_bg_color`, before `intro_transition`:

```python
    hook_font_asset_id: str | None
    hook_animation: OverlayAnimationLiteral
```

Insert after `outro_transition`, before `watermark_enabled`:

```python
    intro_transition_duration_sec: float
    outro_transition_duration_sec: float
    intro_transition_asset_id: str | None
    outro_transition_asset_id: str | None
```

Insert after `watermark_size`, before `progress_bar_enabled`:

```python
    watermark_color: str
    watermark_font: CaptionFontLiteral
    watermark_font_asset_id: str | None
```

Insert after `music_fade_out_sec` (end of the class):

```python
    color_filter: ColorFilterPresetLiteral
    brightness: float
    contrast: float
    saturation: float
    lut_asset_id: str | None
    playback_speed: float
```

- [ ] **Step 4: Extend `ClipStyleConfigPatchPayload`**

Mirror every field added above, as `| None = None`, in the same relative
positions:

```python
    caption_font: CaptionFontLiteral | None = None
    ...
    hook_font: CaptionFontLiteral | None = None
    ...
    caption_font_asset_id: str | None = None
    caption_highlight_color: str | None = None
    caption_uppercase: bool | None = None
    ...
    hook_font_asset_id: str | None = None
    hook_animation: OverlayAnimationLiteral | None = None
    ...
    intro_transition_duration_sec: float | None = None
    outro_transition_duration_sec: float | None = None
    intro_transition_asset_id: str | None = None
    outro_transition_asset_id: str | None = None
    ...
    watermark_color: str | None = None
    watermark_font: CaptionFontLiteral | None = None
    watermark_font_asset_id: str | None = None
    ...
    color_filter: ColorFilterPresetLiteral | None = None
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    lut_asset_id: str | None = None
    playback_speed: float | None = None
```

- [ ] **Step 5: Extend `ClipTimedOverlayPayload`/`CreatePayload`/`PatchPayload`**

Add to `ClipTimedOverlayPayload` (after `image_asset_id`, before
`start_sec`):

```python
    video_asset_id: str | None
    shape: OverlayShapeLiteral
```

Add after `opacity` (end of class):

```python
    font: CaptionFontLiteral
    font_asset_id: str | None
    width: int | None
    animation: OverlayAnimationLiteral
```

Mirror into `ClipTimedOverlayCreatePayload` with defaults:

```python
    video_asset_id: str | None = None
    shape: OverlayShapeLiteral = 'RECTANGLE'
    ...
    font: CaptionFontLiteral = 'MONTSERRAT_BOLD'
    font_asset_id: str | None = None
    width: int | None = None
    animation: OverlayAnimationLiteral = 'NONE'
```

Mirror into `ClipTimedOverlayPatchPayload` as `| None = None`:

```python
    video_asset_id: str | None = None
    shape: OverlayShapeLiteral | None = None
    ...
    font: CaptionFontLiteral | None = None
    font_asset_id: str | None = None
    width: int | None = None
    animation: OverlayAnimationLiteral | None = None
```

- [ ] **Step 6: New `ClipTimedSfx*` payloads**

Add after the `ClipTimedOverlay*` payload block:

```python
class ClipTimedSfxPayload(msgspec.Struct, frozen=True):
    """A one-shot sound effect on a clip candidate."""

    id: str
    candidate_id: str
    sfx_asset_id: str
    start_sec: float
    volume_db: float


class ClipTimedSfxCreatePayload(msgspec.Struct, frozen=True):
    """Create a timed SFX drop."""

    sfx_asset_id: str
    start_sec: float = 0.0
    volume_db: float = 0.0


class ClipTimedSfxPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a timed SFX drop."""

    sfx_asset_id: str | None = None
    start_sec: float | None = None
    volume_db: float | None = None


class ClipSfxListPayload(msgspec.Struct, frozen=True):
    """Paginated list of timed SFX drops."""

    items: list[ClipTimedSfxPayload]
    next_cursor: str | None
    total: int
```

- [ ] **Step 7: Sanity-check with mypy (this file has no dedicated tests, so
  static checking is the safety net until Task 10/12's tests exercise it)**

Run: `docker compose exec web mypy server/apps/clips/logic/value_objects.py`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add server/apps/clips/logic/value_objects.py
git commit -m "feat(clipping): extend value objects with new style/overlay/sfx fields"
```

---

## Task 10: Update `services.py` mappers + patch fields

**Files:**
- Modify: `server/apps/clips/services.py`
- Test: `tests/test_apps/test_clips/test_services.py` (extend existing —
  check with `find tests/test_apps/test_clips -iname "test_services*"`)

**Interfaces:**
- Consumes: everything from Task 9.
- Produces: updated `_to_style_payload`, `_to_layout_payload`,
  `_to_overlay_payload`; updated `patch_style`/`patch_layout`/`patch_overlay`
  field tuples + FK handling.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_clips/test_services.py — add these
import pytest

pytestmark = pytest.mark.django_db


def test_patch_style_updates_new_font_and_transition_fields(
    clip_candidate_factory,
) -> None:
    from server.apps.clips.logic.value_objects import ClipStyleConfigPatchPayload
    from server.apps.clips.services import ClipsService

    candidate = clip_candidate_factory()
    service = ClipsService()  # or resolve via container, per existing tests
    result = service.patch_style(
        str(candidate.id),
        ClipStyleConfigPatchPayload(
            watermark_color='#00FF00',
            watermark_font='POPPINS_BOLD',
            hook_animation='FADE',
            intro_transition='CROSSFADE',
            intro_transition_duration_sec=0.75,
            caption_uppercase=True,
            color_filter='VIVID',
            brightness=0.2,
            playback_speed=1.5,
        ),
    )
    assert result.watermark_color == '#00FF00'
    assert result.watermark_font == 'POPPINS_BOLD'
    assert result.hook_animation == 'FADE'
    assert result.intro_transition == 'CROSSFADE'
    assert result.intro_transition_duration_sec == 0.75
    assert result.caption_uppercase is True
    assert result.color_filter == 'VIVID'
    assert result.brightness == 0.2
    assert result.playback_speed == 1.5


def test_patch_layout_updates_fit_mode(clip_candidate_factory) -> None:
    from server.apps.clips.logic.value_objects import ClipLayoutConfigPatchPayload
    from server.apps.clips.services import ClipsService

    candidate = clip_candidate_factory()
    service = ClipsService()
    result = service.patch_layout(
        str(candidate.id),
        ClipLayoutConfigPatchPayload(fit_mode='BLUR_FILL'),
    )
    assert result.fit_mode == 'BLUR_FILL'


def test_patch_overlay_updates_font_and_animation(
    clip_candidate_factory,
) -> None:
    from server.apps.clips.models import ClipTimedOverlay
    from server.apps.clips.logic.value_objects import ClipTimedOverlayPatchPayload
    from server.apps.clips.services import ClipsService

    candidate = clip_candidate_factory()
    overlay = ClipTimedOverlay.objects.create(
        candidate=candidate, start_sec=0.0, end_sec=1.0,
    )
    service = ClipsService()
    result = service.patch_overlay(
        str(candidate.id),
        str(overlay.id),
        ClipTimedOverlayPatchPayload(font='OSWALD_BOLD', animation='POP'),
    )
    assert result.font == 'OSWALD_BOLD'
    assert result.animation == 'POP'
```

Check how existing tests in `test_services.py` instantiate `ClipsService`
(likely via a DI container fixture, not a bare constructor — match whatever
pattern is already there, since `ClipsService` may have injected
dependencies via punq).

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_services.py -v --no-cov -k "new_font_and_transition or fit_mode or font_and_animation"`
Expected: FAIL — `TypeError` (payload fields rejected by patch tuple / not
present on returned payload).

- [ ] **Step 3: Update `_to_style_payload`**

Add to the constructor call (matching each field's position in the payload
struct from Task 9):

```python
        caption_font_asset_id=(
            str(config.caption_font_asset_id)
            if config.caption_font_asset_id is not None
            else None
        ),
        caption_highlight_color=config.caption_highlight_color,
        caption_uppercase=config.caption_uppercase,
        hook_font_asset_id=(
            str(config.hook_font_asset_id)
            if config.hook_font_asset_id is not None
            else None
        ),
        hook_animation=config.hook_animation,
        intro_transition_duration_sec=config.intro_transition_duration_sec,
        outro_transition_duration_sec=config.outro_transition_duration_sec,
        intro_transition_asset_id=(
            str(config.intro_transition_asset_id)
            if config.intro_transition_asset_id is not None
            else None
        ),
        outro_transition_asset_id=(
            str(config.outro_transition_asset_id)
            if config.outro_transition_asset_id is not None
            else None
        ),
        watermark_color=config.watermark_color,
        watermark_font=config.watermark_font,
        watermark_font_asset_id=(
            str(config.watermark_font_asset_id)
            if config.watermark_font_asset_id is not None
            else None
        ),
        color_filter=config.color_filter,
        brightness=config.brightness,
        contrast=config.contrast,
        saturation=config.saturation,
        lut_asset_id=(
            str(config.lut_asset_id)
            if config.lut_asset_id is not None
            else None
        ),
        playback_speed=config.playback_speed,
```

- [ ] **Step 4: Update `patch_style`**

Add these names to the existing `_apply_patch_fields` tuple (alongside
`caption_font`, `hook_font`, `intro_transition`, `watermark_color`, etc. —
`caption_font`/`hook_font`/`watermark_font`/`watermark_color` already exist
or are simple scalars, just add the new scalar ones):

```python
                'caption_highlight_color',
                'caption_uppercase',
                'hook_animation',
                'intro_transition_duration_sec',
                'outro_transition_duration_sec',
                'watermark_color',
                'watermark_font',
                'color_filter',
                'brightness',
                'contrast',
                'saturation',
                'playback_speed',
```

Extend the existing `fk_map` dict in `patch_style` with the new FK fields:

```python
            'caption_font_asset_id': payload.caption_font_asset_id,
            'hook_font_asset_id': payload.hook_font_asset_id,
            'intro_transition_asset_id': payload.intro_transition_asset_id,
            'outro_transition_asset_id': payload.outro_transition_asset_id,
            'watermark_font_asset_id': payload.watermark_font_asset_id,
            'lut_asset_id': payload.lut_asset_id,
```

(These join the existing `watermark_image_id`/`intro_asset_id`/
`outro_asset_id`/`music_asset_id` entries already in that dict.)

- [ ] **Step 5: Update `_to_layout_payload` and `patch_layout`**

Add `fit_mode=config.fit_mode` to `_to_layout_payload`'s constructor call.
Add `'fit_mode'` to `patch_layout`'s `_apply_patch_fields` tuple (after
`'stack_ratio'`).

- [ ] **Step 6: Update `_to_overlay_payload` and `patch_overlay`**

Add to `_to_overlay_payload`:

```python
        video_asset_id=(
            str(overlay.video_asset_id)
            if overlay.video_asset_id is not None
            else None
        ),
        shape=overlay.shape,
        font=overlay.font,
        font_asset_id=(
            str(overlay.font_asset_id)
            if overlay.font_asset_id is not None
            else None
        ),
        width=overlay.width,
        animation=overlay.animation,
```

Add `'shape'`, `'font'`, `'width'`, `'animation'` to `patch_overlay`'s
`_apply_patch_fields` tuple. Extend `patch_overlay`'s existing single-FK
`image_asset_id` handling into a small loop matching the `fk_map` pattern
used in `patch_style`:

```python
        fk_map = {
            'image_asset_id': payload.image_asset_id,
            'video_asset_id': payload.video_asset_id,
            'font_asset_id': payload.font_asset_id,
        }
        for field_name, value in fk_map.items():
            if value is not None:
                setattr(
                    overlay,
                    field_name,
                    uuid.UUID(value) if value else None,
                )
                update_fields.append(field_name)
```
(replacing the existing single `if payload.image_asset_id is not None: ...`
block with this loop).

Also update `create_overlay` to pass through the new fields when creating:

```python
        overlay = ClipTimedOverlay.objects.create(
            candidate_id=candidate_id,
            overlay_type=payload.overlay_type,
            text=payload.text,
            image_asset_id=(
                uuid.UUID(payload.image_asset_id)
                if payload.image_asset_id
                else None
            ),
            video_asset_id=(
                uuid.UUID(payload.video_asset_id)
                if payload.video_asset_id
                else None
            ),
            shape=payload.shape,
            start_sec=payload.start_sec,
            end_sec=payload.end_sec,
            x=payload.x,
            y=payload.y,
            font_size=payload.font_size,
            color=payload.color,
            opacity=payload.opacity,
            font=payload.font,
            font_asset_id=(
                uuid.UUID(payload.font_asset_id)
                if payload.font_asset_id
                else None
            ),
            width=payload.width,
            animation=payload.animation,
        )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_services.py -v --cov=server.apps.clips.services --cov-report=term-missing -k "new_font_and_transition or fit_mode or font_and_animation"`
Expected: PASS.

Run the full clips test suite to check nothing else broke:
Run: `docker compose exec web pytest tests/test_apps/test_clips/ -v --no-cov`
Expected: all PASS (some pre-existing tests may need their `_sc()`-style
mocks/factories touched if they assert exact field lists — fix forward, not
by weakening assertions).

- [ ] **Step 8: Commit**

```bash
git add server/apps/clips/services.py tests/test_apps/test_clips/test_services.py
git commit -m "feat(clipping): wire new style/layout/overlay fields through services layer"
```

---

## Task 11: `ClipTimedSfx` service CRUD methods

**Files:**
- Modify: `server/apps/clips/services.py`
- Test: `tests/test_apps/test_clips/test_services.py`

**Interfaces:**
- Consumes: `ClipTimedSfx` model (Task 7), `ClipTimedSfx*Payload`s (Task 9).
- Produces: `ClipsService.list_sfx`, `.create_sfx`, `.get_sfx`, `.patch_sfx`,
  `.delete_sfx` — exact mirror of the existing `list_overlays`/
  `create_overlay`/`get_overlay`/`patch_overlay`/`delete_overlay` methods.

- [ ] **Step 1: Write the failing test**

```python
def test_sfx_crud_lifecycle(clip_candidate_factory, library_asset_factory) -> None:
    from server.apps.clips.logic.value_objects import (
        ClipTimedSfxCreatePayload,
        ClipTimedSfxPatchPayload,
    )
    from server.apps.clips.services import ClipsService

    candidate = clip_candidate_factory()
    sfx_asset = library_asset_factory(kind='SFX')
    service = ClipsService()

    created = service.create_sfx(
        str(candidate.id),
        ClipTimedSfxCreatePayload(
            sfx_asset_id=str(sfx_asset.id), start_sec=2.0, volume_db=-3.0,
        ),
    )
    assert created.start_sec == 2.0
    assert created.volume_db == -3.0

    listed = service.list_sfx(str(candidate.id))
    assert listed.total == 1
    assert listed.items[0].id == created.id

    fetched = service.get_sfx(str(candidate.id), created.id)
    assert fetched.id == created.id

    patched = service.patch_sfx(
        str(candidate.id),
        created.id,
        ClipTimedSfxPatchPayload(volume_db=-6.0),
    )
    assert patched.volume_db == -6.0

    service.delete_sfx(str(candidate.id), created.id)
    assert service.list_sfx(str(candidate.id)).total == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_services.py -v --no-cov -k sfx_crud_lifecycle`
Expected: FAIL — `AttributeError` (methods don't exist).

- [ ] **Step 3: Add the mapper + CRUD methods**

Add a mapper function near `_to_overlay_payload`:

```python
def _to_sfx_payload(sfx: 'ClipTimedSfx') -> ClipTimedSfxPayload:
    return ClipTimedSfxPayload(
        id=str(sfx.id),
        candidate_id=str(sfx.candidate_id),
        sfx_asset_id=str(sfx.sfx_asset_id),
        start_sec=sfx.start_sec,
        volume_db=sfx.volume_db,
    )
```

Add the CRUD methods to `ClipsService`, right after `delete_overlay`:

```python
    def list_sfx(
        self,
        candidate_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipSfxListPayload:
        """Return paginated timed SFX drops for a candidate."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        qs = ClipTimedSfx.objects.filter(  # type: ignore[misc]
            candidate_id=candidate_id,
        ).order_by('start_sec', '-id')
        rows, next_cursor, total = paginate_queryset(
            qs,
            cursor=cursor,
            limit=limit,
        )
        return ClipSfxListPayload(
            items=[_to_sfx_payload(row) for row in rows],
            next_cursor=next_cursor,
            total=total,
        )

    def create_sfx(
        self,
        candidate_id: str,
        payload: ClipTimedSfxCreatePayload,
    ) -> ClipTimedSfxPayload:
        """Create a timed SFX drop on a candidate."""
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
            ClipTimedSfx,
        )

        ClipCandidate.objects.get(id=candidate_id)
        sfx = ClipTimedSfx.objects.create(
            candidate_id=candidate_id,
            sfx_asset_id=uuid.UUID(payload.sfx_asset_id),
            start_sec=payload.start_sec,
            volume_db=payload.volume_db,
        )
        invalidate_preview_cache(candidate_id)
        return _to_sfx_payload(sfx)

    def get_sfx(self, candidate_id: str, sfx_id: str) -> ClipTimedSfxPayload:
        """Return one timed SFX drop."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        sfx = ClipTimedSfx.objects.get(  # type: ignore[misc]
            id=sfx_id,
            candidate_id=candidate_id,
        )
        return _to_sfx_payload(sfx)

    def patch_sfx(
        self,
        candidate_id: str,
        sfx_id: str,
        payload: ClipTimedSfxPatchPayload,
    ) -> ClipTimedSfxPayload:
        """Update a timed SFX drop."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        sfx = ClipTimedSfx.objects.get(  # type: ignore[misc]
            id=sfx_id,
            candidate_id=candidate_id,
        )
        update_fields = _apply_patch_fields(
            sfx,
            payload,
            ('start_sec', 'volume_db'),
        )
        if payload.sfx_asset_id is not None:
            sfx.sfx_asset_id = uuid.UUID(payload.sfx_asset_id)
            update_fields.append('sfx_asset_id')
        if update_fields:
            sfx.save(update_fields=update_fields)
            invalidate_preview_cache(candidate_id)
        return _to_sfx_payload(sfx)

    def delete_sfx(self, candidate_id: str, sfx_id: str) -> None:
        """Delete a timed SFX drop."""
        from server.apps.clips.models import ClipTimedSfx  # noqa: PLC0415

        deleted, _ = ClipTimedSfx.objects.filter(  # type: ignore[misc]
            id=sfx_id,
            candidate_id=candidate_id,
        ).delete()
        if deleted:
            invalidate_preview_cache(candidate_id)
```

Add `ClipSfxListPayload`, `ClipTimedSfxCreatePayload`, `ClipTimedSfxPatchPayload`,
`ClipTimedSfxPayload` to the `value_objects` import block at the top of
`services.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_services.py -v --cov=server.apps.clips.services --cov-report=term-missing -k sfx_crud_lifecycle`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/apps/clips/services.py tests/test_apps/test_clips/test_services.py
git commit -m "feat(clipping): add ClipTimedSfx CRUD service methods"
```

---

## Task 12: DMR views + URLs for `ClipTimedSfx`

**Files:**
- Modify: `server/apps/clips/api/views.py`
- Modify: `server/apps/clips/api/urls.py`
- Test: `tests/test_apps/test_clips/test_api/test_sfx_api.py` (create,
  mirroring `tests/test_apps/test_clips/test_api/` conventions for the
  overlay endpoints — check that directory for the exact overlay API test
  file to copy the DMRClient usage pattern from)

**Interfaces:**
- Consumes: `ClipsService.list_sfx/create_sfx/get_sfx/patch_sfx/delete_sfx`
  (Task 11).
- Produces: `GET/POST /candidates/<id>/sfx/`,
  `GET/PATCH/DELETE /candidates/<id>/sfx/<sfx_id>/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_clips/test_api/test_sfx_api.py
import pytest
from dmr.test import DMRClient

pytestmark = pytest.mark.django_db


def test_create_and_list_sfx(
    clip_candidate_factory, library_asset_factory, jwt_auth_headers,
) -> None:
    candidate = clip_candidate_factory()
    sfx_asset = library_asset_factory(kind='SFX')
    client = DMRClient()

    resp = client.post(
        f'/api/v1/clips/candidates/{candidate.id}/sfx/',
        json={'sfx_asset_id': str(sfx_asset.id), 'start_sec': 3.0},
        headers=jwt_auth_headers,
    )
    assert resp.status_code == 201
    sfx_id = resp.json()['id']

    resp = client.get(
        f'/api/v1/clips/candidates/{candidate.id}/sfx/',
        headers=jwt_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()['total'] == 1

    resp = client.patch(
        f'/api/v1/clips/candidates/{candidate.id}/sfx/{sfx_id}/',
        json={'volume_db': -5.0},
        headers=jwt_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()['volume_db'] == -5.0

    resp = client.delete(
        f'/api/v1/clips/candidates/{candidate.id}/sfx/{sfx_id}/',
        headers=jwt_auth_headers,
    )
    assert resp.status_code == 204
```

Check an existing overlay API test file (e.g.
`tests/test_apps/test_clips/test_api/test_overlay_api.py` or similar — find
with `grep -rl "overlays/" tests/test_apps/test_clips/test_api/`) for the
exact URL prefix, `DMRClient` usage, and auth-header fixture name, and match
it precisely rather than guessing.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_api/test_sfx_api.py -v --no-cov`
Expected: FAIL — 404 (routes don't exist).

- [ ] **Step 3: Add the views**

Add to `server/apps/clips/api/views.py`, mirroring
`ClipTimedOverlayCollectionView`/`ClipTimedOverlayDetailView` exactly:

```python
@final
class ClipTimedSfxCollectionView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List or create timed SFX drops."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipSfxListPayload:
        """Return paginated SFX drops for a candidate."""
        return self.resolve(ClipsService).list_sfx(
            str(self.kwargs['candidate_id']),
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ClipTimedSfxCreatePayload],
    ) -> ClipTimedSfxPayload:
        """Create a timed SFX drop."""
        return self.resolve(ClipsService).create_sfx(
            str(self.kwargs['candidate_id']),
            parsed_body,
        )


@final
class ClipTimedSfxDetailView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get, patch, or delete one timed SFX drop."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipTimedSfxPayload:
        """Return one SFX drop."""
        return self.resolve(ClipsService).get_sfx(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['sfx_id']),
        )

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ClipTimedSfxPatchPayload],
    ) -> ClipTimedSfxPayload:
        """Update one SFX drop."""
        return self.resolve(ClipsService).patch_sfx(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['sfx_id']),
            parsed_body,
        )

    @modify(status_code=HTTPStatus.NO_CONTENT)
    def delete(self) -> None:
        """Delete one SFX drop."""
        self.resolve(ClipsService).delete_sfx(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['sfx_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ClipTimedSfx.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'SFX drop not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )
```

Add `ClipSfxListPayload`, `ClipTimedSfxCreatePayload`,
`ClipTimedSfxPatchPayload`, `ClipTimedSfxPayload` to the `value_objects`
import block, and `ClipTimedSfx` to the `models` import block, at the top of
`views.py`.

- [ ] **Step 4: Add the URL routes**

In `server/apps/clips/api/urls.py`, add to `config_urlpatterns` (after the
overlay routes):

```python
    path(
        'candidates/<uuid:candidate_id>/sfx/',
        views.ClipTimedSfxCollectionView.as_view(),
        name='sfx_list',
    ),
    path(
        'candidates/<uuid:candidate_id>/sfx/<uuid:sfx_id>/',
        views.ClipTimedSfxDetailView.as_view(),
        name='sfx_detail',
    ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_clips/test_api/test_sfx_api.py -v --cov=server.apps.clips.api.views --cov-report=term-missing`
Expected: PASS.

- [ ] **Step 6: Regenerate and check the OpenAPI schema**

Run: `docker compose exec web python manage.py dump_openapi_schema -o /tmp/schema.yaml`
Expected: succeeds with no errors; `grep sfx /tmp/schema.yaml` shows the new
paths.

- [ ] **Step 7: Commit**

```bash
git add server/apps/clips/api/views.py server/apps/clips/api/urls.py \
  tests/test_apps/test_clips/test_api/test_sfx_api.py
git commit -m "feat(clipping): add ClipTimedSfx CRUD API endpoints"
```

---

## Task 13: Font resolution + per-render fonts directory

**Files:**
- Modify: `server/apps/rendering/clip_stages/fonts.py` (extend Task 1's
  module)
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_fonts.py`

**Interfaces:**
- Consumes: `curated_font_path`/`curated_font_family` (Task 1),
  `LibraryAsset` model (has `.file`, `.meta` per existing `assets` app).
- Produces: `resolve_drawtext_font(font_choice: str, font_asset: 'LibraryAsset | None') -> tuple[str, str]`
  returning `(fontfile_path, family_name)` — used by hook/watermark/overlay
  drawtext stages. `build_fonts_dir(render_tmp_dir: Path, extra_assets: list['LibraryAsset | None']) -> Path`
  — assembles a per-render fonts folder (hardlinked bundled curated fonts +
  any custom font assets referenced by this render), used by the captions
  stage's `fontsdir`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_apps/test_rendering/test_clip_stages/test_fonts.py
from unittest.mock import MagicMock

from server.apps.rendering.clip_stages.fonts import (
    build_fonts_dir,
    resolve_drawtext_font,
)


def test_resolve_drawtext_font_curated() -> None:
    path, family = resolve_drawtext_font('MONTSERRAT_BOLD', None)
    assert path.endswith('Montserrat-Bold.ttf')
    assert len(family) > 0


def test_resolve_drawtext_font_custom_asset(tmp_path) -> None:
    asset = MagicMock()
    asset.file.read.return_value = b'fake-ttf-bytes'
    asset.meta = {'font_family': 'My Custom Font'}
    path, family = resolve_drawtext_font('MONTSERRAT_BOLD', asset)
    assert family == 'My Custom Font'
    assert path != ''


def test_build_fonts_dir_includes_curated_and_custom(tmp_path) -> None:
    asset = MagicMock()
    asset.file.read.return_value = b'fake-ttf-bytes'
    asset.meta = {'font_family': 'My Custom Font'}
    fonts_dir = build_fonts_dir(tmp_path, [asset, None])
    files = list(fonts_dir.glob('*.ttf'))
    assert len(files) == 17  # 16 curated + 1 custom
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_fonts.py -v --no-cov -k "resolve_drawtext or build_fonts_dir"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Append to `server/apps/rendering/clip_stages/fonts.py`:

```python
import shutil
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.apps.assets.models import LibraryAsset


def resolve_drawtext_font(
    font_choice: str,
    font_asset: 'LibraryAsset | None',
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
    extra_assets: list['LibraryAsset | None'],
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
        if not dest.exists():
            shutil.copy2(src, dest)
    for asset in extra_assets:
        if asset is None:
            continue
        font_bytes: bytes = asset.file.read()
        dest = fonts_dir / f'{asset.id}.ttf'
        dest.write_bytes(font_bytes)
    return fonts_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_fonts.py -v --cov=server.apps.rendering.clip_stages.fonts --cov-report=term-missing`
Expected: all tests PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/fonts.py \
  tests/test_apps/test_rendering/test_clip_stages/test_fonts.py
git commit -m "feat(clipping): add font resolution + per-render fonts directory"
```

---

## Task 14: Extract custom font family name at asset ingest time

**Files:**
- Modify: `server/apps/assets/tasks.py`
- Test: `tests/test_apps/test_assets/test_tasks.py` (extend existing)

**Interfaces:**
- Consumes: `fonttools` (Task 1).
- Produces: `LibraryAsset.meta['font_family']` populated whenever a
  `LibraryAssetKind.FONT` asset is ingested, read by
  `resolve_drawtext_font`/`build_fonts_dir` (Task 13).

- [ ] **Step 1: Write the failing test**

Find the existing ingest test for e.g. `LibraryAssetKind.WATERMARK` or
`LibraryAssetKind.MUSIC` in `tests/test_apps/test_assets/test_tasks.py`
(the branch handling those kinds was referenced in `assets/tasks.py` around
line 111/126/234) and add an equivalent for `FONT`:

```python
def test_ingest_font_asset_extracts_family_name(
    library_asset_factory, real_ttf_bytes,
) -> None:
    from server.apps.assets.models import LibraryAssetKind
    from server.apps.assets.tasks import ingest_library_asset  # match actual name

    asset = library_asset_factory(kind=LibraryAssetKind.FONT)
    # write real_ttf_bytes to asset.file per however the existing
    # ingest tests set up file content
    ingest_library_asset(str(asset.id))  # match actual task/function name
    asset.refresh_from_db()
    assert 'font_family' in asset.meta
    assert len(asset.meta['font_family']) > 0
```

Match this to whatever the *actual* ingest entrypoint function is named in
`assets/tasks.py` (read the file first — the earlier design-phase read only
saw `_ffprobe`/`_run_loudness`/`_RENDITION_PROFILES` and a reference to
`if kind == LibraryAssetKind.WATERMARK` around line 111 and
`if kind in {LibraryAssetKind.INTRO, LibraryAssetKind.OUTRO}` around line
126 and `if asset.kind in {LibraryAssetKind.MUSIC, LibraryAssetKind.SFX}`
around line 234 — find the enclosing function and follow its exact
signature/fixture conventions rather than the sketch above).

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_assets/test_tasks.py -v --no-cov -k font_asset_extracts_family_name`
Expected: FAIL.

- [ ] **Step 3: Add the FONT branch**

In the same conditional block that already special-cases
`LibraryAssetKind.WATERMARK`/`INTRO`/`OUTRO`/`MUSIC`/`SFX` during ingest, add:

```python
    if kind == LibraryAssetKind.FONT:
        from fontTools.ttLib import TTFont  # noqa: PLC0415

        font = TTFont(tmp_path, lazy=True)
        name_table = font['name']
        family = (
            name_table.getDebugName(4)
            or name_table.getDebugName(1)
            or 'Custom Font'
        )
        asset.meta['font_family'] = family
```

(Match the exact local variable name for the downloaded temp file path —
the existing branches use `tmp_path` based on the pattern seen in
`_ffprobe(tmp_path)` calls at line ~200 — confirm by reading the surrounding
function.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_assets/test_tasks.py -v --cov=server.apps.assets.tasks --cov-report=term-missing -k font_asset`
Expected: PASS, no coverage regressions elsewhere in the file.

- [ ] **Step 5: Commit**

```bash
git add server/apps/assets/tasks.py tests/test_apps/test_assets/test_tasks.py
git commit -m "feat(clipping): extract font family name at FONT asset ingest time"
```

---

## Task 15: Wire fontfile/fontsdir into hook, watermark, overlay-text, captions

**Files:**
- Modify: `server/apps/rendering/clip_stages/hook.py`
- Modify: `server/apps/rendering/clip_stages/watermark.py`
- Modify: `server/apps/rendering/clip_stages/timed_overlays.py`
- Modify: `server/apps/rendering/clip_stages/captions.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `resolve_drawtext_font`, `build_fonts_dir` (Task 13).

- [ ] **Step 1: Write the failing tests (one per stage)**

```python
# add to test_remaining_stages.py

@patch('server.apps.rendering.clip_stages.hook.subprocess.run')
@patch('server.apps.rendering.clip_stages.hook.resolve_drawtext_font')
def test_hook_uses_fontfile(
    mock_resolve: MagicMock, mock_run: MagicMock,
) -> None:
    mock_resolve.return_value = ('/fonts/Montserrat-Bold.ttf', 'Montserrat')
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(hook_enabled=True)
    sc.hook_font = 'MONTSERRAT_BOLD'
    sc.hook_font_asset = None
    stage = HookStage(
        hook_text='Hi', output_path=Path('/out.mp4'), style_config=sc,
    )
    with patch('server.apps.rendering.clip_stages.hook.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    assert 'fontfile=/fonts/Montserrat-Bold.ttf' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
@patch('server.apps.rendering.clip_stages.watermark.resolve_drawtext_font')
def test_watermark_text_uses_fontfile(
    mock_resolve: MagicMock, mock_run: MagicMock,
) -> None:
    mock_resolve.return_value = ('/fonts/Poppins-Bold.ttf', 'Poppins')
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(watermark_enabled=True)
    sc.watermark_font = 'POPPINS_BOLD'
    sc.watermark_font_asset = None
    sc.watermark_color = '#00FF00'
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    assert 'fontfile=/fonts/Poppins-Bold.ttf' in joined
    assert 'fontcolor=#00FF00' in joined


@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
@patch('server.apps.rendering.clip_stages.timed_overlays.resolve_drawtext_font')
def test_timed_overlay_text_uses_fontfile(
    mock_resolve: MagicMock, mock_run: MagicMock,
) -> None:
    mock_resolve.return_value = ('/fonts/Oswald-Bold.ttf', 'Oswald')
    mock_run.return_value = MagicMock(returncode=0)
    overlay = MagicMock()
    overlay.overlay_type = 'TEXT'
    overlay.text = 'Hello'
    overlay.font = 'OSWALD_BOLD'
    overlay.font_asset = None
    overlay.font_size = 40
    overlay.color = '#FFFFFF'
    overlay.opacity = 1.0
    overlay.x = 0
    overlay.y = 100
    overlay.start_sec = 0.0
    overlay.end_sec = 2.0
    overlay.animation = 'NONE'
    stage = TimedOverlayStage(output_path=Path('/out.mp4'), timed_overlays=[overlay])
    with patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    assert 'fontfile=/fonts/Oswald-Bold.ttf' in ' '.join(cmd)


@patch('server.apps.rendering.clip_stages.captions.subprocess.run')
@patch('server.apps.rendering.clip_stages.captions.build_fonts_dir')
def test_caption_stage_passes_fontsdir(
    mock_build_dir: MagicMock, mock_run: MagicMock,
) -> None:
    mock_build_dir.return_value = Path('/tmp/render1/fonts')
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(caption_enabled=True)
    stage = CaptionStage(
        transcript_json={'segments': []},
        output_path=Path('/out.mp4'),
        ass_path=Path('/tmp/out.ass'),
        style_config=sc,
        fonts_dir=Path('/tmp/render1/fonts'),
    )
    with (
        patch('server.apps.rendering.clip_stages.captions.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.captions.Path.write_text'),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    assert "fontsdir='/tmp/render1/fonts'" in ' '.join(cmd)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k "fontfile or fontsdir"`
Expected: FAIL — `AttributeError`/`ImportError` (no `resolve_drawtext_font`
import in these modules yet, `CaptionStage` has no `fonts_dir` param).

- [ ] **Step 3: Update `hook.py`**

Add import: `from server.apps.rendering.clip_stages.fonts import resolve_drawtext_font`

In `_overlay()` and `_title_card()`, replace the `drawtext=` string
construction to resolve and include `fontfile=`:

```python
        font_path, _family = resolve_drawtext_font(
            sc.hook_font, sc.hook_font_asset,
        )
        safe_font_path = font_path.replace("'", "\\'").replace(':', '\\:')
```//add this near the top of each method, then extend the drawtext filter string:

```python
        drawtext = (
            f"drawtext=text='{safe_text}'"
            f':fontfile={safe_font_path}'
            f':fontsize={sc.hook_size}'
            ...
        )
```

- [ ] **Step 4: Update `watermark.py`**

Same pattern in `_text_watermark`: resolve
`resolve_drawtext_font(sc.watermark_font, sc.watermark_font_asset)`, add
`:fontfile={path}` to the `drawtext=` string, and change
`color = sc.caption_color` to `color = sc.watermark_color` (this also closes
the watermark-color bug from the spec — no separate task needed, it's a
one-line change alongside the font wiring since both touch the same
`drawtext=` string construction).

- [ ] **Step 5: Update `timed_overlays.py`**

In the TEXT branch of `run()` (see Task 17 for the full branch rewrite —
for *this* task, just add font resolution to the existing text path):
resolve `resolve_drawtext_font(overlay.font, overlay.font_asset)` per
overlay, add `:fontfile={path}` to its `drawtext=` string.

- [ ] **Step 6: Update `captions.py`**

Add `fonts_dir: Path` field to `CaptionStage` (after `style_config`). Update
the `subtitles=` filter string in `run()`:

```python
        fonts_dir_str = str(self.fonts_dir).replace("'", "\\'").replace(':', '\\:')
        cmd = [
            'ffmpeg', '-y', '-i', str(input_path),
            '-vf', f"subtitles='{ass_str}':fontsdir='{fonts_dir_str}'",
            *clip_filter_encode_args(...),
            str(self.output_path),
        ]
```

Also update `ASSGenerator._header()`'s `font = sc.caption_font if sc else
'Montserrat-Bold'` line to resolve the real family name:

```python
        from server.apps.rendering.clip_stages.fonts import (  # noqa: PLC0415
            curated_font_family,
        )
        if sc and sc.caption_font_asset:
            font = sc.caption_font_asset.meta.get('font_family', 'Custom Font')
        else:
            font = curated_font_family(sc.caption_font if sc else 'MONTSERRAT_BOLD')
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages --cov-report=term-missing`
Expected: all PASS, no coverage regressions. `CaptionStage` callers (the
pipeline in Task 28) will need the new `fonts_dir` argument — that's handled
when Task 28 rewires `_build_stages()`; until then this task's own unit
tests construct `CaptionStage` directly with `fonts_dir=...` so they pass in
isolation.

- [ ] **Step 8: Commit**

```bash
git add server/apps/rendering/clip_stages/hook.py \
  server/apps/rendering/clip_stages/watermark.py \
  server/apps/rendering/clip_stages/timed_overlays.py \
  server/apps/rendering/clip_stages/captions.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): wire fontfile/fontsdir into hook, watermark, overlay, caption stages; fix watermark color fallback"
```

---

## Task 16: Real transitions via ffmpeg `xfade`/`acrossfade`

**Files:**
- Modify: `server/apps/rendering/clip_stages/intro_outro.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `sync_ffprobe_duration` (Task 2).
- Produces: `IntroConcatStage`/`OutroConcatStage` now branch on
  `style_config.intro_transition`/`outro_transition`; `NONE` keeps the
  existing fast concat-demuxer path unchanged, everything else (except
  `CUSTOM_ASSET`, handled in Task 17) uses `xfade`/`acrossfade`.

**This is the fix for the core reported bug** — the intro/outro transition
dropdown has never affected output before this task.

- [ ] **Step 1: Write the failing tests**

```python
# add to test_remaining_stages.py

_XFADE_MAP = {
    'CROSSFADE': 'fade',
    'FADE_BLACK': 'fadeblack',
    'FADE_WHITE': 'fadewhite',
    'SLIDE_LEFT': 'slideleft',
    'SLIDE_RIGHT': 'slideright',
    'SLIDE_UP': 'slideup',
    'SLIDE_DOWN': 'slidedown',
    'WIPE_LEFT': 'wipeleft',
    'WIPE_RIGHT': 'wiperight',
    'ZOOM_IN': 'zoomin',
}


@pytest.mark.parametrize(('style_value', 'xfade_name'), list(_XFADE_MAP.items()))
@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
@patch(
    'server.apps.rendering.clip_stages.intro_outro.sync_ffprobe_duration',
    return_value=5.0,
)
def test_intro_concat_xfade_transition(
    mock_probe: MagicMock,
    mock_run: MagicMock,
    style_value: str,
    xfade_name: str,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = style_value
    sc.intro_transition_duration_sec = 0.5
    sc.intro_transition_asset = None
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert f'xfade=transition={xfade_name}' in fc
    assert 'acrossfade' in fc


@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
@patch(
    'server.apps.rendering.clip_stages.intro_outro.sync_ffprobe_duration',
    return_value=0.6,
)
def test_intro_concat_clamps_transition_duration_to_short_clip(
    mock_probe: MagicMock,
    mock_run: MagicMock,
) -> None:
    """A 0.6s intro with a configured 3s crossfade must clamp, not go negative."""
    mock_run.return_value = MagicMock(returncode=0)
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = 'CROSSFADE'
    sc.intro_transition_duration_sec = 3.0
    sc.intro_transition_asset = None
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    # duration must be clamped to <= 90% of 0.6s = 0.54s, never the full 3s
    assert 'xfade=transition=fade:duration=0.54' in fc


def test_intro_concat_none_transition_uses_fast_concat_path() -> None:
    """NONE must still use the cheap stream-copy concat, no probe/xfade."""
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = 'NONE'
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run') as mock_run,
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        stage.run(Path('/in.mp4'))
        assert mock_run.call_count == 2  # scale + concat, same as before
        for call in mock_run.call_args_list:
            assert '-filter_complex' not in call[0][0]
```

Add equivalent `test_outro_concat_xfade_transition`/
`test_outro_concat_none_transition_uses_fast_concat_path` tests mirroring the
above against `OutroConcatStage`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k xfade`
Expected: FAIL — current code always does hard concat, no `xfade` ever
appears.

- [ ] **Step 3: Rewrite `intro_outro.py`**

Replace the full file:

```python
"""IntroConcatStage and OutroConcatStage — prepend/append intro/outro clips."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.probe import sync_ffprobe_duration

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')

_XFADE_TRANSITIONS: dict[str, str] = {
    'CROSSFADE': 'fade',
    'FADE_BLACK': 'fadeblack',
    'FADE_WHITE': 'fadewhite',
    'SLIDE_LEFT': 'slideleft',
    'SLIDE_RIGHT': 'slideright',
    'SLIDE_UP': 'slideup',
    'SLIDE_DOWN': 'slidedown',
    'WIPE_LEFT': 'wipeleft',
    'WIPE_RIGHT': 'wiperight',
    'ZOOM_IN': 'zoomin',
}

# A transition can never eat more than this fraction of the shorter clip,
# to avoid a negative/invalid xfade offset on very short intros/outros.
_MAX_TRANSITION_FRACTION = 0.9


def _run_ffmpeg(cmd: list[str], label: str) -> None:
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f'{label} ffmpeg failed: {result.stderr}')


def _scale_asset(
    asset_bytes: bytes,
    *,
    width: int,
    height: int,
    fps: int,
    crf: int,
    preset: str,
    audio_bitrate: str,
    label: str,
) -> str:
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        src_path = tmp.name
    Path(src_path).write_bytes(asset_bytes)

    scaled_path = src_path + '_scaled.mp4'
    _run_ffmpeg(
        [
            'ffmpeg', '-y', '-i', src_path,
            '-vf', f'scale={width}:{height},fps={fps}',
            '-c:v', 'libx264', '-crf', str(crf), '-preset', preset,
            '-c:a', 'aac', '-b:a', audio_bitrate,
            scaled_path,
        ],
        f'{label} scale',
    )
    Path(src_path).unlink(missing_ok=True)
    return scaled_path


def _fast_concat(first: str, second: str, output_path: Path, label: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, encoding='utf-8',
    ) as f:
        f.write(f"file '{first}'\n")
        f.write(f"file '{second}'\n")
        list_path = f.name
    _run_ffmpeg(
        [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', list_path, '-c', 'copy', str(output_path),
        ],
        f'{label} concat',
    )
    Path(list_path).unlink(missing_ok=True)


def _xfade_transition_cmd(
    *,
    first_path: str,
    second_path: str,
    xfade_name: str,
    duration: float,
    offset: float,
    output_path: Path,
    crf: int,
    preset: str,
    fps: int,
    audio_bitrate: str,
) -> list[str]:
    filter_complex = (
        f'[0:v][1:v]xfade=transition={xfade_name}:duration={duration:.3f}'
        f':offset={offset:.3f}[v];'
        f'[0:a][1:a]acrossfade=d={duration:.3f}[a]'
    )
    return [
        'ffmpeg', '-y', '-i', first_path, '-i', second_path,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '[a]',
        '-c:v', 'libx264', '-crf', str(crf), '-preset', preset,
        '-pix_fmt', 'yuv420p', '-r', str(fps),
        '-c:a', 'aac', '-b:a', audio_bitrate,
        str(output_path),
    ]


def _clamped_transition_duration(
    configured: float, first_dur: float, second_dur: float,
) -> float:
    max_allowed = min(first_dur, second_dur) * _MAX_TRANSITION_FRACTION
    return min(configured, max_allowed)


def _apply_boundary(
    *,
    transition: str,
    duration_sec: float,
    first_path: str,
    second_path: str,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    crf: int,
    preset: str,
    audio_bitrate: str,
    label: str,
) -> None:
    if transition == 'NONE' or transition not in _XFADE_TRANSITIONS:
        _fast_concat(first_path, second_path, output_path, label)
        return
    first_dur = sync_ffprobe_duration(first_path)
    second_dur = sync_ffprobe_duration(second_path)
    duration = _clamped_transition_duration(duration_sec, first_dur, second_dur)
    offset = max(0.0, first_dur - duration)
    cmd = _xfade_transition_cmd(
        first_path=first_path,
        second_path=second_path,
        xfade_name=_XFADE_TRANSITIONS[transition],
        duration=duration,
        offset=offset,
        output_path=output_path,
        crf=crf,
        preset=preset,
        fps=fps,
        audio_bitrate=audio_bitrate,
    )
    _run_ffmpeg(cmd, f'{label} xfade')


@final
@dataclass
class IntroConcatStage(RenderStage):
    """Stage: prepend intro clip, applying a transition if configured."""

    output_path: Path
    style_config: ClipStyleConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = 'slow'
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        return 'intro_concat'

    @property
    @override
    def order(self) -> int:
        return 2

    @override
    def should_run(self) -> bool:
        return (
            self.style_config is not None
            and self.style_config.intro_asset is not None
        )

    @override
    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        assert sc is not None  # noqa: S101
        assert sc.intro_asset is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        intro_bytes: bytes = sc.intro_asset.file.read()
        scaled_intro = _scale_asset(
            intro_bytes,
            width=self.width, height=self.height, fps=self.fps,
            crf=self.crf, preset=self.preset, audio_bitrate=self.audio_bitrate,
            label='IntroConcatStage',
        )
        _apply_boundary(
            transition=sc.intro_transition,
            duration_sec=sc.intro_transition_duration_sec,
            first_path=scaled_intro,
            second_path=str(input_path),
            output_path=self.output_path,
            width=self.width, height=self.height, fps=self.fps,
            crf=self.crf, preset=self.preset, audio_bitrate=self.audio_bitrate,
            label='IntroConcatStage',
        )
        Path(scaled_intro).unlink(missing_ok=True)
        return self.output_path


@final
@dataclass
class OutroConcatStage(RenderStage):
    """Stage: append outro clip, applying a transition if configured."""

    output_path: Path
    style_config: ClipStyleConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = 'slow'
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        return 'outro_concat'

    @property
    @override
    def order(self) -> int:
        return 9

    @override
    def should_run(self) -> bool:
        return (
            self.style_config is not None
            and self.style_config.outro_asset is not None
        )

    @override
    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        assert sc is not None  # noqa: S101
        assert sc.outro_asset is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        outro_bytes: bytes = sc.outro_asset.file.read()
        scaled_outro = _scale_asset(
            outro_bytes,
            width=self.width, height=self.height, fps=self.fps,
            crf=self.crf, preset=self.preset, audio_bitrate=self.audio_bitrate,
            label='OutroConcatStage',
        )
        _apply_boundary(
            transition=sc.outro_transition,
            duration_sec=sc.outro_transition_duration_sec,
            first_path=str(input_path),
            second_path=scaled_outro,
            output_path=self.output_path,
            width=self.width, height=self.height, fps=self.fps,
            crf=self.crf, preset=self.preset, audio_bitrate=self.audio_bitrate,
            label='OutroConcatStage',
        )
        Path(scaled_outro).unlink(missing_ok=True)
        return self.output_path
```

Note this rewrite changes the existing error-message strings the pre-existing
tests assert on (`'IntroConcatStage scale ffmpeg failed'` etc. via the
`_run_ffmpeg`/`_scale_asset` helpers using the same `f'{label} scale'`/
`f'{label} concat'` format) — the pre-existing passing tests from before this
task should keep passing unmodified since the message format is preserved.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.intro_outro --cov-report=term-missing`
Expected: all PASS (new xfade tests + all pre-existing intro/outro tests),
100% coverage on `intro_outro.py`.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/intro_outro.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "fix(clipping): implement real xfade/acrossfade transitions (was silent no-op)"
```

---

## Task 17: Custom transition-video assets (`CUSTOM_ASSET`)

**Files:**
- Modify: `server/apps/rendering/clip_stages/intro_outro.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `intro_transition_asset`/`outro_transition_asset` (Task 4).
- Produces: `_apply_boundary` grows a `CUSTOM_ASSET` branch that composites
  the transition asset over the boundary via a `blend=all_mode=screen`
  filter instead of `xfade`.

- [ ] **Step 1: Write the failing test**

```python
@patch('server.apps.rendering.clip_stages.intro_outro.subprocess.run')
def test_intro_concat_custom_transition_asset(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    intro_asset = MagicMock()
    intro_asset.file.read.return_value = b'fake_video_bytes'
    transition_asset = MagicMock()
    transition_asset.file.read.return_value = b'fake_transition_bytes'
    sc = _sc()
    sc.intro_asset = intro_asset
    sc.intro_transition = 'CUSTOM_ASSET'
    sc.intro_transition_asset = transition_asset
    sc.intro_transition_duration_sec = 0.5
    stage = IntroConcatStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.intro_outro.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.intro_outro.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'blend=all_mode=screen' in fc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k custom_transition_asset`
Expected: FAIL — `CUSTOM_ASSET` currently falls through to the fast-concat
`else` branch (not in `_XFADE_TRANSITIONS`), no `blend` filter appears.

- [ ] **Step 3: Add the `CUSTOM_ASSET` branch**

Add a new helper and wire it into `_apply_boundary`:

```python
def _custom_asset_transition_cmd(
    *,
    first_path: str,
    second_path: str,
    transition_asset_path: str,
    duration: float,
    output_path: Path,
    crf: int,
    preset: str,
    fps: int,
    audio_bitrate: str,
) -> list[str]:
    # Overlay the transition video (e.g. a light-leak/film-burn clip) across
    # the cut point using a screen blend, then hard-cut underneath it.
    filter_complex = (
        f'[0:v][1:v]concat=n=2:v=1:a=0[base];'
        f'[base][2:v]blend=all_mode=screen:all_opacity=1[v]'
    )
    return [
        'ffmpeg', '-y', '-i', first_path, '-i', second_path,
        '-i', transition_asset_path,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '0:a',
        '-c:v', 'libx264', '-crf', str(crf), '-preset', preset,
        '-pix_fmt', 'yuv420p', '-r', str(fps),
        '-c:a', 'aac', '-b:a', audio_bitrate,
        str(output_path),
    ]
```

Update `_apply_boundary`'s signature to accept
`transition_asset_bytes: bytes | None = None`, and its body:

```python
def _apply_boundary(
    *,
    transition: str,
    duration_sec: float,
    first_path: str,
    second_path: str,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    crf: int,
    preset: str,
    audio_bitrate: str,
    label: str,
    transition_asset_bytes: bytes | None = None,
) -> None:
    if transition == 'CUSTOM_ASSET' and transition_asset_bytes is not None:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            asset_path = tmp.name
        Path(asset_path).write_bytes(transition_asset_bytes)
        cmd = _custom_asset_transition_cmd(
            first_path=first_path,
            second_path=second_path,
            transition_asset_path=asset_path,
            duration=duration_sec,
            output_path=output_path,
            crf=crf, preset=preset, fps=fps, audio_bitrate=audio_bitrate,
        )
        _run_ffmpeg(cmd, f'{label} custom transition')
        Path(asset_path).unlink(missing_ok=True)
        return
    if transition == 'NONE' or transition not in _XFADE_TRANSITIONS:
        _fast_concat(first_path, second_path, output_path, label)
        return
    # ... (existing xfade branch from Task 16, unchanged)
```

Update both `IntroConcatStage.run()` and `OutroConcatStage.run()` to pass
`transition_asset_bytes=sc.intro_transition_asset.file.read() if
sc.intro_transition_asset else None` (respectively `outro_transition_asset`)
into their `_apply_boundary` calls.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.intro_outro --cov-report=term-missing`
Expected: PASS, 100% coverage maintained.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/intro_outro.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): add custom transition-video asset compositing (CUSTOM_ASSET)"
```

---

## Task 18: Fix image-overlay bug + add `width`

**Files:**
- Modify: `server/apps/rendering/clip_stages/timed_overlays.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Produces: `TimedOverlayStage.run()` now branches on `overlay.overlay_type`;
  `IMAGE` overlays actually render (previously silently skipped — this is
  the second reported bug).

- [ ] **Step 1: Write the failing test**

```python
@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_image_type_renders(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    image_asset = MagicMock()
    image_asset.file.read.return_value = b'fake_png_bytes'
    overlay = MagicMock()
    overlay.overlay_type = 'IMAGE'
    overlay.image_asset = image_asset
    overlay.video_asset = None
    overlay.width = 200
    overlay.opacity = 0.9
    overlay.x = 10
    overlay.y = 20
    overlay.start_sec = 1.0
    overlay.end_sec = 4.0
    overlay.animation = 'NONE'
    stage = TimedOverlayStage(output_path=Path('/out.mp4'), timed_overlays=[overlay])
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'overlay=' in fc
    assert "enable='between(t,1.0,4.0)'" in fc
    assert 'scale=200:-1' in fc
```

Before this fix, this test would have asserted the OLD (buggy) behavior of
silently returning `input_path` unchanged for an IMAGE overlay — confirm by
running it against the current code first if you want to see the bug
directly:

Run (against pre-fix code): the assertion `'overlay=' in fc` fails with a
`ValueError` (`-filter_complex` never appears in `cmd` because the current
code only ever emits `drawtext` via `-vf`, or returns the input unchanged).

- [ ] **Step 2: Run test to verify it fails (post-fix expectations, pre-fix code)**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k image_type_renders`
Expected: FAIL.

- [ ] **Step 3: Rewrite `TimedOverlayStage.run()`**

Replace the body of `timed_overlays.py`'s `run()` method (keep `should_run`
unchanged — it already correctly checks `len(self.timed_overlays) > 0`) with
a per-overlay-type dispatch. This also folds in Task 15's font wiring for the
TEXT branch (don't duplicate it if Task 15 already landed it — merge):

```python
    @override
    def run(self, input_path: Path) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        current = str(input_path)
        any_applied = False
        for overlay in self.timed_overlays:
            if overlay.overlay_type == 'TEXT' and overlay.text:
                current = self._apply_text(current, overlay)
                any_applied = True
            elif overlay.overlay_type == 'IMAGE' and overlay.image_asset:
                current = self._apply_media_overlay(
                    current, overlay, overlay.image_asset.file.read(),
                    is_video=False,
                )
                any_applied = True
            elif overlay.overlay_type == 'VIDEO' and overlay.video_asset:
                current = self._apply_media_overlay(
                    current, overlay, overlay.video_asset.file.read(),
                    is_video=True,
                )
                any_applied = True
        if not any_applied:
            return input_path
        final_path = Path(current)
        if final_path != self.output_path:
            final_path.rename(self.output_path)
        return self.output_path
```

Add `_apply_text` (extracted from the existing inline drawtext logic, with
`fontfile=` from Task 15 already folded in) and `_apply_media_overlay`
(new, for IMAGE — VIDEO's shape-masking variant is Task 20):

```python
    def _apply_text(self, input_path: str, overlay: 'ClipTimedOverlay') -> str:
        from server.apps.rendering.clip_stages.fonts import (  # noqa: PLC0415
            resolve_drawtext_font,
        )

        safe = overlay.text.replace("'", "\\'").replace(':', '\\:')
        font_path, _family = resolve_drawtext_font(
            overlay.font, overlay.font_asset,
        )
        safe_font = font_path.replace("'", "\\'").replace(':', '\\:')
        part = (
            f"drawtext=text='{safe}'"
            f':fontfile={safe_font}'
            f':fontsize={overlay.font_size}'
            f':fontcolor={overlay.color}@{overlay.opacity}'
            f':x={overlay.x}:y={overlay.y}'
            f":enable='between(t,{overlay.start_sec},{overlay.end_sec})'"
        )
        out = self._next_tmp_path()
        cmd = [
            'ffmpeg', '-y', '-i', input_path, '-vf', part,
            *clip_filter_encode_args(
                crf=self.crf, preset=self.preset,
                fps=self.fps, audio_bitrate=self.audio_bitrate,
            ),
            out,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        if result.returncode != 0:
            raise RuntimeError(f'TimedOverlayStage text ffmpeg failed: {result.stderr}')
        return out

    def _apply_media_overlay(
        self,
        input_path: str,
        overlay: 'ClipTimedOverlay',
        media_bytes: bytes,
        *,
        is_video: bool,
    ) -> str:
        suffix = '.mp4' if is_video else '.png'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            media_path = tmp.name
        Path(media_path).write_bytes(media_bytes)

        width = overlay.width or 300
        overlay_input = ['-i', media_path] if is_video else ['-loop', '1', '-i', media_path]
        filter_complex = (
            f'[1:v]scale={width}:-1,format=rgba,'
            f'colorchannelmixer=aa={overlay.opacity}[ov];'
            f"[0:v][ov]overlay={overlay.x}:{overlay.y}"
            f":enable='between(t,{overlay.start_sec},{overlay.end_sec})'[vout]"
        )
        out = self._next_tmp_path()
        cmd = [
            'ffmpeg', '-y', '-i', input_path, *overlay_input,
            '-filter_complex', filter_complex,
            '-map', '[vout]', '-map', '0:a?',
            *clip_filter_encode_args(
                crf=self.crf, preset=self.preset,
                fps=self.fps, audio_bitrate=self.audio_bitrate,
            ),
            '-shortest',
            out,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        Path(media_path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f'TimedOverlayStage media ffmpeg failed: {result.stderr}')
        return out

    def _next_tmp_path(self) -> str:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            return tmp.name
```

Add `import tempfile` to the top of the file (needed for the new methods).

Note: the multi-overlay loop above chains ffmpeg calls one overlay at a
time (each producing a new temp file consumed by the next), matching the
existing codebase's general pattern of sequential single-purpose ffmpeg
calls rather than one giant filter graph — simpler to test and debug, at
the cost of an extra encode pass per overlay. For clips with many overlays
this is less efficient than a single filter_complex; acceptable for
short-form clips with a handful of overlays. Revisit only if profiling shows
it's a real bottleneck.

- [ ] **Step 4: Run test to verify it passes, plus regression-check existing tests**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.timed_overlays --cov-report=term-missing -k "timed_overlay or TimedOverlay"`
Expected: all PASS, including the pre-existing
`test_timed_overlay_stage_runs_with_overlays`/
`test_timed_overlay_returns_input_when_no_text`/
`test_timed_overlay_run_text_ffmpeg`/`test_timed_overlay_run_ffmpeg_failure`
tests — update any of those that mock `overlay.overlay_type`/`.font`/
`.font_asset`/`.image_asset`/`.video_asset`/`.width`/`.animation` attributes
that didn't exist on the `MagicMock()` before (MagicMock auto-creates
attributes so this should mostly just work, but assert the exact values the
rewritten code now reads).

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/timed_overlays.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "fix(clipping): render IMAGE timed overlays (was silently skipped)"
```

---

## Task 19: Overlay entrance/exit animation + hook animation

**Files:**
- Modify: `server/apps/rendering/clip_stages/timed_overlays.py`
- Modify: `server/apps/rendering/clip_stages/hook.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `overlay.animation`/`ClipStyleConfig.hook_animation` (Task 4/6).
- Produces: text overlays get `alpha`/`x`/`y` time-expressions for
  fade/slide; image/video overlays get chained `fade` filters; hook reuses
  the text technique.

- [ ] **Step 1: Write the failing tests**

```python
_ANIM_FADE_DURATION = 0.3


def test_animation_alpha_expr_fade() -> None:
    from server.apps.rendering.clip_stages.timed_overlays import (
        _animation_alpha_expr,
    )
    expr = _animation_alpha_expr('FADE', start=1.0, end=4.0)
    assert 'if(lt(t,1.3)' in expr
    assert 'if(lt(t,3.7)' in expr


def test_animation_alpha_expr_none_returns_one() -> None:
    from server.apps.rendering.clip_stages.timed_overlays import (
        _animation_alpha_expr,
    )
    assert _animation_alpha_expr('NONE', start=0.0, end=1.0) == '1'


@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_text_fade_animation(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    overlay = MagicMock()
    overlay.overlay_type = 'TEXT'
    overlay.text = 'Hi'
    overlay.font = 'MONTSERRAT_BOLD'
    overlay.font_asset = None
    overlay.font_size = 40
    overlay.color = '#FFFFFF'
    overlay.opacity = 1.0
    overlay.x = 0
    overlay.y = 100
    overlay.start_sec = 1.0
    overlay.end_sec = 4.0
    overlay.animation = 'FADE'
    stage = TimedOverlayStage(output_path=Path('/out.mp4'), timed_overlays=[overlay])
    with patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    assert 'alpha=' in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k "animation_alpha_expr or fade_animation"`
Expected: FAIL — `ImportError`/no `alpha=` in the drawtext string yet.

- [ ] **Step 3: Add the animation helper + wire into `_apply_text`/`_apply_media_overlay`**

Add to `timed_overlays.py`:

```python
def _animation_alpha_expr(animation: str, *, start: float, end: float) -> str:
    """Return a drawtext `alpha=` expression for the fade in/out window.

    POP is approximated as a fast fade for text (a true scale-bounce isn't
    expressible via drawtext's alpha option) — slide directions only affect
    position, handled separately in _animation_xy_expr.
    """
    if animation in {'NONE', 'SLIDE_LEFT', 'SLIDE_RIGHT', 'SLIDE_UP', 'SLIDE_DOWN'}:
        return '1'
    d = _ANIM_FADE_DURATION
    return (
        f'if(lt(t,{start + d}),(t-{start})/{d},'
        f'if(lt(t,{end - d}),1,({end}-t)/{d}))'
    )


def _animation_xy_expr(
    animation: str, *, base_x: int, base_y: int, start: float, end: float,
) -> tuple[str, str]:
    """Return (x_expr, y_expr) — slides the element in/out along one axis."""
    d = _ANIM_FADE_DURATION
    offset = 60  # px travel distance for the slide-in/out
    if animation == 'SLIDE_LEFT':
        x = (
            f'if(lt(t,{start + d}),{base_x}-{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_x},'
            f'{base_x}-{offset}*(1-({end}-t)/{d})))'
        )
        return x, str(base_y)
    if animation == 'SLIDE_RIGHT':
        x = (
            f'if(lt(t,{start + d}),{base_x}+{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_x},'
            f'{base_x}+{offset}*(1-({end}-t)/{d})))'
        )
        return x, str(base_y)
    if animation == 'SLIDE_UP':
        y = (
            f'if(lt(t,{start + d}),{base_y}-{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_y},'
            f'{base_y}-{offset}*(1-({end}-t)/{d})))'
        )
        return str(base_x), y
    if animation == 'SLIDE_DOWN':
        y = (
            f'if(lt(t,{start + d}),{base_y}+{offset}*(1-(t-{start})/{d}),'
            f'if(lt(t,{end - d}),{base_y},'
            f'{base_y}+{offset}*(1-({end}-t)/{d})))'
        )
        return str(base_x), y
    return str(base_x), str(base_y)
```

In `_apply_text`, replace the fixed `:x={overlay.x}:y={overlay.y}` segment:

```python
        alpha_expr = _animation_alpha_expr(
            overlay.animation, start=overlay.start_sec, end=overlay.end_sec,
        )
        x_expr, y_expr = _animation_xy_expr(
            overlay.animation,
            base_x=overlay.x, base_y=overlay.y,
            start=overlay.start_sec, end=overlay.end_sec,
        )
        part = (
            f"drawtext=text='{safe}'"
            f':fontfile={safe_font}'
            f':fontsize={overlay.font_size}'
            f":fontcolor={overlay.color}"
            f":alpha='{alpha_expr}'"
            f":x='{x_expr}':y='{y_expr}'"
            f":enable='between(t,{overlay.start_sec},{overlay.end_sec})'"
        )
```

(Note `fontcolor` no longer carries `@{opacity}` since `alpha=` now owns
transparency — keep `overlay.opacity` factored into `alpha_expr` for the
`NONE`/slide cases instead: change `_animation_alpha_expr`'s `'1'` returns
to return `str(opacity)` and thread `opacity` through as a parameter, and
multiply it into the fade expression's `1` terms too, so static opacity
still works when there's no animation.)

In `_apply_media_overlay`, add fade-in/out for non-`NONE` animations by
chaining `fade` filters before the `colorchannelmixer`:

```python
        fade_filters = ''
        if overlay.animation != 'NONE':
            d = _ANIM_FADE_DURATION
            fade_filters = (
                f',fade=t=in:st={overlay.start_sec}:d={d}:alpha=1'
                f',fade=t=out:st={overlay.end_sec - d}:d={d}:alpha=1'
            )
        filter_complex = (
            f'[1:v]scale={width}:-1,format=rgba,'
            f'colorchannelmixer=aa={overlay.opacity}{fade_filters}[ov];'
            f"[0:v][ov]overlay={overlay.x}:{overlay.y}"
            f":enable='between(t,{overlay.start_sec},{overlay.end_sec})'[vout]"
        )
```

- [ ] **Step 4: Wire `hook_animation` into `hook.py`**

In `HookStage._overlay()`, reuse the same
`_animation_alpha_expr`/`_animation_xy_expr` helpers (import from
`timed_overlays`) keyed on `sc.hook_animation`, `start=0`,
`end=sc.hook_duration_sec`, applied to the hook's `drawtext=` filter the
same way as `_apply_text` above.

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.timed_overlays --cov=server.apps.rendering.clip_stages.hook --cov-report=term-missing`
Expected: all PASS, 100% coverage on both modules.

- [ ] **Step 6: Commit**

```bash
git add server/apps/rendering/clip_stages/timed_overlays.py \
  server/apps/rendering/clip_stages/hook.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): add entrance/exit animation to overlays and hook"
```

---

## Task 20: Video/PIP overlays with shape masking

**Files:**
- Modify: `server/apps/rendering/clip_stages/timed_overlays.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `overlay.video_asset`/`.shape` (Task 6), `_apply_media_overlay`
  (Task 18).

- [ ] **Step 1: Write the failing test**

```python
@patch('server.apps.rendering.clip_stages.timed_overlays.subprocess.run')
def test_timed_overlay_video_circle_shape(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    video_asset = MagicMock()
    video_asset.file.read.return_value = b'fake_video_bytes'
    overlay = MagicMock()
    overlay.overlay_type = 'VIDEO'
    overlay.image_asset = None
    overlay.video_asset = video_asset
    overlay.shape = 'CIRCLE'
    overlay.width = 240
    overlay.opacity = 1.0
    overlay.x = 50
    overlay.y = 50
    overlay.start_sec = 0.0
    overlay.end_sec = 5.0
    overlay.animation = 'NONE'
    stage = TimedOverlayStage(output_path=Path('/out.mp4'), timed_overlays=[overlay])
    with (
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.timed_overlays.Path.unlink'),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'geq=' in fc  # circular alpha mask
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k video_circle_shape`
Expected: FAIL — no shape masking exists yet.

- [ ] **Step 3: Add shape masking to `_apply_media_overlay`**

```python
def _shape_mask_filter(shape: str, width: int) -> str:
    """Return a geq alpha-mask filter for CIRCLE/ROUNDED, or '' for RECTANGLE."""
    if shape == 'CIRCLE':
        r = width // 2
        return (
            f',format=rgba,geq='
            f"r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='if(lte(pow(X-{r}\\,2)+pow(Y-{r}\\,2)\\,pow({r}\\,2))\\,255\\,0)'"
        )
    if shape == 'ROUNDED':
        return ',format=rgba'  # rounded-rect mask refined in a later pass
    return ''
```

Update `_apply_media_overlay` to apply the mask after scaling:

```python
        mask_filter = _shape_mask_filter(overlay.shape, width) if is_video else ''
        filter_complex = (
            f'[1:v]scale={width}:-1{mask_filter},format=rgba,'
            f'colorchannelmixer=aa={overlay.opacity}{fade_filters}[ov];'
            ...
        )
```

(Only apply `_shape_mask_filter` for `is_video=True` at this step — image
overlay shape-masking is the same function, reusable, but keep this task
scoped to the reported VIDEO/PIP use case per the spec; wire it for images
too here if trivial, since the helper is shape-agnostic.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.timed_overlays --cov-report=term-missing`
Expected: PASS, 100% coverage (add a `RECTANGLE`-shape test asserting no
`geq=` appears, and a `ROUNDED` test, to cover all three branches of
`_shape_mask_filter`).

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/timed_overlays.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): add video/PIP overlays with circle/rounded shape masking"
```

---

## Task 21: Wire `caption_animation` into `ASSGenerator` (fix third no-op bug)

**Files:**
- Modify: `server/apps/rendering/clip_stages/captions.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `style_config.caption_animation` (already existed on the model —
  this task only fixes the ASS generator ignoring it).

- [ ] **Step 1: Write the failing test**

```python
def test_ass_generator_fade_animation_adds_fad_tag() -> None:
    sc = _sc()
    sc.caption_animation = 'FADE'
    transcript = {
        'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Hello'}],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert '\\fad(' in result


def test_ass_generator_pop_animation_adds_transform_tag() -> None:
    sc = _sc()
    sc.caption_animation = 'POP'
    transcript = {
        'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Hello'}],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert '\\t(' in result


def test_ass_generator_none_animation_adds_no_tag() -> None:
    sc = _sc()
    sc.caption_animation = 'NONE'
    transcript = {
        'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Hello'}],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert '\\fad(' not in result
    assert '\\t(' not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k "fade_animation_adds or pop_animation_adds or none_animation_adds"`
Expected: FAIL — `ASSGenerator` currently never reads `caption_animation` at
all, so no tag ever appears regardless of setting.

- [ ] **Step 3: Update `ASSGenerator._dialogue()`**

```python
    def _animation_tag(self) -> str:
        sc = self.style_config
        animation = sc.caption_animation if sc else 'NONE'
        if animation == 'FADE':
            return '{\\fad(200,200)}'
        if animation == 'POP':
            return '{\\t(0,150,\\fscx120\\fscy120)\\t(150,250,\\fscx100\\fscy100)}'
        return ''

    def _dialogue(self, start: float, end: float, text: str) -> str:
        tag = self._animation_tag()
        return (
            f'Dialogue: 0,{self._ass_time(start)},{self._ass_time(end)},'
            f'Default,,0,0,0,,{tag}{text}'
        )
```

- [ ] **Step 4: Run test to verify it passes, no regressions**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.captions --cov-report=term-missing`
Expected: all PASS including every pre-existing `ASSGenerator` test (they
assert `'Dialogue:' in result` or specific text substrings, which still hold
since the animation tag is a prefix, not a replacement).

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/captions.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "fix(clipping): wire caption_animation into ASS output (was silent no-op)"
```

---

## Task 22: Karaoke-highlight caption style + uppercase toggle

**Files:**
- Modify: `server/apps/rendering/clip_stages/captions.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `CaptionStyle.KARAOKE_HIGHLIGHT` (Task 3),
  `caption_highlight_color`/`caption_uppercase` (Task 4).
- Produces: `ASSGenerator._karaoke_highlight()` — one overlapping Dialogue
  line per word-time-window, full segment text with the active word
  recolored via an inline `\c` override tag.

- [ ] **Step 1: Write the failing test**

```python
def test_ass_generator_karaoke_highlight_produces_overlapping_dialogues() -> None:
    sc = _sc()
    sc.caption_style = 'KARAOKE_HIGHLIGHT'
    sc.caption_highlight_color = '#FFD400'
    transcript = {
        'segments': [
            {
                'start': 0.0, 'end': 2.0, 'text': 'Hello world',
                'words': [
                    {'word': 'Hello', 'start': 0.0, 'end': 1.0},
                    {'word': 'world', 'start': 1.0, 'end': 2.0},
                ],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert result.count('Dialogue:') == 2  # one per word window
    assert 'Hello' in result
    assert 'world' in result
    assert '\\c&H' in result  # inline color override for the highlighted word


def test_caption_uppercase_transforms_chunked_text() -> None:
    sc = _sc()
    sc.caption_uppercase = True
    transcript = {
        'segments': [
            {
                'start': 0.0, 'end': 1.0, 'text': 'hello',
                'words': [{'word': 'hello', 'start': 0.0, 'end': 1.0}],
            },
        ],
    }
    gen = ASSGenerator(transcript_json=transcript, style_config=sc)
    result = gen.generate()
    assert 'HELLO' in result
    assert 'hello' not in result.replace('HELLO', '')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k "karaoke_highlight or caption_uppercase"`
Expected: FAIL — `KARAOKE_HIGHLIGHT` isn't dispatched in `generate()`, and
uppercase is never applied.

- [ ] **Step 3: Implement**

In `ASSGenerator.generate()`, add the dispatch branch (alongside the
existing `WORD_BY_WORD`/`LOWER_THIRD`/`EMOJI_ACCENT`/`CHUNKED` branches):

```python
        elif style == CaptionStyle.KARAOKE_HIGHLIGHT:
            dialogues = self._karaoke_highlight(segments)
```

Add the method:

```python
    def _karaoke_highlight(self, segments: list[dict[str, Any]]) -> list[str]:
        sc = self.style_config
        highlight = self._ass_color(
            sc.caption_highlight_color if sc else '#FFD400',
        )
        lines = []
        for seg in segments:
            words = seg.get('words', [])
            if not words:
                continue
            full_text = ' '.join(
                w.get('word', '').strip() for w in words if w.get('word', '').strip()
            )
            if not full_text:
                continue
            for i, word in enumerate(words):
                w_start = float(word.get('start', 0))
                w_end = float(word.get('end', w_start + 0.3))
                parts = []
                for j, other in enumerate(words):
                    token = other.get('word', '').strip()
                    if not token:
                        continue
                    if j == i:
                        parts.append(f'{{\\c{highlight}}}{token}{{\\c&HFFFFFF&}}')
                    else:
                        parts.append(token)
                lines.append(self._dialogue(w_start, w_end, ' '.join(parts)))
        return lines
```

Apply uppercase in `generate()`, right before the header/dialogues are
joined — the simplest correct place is inside each style method right
before appending, but since every style path funnels through
`self._dialogue(start, end, text)` or a text-producing helper, apply it once
centrally. Change `_dialogue`'s signature call sites — simplest: uppercase
at the top of `generate()` by transforming `segments` in place before
dispatch:

```python
    def generate(self) -> str:
        sc = self.style_config
        style = sc.caption_style if sc else CaptionStyle.CHUNKED
        segments = self.transcript_json.get('segments', [])
        if sc and sc.caption_uppercase:
            segments = _uppercase_segments(segments)
        ...
```

Add the module-level helper:

```python
def _uppercase_segments(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for seg in segments:
        new_seg = dict(seg)
        if 'text' in new_seg:
            new_seg['text'] = new_seg['text'].upper()
        if 'words' in new_seg:
            new_seg['words'] = [
                {**w, 'word': w.get('word', '').upper()} for w in new_seg['words']
            ]
        result.append(new_seg)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.captions --cov-report=term-missing`
Expected: all PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/captions.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): add karaoke-highlight caption style + uppercase toggle"
```

---

## Task 23: Watermark `CENTER`/`TILED` positions

**Files:**
- Modify: `server/apps/rendering/clip_stages/watermark.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `WatermarkPosition.CENTER`/`TILED` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
def test_watermark_position_center_coords() -> None:
    sc = _sc(watermark_enabled=True)
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    x, y = stage._position_coords('CENTER')
    assert x == '(w-w)/2'
    assert y == '(h-h)/2'


@patch('server.apps.rendering.clip_stages.watermark.subprocess.run')
def test_watermark_tiled_position_emits_grid(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(watermark_enabled=True)
    sc.watermark_position = 'TILED'
    sc.watermark_size = 100
    stage = WatermarkStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.watermark.Path.mkdir'):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    # more than one drawtext instance for a tiled grid
    assert joined.count('drawtext=') > 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k "position_center_coords or tiled_position"`
Expected: FAIL — `_position_coords` has no `CENTER` entry (falls through to
the `BOTTOM_RIGHT` default), and there's no tiling logic at all.

- [ ] **Step 3: Implement**

Update `_position_coords`:

```python
    def _position_coords(self, position: str) -> tuple[str, str]:
        """Convert position name to x:y ffmpeg expressions."""
        positions: dict[str, tuple[str, str]] = {
            'TOP_LEFT': ('20', '20'),
            'TOP_RIGHT': ('w-w-20', '20'),
            'BOTTOM_LEFT': ('20', 'h-h-20'),
            'BOTTOM_RIGHT': ('w-w-20', 'h-h-20'),
            'CENTER': ('(w-w)/2', '(h-h)/2'),
        }
        return positions.get(position, ('w-w-20', 'h-h-20'))
```

Add a tiled-grid branch to `_text_watermark` (mirror for
`_image_watermark` — the plan shows text; apply the same grid-of-instances
idea to the image path too, using chained `overlay=` calls instead of
chained `drawtext=`):

```python
    def _tiled_positions(
        self, watermark_size: int, cols: int = 3, rows: int = 5,
    ) -> list[tuple[int, int]]:
        spacing_x = 1080 // cols
        spacing_y = 1920 // rows
        return [
            (c * spacing_x + spacing_x // 4, r * spacing_y + spacing_y // 4)
            for r in range(rows)
            for c in range(cols)
        ]

    def _text_watermark(self, input_path: Path, sc: 'ClipStyleConfig') -> Path:
        safe_text = sc.watermark_text.replace("'", "\\'").replace(':', '\\:')
        font_path, _family = resolve_drawtext_font(
            sc.watermark_font, sc.watermark_font_asset,
        )
        safe_font = font_path.replace("'", "\\'").replace(':', '\\:')
        color = sc.watermark_color

        if sc.watermark_position == 'TILED':
            positions = self._tiled_positions(sc.watermark_size)
            parts = [
                (
                    f"drawtext=text='{safe_text}'"
                    f':fontfile={safe_font}'
                    f':fontsize={sc.watermark_size}'
                    f':fontcolor={color}@{sc.watermark_opacity}'
                    f':x={x}:y={y}'
                )
                for x, y in positions
            ]
            drawtext = ','.join(parts)
        else:
            x, y = self._position_coords(sc.watermark_position)
            drawtext = (
                f"drawtext=text='{safe_text}'"
                f':fontfile={safe_font}'
                f':fontsize={sc.watermark_size}'
                f':fontcolor={color}@{sc.watermark_opacity}'
                f':x={x}:y={y}'
            )
        # ... existing cmd construction, unchanged
```

Add `from server.apps.rendering.clip_stages.fonts import
resolve_drawtext_font` to the imports if Task 15 didn't already add it here
(it should have — this task only adds the `TILED`/`CENTER` branch on top).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.watermark --cov-report=term-missing`
Expected: PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/watermark.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): add CENTER and TILED watermark positions"
```

---

## Task 24: `ColorGradeStage` (presets, manual adjustments, LUT)

**Files:**
- Create: `server/apps/rendering/clip_stages/color_grade.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_color_grade.py`

**Interfaces:**
- Consumes: `ColorFilterPreset` (Task 3), `brightness`/`contrast`/
  `saturation`/`lut_asset` (Task 4).
- Produces: `ColorGradeStage(RenderStage)` — order between `trim_and_crop`
  (1) and `intro_concat` (2), i.e. `order = 2`, with every later stage's
  `order` shifting by one (finalized in Task 28's pipeline rewrite — this
  task builds the stage in isolation with a placeholder `order`, Task 28
  fixes the final numbering across the whole file at once so there's only
  one place where every stage's number is decided).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_apps/test_rendering/test_clip_stages/test_color_grade.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.apps.rendering.clip_stages.color_grade import ColorGradeStage


def _sc(color_filter: str = 'NONE', brightness: float = 0.0,
        contrast: float = 0.0, saturation: float = 0.0, lut_asset=None) -> MagicMock:
    sc = MagicMock()
    sc.color_filter = color_filter
    sc.brightness = brightness
    sc.contrast = contrast
    sc.saturation = saturation
    sc.lut_asset = lut_asset
    return sc


def test_should_run_false_when_all_defaults() -> None:
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=_sc())
    assert stage.should_run() is False


def test_should_run_true_when_preset_set() -> None:
    stage = ColorGradeStage(
        output_path=Path('/out.mp4'), style_config=_sc(color_filter='VIVID'),
    )
    assert stage.should_run() is True


def test_should_run_true_when_manual_adjustment_set() -> None:
    stage = ColorGradeStage(
        output_path=Path('/out.mp4'), style_config=_sc(brightness=0.1),
    )
    assert stage.should_run() is True


@patch('server.apps.rendering.clip_stages.color_grade.subprocess.run')
def test_preset_eq_filter_applied(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    sc = _sc(color_filter='VIVID', brightness=0.1, contrast=0.05)
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.color_grade.Path.mkdir'):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-vf') + 1]
    assert 'eq=' in fc


@patch('server.apps.rendering.clip_stages.color_grade.subprocess.run')
def test_lut_asset_takes_precedence(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    lut_asset = MagicMock()
    lut_asset.file.read.return_value = b'fake cube data'
    sc = _sc(color_filter='VIVID', lut_asset=lut_asset)
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=sc)
    with (
        patch('server.apps.rendering.clip_stages.color_grade.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.color_grade.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.color_grade.Path.unlink'),
    ):
        stage.run(Path('/in.mp4'))
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index('-vf') + 1]
    assert 'lut3d=' in fc
    assert 'eq=' not in fc


@patch('server.apps.rendering.clip_stages.color_grade.subprocess.run')
def test_color_grade_ffmpeg_failure(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stderr='bad filter')
    sc = _sc(color_filter='MOODY')
    stage = ColorGradeStage(output_path=Path('/out.mp4'), style_config=sc)
    with patch('server.apps.rendering.clip_stages.color_grade.Path.mkdir'):
        with pytest.raises(RuntimeError, match='ColorGradeStage'):
            stage.run(Path('/in.mp4'))
```

Add `import pytest` at the top of the test file (needed for the last test).

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_color_grade.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# server/apps/rendering/clip_stages/color_grade.py
"""ColorGradeStage — preset filters, manual adjustments, and custom LUTs."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.encode import clip_filter_encode_args

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')

# preset -> (brightness_delta, contrast_delta, saturation_delta)
_PRESET_EQ: dict[str, tuple[float, float, float]] = {
    'NONE': (0.0, 1.0, 1.0),
    'VIVID': (0.02, 1.15, 1.4),
    'MOODY': (-0.05, 1.1, 0.8),
    'WARM': (0.03, 1.05, 1.1),
    'COOL': (-0.02, 1.05, 0.95),
    'BLACK_WHITE': (0.0, 1.1, 0.0),
    'VINTAGE': (-0.03, 0.9, 0.7),
}


@final
@dataclass
class ColorGradeStage(RenderStage):
    """Apply a color-filter preset, manual adjustments, and/or a custom LUT."""

    output_path: Path
    style_config: ClipStyleConfig | None
    crf: int = 18
    preset: str = 'slow'
    fps: int = 30
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        return 'color_grade'

    @property
    @override
    def order(self) -> int:
        return 2

    @override
    def should_run(self) -> bool:
        sc = self.style_config
        if sc is None:
            return False
        return bool(
            sc.color_filter != 'NONE'
            or sc.brightness != 0.0
            or sc.contrast != 0.0
            or sc.saturation != 0.0
            or sc.lut_asset is not None,
        )

    @override
    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        assert sc is not None  # noqa: S101
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if sc.lut_asset is not None:
            vf, cleanup = self._lut_filter(sc)
        else:
            vf, cleanup = self._eq_filter(sc), None

        cmd = [
            'ffmpeg', '-y', '-i', str(input_path),
            '-vf', vf,
            *clip_filter_encode_args(
                crf=self.crf, preset=self.preset,
                fps=self.fps, audio_bitrate=self.audio_bitrate,
            ),
            str(self.output_path),
        ]
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, check=False,
        )
        if cleanup:
            Path(cleanup).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f'ColorGradeStage ffmpeg failed: {result.stderr}')
        return self.output_path

    def _eq_filter(self, sc: ClipStyleConfig) -> str:
        base_b, base_c, base_s = _PRESET_EQ.get(sc.color_filter, (0.0, 1.0, 1.0))
        brightness = base_b + sc.brightness
        contrast = base_c + sc.contrast
        saturation = max(0.0, base_s + sc.saturation)
        return f'eq=brightness={brightness:.3f}:contrast={contrast:.3f}:saturation={saturation:.3f}'

    def _lut_filter(self, sc: ClipStyleConfig) -> tuple[str, str]:
        lut_bytes: bytes = sc.lut_asset.file.read()
        with tempfile.NamedTemporaryFile(suffix='.cube', delete=False) as tmp:
            lut_path = tmp.name
        Path(lut_path).write_bytes(lut_bytes)
        safe_path = lut_path.replace("'", "\\'").replace(':', '\\:')
        return f"lut3d='{safe_path}'", lut_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_color_grade.py -v --cov=server.apps.rendering.clip_stages.color_grade --cov-report=term-missing`
Expected: all PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/color_grade.py \
  tests/test_apps/test_rendering/test_clip_stages/test_color_grade.py
git commit -m "feat(clipping): add ColorGradeStage (presets, manual adjustments, LUT)"
```

---

## Task 25: Speed ramp + transcript timestamp scaling

**Files:**
- Modify: `server/apps/rendering/clip_stages/trim_crop.py`
- Modify: `server/apps/rendering/clip_render_pipeline.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py`
- Test: `tests/test_apps/test_rendering/test_clip_render_pipeline.py`

**Interfaces:**
- Consumes: `style_config.playback_speed` (Task 4).
- Produces: `TrimAndCropStage` applies `setpts`/chained `atempo`;
  `ClipRenderPipeline` scales `transcript_json` timestamps by
  `1 / playback_speed` before building caption/hook stages — **this is the
  critical correctness item flagged in the spec**: skipping this silently
  desyncs captions the moment speed ≠ 1.0.

- [ ] **Step 1: Write the failing tests**

```python
# add to test_trim_crop.py

def test_center_crop_cmd_includes_speed_filters_when_not_default() -> None:
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'), start_sec=0.0, end_sec=10.0,
        output_path=Path('/out.mp4'), layout_config=None, playback_speed=2.0,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    vf = cmd[cmd.index('-vf') + 1]
    af_index = cmd.index('-af') if '-af' in cmd else None
    assert 'setpts=0.5*PTS' in vf
    assert af_index is not None
    assert 'atempo=2.0' in cmd[af_index + 1]


def test_center_crop_cmd_skips_speed_filters_at_default() -> None:
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'), start_sec=0.0, end_sec=10.0,
        output_path=Path('/out.mp4'), layout_config=None, playback_speed=1.0,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    assert '-af' not in cmd


def test_extreme_speed_chains_multiple_atempo() -> None:
    """atempo maxes at 2.0x per instance — 3x speed needs 2 chained calls."""
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'), start_sec=0.0, end_sec=10.0,
        output_path=Path('/out.mp4'), layout_config=None, playback_speed=3.0,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    af_index = cmd.index('-af')
    assert cmd[af_index + 1].count('atempo=') == 2
```

```python
# add to test_clip_render_pipeline.py (or create if it doesn't exist —
# check `find tests/test_apps/test_rendering -iname "*render_pipeline*"`)

def test_scale_transcript_scales_word_and_segment_timestamps() -> None:
    from server.apps.rendering.clip_render_pipeline import _scale_transcript

    transcript = {
        'segments': [
            {
                'start': 2.0, 'end': 4.0, 'text': 'hi',
                'words': [{'word': 'hi', 'start': 2.0, 'end': 4.0}],
            },
        ],
    }
    scaled = _scale_transcript(transcript, playback_speed=2.0)
    seg = scaled['segments'][0]
    assert seg['start'] == 1.0
    assert seg['end'] == 2.0
    assert seg['words'][0]['start'] == 1.0
    assert seg['words'][0]['end'] == 2.0


def test_scale_transcript_noop_at_default_speed() -> None:
    from server.apps.rendering.clip_render_pipeline import _scale_transcript

    transcript = {'segments': [{'start': 2.0, 'end': 4.0, 'text': 'hi'}]}
    assert _scale_transcript(transcript, playback_speed=1.0) == transcript
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py tests/test_apps/test_rendering/test_clip_render_pipeline.py -v --no-cov -k "speed or atempo or scale_transcript"`
Expected: FAIL — no `playback_speed` param, no `_scale_transcript` function.

- [ ] **Step 3: Update `TrimAndCropStage`**

Add `playback_speed: float = 1.0` field to the dataclass (after
`audio_bitrate`). Add a helper and thread it into all three `_*_cmd` methods
(`_center_crop_cmd`/`_smart_crop_cmd`/`_spatial_stack_cmd`):

```python
    def _speed_filters(self) -> tuple[str, str]:
        """Return (video_vf_suffix, audio_af) for playback_speed, or ('', '')."""
        if self.playback_speed == 1.0:
            return '', ''
        video = f',setpts={1 / self.playback_speed:.6f}*PTS'
        remaining = self.playback_speed
        atempo_parts = []
        while remaining > 2.0:
            atempo_parts.append('atempo=2.0')
            remaining /= 2.0
        while remaining < 0.5:
            atempo_parts.append('atempo=0.5')
            remaining /= 0.5
        atempo_parts.append(f'atempo={remaining:.4f}')
        return video, ','.join(atempo_parts)
```

In `_center_crop_cmd`, change the `-vf` value construction:

```python
    def _center_crop_cmd(self, input_path: Path) -> list[str]:
        video_suffix, audio_af = self._speed_filters()
        cmd = [
            'ffmpeg', '-y', '-i', str(input_path),
            '-ss', str(self.start_sec), '-to', str(self.end_sec),
            '-vf', (
                f'crop=ih*9/16:ih,scale={self.width}:{self.height},'
                f'fps={self.fps}{video_suffix}'
            ),
        ]
        if audio_af:
            cmd += ['-af', audio_af]
        cmd += [
            '-c:v', 'libx264', '-crf', str(self.crf), '-preset', self.preset,
            '-c:a', 'aac', '-b:a', self.audio_bitrate,
            '-movflags', 'faststart', str(self.output_path),
        ]
        return cmd
```

Apply the same `video_suffix`/`audio_af` insertion to `_smart_crop_cmd`'s
`-vf` value and `_spatial_stack_cmd`'s `filter_complex` (append
`video_suffix` to the `[out]`-producing chain and add `-af` similarly, or —
simpler for the spatial-stack case, since it already builds a
`filter_complex` — append the `setpts` term directly onto the final
`vstack=inputs=2[out]` output by inserting a `,setpts=...` after it and
adding `-af` alongside the existing `-map 0:a`).

- [ ] **Step 4: Update `ClipRenderPipeline` to scale the transcript**

Add to `clip_render_pipeline.py`, module level:

```python
def _scale_transcript(
    transcript_json: dict[str, Any], *, playback_speed: float,
) -> dict[str, Any]:
    """Scale caption/hook timestamps to match a sped-up/slowed-down clip.

    Whisper timestamps are for the original-speed audio — if the video is
    played back at `playback_speed`, every timestamp must shrink/grow by
    the same factor or captions drift out of sync.
    """
    if playback_speed == 1.0:
        return transcript_json
    factor = 1.0 / playback_speed
    scaled_segments = []
    for seg in transcript_json.get('segments', []):
        new_seg = dict(seg)
        new_seg['start'] = seg['start'] * factor
        new_seg['end'] = seg['end'] * factor
        if 'words' in seg:
            new_seg['words'] = [
                {**w, 'start': w['start'] * factor, 'end': w['end'] * factor}
                for w in seg['words']
            ]
        scaled_segments.append(new_seg)
    return {**transcript_json, 'segments': scaled_segments}
```

In `_build_stages()`, before constructing `TrimAndCropStage`, add:

```python
        c = self.config
        transcript_json = _scale_transcript(
            c.transcript_json,
            playback_speed=(
                c.style_config.playback_speed if c.style_config else 1.0
            ),
        )
```

Use `transcript_json` (the scaled one) instead of `c.transcript_json` when
constructing `CaptionTranslationStage`/`CaptionStage`. Pass
`playback_speed=c.style_config.playback_speed if c.style_config else 1.0` to
`TrimAndCropStage`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py tests/test_apps/test_rendering/test_clip_render_pipeline.py -v --cov=server.apps.rendering.clip_stages.trim_crop --cov=server.apps.rendering.clip_render_pipeline --cov-report=term-missing`
Expected: all PASS, 100% coverage.

- [ ] **Step 6: Commit**

```bash
git add server/apps/rendering/clip_stages/trim_crop.py \
  server/apps/rendering/clip_render_pipeline.py \
  tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py \
  tests/test_apps/test_rendering/test_clip_render_pipeline.py
git commit -m "feat(clipping): add playback_speed with transcript timestamp scaling"
```

---

## Task 26: `fit_mode` blurred-background fill

**Files:**
- Modify: `server/apps/rendering/clip_stages/trim_crop.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py`

**Interfaces:**
- Consumes: `ClipLayoutConfig.fit_mode` (Task 5).

- [ ] **Step 1: Write the failing test**

```python
def test_center_crop_blur_fill_mode() -> None:
    layout = MagicMock()
    layout.render_mode = 'CENTER_CROP'
    layout.fit_mode = 'BLUR_FILL'
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'), start_sec=0.0, end_sec=10.0,
        output_path=Path('/out.mp4'), layout_config=layout,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    vf = cmd[cmd.index('-vf') + 1] if '-vf' in cmd else cmd[cmd.index('-filter_complex') + 1]
    assert 'boxblur' in vf
    assert 'overlay' in vf


def test_center_crop_default_fit_mode_unchanged() -> None:
    layout = MagicMock()
    layout.render_mode = 'CENTER_CROP'
    layout.fit_mode = 'CROP'
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'), start_sec=0.0, end_sec=10.0,
        output_path=Path('/out.mp4'), layout_config=layout,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    vf = cmd[cmd.index('-vf') + 1]
    assert 'boxblur' not in vf
    assert vf == 'crop=ih*9/16:ih,scale=1080:1920,fps=30'
```

Add `from unittest.mock import MagicMock` to the test file's imports if not
already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py -v --no-cov -k "blur_fill or default_fit_mode"`
Expected: FAIL — `fit_mode` isn't read anywhere yet.

- [ ] **Step 3: Implement**

`_center_crop_cmd` is the natural home for `BLUR_FILL` (it's the mismatched-
aspect-ratio path; `SMART_CROP`/`SPATIAL_STACK` already choose their own
framing deliberately and don't need a blur-fill fallback). Branch at the top
of `_center_crop_cmd`:

```python
    def _center_crop_cmd(self, input_path: Path) -> list[str]:
        lc = self.layout_config
        fit_mode = lc.fit_mode if lc else 'CROP'
        video_suffix, audio_af = self._speed_filters()
        if fit_mode == 'BLUR_FILL':
            vf = (
                f'split=2[bg][fg];'
                f'[bg]scale={self.width}:{self.height}:force_original_aspect_ratio=increase,'
                f'crop={self.width}:{self.height},boxblur=20:5[bgblur];'
                f'[fg]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease[fgfit];'
                f'[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2,fps={self.fps}{video_suffix}'
            )
        else:
            vf = f'crop=ih*9/16:ih,scale={self.width}:{self.height},fps={self.fps}{video_suffix}'
        cmd = [
            'ffmpeg', '-y', '-i', str(input_path),
            '-ss', str(self.start_sec), '-to', str(self.end_sec),
            '-vf', vf,
        ]
        if audio_af:
            cmd += ['-af', audio_af]
        cmd += [
            '-c:v', 'libx264', '-crf', str(self.crf), '-preset', self.preset,
            '-c:a', 'aac', '-b:a', self.audio_bitrate,
            '-movflags', 'faststart', str(self.output_path),
        ]
        return cmd
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py -v --cov=server.apps.rendering.clip_stages.trim_crop --cov-report=term-missing`
Expected: all PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/trim_crop.py \
  tests/test_apps/test_rendering/test_clip_stages/test_trim_crop.py
git commit -m "feat(clipping): add BLUR_FILL fit mode for mismatched aspect ratios"
```

---

## Task 27: Generalize `MusicMixStage` to mix `ClipTimedSfx`

**Files:**
- Modify: `server/apps/rendering/clip_stages/music_mix.py`
- Test: `tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py`

**Interfaces:**
- Consumes: `ClipTimedSfx` (Task 7).
- Produces: `MusicMixStage` gains a `timed_sfx: list[ClipTimedSfx]` field;
  `should_run()` becomes true if music OR any SFX is present; `run()` mixes
  N+1 audio inputs (background music + each SFX one-shot) via `amix`.

- [ ] **Step 1: Write the failing test**

```python
def test_music_mix_stage_runs_with_sfx_only_no_music() -> None:
    sfx = MagicMock()
    sfx.sfx_asset.file.read.return_value = b'fake_sfx'
    sfx.start_sec = 3.0
    sfx.volume_db = 0.0
    sc = _sc(music_enabled=False)
    stage = MusicMixStage(
        output_path=Path('/out.mp4'), style_config=sc,
        video_duration_sec=30.0, timed_sfx=[sfx],
    )
    assert stage.should_run() is True


@patch('server.apps.rendering.clip_stages.music_mix.subprocess.run')
def test_music_mix_stage_mixes_music_and_sfx(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    music_asset = MagicMock()
    music_asset.file.read.return_value = b'fake_music'
    sfx = MagicMock()
    sfx.sfx_asset.file.read.return_value = b'fake_sfx'
    sfx.start_sec = 3.0
    sfx.volume_db = -3.0
    sc = _sc(music_enabled=True)
    sc.music_asset = music_asset
    sc.music_volume_db = -10.0
    sc.music_fade_in_sec = 0.5
    sc.music_fade_out_sec = 0.5
    stage = MusicMixStage(
        output_path=Path('/out.mp4'), style_config=sc,
        video_duration_sec=30.0, timed_sfx=[sfx],
    )
    with (
        patch('server.apps.rendering.clip_stages.music_mix.Path.mkdir'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.write_bytes'),
        patch('server.apps.rendering.clip_stages.music_mix.Path.unlink'),
    ):
        result = stage.run(Path('/in.mp4'))
    assert result == Path('/out.mp4')
    cmd = mock_run.call_args[0][0]
    joined = ' '.join(cmd)
    assert 'amix=inputs=3' in joined  # base audio + music + 1 sfx
    assert 'adelay=3000' in joined  # sfx starts at 3.0s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --no-cov -k "sfx_only or mixes_music_and_sfx"`
Expected: FAIL — no `timed_sfx` field exists, `should_run`/`run` don't
handle it.

- [ ] **Step 3: Rewrite `MusicMixStage`**

Add `timed_sfx: list[ClipTimedSfx] = field(default_factory=list)` to the
dataclass (add `from dataclasses import field` to imports if not already
imported — check first). Update `should_run`:

```python
    @override
    def should_run(self) -> bool:
        music_active = (
            self.style_config is not None
            and self.style_config.music_enabled
            and self.style_config.music_asset is not None
        )
        return music_active or len(self.timed_sfx) > 0
```

Rewrite `run()` to build a variable-length `filter_complex` instead of the
fixed two-input one:

```python
    @override
    def run(self, input_path: Path) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        sc = self.style_config
        dur = self.video_duration_sec

        inputs = ['-i', str(input_path)]
        audio_labels = []
        tmp_paths = []

        if sc is not None and sc.music_enabled and sc.music_asset is not None:
            music_bytes: bytes = sc.music_asset.file.read()
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                music_path = tmp.name
            Path(music_path).write_bytes(music_bytes)
            tmp_paths.append(music_path)
            idx = len(tmp_paths)
            inputs += ['-i', music_path]
            gain = 10 ** (sc.music_volume_db / 20.0)
            fi, fo = sc.music_fade_in_sec, sc.music_fade_out_sec
            filt = (
                f'[{idx}:a]volume={gain:.4f},'
                f'afade=t=in:st=0:d={fi},'
                f'afade=t=out:st={max(0.0, dur - fo):.3f}:d={fo},'
                f'apad,atrim=duration={dur:.3f}[m{idx}]'
            )
            audio_labels.append((filt, f'[m{idx}]'))

        for sfx in self.timed_sfx:
            sfx_bytes: bytes = sfx.sfx_asset.file.read()
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                sfx_path = tmp.name
            Path(sfx_path).write_bytes(sfx_bytes)
            tmp_paths.append(sfx_path)
            idx = len(tmp_paths)
            inputs += ['-i', sfx_path]
            gain = 10 ** (sfx.volume_db / 20.0)
            delay_ms = int(sfx.start_sec * 1000)
            filt = (
                f'[{idx}:a]volume={gain:.4f},'
                f'adelay={delay_ms}|{delay_ms}[s{idx}]'
            )
            audio_labels.append((filt, f'[s{idx}]'))

        filter_parts = [filt for filt, _ in audio_labels]
        refs = ''.join(label for _, label in audio_labels)
        n = 1 + len(audio_labels)
        filter_parts.append(
            f'[0:a]{refs}amix=inputs={n}:duration=first[aout]',
        )
        filter_complex = ';'.join(filter_parts)

        cmd = [
            'ffmpeg', '-y', *inputs,
            '-filter_complex', filter_complex,
            '-map', '0:v', '-map', '[aout]',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
            str(self.output_path),
        ]
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, check=False,
        )
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f'MusicMixStage ffmpeg failed: {result.stderr}')
        return self.output_path
```

Add `TYPE_CHECKING` import for `ClipTimedSfx` alongside the existing
`ClipStyleConfig` import.

- [ ] **Step 4: Run tests to verify they pass, no regressions**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py -v --cov=server.apps.rendering.clip_stages.music_mix --cov-report=term-missing`
Expected: all PASS including the pre-existing music-only tests (the
music-only `filter_complex` shape changes slightly — `amix=inputs=2` instead
of a name like `[m1]` — update those tests' assertions if they checked for
an exact string that no longer matches; the *behavior* — mixing base audio
with a faded/trimmed music track — is unchanged).

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_stages/music_mix.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): generalize MusicMixStage to mix ClipTimedSfx one-shots"
```

---

## Task 28: Final pipeline wiring — `PipelineRenderConfig` + `_build_stages()`

**Files:**
- Modify: `server/apps/rendering/clip_render_pipeline.py`
- Modify: `server/apps/clips/preview_render.py` (whatever calls
  `ClipRenderPipeline`/`PipelineRenderConfig` — find every call site with
  `grep -rn "PipelineRenderConfig(" server/` first and update all of them)
- Test: `tests/test_apps/test_rendering/test_clip_render_pipeline.py`

**Interfaces:**
- Consumes: every stage from Tasks 15-27.
- Produces: the final stage order (11 stages, per spec §13):
  `trim_and_crop` (1) → `color_grade` (2) → `intro_concat` (3) → `hook` (4)
  → `caption_translation` (5) → `captions` (6) → `watermark` (7) →
  `timed_overlays` (8) → `progress_bar` (9) → `outro_concat` (10) →
  `music_and_sfx_mix` (11). `PipelineRenderConfig` gains `timed_sfx:
  list[ClipTimedSfx] = field(default_factory=list)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_rendering/test_clip_render_pipeline.py — add/extend
from server.apps.rendering.clip_render_pipeline import (
    ClipRenderPipeline,
    PipelineRenderConfig,
)


def test_build_stages_produces_eleven_stages_in_order(tmp_path) -> None:
    config = PipelineRenderConfig(
        source_path=tmp_path / 'src.mp4',
        output_path=tmp_path / 'out.mp4',
        start_sec=0.0, end_sec=10.0, hook_text='',
        transcript_json={'segments': []},
        layout_config=None, style_config=None,
    )
    pipeline = ClipRenderPipeline(config)
    stages = pipeline._build_stages()
    assert [s.order for s in stages] == list(range(1, 12))
    assert [s.name for s in stages] == [
        'trim_and_crop', 'color_grade', 'intro_concat', 'hook',
        'caption_translation', 'captions', 'watermark', 'timed_overlays',
        'progress_bar', 'outro_concat', 'music_and_sfx_mix',
    ]


def test_pipeline_render_config_accepts_timed_sfx(tmp_path) -> None:
    sfx = object()  # placeholder — real ClipTimedSfx not needed for this check
    config = PipelineRenderConfig(
        source_path=tmp_path / 'src.mp4',
        output_path=tmp_path / 'out.mp4',
        start_sec=0.0, end_sec=10.0, hook_text='',
        transcript_json={'segments': []},
        layout_config=None, style_config=None,
        timed_sfx=[sfx],
    )
    assert config.timed_sfx == [sfx]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_render_pipeline.py -v --no-cov -k "eleven_stages or timed_sfx"`
Expected: FAIL — current pipeline has 10 stages named
`watermark`(order 6)/`music_mix`(order 10), no `color_grade`, no
`timed_sfx` field.

- [ ] **Step 3: Rewrite `PipelineRenderConfig` and `_build_stages()`**

Add `timed_sfx: list[ClipTimedSfx] = field(default_factory=list)` to
`PipelineRenderConfig` (alongside `timed_overlays`). Add `ClipTimedSfx` to
the `TYPE_CHECKING` import block.

Replace `_build_stages()` entirely:

```python
    def _build_stages(self) -> list[RenderStage]:
        from server.apps.rendering.clip_stages.captions import (  # noqa: PLC0415
            CaptionStage,
            CaptionTranslationStage,
        )
        from server.apps.rendering.clip_stages.color_grade import (  # noqa: PLC0415
            ColorGradeStage,
        )
        from server.apps.rendering.clip_stages.fonts import (  # noqa: PLC0415
            build_fonts_dir,
        )
        from server.apps.rendering.clip_stages.hook import (  # noqa: PLC0415
            HookStage,
        )
        from server.apps.rendering.clip_stages.intro_outro import (  # noqa: PLC0415
            IntroConcatStage,
            OutroConcatStage,
        )
        from server.apps.rendering.clip_stages.music_mix import (  # noqa: PLC0415
            MusicMixStage,
        )
        from server.apps.rendering.clip_stages.progress_bar import (  # noqa: PLC0415
            ProgressBarStage,
        )
        from server.apps.rendering.clip_stages.timed_overlays import (  # noqa: PLC0415
            TimedOverlayStage,
        )
        from server.apps.rendering.clip_stages.trim_crop import (  # noqa: PLC0415
            TrimAndCropStage,
        )
        from server.apps.rendering.clip_stages.watermark import (  # noqa: PLC0415
            WatermarkStage,
        )

        c = self.config
        clip_dur = c.end_sec - c.start_sec
        render_dir = c.render_id or 'default'
        tmp = Path(tempfile.gettempdir()) / 'clip_renders' / render_dir
        tmp.mkdir(parents=True, exist_ok=True)

        playback_speed = (
            c.style_config.playback_speed if c.style_config else 1.0
        )
        transcript_json = _scale_transcript(
            c.transcript_json, playback_speed=playback_speed,
        )
        font_assets = (
            [c.style_config.caption_font_asset]
            if c.style_config and c.style_config.caption_font_asset
            else []
        )
        fonts_dir = build_fonts_dir(tmp, font_assets)

        return [
            TrimAndCropStage(
                source_path=c.source_path, start_sec=c.start_sec, end_sec=c.end_sec,
                output_path=tmp / '01_trim_crop.mp4', layout_config=c.layout_config,
                width=c.width, height=c.height, fps=c.fps, crf=c.crf,
                preset=c.preset, audio_bitrate=c.audio_bitrate,
                playback_speed=playback_speed,
            ),
            ColorGradeStage(
                output_path=tmp / '02_color_grade.mp4', style_config=c.style_config,
                crf=c.crf, preset=c.preset, fps=c.fps, audio_bitrate=c.audio_bitrate,
            ),
            IntroConcatStage(
                output_path=tmp / '03_intro.mp4', style_config=c.style_config,
                width=c.width, height=c.height, fps=c.fps, crf=c.crf,
                preset=c.preset, audio_bitrate=c.audio_bitrate,
            ),
            HookStage(
                hook_text=c.hook_text, output_path=tmp / '04_hook.mp4',
                style_config=c.style_config, crf=c.crf, preset=c.preset,
                width=c.width, height=c.height, fps=c.fps, audio_bitrate=c.audio_bitrate,
            ),
            CaptionTranslationStage(
                transcript_json=transcript_json,
                output_path=tmp / '05_caption_translation.mp4',
                style_config=c.style_config,
            ),
            CaptionStage(
                transcript_json=transcript_json, output_path=tmp / '06_captions.mp4',
                ass_path=tmp / 'captions.ass', style_config=c.style_config,
                fonts_dir=fonts_dir, video_width=c.width, video_height=c.height,
                crf=c.crf, preset=c.preset, fps=c.fps, audio_bitrate=c.audio_bitrate,
            ),
            WatermarkStage(
                output_path=tmp / '07_watermark.mp4', style_config=c.style_config,
                crf=c.crf, preset=c.preset, fps=c.fps, audio_bitrate=c.audio_bitrate,
            ),
            TimedOverlayStage(
                output_path=tmp / '08_timed_overlays.mp4',
                timed_overlays=c.timed_overlays, crf=c.crf, preset=c.preset,
                fps=c.fps, audio_bitrate=c.audio_bitrate,
            ),
            ProgressBarStage(
                output_path=tmp / '09_progress_bar.mp4', style_config=c.style_config,
                video_duration_sec=clip_dur, width=c.width, crf=c.crf,
                preset=c.preset, fps=c.fps, audio_bitrate=c.audio_bitrate,
            ),
            OutroConcatStage(
                output_path=tmp / '10_outro.mp4', style_config=c.style_config,
                width=c.width, height=c.height, fps=c.fps, crf=c.crf,
                preset=c.preset, audio_bitrate=c.audio_bitrate,
            ),
            MusicMixStage(
                output_path=tmp / '11_music_and_sfx.mp4', style_config=c.style_config,
                video_duration_sec=clip_dur, timed_sfx=c.timed_sfx,
            ),
        ]
```

Update `MusicMixStage.name` (in `music_mix.py`) from `'music_mix'` to
`'music_and_sfx_mix'` to match the name asserted in this task's test — this
is a one-line change, made here rather than in Task 27, since Task 27 didn't
know the final pipeline-wide name yet.

Update every call site that constructs `PipelineRenderConfig` (found via
`grep -rn "PipelineRenderConfig(" server/`) to pass `timed_sfx=` (fetched the
same way `timed_overlays` is already fetched at that call site — likely a
`ClipTimedSfx.objects.filter(candidate_id=...)` query mirroring whatever
already fetches `ClipTimedOverlay` rows there).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_clip_render_pipeline.py -v --cov=server.apps.rendering.clip_render_pipeline --cov-report=term-missing`
Expected: all PASS, 100% coverage.

Run the full test suite to catch any other stale references to the old
10-stage numbering or `'music_mix'` name:

Run: `docker compose exec web pytest --no-cov`
Expected: all PASS. Fix forward any test that hardcoded the old `order`
values (e.g. `assert stage.order == 6` for watermark, now `7`) — these are
expected, intentional breaks from the renumbering, not regressions.

- [ ] **Step 5: Commit**

```bash
git add server/apps/rendering/clip_render_pipeline.py \
  server/apps/rendering/clip_stages/music_mix.py \
  server/apps/clips/preview_render.py \
  tests/test_apps/test_rendering/test_clip_render_pipeline.py \
  tests/test_apps/test_rendering/test_clip_stages/test_remaining_stages.py
git commit -m "feat(clipping): wire color grade + font system + SFX into the 11-stage pipeline"
```

- [ ] **Step 6: Full coverage + lint + type-check gate**

Run: `docker compose exec web pytest --cov-fail-under=100`
Expected: PASS at 100%.

Run: `docker compose exec web ruff check .`
Run: `docker compose exec web ruff format --check .`
Run: `docker compose exec web mypy server`
Run: `docker compose exec web lint-imports`
Expected: all clean. Fix anything this surfaces before moving to Task 29 —
this is the natural checkpoint since every render-stage file has now been
touched.

---

## Task 29: Extend `seed_blueprints.py` with clipping blueprints

**Files:**
- Modify: `server/apps/pipelines/management/commands/seed_blueprints.py`
- Test: `tests/test_apps/test_pipelines/test_management/test_seed_blueprints.py`
  (create if missing — check
  `find tests/test_apps/test_pipelines -iname "*seed_blueprint*"` first)

**Interfaces:**
- Produces: `seed_blueprints` now also seeds `clipping_v1` and
  `clipping_v1_manual` via `update_or_create`, using the exact same graph
  shapes already created by migrations `0003_add_clipping_v1_blueprint.py`
  and `0006_add_clipping_v1_manual_blueprint.py` — this does **not** change
  the DAG shape (see spec §12); it just makes the existing blueprints
  reseedable/updatable without writing a new migration each time.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apps/test_pipelines/test_management/test_seed_blueprints.py
import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_seed_blueprints_creates_clipping_v1() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='clipping_v1')
    assert bp.kind == 'CLIPPING'
    keys = {s['key'] for s in bp.graph['stages']}
    assert keys == {
        'clip_ingest', 'clip_transcribe', 'clip_analyze',
        'clip_approval_gate', 'clip_render', 'clip_distribute',
    }


def test_seed_blueprints_creates_clipping_v1_manual() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='clipping_v1_manual')
    assert bp.kind == 'CLIPPING'
    keys = {s['key'] for s in bp.graph['stages']}
    assert keys == {
        'clip_ingest', 'clip_transcribe', 'clip_manual_setup',
        'clip_approval_gate', 'clip_render', 'clip_distribute',
    }


def test_seed_blueprints_is_idempotent_on_rerun() -> None:
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    call_command('seed_blueprints')
    assert PipelineBlueprint.objects.filter(name='clipping_v1').count() == 1
    assert (
        PipelineBlueprint.objects.filter(name='clipping_v1_manual').count() == 1
    )


def test_seed_blueprints_still_creates_longform_v1() -> None:
    """Regression guard — don't break the existing longform seeding."""
    from server.apps.pipelines.models import PipelineBlueprint

    call_command('seed_blueprints')
    assert PipelineBlueprint.objects.filter(name='longform_v1').exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_management/test_seed_blueprints.py -v --no-cov -k clipping`
Expected: FAIL — `PipelineBlueprint.DoesNotExist` (command only seeds
`longform_v1` today; `clipping_v1`/`clipping_v1_manual` already exist in the
DB from the historical migrations, but re-running the command doesn't touch
them, so the *test* — which likely runs against a fresh test DB where
migrations already applied — would actually find them existing already;
the failure mode to check for here is: assert the command's `stdout`
mentions both clipping blueprints, proving the command itself is
responsible, not just leftover migration state. Adjust the test to capture
`call_command('seed_blueprints', stdout=out)` and assert
`'clipping_v1' in out.getvalue()` if the plain existence check doesn't
actually fail pre-change.)

- [ ] **Step 3: Extend the command**

Add the two graph constants (copied verbatim from the migrations) above the
existing `_LONGFORM_V1_GRAPH`:

```python
_CLIPPING_V1_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'clip_ingest', 'depends_on': []},
        {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
        {
            'key': 'clip_analyze',
            'depends_on': ['clip_transcribe'],
            'config': {'clips_requested': 5},
        },
        {
            'key': 'clip_approval_gate',
            'depends_on': ['clip_analyze'],
            'gate': True,
        },
        {'key': 'clip_render', 'depends_on': ['clip_approval_gate']},
        {'key': 'clip_distribute', 'depends_on': ['clip_render']},
    ],
}

_CLIPPING_V1_MANUAL_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'clip_ingest', 'depends_on': []},
        {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
        {'key': 'clip_manual_setup', 'depends_on': ['clip_transcribe']},
        {
            'key': 'clip_approval_gate',
            'depends_on': ['clip_manual_setup'],
            'gate': True,
        },
        {'key': 'clip_render', 'depends_on': ['clip_approval_gate']},
        {'key': 'clip_distribute', 'depends_on': ['clip_render']},
    ],
}
```

Update `Command.handle()`:

```python
    @override
    def handle(self, *args: object, **options: object) -> None:
        """Create or update the longform_v1 and clipping_v1* blueprints."""
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineBlueprint,
            PipelineKind,
        )

        specs = [
            ('longform_v1', PipelineKind.LONGFORM, _LONGFORM_V1_GRAPH),
            ('clipping_v1', 'CLIPPING', _CLIPPING_V1_GRAPH),
            ('clipping_v1_manual', 'CLIPPING', _CLIPPING_V1_MANUAL_GRAPH),
        ]
        for name, kind, graph in specs:
            bp, created = PipelineBlueprint.objects.update_or_create(
                name=name,
                kind=kind,
                defaults={'graph': graph, 'is_active': True},
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{action} blueprint: {bp}'))
```

Check whether `PipelineKind` has a `CLIPPING` member the same way it has
`LONGFORM` (referenced as `PipelineKind.LONGFORM` in the existing code) — if
so, use `PipelineKind.CLIPPING` instead of the bare string `'CLIPPING'` for
consistency; the migrations used the bare string because migrations can't
safely import current app code, but this management command can and should
prefer the enum.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_management/test_seed_blueprints.py -v --cov=server.apps.pipelines.management.commands.seed_blueprints --cov-report=term-missing`
Expected: all 4 tests PASS, 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add server/apps/pipelines/management/commands/seed_blueprints.py \
  tests/test_apps/test_pipelines/test_management/test_seed_blueprints.py
git commit -m "feat(pipelines): seed clipping_v1/clipping_v1_manual blueprints from seed_blueprints command"
```

---

## Final verification (run once, after all 29 tasks)

- [ ] **Full test suite + coverage gate**

Run: `docker compose exec web pytest`
Expected: 100% pass, `--cov-fail-under=100` satisfied (it's the default per
`pyproject.toml`).

- [ ] **Lint, format, type-check, migration lint**

```bash
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web mypy server
docker compose exec web lint-imports
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: all clean.

- [ ] **Real end-to-end render smoke test**

Per the spec's testing note, command-construction unit tests can't catch a
malformed ffmpeg filter graph — run at least one real render through the
docker stack (using `just run shell` to drop into a Django shell, construct
a `ClipCandidate` with a real short source video, a `ClipStyleConfig` with a
non-default `intro_transition`, `color_filter`, `playback_speed`, and a
custom `caption_font_asset`, and call `ClipRenderPipeline(config).run()`
directly) to confirm the new `xfade`, `lut3d`, `geq` mask, and
`fontsdir`-based subtitle filters actually execute against real ffmpeg
rather than just asserting on mocked command strings.

- [ ] **Regenerate and inspect the OpenAPI schema**

Run: `docker compose exec web python manage.py dump_openapi_schema -o /tmp/schema.yaml`
Expected: succeeds; spot-check that every new field/enum from this plan
appears (`grep -E "watermark_color|CUSTOM_ASSET|KARAOKE_HIGHLIGHT|playback_speed|sfx" /tmp/schema.yaml`).
This file is what gets copied into `reelforge-frontend/schema.yaml` to
regenerate the frontend API client — see the companion frontend plan.

---

## Self-Review Notes

- **Spec coverage:** every numbered section of
  `2026-07-06-clipping-fully-featured-design.md` (§4 fonts → Tasks 1, 13-15;
  §5 transitions → Tasks 16-17; §6 overlays → Tasks 18-20; §7 captions →
  Tasks 21-22; §8 watermark → Tasks 15, 23; §9 color grading → Task 24;
  §10 speed → Task 25; §11 SFX → Tasks 7, 11-12, 27; §12 blueprint →
  Task 29; §13 pipeline shape → Task 28) maps to a task above.
- **Placeholder scan:** no TBD/TODO left in any step; the one place with
  genuine external uncertainty (exact google/fonts GitHub paths in Task 1)
  is handled with a verification step and a documented fallback
  (`fonttools varLib.instancer`), not a placeholder.
- **Type consistency:** `resolve_drawtext_font`, `build_fonts_dir`,
  `sync_ffprobe_duration`, `_scale_transcript` are each defined once (Tasks
  2/13/25) and referenced with the same signature everywhere they're used
  later (Tasks 15/18/19/23/28).
