# Documentary Blueprint — Foundations & Provider Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the blueprint-profile mechanism, the three shared-code seams, the
migrations, and a fully tested stock-media provider client library — with zero
behavior change to any existing pipeline.

**Architecture:** A pure `BlueprintProfile` registry maps a blueprint's declared
profile to the stage keys playing each visual role, defaulting to today's AI
stages when absent. `assembly` and the new review dispatcher resolve roles
through it. Separately, a `stock/` client package exposes one `FootageProvider`
Protocol with four adapters behind a Redis-cached, rate-limited search facade.

**Tech Stack:** Python 3.13, Django 6.0, pytest, httpx, attrs, msgspec,
structlog, Redis (`aioredis`), ffmpeg.

**Covers:** §12 steps 1–5 of
`docs/superpowers/specs/2026-07-26-longform-documentary-blueprint-design.md`.
Steps 6–10 are in `2026-07-26-documentary-blueprint-pipeline.md`.

## Global Constraints

- Python 3.13.x, Django 6.0.x.
- `ruff`: single quotes, 80-char line length.
- `mypy` strict — all public functions annotated.
- 100% test coverage — `--cov-fail-under=100` in `pyproject.toml`.
- `--doctest-modules` is active — docstring examples must be valid.
- **Never** add `from __future__ import annotations` to files registered with
  punq.
- `@final` on every concrete class; `@attrs.define(slots=True, frozen=True)` for
  service objects; `msgspec.Struct` for API value objects; `pydantic.BaseModel`
  for stage output schemas (see `server/apps/pipelines/schemas.py`).
- Migrations must be backward-compatible (zero-downtime); verified by
  `python manage.py lintmigrations`.
- Inline imports inside functions need `# noqa: PLC0415` (the codebase-wide
  pattern for deferred Django imports).
- All commands run in Docker: `docker compose exec web <cmd>`. `just run <cmd>`
  works for `manage.py` commands without the app container.
- Every new `server.apps.pipelines.stages.* -> server.apps.generation.clients.*`
  or `-> server.apps.assets.models` import **must** be added to
  `.importlinter`'s `apps-independence` `ignore_imports` list, or
  `lint-imports` fails.

## Verification Commands

```bash
docker compose exec web pytest --no-cov          # fast TDD loop
docker compose exec web pytest                   # full run, 100% coverage gate
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web mypy server
docker compose exec web lint-imports
docker compose exec web python manage.py lintmigrations
```

---

## Provider fixtures — status per provider

**Already captured from live APIs** (committed under
`tests/test_apps/test_generation/test_stock/fixtures/`, 2026-07-26 — these
three need no API key):

- `openverse_image_search.json`
- `wikimedia_search.json`
- `archive_org_search.json`

**Doc-derived, NOT live-verified** — `PEXELS_API_KEY` and `PIXABAY_API_KEY` are
not configured, and the operator chose to proceed rather than wait for keys:

- `pexels_video_search.json`, `pexels_photo_search.json`
- `pixabay_video_search.json`, `pixabay_photo_search.json`

Build these two adapters from the published API docs
(<https://www.pexels.com/api/documentation/>, <https://pixabay.com/api/docs/>).
**Put `"_doc_derived": true` at the top of each of those four fixtures and a
warning in the test module docstring**, so the gap is visible. Re-verify both
adapters against live responses once keys exist — they are the two most likely
to need mapping corrections.

**Resolved: Openverse serves no video.** Probed 2026-07-26 — `/v1/images/` and
`/v1/audio/` return 200; `/v1/video/` and `/v1/videos/` both 404. The design
doc's claim that Openverse supplies archival video is wrong. Therefore:
`OpenverseProvider` is **image-only**, and **`ArchiveOrgProvider` is required**
(not conditional) for archival video. Task 9 builds both.

## Licence safety — NC and ND must be excluded by default

The captured Openverse fixture returns `by-nc-nd` content. **NonCommercial**
forbids use on a monetized channel and **NoDerivatives** forbids editing the
work into a video — both are exactly what this pipeline does.

`allowed_licenses` defaulting to empty means "no restriction", so the floor
needs a denylist that applies regardless: any licence code containing `nc` or
`nd` is rejected in `passes_quality_floor`. This is implemented in Task 6 and
is not configurable off.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `server/apps/pipelines/logic/blueprint_profiles.py` | `BlueprintProfile` value object, registry, `resolve_role()`. Pure — no ORM. |
| `server/apps/generation/clients/stock/__init__.py` | Package marker. |
| `server/apps/generation/clients/stock/base.py` | `FootageCandidate` struct + `FootageProvider` Protocol. |
| `server/apps/generation/clients/stock/pexels.py` | Pexels video+photo adapter. |
| `server/apps/generation/clients/stock/pixabay.py` | Pixabay video+photo adapter. |
| `server/apps/generation/clients/stock/wikimedia.py` | Wikimedia Commons adapter. |
| `server/apps/generation/clients/stock/openverse.py` | Openverse (and/or archive.org) adapter. |
| `server/apps/generation/clients/stock/registry.py` | Name→provider map, ordered multi-provider search with early exit. |
| `server/apps/generation/clients/stock/cache.py` | Redis search cache + per-provider rate limiting. |

**Modified:**

| Path | Change |
|---|---|
| `server/apps/rendering/ffmpeg.py` | Add public `ken_burns()`. |
| `server/apps/pipelines/stages/motion.py` | Delegate to `ffmpeg.ken_burns()`. |
| `server/apps/pipelines/stages/assembly.py:95` | Role-resolve `stage_key='motion'`. |
| `server/apps/assets/models.py` | `AssetKind.FOOTAGE`; `FootageCredit` model. |
| `server/apps/channels/models.py` | `FootageSourcingConfig` model. |
| `server/settings/components/common.py` | Provider API key settings. |

---

## Task 1: Blueprint profile registry

**Files:**
- Create: `server/apps/pipelines/logic/blueprint_profiles.py`
- Test: `tests/test_apps/test_pipelines/test_logic/test_blueprint_profiles.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `BlueprintProfile` — frozen attrs class, fields `key: str`,
    `roles: Mapping[str, str]`.
  - `AI_VISUAL: BlueprintProfile`, `DOCUMENTARY_FOOTAGE: BlueprintProfile`.
  - `PROFILE_REGISTRY: dict[str, BlueprintProfile]`.
  - `resolve_role(blueprint_snapshot: dict[str, Any], role: str) -> str`.
  - `resolve_profile_key(blueprint_snapshot: dict[str, Any]) -> str`.
  - Role name constants `PROMPT_STAGE`, `SOURCE_STAGE`, `SEGMENT_STAGE`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_pipelines/test_logic/test_blueprint_profiles.py`:

```python
"""Tests for blueprint profile role resolution."""

import pytest

from server.apps.pipelines.logic.blueprint_profiles import (
    PROFILE_REGISTRY,
    PROMPT_STAGE,
    SEGMENT_STAGE,
    SOURCE_STAGE,
    resolve_profile_key,
    resolve_role,
)


def test_absent_profile_defaults_to_ai_visual() -> None:
    """A graph with no profile key behaves exactly as it does today."""
    snapshot: dict[str, object] = {'stages': []}
    assert resolve_profile_key(snapshot) == 'ai_visual'
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'motion'
    assert resolve_role(snapshot, SOURCE_STAGE) == 'image_gen'
    assert resolve_role(snapshot, PROMPT_STAGE) == 'visual_prompts'


def test_documentary_profile_resolves_footage_stages() -> None:
    """The documentary profile maps roles to the footage stages."""
    snapshot = {'stages': [], 'profile': 'documentary_footage'}
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'footage_prep'
    assert resolve_role(snapshot, SOURCE_STAGE) == 'footage_search'
    assert resolve_role(snapshot, PROMPT_STAGE) == 'footage_queries'


def test_unknown_profile_falls_back_to_ai_visual() -> None:
    """An unregistered profile name must not crash a running pipeline."""
    snapshot = {'stages': [], 'profile': 'not_a_real_profile'}
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'motion'


def test_explicit_roles_override_the_profile() -> None:
    """A graph may override one role without defining a new profile."""
    snapshot = {
        'stages': [],
        'profile': 'documentary_footage',
        'roles': {'segment_stage': 'custom_segment'},
    }
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'custom_segment'
    assert resolve_role(snapshot, SOURCE_STAGE) == 'footage_search'


def test_unknown_role_raises() -> None:
    """An unknown role name is a programming error, not a runtime fallback."""
    with pytest.raises(KeyError):
        resolve_role({'stages': []}, 'nonexistent_role')


def test_registry_contains_both_profiles() -> None:
    """Both shipped profiles are registered under their key."""
    assert set(PROFILE_REGISTRY) == {'ai_visual', 'documentary_footage'}
    for key, profile in PROFILE_REGISTRY.items():
        assert profile.key == key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_blueprint_profiles.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named
'server.apps.pipelines.logic.blueprint_profiles'`

- [ ] **Step 3: Write the implementation**

Create `server/apps/pipelines/logic/blueprint_profiles.py`:

```python
"""Blueprint profiles — map a blueprint to its visual stage roles.

A blueprint graph may declare ``profile`` to select which registered stages
play each visual role. Absent, it resolves to ``ai_visual`` so existing
blueprints behave exactly as they did before profiles existed.

>>> resolve_role({'stages': []}, SEGMENT_STAGE)
'motion'
>>> resolve_role({'profile': 'documentary_footage'}, SEGMENT_STAGE)
'footage_prep'
"""

from collections.abc import Mapping
from typing import Any, Final, final

import attrs

PROMPT_STAGE: Final = 'prompt_stage'
SOURCE_STAGE: Final = 'source_stage'
SEGMENT_STAGE: Final = 'segment_stage'

_ROLE_NAMES: Final = frozenset({PROMPT_STAGE, SOURCE_STAGE, SEGMENT_STAGE})

DEFAULT_PROFILE_KEY: Final = 'ai_visual'


@final
@attrs.define(slots=True, frozen=True)
class BlueprintProfile:
    """Maps visual role names to the stage keys that implement them."""

    key: str
    roles: Mapping[str, str]


AI_VISUAL: Final = BlueprintProfile(
    key='ai_visual',
    roles={
        PROMPT_STAGE: 'visual_prompts',
        SOURCE_STAGE: 'image_gen',
        SEGMENT_STAGE: 'motion',
    },
)

DOCUMENTARY_FOOTAGE: Final = BlueprintProfile(
    key='documentary_footage',
    roles={
        PROMPT_STAGE: 'footage_queries',
        SOURCE_STAGE: 'footage_search',
        SEGMENT_STAGE: 'footage_prep',
    },
)

PROFILE_REGISTRY: Final[dict[str, BlueprintProfile]] = {
    AI_VISUAL.key: AI_VISUAL,
    DOCUMENTARY_FOOTAGE.key: DOCUMENTARY_FOOTAGE,
}


def resolve_profile_key(blueprint_snapshot: dict[str, Any]) -> str:
    """Return the profile key for a graph, defaulting to ``ai_visual``."""
    key = blueprint_snapshot.get('profile') or DEFAULT_PROFILE_KEY
    return str(key) if str(key) in PROFILE_REGISTRY else DEFAULT_PROFILE_KEY


def resolve_role(blueprint_snapshot: dict[str, Any], role: str) -> str:
    """Return the stage key playing ``role`` for this blueprint.

    Raises:
        KeyError: If ``role`` is not a known visual role name.
    """
    if role not in _ROLE_NAMES:
        msg = f'Unknown blueprint role: {role}'
        raise KeyError(msg)
    overrides = blueprint_snapshot.get('roles') or {}
    override = overrides.get(role) if isinstance(overrides, dict) else None
    if override:
        return str(override)
    profile = PROFILE_REGISTRY[resolve_profile_key(blueprint_snapshot)]
    return profile.roles[role]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_blueprint_profiles.py -v --no-cov`
Expected: PASS, 6 passed

- [ ] **Step 5: Run lint, types, and doctests**

Run:
```bash
docker compose exec web ruff check server/apps/pipelines/logic/blueprint_profiles.py
docker compose exec web mypy server
docker compose exec web pytest --doctest-modules server/apps/pipelines/logic/blueprint_profiles.py --no-cov
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add server/apps/pipelines/logic/blueprint_profiles.py \
        tests/test_apps/test_pipelines/test_logic/test_blueprint_profiles.py
git commit -m "feat(pipelines): add blueprint profile role registry"
```

---

## Task 2: Assembly resolves its segment stage by role

This is the single unavoidable edit to shared render-path code. It lands alone
so a regression is trivially bisectable.

**Files:**
- Modify: `server/apps/pipelines/stages/assembly.py:85-104`
- Test: `tests/test_apps/test_pipelines/test_stages/test_assembly.py`

**Interfaces:**
- Consumes: `resolve_role`, `SEGMENT_STAGE` from Task 1.
- Produces: no signature change. `_build_scene_asset_map(ctx)` keeps its
  signature and returns `dict[int, str]`.

- [ ] **Step 1: Confirm the existing assembly tests are green first**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_assembly.py -v --no-cov`
Expected: PASS. If it fails here, stop — the baseline is broken and this task
cannot prove anything.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_apps/test_pipelines/test_stages/test_assembly.py`:

```python
def test_build_scene_asset_map_defaults_to_motion() -> None:
    """A blueprint with no profile still reads motion shard outputs."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.stages.assembly import _resolve_segment_stage

    ctx = MagicMock()
    ctx.run.blueprint_snapshot = {'stages': []}
    assert _resolve_segment_stage(ctx) == 'motion'


def test_build_scene_asset_map_uses_documentary_segment_stage() -> None:
    """A documentary blueprint reads footage_prep shard outputs instead."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.stages.assembly import _resolve_segment_stage

    ctx = MagicMock()
    ctx.run.blueprint_snapshot = {
        'stages': [],
        'profile': 'documentary_footage',
    }
    assert _resolve_segment_stage(ctx) == 'footage_prep'
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_assembly.py -k resolve_segment -v --no-cov`
Expected: FAIL — `ImportError: cannot import name '_resolve_segment_stage'`

- [ ] **Step 4: Write the implementation**

In `server/apps/pipelines/stages/assembly.py`, add the helper above
`_build_scene_asset_map`:

```python
def _resolve_segment_stage(ctx: StageContext) -> str:
    """Return the stage key that produced this run's video segments."""
    from server.apps.pipelines.logic.blueprint_profiles import (  # noqa: PLC0415
        SEGMENT_STAGE,
        resolve_role,
    )

    return resolve_role(ctx.run.blueprint_snapshot or {}, SEGMENT_STAGE)
```

Then change the single hardcoded key inside `_build_scene_asset_map`. Replace:

```python
    scene_map: dict[int, str] = {}
    async for child in StageExecution.objects.filter(
        run=ctx.run,
        stage_key='motion',
        parent__isnull=False,
        status=StageStatus.SUCCEEDED,
    ).order_by('shard_index'):
```

with:

```python
    scene_map: dict[int, str] = {}
    async for child in StageExecution.objects.filter(
        run=ctx.run,
        stage_key=_resolve_segment_stage(ctx),
        parent__isnull=False,
        status=StageStatus.SUCCEEDED,
    ).order_by('shard_index'):
```

Also update the docstring's first line to:

```python
    """Return {scene_idx: asset_id} from the run's segment stage children."""
```

- [ ] **Step 5: Run the full assembly suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_assembly.py -v --no-cov`
Expected: PASS — all pre-existing tests plus the 2 new ones. **Any pre-existing
failure here means this change broke `longform_v1` — revert and reassess.**

- [ ] **Step 6: Commit**

```bash
git add server/apps/pipelines/stages/assembly.py \
        tests/test_apps/test_pipelines/test_stages/test_assembly.py
git commit -m "refactor(assembly): resolve segment stage via blueprint profile"
```

---

## Task 3: Extract `ken_burns()` into the rendering layer

**Files:**
- Modify: `server/apps/rendering/ffmpeg.py`
- Modify: `server/apps/pipelines/stages/motion.py:19-107`
- Test: `tests/test_apps/test_rendering/test_ffmpeg_ken_burns.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_motion.py` (must stay
  green unchanged)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `async def ken_burns(image_bytes: bytes, duration_s: float,
  preset_idx: int = 0) -> bytes` in `server.apps.rendering.ffmpeg`.

- [ ] **Step 1: Confirm the motion baseline is green**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_motion.py -v --no-cov`
Expected: PASS

- [ ] **Step 2: Write the failing test**

Create `tests/test_apps/test_rendering/test_ffmpeg_ken_burns.py`:

```python
"""Tests for the shared Ken Burns ffmpeg helper."""

import asyncio
from pathlib import Path

import pytest

from server.apps.rendering.ffmpeg import async_ffprobe, ken_burns


def _tiny_jpeg(tmp_path: Path) -> bytes:
    """Render a 320x240 solid-colour JPEG with ffmpeg and return its bytes."""
    out = tmp_path / 'src.jpg'
    proc = asyncio.run(
        asyncio.create_subprocess_exec(
            'ffmpeg', '-y', '-f', 'lavfi',
            '-i', 'color=c=blue:s=320x240', '-frames:v', '1', str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        ),
    )
    asyncio.run(proc.wait())
    return out.read_bytes()


def test_ken_burns_produces_a_video_of_requested_duration(
    tmp_path: Path,
) -> None:
    """A still image becomes an mp4 of roughly the requested length."""
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(ken_burns(image_bytes, duration_s=2.0))
    assert video_bytes
    out = tmp_path / 'out.mp4'
    out.write_bytes(video_bytes)
    probe = asyncio.run(async_ffprobe(str(out)))
    duration = float(probe['format']['duration'])
    assert 1.5 <= duration <= 2.5


def test_ken_burns_rejects_empty_image() -> None:
    """Empty input is a programming error, caught immediately."""
    with pytest.raises(AssertionError):
        asyncio.run(ken_burns(b'', duration_s=2.0))


def test_ken_burns_rejects_nonpositive_duration(tmp_path: Path) -> None:
    """Zero or negative duration is rejected before invoking ffmpeg."""
    image_bytes = _tiny_jpeg(tmp_path)
    with pytest.raises(AssertionError):
        asyncio.run(ken_burns(image_bytes, duration_s=0.0))


def test_ken_burns_preset_index_wraps(tmp_path: Path) -> None:
    """preset_idx beyond the preset count wraps instead of raising."""
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(
        ken_burns(image_bytes, duration_s=1.0, preset_idx=99),
    )
    assert video_bytes
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_ffmpeg_ken_burns.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'ken_burns'`

- [ ] **Step 4: Move the implementation into `ffmpeg.py`**

Add to `server/apps/rendering/ffmpeg.py` (module level, near the other
public helpers):

```python
_KEN_BURNS_PRESETS = [
    "zoompan=z='zoom+0.008':d=150:s=1920x1080",
    "zoompan=z='1.12-0.008*on':d=150:s=1920x1080",
    "zoompan=x='iw/2-(iw/zoom/2)+on*8':z=1.08:d=150:s=1920x1080",
    "zoompan=x='iw-(iw/zoom/2)-on*8':z=1.08:d=150:s=1920x1080",
]


async def ken_burns(
    image_bytes: bytes,
    duration_s: float,
    preset_idx: int = 0,
) -> bytes:
    """Apply a Ken Burns zoom/pan to image bytes and return mp4 bytes."""
    assert image_bytes, 'image_bytes must be non-empty'
    assert duration_s > 0, f'duration_s must be > 0, got {duration_s}'

    with (
        tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as img_f,
        tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as vid_f,
    ):
        img_path = img_f.name
        vid_path = vid_f.name
    try:
        await asyncio.to_thread(Path(img_path).write_bytes, image_bytes)

        frames = int(duration_s * 30)
        vf = _KEN_BURNS_PRESETS[preset_idx % len(_KEN_BURNS_PRESETS)].replace(
            'd=150',
            f'd={frames}',
        )
        cmd = [
            'ffmpeg', '-y', '-loop', '1', '-i', img_path,
            '-vf', vf, '-t', str(duration_s), '-r', '30',
            '-c:v', 'libx264', '-crf', '16', '-pix_fmt', 'yuv420p',
            '-an', vid_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f'FFmpeg Ken Burns failed: {stderr.decode()[:300]}',
            )

        video_bytes = await asyncio.to_thread(Path(vid_path).read_bytes)
        assert video_bytes, 'Ken Burns produced empty video'
        return video_bytes
    finally:
        await asyncio.to_thread(Path(img_path).unlink, missing_ok=True)
        await asyncio.to_thread(Path(vid_path).unlink, missing_ok=True)
```

Verify `asyncio`, `tempfile`, and `Path` are already imported at the top of
`ffmpeg.py`; add any that are missing.

- [ ] **Step 5: Point `motion.py` at the shared helper**

In `server/apps/pipelines/stages/motion.py`, delete the `_KEN_BURNS_PRESETS`
list and the entire `_run_ken_burns` function, then replace the call site in
`MotionStage.run`:

```python
            image_bytes = await asyncio.to_thread(image_asset.file.read)
            video_bytes = await _run_ken_burns(
                image_bytes=image_bytes,
                duration_s=est_seconds,
                preset_idx=scene_idx,
            )
            method = 'ken_burns'
```

with:

```python
            image_bytes = await asyncio.to_thread(image_asset.file.read)
            video_bytes = await ffmpeg.ken_burns(
                image_bytes=image_bytes,
                duration_s=est_seconds,
                preset_idx=scene_idx,
            )
            method = 'ken_burns'
```

Add the import at the top of `motion.py`:

```python
from server.apps.rendering import ffmpeg
```

Remove now-unused imports (`tempfile`, and `Path` if nothing else uses them);
`ruff check` will name them.

- [ ] **Step 6: Add the import-linter exemption**

In `.importlinter`, under the `apps-independence` contract's `ignore_imports`,
add next to the existing assembly/qc rendering lines:

```
  server.apps.pipelines.stages.motion -> server.apps.rendering.ffmpeg
```

- [ ] **Step 7: Verify both suites and the import contract**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_rendering/test_ffmpeg_ken_burns.py tests/test_apps/test_pipelines/test_stages/test_motion.py -v --no-cov
docker compose exec web lint-imports
docker compose exec web ruff check server/apps/pipelines/stages/motion.py server/apps/rendering/ffmpeg.py
```
Expected: all PASS. **`test_motion.py` must pass without being edited** — that
is the proof this refactor changed no behavior.

- [ ] **Step 8: Commit**

```bash
git add server/apps/rendering/ffmpeg.py \
        server/apps/pipelines/stages/motion.py \
        tests/test_apps/test_rendering/test_ffmpeg_ken_burns.py \
        .importlinter
git commit -m "refactor(rendering): extract ken_burns helper from motion stage"
```

---

## Task 4: `AssetKind.FOOTAGE` and the `FootageCredit` model

**Files:**
- Modify: `server/apps/assets/models.py`
- Create: `server/apps/assets/migrations/00XX_footage_kind_and_credit.py`
  (generated)
- Test: `tests/test_apps/test_assets/test_footage_credit.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `AssetKind.FOOTAGE` — value `'FOOTAGE'`.
  - `FootageCredit` model with fields `asset` (FK `assets.Asset`,
    `related_name='credits'`), `run` (FK `pipelines.PipelineRun`,
    `related_name='footage_credits'`), `scene_idx: int`, `provider: str`,
    `license: str`, `license_url: str`, `author: str`, `source_url: str`,
    `title: str`, `attribution_required: bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_assets/test_footage_credit.py`:

```python
"""Tests for FOOTAGE asset kind and the FootageCredit provenance row."""

import pytest
from django.core.files.base import ContentFile

from server.apps.assets.models import Asset, AssetKind, FootageCredit


@pytest.mark.django_db
def test_footage_is_a_valid_asset_kind() -> None:
    """A FOOTAGE asset saves without violating the kind check constraint."""
    asset = Asset(kind=AssetKind.FOOTAGE, mime='video/mp4', checksum='abc')
    asset.file.save('clip.mp4', ContentFile(b'x'), save=False)
    asset.save()
    assert Asset.objects.filter(kind=AssetKind.FOOTAGE).count() == 1


@pytest.mark.django_db
def test_footage_credit_records_provenance() -> None:
    """A credit row links an asset to its provider licence terms."""
    asset = Asset(kind=AssetKind.FOOTAGE, mime='image/jpeg', checksum='def')
    asset.file.save('still.jpg', ContentFile(b'x'), save=False)
    asset.save()

    credit = FootageCredit.objects.create(
        asset=asset,
        scene_idx=4,
        provider='wikimedia',
        license='CC-BY-4.0',
        license_url='https://creativecommons.org/licenses/by/4.0/',
        author='A Photographer',
        source_url='https://commons.wikimedia.org/wiki/File:X.jpg',
        title='A Photograph',
        attribution_required=True,
    )
    assert credit.attribution_required is True
    assert asset.credits.count() == 1
    assert str(credit) == 'wikimedia CC-BY-4.0 (scene 4)'


@pytest.mark.django_db
def test_footage_credit_defaults_to_no_attribution() -> None:
    """Providers like Pexels do not require attribution by default."""
    asset = Asset(kind=AssetKind.FOOTAGE, mime='video/mp4', checksum='ghi')
    asset.file.save('clip.mp4', ContentFile(b'x'), save=False)
    asset.save()
    credit = FootageCredit.objects.create(
        asset=asset,
        scene_idx=0,
        provider='pexels',
        license='pexels',
        source_url='https://www.pexels.com/video/1/',
    )
    assert credit.attribution_required is False
    assert credit.author == ''
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_assets/test_footage_credit.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'FootageCredit'`

- [ ] **Step 3: Add the enum value and the model**

In `server/apps/assets/models.py`, add to `AssetKind` after `DOC`:

```python
    FOOTAGE = 'FOOTAGE', 'Footage'
```

Then append the model at the end of the file:

```python
class FootageCredit(UUIDModel, TimeStampedModel):
    """Licence provenance for one sourced footage asset."""

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name='credits',
    )
    run = models.ForeignKey(
        'pipelines.PipelineRun',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='footage_credits',
        db_index=True,
    )
    scene_idx = models.PositiveIntegerField()
    provider = models.CharField(max_length=32, db_index=True)
    license = models.CharField(max_length=64)
    license_url = models.URLField(blank=True, default='')
    author = models.CharField(max_length=200, blank=True, default='')
    source_url = models.URLField()
    title = models.CharField(max_length=300, blank=True, default='')
    attribution_required = models.BooleanField(default=False)

    class Meta:
        """Meta options for FootageCredit."""

        ordering: ClassVar = ['scene_idx']

    @override
    def __str__(self) -> str:
        """Return provider, licence, and scene for admin display."""
        return f'{self.provider} {self.license} (scene {self.scene_idx})'
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `just run makemigrations assets`
Expected: creates a migration adding the `FootageCredit` model and altering
`assets_asset_kind_valid`.

Open the generated file and confirm it contains **only** a `CreateModel` and a
constraint `RemoveConstraint`/`AddConstraint` pair. Nothing else should change.

- [ ] **Step 5: Verify the migration is backward-compatible**

Run:
```bash
just run lintmigrations
just run migrate
```
Expected: `lintmigrations` reports OK. Widening a check constraint is
backward-compatible; if the linter flags the constraint swap, add the
`# noqa` marker the codebase already uses for constraint edits and record why in
the migration docstring.

- [ ] **Step 6: Run tests**

Run: `docker compose exec web pytest tests/test_apps/test_assets/test_footage_credit.py -v --no-cov`
Expected: PASS, 3 passed

- [ ] **Step 7: Commit**

```bash
git add server/apps/assets/models.py server/apps/assets/migrations/ \
        tests/test_apps/test_assets/test_footage_credit.py
git commit -m "feat(assets): add FOOTAGE kind and FootageCredit provenance"
```

---

## Task 5: `FootageSourcingConfig` channel model

**Files:**
- Modify: `server/apps/channels/models.py`
- Create: `server/apps/channels/migrations/00XX_footage_sourcing_config.py`
  (generated)
- Test: `tests/test_apps/test_channels/test_footage_sourcing_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SourcingMode` TextChoices: `STOCK_FIRST='stock_first'`,
    `ARCHIVAL_FIRST='archival_first'`, `BALANCED='balanced'`.
  - `RerankMode` TextChoices: `VISION='vision'`, `METADATA='metadata'`,
    `NONE='none'`.
  - `FootageSourcingConfig` — OneToOne on `Channel`,
    `related_name='footage_sourcing'`.
  - `Channel.footage_sourcing_or_default() -> FootageSourcingConfig` returning
    an **unsaved** default instance when the channel has no config row.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_channels/test_footage_sourcing_config.py`:

```python
"""Tests for per-channel footage sourcing configuration."""

import pytest

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    FootageSourcingConfig,
    RerankMode,
    SourcingMode,
)


@pytest.fixture
def channel(db: None) -> Channel:
    return Channel.objects.create(name='Doc Channel', kind=ChannelKind.LONGFORM)


@pytest.mark.django_db
def test_defaults_are_documentary_safe(channel: Channel) -> None:
    """A config created with no arguments is usable as-is."""
    config = FootageSourcingConfig.objects.create(channel=channel)
    assert config.ai_fallback_enabled is True
    assert config.rerank_mode == RerankMode.VISION
    assert config.sourcing_mode == SourcingMode.STOCK_FIRST
    assert config.candidates_per_scene == 8
    assert config.min_clip_width == 1280
    assert config.min_clip_duration_s == pytest.approx(3.0)
    assert config.require_attribution is True
    assert config.enabled_providers == []


@pytest.mark.django_db
def test_provider_order_is_preserved(channel: Channel) -> None:
    """enabled_providers is an ordered priority list, not a set."""
    config = FootageSourcingConfig.objects.create(
        channel=channel,
        enabled_providers=['wikimedia', 'openverse', 'pexels'],
    )
    config.refresh_from_db()
    assert config.enabled_providers == ['wikimedia', 'openverse', 'pexels']


@pytest.mark.django_db
def test_channel_without_config_gets_unsaved_defaults(
    channel: Channel,
) -> None:
    """Channels with no config row still resolve to usable defaults."""
    config = channel.footage_sourcing_or_default()
    assert config.pk is None
    assert config.ai_fallback_enabled is True
    assert config.rerank_mode == RerankMode.VISION


@pytest.mark.django_db
def test_channel_with_config_returns_the_saved_row(channel: Channel) -> None:
    """An existing config row wins over the defaults."""
    FootageSourcingConfig.objects.create(
        channel=channel,
        ai_fallback_enabled=False,
    )
    config = channel.footage_sourcing_or_default()
    assert config.pk is not None
    assert config.ai_fallback_enabled is False


@pytest.mark.django_db
def test_invalid_sourcing_mode_is_rejected(channel: Channel) -> None:
    """The check constraint rejects an unknown sourcing mode."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        FootageSourcingConfig.objects.create(
            channel=channel,
            sourcing_mode='not_a_mode',
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_channels/test_footage_sourcing_config.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'FootageSourcingConfig'`

- [ ] **Step 3: Write the implementation**

In `server/apps/channels/models.py`, add the choice classes near the other
`TextChoices` at the top:

```python
class SourcingMode(models.TextChoices):
    """Which family of providers a channel prefers."""

    STOCK_FIRST = 'stock_first', 'Stock first'
    ARCHIVAL_FIRST = 'archival_first', 'Archival first'
    BALANCED = 'balanced', 'Balanced'


class RerankMode(models.TextChoices):
    """How footage candidates are scored before selection."""

    VISION = 'vision', 'Vision model'
    METADATA = 'metadata', 'Metadata only'
    NONE = 'none', 'No re-ranking'
```

Append the model at the end of the file:

```python
class FootageSourcingConfig(UUIDModel, TimeStampedModel):
    """Per-channel stock/archival footage sourcing rules."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name='footage_sourcing',
    )
    enabled_providers = ArrayField(
        models.CharField(max_length=32),
        default=list,
        blank=True,
        help_text='Ordered provider priority. Order is significant.',
    )
    sourcing_mode = models.CharField(
        max_length=15,
        choices=SourcingMode.choices,
        default=SourcingMode.STOCK_FIRST,
    )
    ai_fallback_enabled = models.BooleanField(default=True)
    rerank_mode = models.CharField(
        max_length=10,
        choices=RerankMode.choices,
        default=RerankMode.VISION,
    )
    candidates_per_scene = models.PositiveSmallIntegerField(default=8)
    min_clip_width = models.PositiveIntegerField(default=1280)
    min_clip_duration_s = models.FloatField(default=3.0)
    allowed_licenses = ArrayField(
        models.CharField(max_length=40),
        default=list,
        blank=True,
    )
    require_attribution = models.BooleanField(default=True)

    class Meta:
        """Meta options for FootageSourcingConfig."""

        verbose_name = 'Footage sourcing config'
        constraints: ClassVar = [
            models.CheckConstraint(
                name='channels_footagesourcing_mode_valid',
                condition=models.Q(sourcing_mode__in=SourcingMode.values),
            ),
            models.CheckConstraint(
                name='channels_footagesourcing_rerank_valid',
                condition=models.Q(rerank_mode__in=RerankMode.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        """Return a reference to the parent channel."""
        return f'FootageSourcingConfig for {self.channel}'
```

Add the accessor to `Channel`, next to the other `assembly_style_*` helpers:

```python
    def footage_sourcing_or_default(self) -> 'FootageSourcingConfig':
        """Return this channel's footage config, or unsaved defaults."""
        try:
            return self.footage_sourcing
        except FootageSourcingConfig.DoesNotExist:
            return FootageSourcingConfig(channel=self)
```

- [ ] **Step 4: Generate, lint, and apply the migration**

Run:
```bash
just run makemigrations channels
just run lintmigrations
just run migrate
```
Expected: a pure `CreateModel` migration; `lintmigrations` reports OK.

- [ ] **Step 5: Run tests**

Run: `docker compose exec web pytest tests/test_apps/test_channels/test_footage_sourcing_config.py -v --no-cov`
Expected: PASS, 5 passed

- [ ] **Step 6: Commit**

```bash
git add server/apps/channels/models.py server/apps/channels/migrations/ \
        tests/test_apps/test_channels/test_footage_sourcing_config.py
git commit -m "feat(channels): add FootageSourcingConfig per-channel settings"
```

---

## Task 6: Provider contract — `FootageCandidate` and `FootageProvider`

**Files:**
- Create: `server/apps/generation/clients/stock/__init__.py`
- Create: `server/apps/generation/clients/stock/base.py`
- Modify: `server/settings/components/common.py`
- Test: `tests/test_apps/test_generation/test_stock/test_base.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MediaType` — `Literal['video', 'image']`.
  - `FootageCandidate` — frozen attrs class with fields: `provider: str`,
    `external_id: str`, `media_type: MediaType`, `download_url: str`,
    `thumb_url: str`, `source_page_url: str`, `width: int`, `height: int`,
    `duration_s: float | None`, `license: str`, `license_url: str`,
    `author: str`, `attribution_required: bool`, `title: str`,
    `tags: tuple[str, ...]`.
  - `FootageProvider` Protocol with `name: str` and
    `async def search(query: str, *, media_type: MediaType,
    orientation: str, min_width: int, limit: int)
    -> list[FootageCandidate]`.
  - `passes_quality_floor(candidate, *, min_width, min_duration_s,
    allowed_licenses) -> bool`.
  - Settings: `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `OPENVERSE_API_TOKEN`
    (all `str`, default `''`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_generation/test_stock/test_base.py`:

```python
"""Tests for the shared footage provider contract."""

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    passes_quality_floor,
)


def _candidate(**overrides: object) -> FootageCandidate:
    defaults: dict[str, object] = {
        'provider': 'pexels',
        'external_id': '1',
        'media_type': 'video',
        'download_url': 'https://example.test/v.mp4',
        'thumb_url': 'https://example.test/t.jpg',
        'source_page_url': 'https://example.test/p',
        'width': 1920,
        'height': 1080,
        'duration_s': 10.0,
        'license': 'pexels',
        'license_url': '',
        'author': 'Someone',
        'attribution_required': False,
        'title': 'A clip',
        'tags': (),
    }
    defaults.update(overrides)
    return FootageCandidate(**defaults)  # type: ignore[arg-type]


def test_candidate_is_immutable() -> None:
    """Candidates are frozen value objects."""
    import attrs
    import pytest

    candidate = _candidate()
    with pytest.raises(attrs.exceptions.FrozenInstanceError):
        candidate.width = 640  # type: ignore[misc]


def test_quality_floor_accepts_a_good_candidate() -> None:
    """A large, long-enough, permissively licensed clip passes."""
    assert passes_quality_floor(
        _candidate(),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_quality_floor_rejects_low_resolution() -> None:
    """Below the width floor is rejected."""
    assert not passes_quality_floor(
        _candidate(width=640),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_quality_floor_rejects_short_video() -> None:
    """A video shorter than the duration floor is rejected."""
    assert not passes_quality_floor(
        _candidate(duration_s=1.0),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_quality_floor_ignores_duration_for_images() -> None:
    """Stills have no duration and must not be rejected for it."""
    assert passes_quality_floor(
        _candidate(media_type='image', duration_s=None),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_empty_allowlist_permits_any_license() -> None:
    """An empty allowlist means 'no licence restriction'."""
    assert passes_quality_floor(
        _candidate(license='CC-BY-SA-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )


def test_license_allowlist_is_enforced_when_set() -> None:
    """A non-empty allowlist rejects licences outside it."""
    assert not passes_quality_floor(
        _candidate(license='CC-BY-SA-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=['pexels', 'public-domain'],
    )


def test_noncommercial_is_always_rejected() -> None:
    """NC content cannot be used on a monetized channel, allowlist or not."""
    assert not passes_quality_floor(
        _candidate(license='by-nc-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=['by-nc-4.0'],
    )


def test_noderivatives_is_always_rejected() -> None:
    """ND content cannot be edited into a video, allowlist or not."""
    assert not passes_quality_floor(
        _candidate(license='by-nc-nd-2.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=['by-nc-nd-2.0'],
    )


def test_share_alike_is_permitted() -> None:
    """SA is compatible with this use; only NC and ND are excluded."""
    assert passes_quality_floor(
        _candidate(license='by-sa-4.0'),
        min_width=1280,
        min_duration_s=3.0,
        allowed_licenses=[],
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/test_base.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named
'server.apps.generation.clients.stock'`

- [ ] **Step 3: Write the implementation**

Create `server/apps/generation/clients/stock/__init__.py`:

```python
"""Stock and public-domain footage provider clients."""
```

Create `server/apps/generation/clients/stock/base.py`:

```python
"""Shared contract for stock/archival footage providers."""

from collections.abc import Sequence
from typing import Literal, Protocol, final

import attrs

MediaType = Literal['video', 'image']


@final
@attrs.define(slots=True, frozen=True)
class FootageCandidate:
    """One searchable media item returned by a footage provider."""

    provider: str
    external_id: str
    media_type: MediaType
    download_url: str
    thumb_url: str
    source_page_url: str
    width: int
    height: int
    duration_s: float | None
    license: str
    license_url: str
    author: str
    attribution_required: bool
    title: str
    tags: tuple[str, ...]


class FootageProvider(Protocol):
    """A searchable source of stock or public-domain media."""

    name: str

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Return candidates matching the query, best-effort ordered."""
        ...


def is_commercially_usable(license_code: str) -> bool:
    """Return False for NonCommercial or NoDerivatives licences.

    These channels are monetized and every clip is edited into a longer
    work, so ``nc`` (no commercial use) and ``nd`` (no derivative works)
    material can never be used. This floor is not configurable — an empty
    ``allowed_licenses`` must not be read as permission to use NC/ND.

    >>> is_commercially_usable('by-sa-4.0')
    True
    >>> is_commercially_usable('by-nc-nd-2.0')
    False
    """
    parts = set(license_code.casefold().replace('_', '-').split('-'))
    return not ({'nc', 'nd'} & parts)


def passes_quality_floor(
    candidate: FootageCandidate,
    *,
    min_width: int,
    min_duration_s: float,
    allowed_licenses: Sequence[str],
) -> bool:
    """Return True when a candidate clears the channel's quality floor.

    An empty ``allowed_licenses`` means no *additional* restriction beyond
    the always-on NC/ND exclusion. Duration is only checked for video —
    stills legitimately have ``duration_s=None``.
    """
    if not is_commercially_usable(candidate.license):
        return False
    if candidate.width < min_width:
        return False
    if candidate.media_type == 'video':
        if candidate.duration_s is None:
            return False
        if candidate.duration_s < min_duration_s:
            return False
    return not allowed_licenses or candidate.license in allowed_licenses
```

- [ ] **Step 4: Add provider API key settings**

In `server/settings/components/common.py`, next to the existing
`EXA_API_KEY` line:

```python
PEXELS_API_KEY: str = config('PEXELS_API_KEY', default='')
PIXABAY_API_KEY: str = config('PIXABAY_API_KEY', default='')
OPENVERSE_API_TOKEN: str = config('OPENVERSE_API_TOKEN', default='')
```

Wikimedia Commons needs no key.

- [ ] **Step 5: Run tests and type checks**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_generation/test_stock/test_base.py -v --no-cov
docker compose exec web mypy server
docker compose exec web ruff check server/apps/generation/clients/stock/
docker compose exec web pytest --doctest-modules server/apps/generation/clients/stock/base.py --no-cov
```
Expected: PASS, 10 passed

- [ ] **Step 6: Commit**

```bash
git add server/apps/generation/clients/stock/ \
        server/settings/components/common.py \
        tests/test_apps/test_generation/test_stock/
git commit -m "feat(generation): add footage provider contract and settings"
```

---

## Task 7: Pexels adapter

**Files:**
- Create: `server/apps/generation/clients/stock/pexels.py`
- Create: `tests/test_apps/test_generation/test_stock/fixtures/pexels_video_search.json`
- Create: `tests/test_apps/test_generation/test_stock/fixtures/pexels_photo_search.json`
- Test: `tests/test_apps/test_generation/test_stock/test_pexels.py`

**Interfaces:**
- Consumes: `FootageCandidate`, `MediaType` from Task 6.
- Produces: `PexelsProvider` class with `name = 'pexels'` satisfying
  `FootageProvider`.

- [ ] **Step 1: Build the fixtures from the published docs**

`PEXELS_API_KEY` is not configured, so these fixtures are **doc-derived, not
live-captured** — a deliberate operator decision, with the known risk that the
mapping is verified against the documentation rather than a real response.

Read <https://www.pexels.com/api/documentation/> and hand-write two fixtures
matching the documented response shape for
`GET /videos/search` and `GET /v1/search`, three results each.

Each fixture **must** start with:

```json
{"_doc_derived": true, "_source": "https://www.pexels.com/api/documentation/",
 "_captured": "2026-07-26 — from docs, NOT a live response", ...}
```

and the test module docstring must open with:

```
WARNING: fixtures are doc-derived, not captured from a live API. Re-verify
this adapter against a real response once PEXELS_API_KEY is configured.
```

Record the exact field path used for each `FootageCandidate` attribute in the
adapter's module docstring, so a later live check is a diff rather than a
re-read.

- [ ] **Step 2: Write the failing test**

Create `tests/test_apps/test_generation/test_stock/test_pexels.py`. Load the
fixture captured in Step 1 rather than inlining JSON:

```python
"""Tests for the Pexels footage adapter.

Fixtures captured from https://api.pexels.com on the date this module was
added. Field mapping is documented in `pexels.py`.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.pexels import PexelsProvider

_FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES / name).read_text())


def _mock_response(payload: dict[str, object]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@pytest.mark.asyncio
async def test_video_search_maps_candidates() -> None:
    """Each video result becomes a well-formed FootageCandidate."""
    payload = _load('pexels_video_search.json')
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await PexelsProvider(api_key='k').search(
            'ocean waves',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.provider == 'pexels'
        assert candidate.media_type == 'video'
        assert candidate.download_url.startswith('http')
        assert candidate.thumb_url.startswith('http')
        assert candidate.width > 0
        assert candidate.duration_s is not None
        assert candidate.attribution_required is False
        assert candidate.license == 'pexels'


@pytest.mark.asyncio
async def test_photo_search_maps_candidates() -> None:
    """Photo results map to image candidates with no duration."""
    payload = _load('pexels_photo_search.json')
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await PexelsProvider(api_key='k').search(
            'ocean waves',
            media_type='image',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.media_type == 'image'
        assert candidate.duration_s is None


@pytest.mark.asyncio
async def test_rate_limit_raises_retryable() -> None:
    """HTTP 429 surfaces as RetryableProviderError with the status code."""
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 429
    resp.text = 'rate limited'
    with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=resp)):
        with pytest.raises(RetryableProviderError) as exc_info:
            await PexelsProvider(api_key='k').search(
                'x', media_type='video', orientation='landscape',
                min_width=1280, limit=3,
            )
    assert exc_info.value.status_code == 429
    assert exc_info.value.provider == 'pexels'


@pytest.mark.asyncio
async def test_missing_api_key_returns_no_candidates() -> None:
    """An unconfigured provider is skipped, not an error."""
    results = await PexelsProvider(api_key='').search(
        'x', media_type='video', orientation='landscape',
        min_width=1280, limit=3,
    )
    assert results == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/test_pexels.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: ...stock.pexels`

- [ ] **Step 4: Write the implementation**

Create `server/apps/generation/clients/stock/pexels.py`. Map fields to the
paths recorded in Step 1; the structure below is the contract, and the exact
JSON keys come from the captured fixture:

```python
"""Pexels footage provider — free stock video and photos.

Licence: Pexels licence, attribution not required.
Rate limit: 200 requests/hour on the free tier.
"""

from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_VIDEO_URL = 'https://api.pexels.com/videos/search'
_PHOTO_URL = 'https://api.pexels.com/v1/search'
_TIMEOUT_S = 20.0


@final
class PexelsProvider:
    """Searches Pexels for stock video and photography."""

    name = 'pexels'

    def __init__(self, api_key: str) -> None:
        """Initialise with the Pexels API key ('' disables the provider)."""
        self._api_key = api_key

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search Pexels and return normalised candidates."""
        if not self._api_key:
            return []
        url = _VIDEO_URL if media_type == 'video' else _PHOTO_URL
        params = {
            'query': query,
            'per_page': limit,
            'orientation': orientation,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                url,
                params=params,
                headers={'Authorization': self._api_key},
            )
        if not resp.is_success:
            raise RetryableProviderError(
                f'Pexels {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        data = resp.json()
        if media_type == 'video':
            return [
                self._video_candidate(item, min_width)
                for item in data.get('videos', [])
            ]
        return [
            self._photo_candidate(item)
            for item in data.get('photos', [])
        ]

    def _video_candidate(
        self,
        item: dict[str, Any],
        min_width: int,
    ) -> FootageCandidate:
        """Map one Pexels video result, picking the best usable rendition."""
        files = sorted(
            item.get('video_files', []),
            key=lambda f: int(f.get('width') or 0),
            reverse=True,
        )
        usable = [f for f in files if int(f.get('width') or 0) >= min_width]
        chosen = (usable[-1] if usable else files[0]) if files else {}
        user = item.get('user') or {}
        return FootageCandidate(
            provider=self.name,
            external_id=str(item.get('id', '')),
            media_type='video',
            download_url=str(chosen.get('link', '')),
            thumb_url=str(item.get('image', '')),
            source_page_url=str(item.get('url', '')),
            width=int(chosen.get('width') or item.get('width') or 0),
            height=int(chosen.get('height') or item.get('height') or 0),
            duration_s=float(item.get('duration') or 0.0),
            license='pexels',
            license_url='https://www.pexels.com/license/',
            author=str(user.get('name', '')),
            attribution_required=False,
            title=str(item.get('alt') or ''),
            tags=(),
        )

    def _photo_candidate(self, item: dict[str, Any]) -> FootageCandidate:
        """Map one Pexels photo result."""
        src = item.get('src') or {}
        return FootageCandidate(
            provider=self.name,
            external_id=str(item.get('id', '')),
            media_type='image',
            download_url=str(src.get('original', '')),
            thumb_url=str(src.get('medium', '')),
            source_page_url=str(item.get('url', '')),
            width=int(item.get('width') or 0),
            height=int(item.get('height') or 0),
            duration_s=None,
            license='pexels',
            license_url='https://www.pexels.com/license/',
            author=str(item.get('photographer', '')),
            attribution_required=False,
            title=str(item.get('alt') or ''),
            tags=(),
        )
```

`_video_candidate` picks the **smallest rendition at or above** `min_width`,
not the largest available — downloading a 4K file to crop to 1080p wastes
bandwidth and time.

- [ ] **Step 5: Run tests**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/test_pexels.py -v --no-cov`
Expected: PASS, 4 passed

- [ ] **Step 6: Commit**

```bash
git add server/apps/generation/clients/stock/pexels.py \
        tests/test_apps/test_generation/test_stock/
git commit -m "feat(generation): add Pexels footage provider adapter"
```

---

## Task 8: Pixabay and Wikimedia adapters

Two adapters in one task — they share the capture-then-map workflow and neither
is independently rejectable.

**Files:**
- Create: `server/apps/generation/clients/stock/pixabay.py`
- Create: `server/apps/generation/clients/stock/wikimedia.py`
- Create: `tests/.../fixtures/pixabay_video_search.json`
- Create: `tests/.../fixtures/pixabay_photo_search.json`
- Create: `tests/.../fixtures/wikimedia_search.json`
- Test: `tests/test_apps/test_generation/test_stock/test_pixabay.py`
- Test: `tests/test_apps/test_generation/test_stock/test_wikimedia.py`

**Interfaces:**
- Consumes: `FootageCandidate`, `MediaType` from Task 6.
- Produces: `PixabayProvider` (`name = 'pixabay'`), `WikimediaProvider`
  (`name = 'wikimedia'`), both satisfying `FootageProvider`.

- [ ] **Step 1: Fixtures — one doc-derived, one already captured**

**Pixabay:** `PIXABAY_API_KEY` is not configured. Hand-write
`pixabay_video_search.json` and `pixabay_photo_search.json` from
<https://pixabay.com/api/docs/>, with the same `_doc_derived` marker and test
docstring warning described in Task 7 Step 1.

**Wikimedia:** `wikimedia_search.json` is **already committed** — captured live
on 2026-07-26, no key needed. Read it before writing the mapping. Verified
facts from that capture, which correct earlier drafts of this plan:

- `imageinfo[0]` keys are `url`, `width`, `height`, `size`, `descriptionurl`,
  `descriptionshorturl`. **There is no `thumburl`** unless `iiurlwidth` is
  requested — fall back to `url`.
- `extmetadata` carries **`AttributionRequired`** (string `'true'`/`'false'`).
  Read it rather than hardcoding `True`; default to `True` when the key is
  absent, since over-attributing is harmless and under-attributing is not.
- `extmetadata` has **no `LicenseUrl`** key. Use `License` (a code such as
  `pd`, `cc-by-sa-4.0`) for the licence, `LicenseShortName` for display, and
  leave `license_url` empty.
- `Artist` contains HTML and needs the `_strip_html` helper.

- [ ] **Step 2: Write the failing Pixabay test**

Create `tests/test_apps/test_generation/test_stock/test_pixabay.py`:

```python
"""Tests for the Pixabay footage adapter.

Fixtures captured from https://pixabay.com/api/ on the date this module was
added. Pixabay licence does not require attribution.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.pixabay import PixabayProvider

_FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES / name).read_text())


def _mock_response(payload: dict[str, object]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@pytest.mark.asyncio
async def test_video_search_maps_candidates() -> None:
    """Video hits map to video candidates with a duration."""
    payload = _load('pixabay_video_search.json')
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await PixabayProvider(api_key='k').search(
            'ocean', media_type='video', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.provider == 'pixabay'
        assert candidate.media_type == 'video'
        assert candidate.duration_s is not None
        assert candidate.attribution_required is False


@pytest.mark.asyncio
async def test_photo_search_maps_candidates() -> None:
    """Photo hits map to image candidates with tags populated."""
    payload = _load('pixabay_photo_search.json')
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await PixabayProvider(api_key='k').search(
            'ocean', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results
    assert all(c.media_type == 'image' for c in results)
    assert all(c.duration_s is None for c in results)


@pytest.mark.asyncio
async def test_rate_limit_raises_retryable() -> None:
    """HTTP 429 surfaces as RetryableProviderError."""
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 429
    resp.text = 'rate limited'
    with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=resp)):
        with pytest.raises(RetryableProviderError):
            await PixabayProvider(api_key='k').search(
                'x', media_type='video', orientation='landscape',
                min_width=1280, limit=3,
            )


@pytest.mark.asyncio
async def test_missing_api_key_returns_no_candidates() -> None:
    """An unconfigured provider is skipped, not an error."""
    results = await PixabayProvider(api_key='').search(
        'x', media_type='video', orientation='landscape',
        min_width=1280, limit=3,
    )
    assert results == []
```

- [ ] **Step 3: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/test_pixabay.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: ...stock.pixabay`

- [ ] **Step 4: Implement the Pixabay adapter**

Create `server/apps/generation/clients/stock/pixabay.py`:

```python
"""Pixabay footage provider — free stock video and photos.

Licence: Pixabay content licence, attribution not required.
Rate limit: 100 requests/minute on the free tier.
"""

from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_VIDEO_URL = 'https://pixabay.com/api/videos/'
_PHOTO_URL = 'https://pixabay.com/api/'
_TIMEOUT_S = 20.0
_LICENSE_URL = 'https://pixabay.com/service/license-summary/'


@final
class PixabayProvider:
    """Searches Pixabay for stock video and photography."""

    name = 'pixabay'

    def __init__(self, api_key: str) -> None:
        """Initialise with the Pixabay API key ('' disables the provider)."""
        self._api_key = api_key

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search Pixabay and return normalised candidates."""
        if not self._api_key:
            return []
        url = _VIDEO_URL if media_type == 'video' else _PHOTO_URL
        params: dict[str, Any] = {
            'key': self._api_key,
            'q': query,
            'per_page': max(limit, 3),
        }
        if media_type == 'image':
            params['orientation'] = (
                'horizontal' if orientation == 'landscape' else 'vertical'
            )
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(url, params=params)
        if not resp.is_success:
            raise RetryableProviderError(
                f'Pixabay {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        hits = resp.json().get('hits', [])
        builder = (
            self._video_candidate
            if media_type == 'video'
            else self._photo_candidate
        )
        return [builder(hit, min_width) for hit in hits[:limit]]

    def _video_candidate(
        self,
        hit: dict[str, Any],
        min_width: int,
    ) -> FootageCandidate:
        """Map one Pixabay video hit to the smallest adequate rendition."""
        renditions = [
            r for r in (hit.get('videos') or {}).values()
            if isinstance(r, dict) and r.get('url')
        ]
        renditions.sort(key=lambda r: int(r.get('width') or 0))
        usable = [r for r in renditions if int(r.get('width') or 0) >= min_width]
        chosen = (usable[0] if usable else renditions[-1]) if renditions else {}
        return FootageCandidate(
            provider=self.name,
            external_id=str(hit.get('id', '')),
            media_type='video',
            download_url=str(chosen.get('url', '')),
            thumb_url=str(hit.get('userImageURL') or ''),
            source_page_url=str(hit.get('pageURL', '')),
            width=int(chosen.get('width') or 0),
            height=int(chosen.get('height') or 0),
            duration_s=float(hit.get('duration') or 0.0),
            license='pixabay',
            license_url=_LICENSE_URL,
            author=str(hit.get('user', '')),
            attribution_required=False,
            title=str(hit.get('tags', '')),
            tags=tuple(
                t.strip() for t in str(hit.get('tags', '')).split(',') if t
            ),
        )

    def _photo_candidate(
        self,
        hit: dict[str, Any],
        min_width: int,
    ) -> FootageCandidate:
        """Map one Pixabay photo hit."""
        del min_width  # photos expose a single large rendition
        return FootageCandidate(
            provider=self.name,
            external_id=str(hit.get('id', '')),
            media_type='image',
            download_url=str(hit.get('largeImageURL', '')),
            thumb_url=str(hit.get('previewURL', '')),
            source_page_url=str(hit.get('pageURL', '')),
            width=int(hit.get('imageWidth') or 0),
            height=int(hit.get('imageHeight') or 0),
            duration_s=None,
            license='pixabay',
            license_url=_LICENSE_URL,
            author=str(hit.get('user', '')),
            attribution_required=False,
            title=str(hit.get('tags', '')),
            tags=tuple(
                t.strip() for t in str(hit.get('tags', '')).split(',') if t
            ),
        )
```

- [ ] **Step 5: Write the failing Wikimedia test**

Create `tests/test_apps/test_generation/test_stock/test_wikimedia.py`:

```python
"""Tests for the Wikimedia Commons adapter.

Fixture captured from the MediaWiki API on the date this module was added.
Licences vary per file and attribution is usually REQUIRED.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.wikimedia import WikimediaProvider

_FIXTURES = Path(__file__).parent / 'fixtures'


def _mock_response(payload: dict[str, object]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@pytest.mark.asyncio
async def test_search_maps_candidates_with_licence_metadata() -> None:
    """Commons results carry licence, author, and a source page."""
    payload = json.loads((_FIXTURES / 'wikimedia_search.json').read_text())
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await WikimediaProvider().search(
            'battleship', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.provider == 'wikimedia'
        assert candidate.source_page_url.startswith('http')
        assert candidate.license


@pytest.mark.asyncio
async def test_attribution_required_is_read_from_extmetadata() -> None:
    """AttributionRequired='false' is honoured, not overridden to True."""
    payload = {'query': {'pages': {'1': {
        'pageid': 1, 'title': 'File:X.jpg',
        'imageinfo': [{
            'url': 'https://upload.test/x.jpg',
            'descriptionurl': 'https://commons.test/x',
            'width': 2000, 'height': 1400,
            'extmetadata': {
                'AttributionRequired': {'value': 'false'},
                'License': {'value': 'pd'},
                'Artist': {'value': '<a href="/x">Someone</a>'},
            },
        }],
    }}}}
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await WikimediaProvider().search(
            'x', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results[0].attribution_required is False
    assert results[0].license == 'pd'
    assert results[0].author == 'Someone'


@pytest.mark.asyncio
async def test_absent_attribution_flag_defaults_to_required() -> None:
    """A missing AttributionRequired key errs toward attributing."""
    payload = {'query': {'pages': {'1': {
        'pageid': 1, 'title': 'File:Y.jpg',
        'imageinfo': [{
            'url': 'https://upload.test/y.jpg',
            'descriptionurl': 'https://commons.test/y',
            'width': 2000, 'height': 1400,
            'extmetadata': {'License': {'value': 'cc-by-sa-4.0'}},
        }],
    }}}}
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await WikimediaProvider().search(
            'y', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results[0].attribution_required is True


@pytest.mark.asyncio
async def test_empty_result_set_returns_empty_list() -> None:
    """A search with no matches yields no candidates, not an error."""
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response({'batchcomplete': ''}),
    )):
        results = await WikimediaProvider().search(
            'zzzznomatch', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results == []


@pytest.mark.asyncio
async def test_server_error_raises_retryable() -> None:
    """A 5xx from Commons is retryable."""
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 503
    resp.text = 'unavailable'
    with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=resp)):
        with pytest.raises(RetryableProviderError):
            await WikimediaProvider().search(
                'x', media_type='image', orientation='landscape',
                min_width=1280, limit=3,
            )
```

- [ ] **Step 6: Implement the Wikimedia adapter**

Create `server/apps/generation/clients/stock/wikimedia.py`:

```python
"""Wikimedia Commons provider — public-domain and CC archival media.

No API key required. Licences vary per file and attribution is normally
required, so every candidate is flagged ``attribution_required=True``.
"""

import re
from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_API_URL = 'https://commons.wikimedia.org/w/api.php'
_TIMEOUT_S = 25.0
_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(value: str) -> str:
    """Commons extmetadata embeds HTML in Artist; render it as plain text."""
    return _TAG_RE.sub('', value).strip()


@final
class WikimediaProvider:
    """Searches Wikimedia Commons for archival images and video."""

    name = 'wikimedia'

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search Commons and return normalised candidates."""
        del orientation, min_width  # Commons has no server-side filters
        filetype = 'video' if media_type == 'video' else 'bitmap'
        params = {
            'action': 'query',
            'generator': 'search',
            'gsrsearch': f'filetype:{filetype} {query}',
            'gsrlimit': limit,
            'gsrnamespace': 6,
            'prop': 'imageinfo',
            'iiprop': 'url|size|extmetadata',
            'format': 'json',
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(_API_URL, params=params)
        if not resp.is_success:
            raise RetryableProviderError(
                f'Wikimedia {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        pages = (resp.json().get('query') or {}).get('pages') or {}
        return [
            self._candidate(page, media_type)
            for page in pages.values()
            if page.get('imageinfo')
        ]

    def _candidate(
        self,
        page: dict[str, Any],
        media_type: MediaType,
    ) -> FootageCandidate:
        """Map one Commons page with imageinfo to a candidate."""
        info = page['imageinfo'][0]
        meta = info.get('extmetadata') or {}

        def _meta(key: str) -> str:
            entry = meta.get(key) or {}
            return str(entry.get('value', '')) if isinstance(entry, dict) else ''

        # extmetadata.AttributionRequired is a string 'true'/'false' and is
        # sometimes absent. Absent defaults to True: over-attributing is
        # harmless, under-attributing is a licence violation.
        raw_required = _meta('AttributionRequired')
        attribution_required = (
            raw_required.strip().casefold() != 'false' if raw_required else True
        )
        return FootageCandidate(
            provider=self.name,
            external_id=str(page.get('pageid', '')),
            media_type=media_type,
            download_url=str(info.get('url', '')),
            thumb_url=str(info.get('thumburl') or info.get('url', '')),
            source_page_url=str(info.get('descriptionurl', '')),
            width=int(info.get('width') or 0),
            height=int(info.get('height') or 0),
            duration_s=(
                float(info.get('duration') or 0.0)
                if media_type == 'video'
                else None
            ),
            license=_meta('License') or 'unknown',
            license_url='',
            author=_strip_html(_meta('Artist')),
            attribution_required=attribution_required,
            title=str(page.get('title', '')),
            tags=(),
        )
```

- [ ] **Step 7: Run both suites**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/ -v --no-cov`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add server/apps/generation/clients/stock/pixabay.py \
        server/apps/generation/clients/stock/wikimedia.py \
        tests/test_apps/test_generation/test_stock/
git commit -m "feat(generation): add Pixabay and Wikimedia footage adapters"
```

---

## Task 9: Archival video source — resolve Openverse vs archive.org

**Files:**
- Create: `server/apps/generation/clients/stock/openverse.py`
- Create: `tests/.../fixtures/openverse_image_search.json`
- Test: `tests/test_apps/test_generation/test_stock/test_openverse.py`
- Possibly create: `server/apps/generation/clients/stock/archive_org.py` +
  its fixture and test (see Step 1)

**Interfaces:**
- Consumes: `FootageCandidate`, `MediaType` from Task 6.
- Produces: `OpenverseProvider` (`name = 'openverse'`), and — only if Step 1
  confirms it is needed — `ArchiveOrgProvider` (`name = 'archive_org'`).

- [ ] **Step 1: Read the committed fixtures — the question is already settled**

Openverse was probed on 2026-07-26: `/v1/images/` and `/v1/audio/` return 200;
`/v1/video/` and `/v1/videos/` both return **404**. Openverse serves no video.
Both fixtures are **already committed** — no key is needed for either API:

- `openverse_image_search.json`
- `archive_org_search.json`

So this task builds **both** providers, unconditionally:

1. `OpenverseProvider` — images only; returns `[]` for `media_type='video'`.
2. `ArchiveOrgProvider` — archival video via `advancedsearch.php` +
   `metadata/{identifier}`.

Verified facts from the captured fixtures:

- **Openverse** results carry `url` (full image), `thumbnail`,
  `foreign_landing_url`, `creator`, `license` (bare code like `by-nc-nd`),
  `license_version`, `license_url`, `width`, `height`, `title`, `tags`,
  `attribution`, `provider`, `source`.
- **Openverse returns NC and ND content** — the sample's first result is
  `by-nc-nd`. `passes_quality_floor` from Task 6 rejects those, but the
  adapter must still map the licence faithfully so the filter can see it.
  Do **not** normalise `by-nc-nd` to `by`.
- **archive.org** `advancedsearch.php` returns `response.docs[]` where each doc
  has only the fields named in `fl[]`, and **requested fields are omitted when
  the item lacks them** — the captured sample requested `licenseurl` and the
  docs came back with only `identifier` and `title`. Treat every field except
  `identifier` as optional, and default `license` to `'unknown'` with
  `attribution_required=True` when `licenseurl` is absent.
- Getting a playable archive.org file URL needs a second call to
  `https://archive.org/metadata/{identifier}`; build the download URL as
  `https://archive.org/download/{identifier}/{file_name}` from the first
  `.mp4` in that response's `files[]`.

- [ ] **Step 2: Write the failing Openverse test**

Create `tests/test_apps/test_generation/test_stock/test_openverse.py`:

```python
"""Tests for the Openverse adapter.

Fixture captured from https://api.openverse.org/v1/ on the date this module
was added. See openverse.py for the media-type support finding.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.openverse import OpenverseProvider

_FIXTURES = Path(__file__).parent / 'fixtures'


def _mock_response(payload: dict[str, object]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@pytest.mark.asyncio
async def test_image_search_maps_candidates() -> None:
    """CC-licensed image results map with licence and creator populated."""
    payload = json.loads(
        (_FIXTURES / 'openverse_image_search.json').read_text(),
    )
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await OpenverseProvider(token='').search(
            'battleship', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results
    for candidate in results:
        assert candidate.provider == 'openverse'
        assert candidate.media_type == 'image'
        assert candidate.license
        assert candidate.source_page_url.startswith('http')


@pytest.mark.asyncio
async def test_public_domain_does_not_require_attribution() -> None:
    """CC0/PDM candidates are flagged as attribution-optional."""
    payload = {
        'results': [{
            'id': 'abc',
            'title': 'A public domain photo',
            'url': 'https://example.test/full.jpg',
            'thumbnail': 'https://example.test/thumb.jpg',
            'foreign_landing_url': 'https://example.test/page',
            'width': 2000,
            'height': 1400,
            'license': 'cc0',
            'license_version': '1.0',
            'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
            'creator': 'Someone',
        }],
    }
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await OpenverseProvider(token='').search(
            'x', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results[0].attribution_required is False


@pytest.mark.asyncio
async def test_by_license_requires_attribution() -> None:
    """CC-BY family candidates require attribution."""
    payload = {
        'results': [{
            'id': 'def',
            'title': 'A CC-BY photo',
            'url': 'https://example.test/full.jpg',
            'thumbnail': 'https://example.test/thumb.jpg',
            'foreign_landing_url': 'https://example.test/page',
            'width': 2000,
            'height': 1400,
            'license': 'by-sa',
            'license_version': '4.0',
            'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
            'creator': 'Someone',
        }],
    }
    with patch('httpx.AsyncClient.get', new=AsyncMock(
        return_value=_mock_response(payload),
    )):
        results = await OpenverseProvider(token='').search(
            'x', media_type='image', orientation='landscape',
            min_width=1280, limit=3,
        )
    assert results[0].attribution_required is True


@pytest.mark.asyncio
async def test_video_media_type_returns_empty() -> None:
    """Openverse indexes no video; the provider declines rather than fails."""
    results = await OpenverseProvider(token='').search(
        'x', media_type='video', orientation='landscape',
        min_width=1280, limit=3,
    )
    assert results == []
```

If Step 1 found that Openverse *does* serve video, replace the last test with
one asserting video candidates map correctly.

- [ ] **Step 3: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/test_openverse.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: ...stock.openverse`

- [ ] **Step 4: Implement the Openverse adapter**

Create `server/apps/generation/clients/stock/openverse.py`:

```python
"""Openverse provider — CC-licensed and public-domain media.

Media-type support: images only (verified against the live API — see the
project design doc, which originally assumed video support). Video requests
return an empty list so the provider can sit in a channel's priority list
without breaking video-preferring scenes.

An API token raises rate limits but is not required.
"""

from typing import Any, final

import httpx

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    MediaType,
)
from server.common.exceptions import RetryableProviderError

_IMAGE_URL = 'https://api.openverse.org/v1/images/'
_TIMEOUT_S = 25.0
_NO_ATTRIBUTION_LICENSES = frozenset({'cc0', 'pdm'})


@final
class OpenverseProvider:
    """Searches Openverse for CC-licensed still imagery."""

    name = 'openverse'

    def __init__(self, token: str = '') -> None:
        """Initialise with an optional Openverse API token."""
        self._token = token

    async def search(
        self,
        query: str,
        *,
        media_type: MediaType,
        orientation: str,
        min_width: int,
        limit: int,
    ) -> list[FootageCandidate]:
        """Search Openverse images; video is unsupported and returns []."""
        del orientation, min_width
        if media_type != 'image':
            return []
        headers = (
            {'Authorization': f'Bearer {self._token}'} if self._token else {}
        )
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                _IMAGE_URL,
                params={'q': query, 'page_size': limit},
                headers=headers,
            )
        if not resp.is_success:
            raise RetryableProviderError(
                f'Openverse {resp.status_code}: {resp.text[:200]}',
                provider=self.name,
                status_code=resp.status_code,
            )
        return [
            self._candidate(item)
            for item in resp.json().get('results', [])
        ]

    def _candidate(self, item: dict[str, Any]) -> FootageCandidate:
        """Map one Openverse result to a candidate."""
        license_code = str(item.get('license', '')).lower()
        version = str(item.get('license_version', ''))
        label = f'{license_code}-{version}'.strip('-') or 'unknown'
        return FootageCandidate(
            provider=self.name,
            external_id=str(item.get('id', '')),
            media_type='image',
            download_url=str(item.get('url', '')),
            thumb_url=str(item.get('thumbnail') or item.get('url', '')),
            source_page_url=str(item.get('foreign_landing_url', '')),
            width=int(item.get('width') or 0),
            height=int(item.get('height') or 0),
            duration_s=None,
            license=label,
            license_url=str(item.get('license_url', '')),
            author=str(item.get('creator', '')),
            attribution_required=(
                license_code not in _NO_ATTRIBUTION_LICENSES
            ),
            title=str(item.get('title', '')),
            tags=(),
        )
```

- [ ] **Step 5: Add the archive.org provider**

Write `test_archive_org.py` against the committed `archive_org_search.json`,
covering: candidate mapping from a search doc plus its `metadata` response, a
doc missing `licenseurl` (defaults to `license='unknown'` and
`attribution_required=True`), an empty `response.docs`, an item whose
`metadata.files[]` has no `.mp4` (skipped, not crashed), and a 5xx retryable
error.

Then implement `ArchiveOrgProvider` with `name = 'archive_org'`, returning `[]`
for `media_type='image'` (it is the archival **video** source; Wikimedia and
Openverse cover stills). Two calls per result: `advancedsearch.php` for
identifiers, then `metadata/{identifier}` for the file list. Set
`attribution_required` from `licenseurl` with the same CC0/PDM rule as
Openverse, defaulting to `True` when absent.

- [ ] **Step 6: Run the full stock suite**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/ -v --no-cov`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add server/apps/generation/clients/stock/ \
        tests/test_apps/test_generation/test_stock/
git commit -m "feat(generation): add Openverse adapter and archival video source"
```

---

## Task 10: Cached, rate-limited multi-provider search facade

**Files:**
- Create: `server/apps/generation/clients/stock/cache.py`
- Create: `server/apps/generation/clients/stock/registry.py`
- Test: `tests/test_apps/test_generation/test_stock/test_cache.py`
- Test: `tests/test_apps/test_generation/test_stock/test_registry.py`

**Interfaces:**
- Consumes: `FootageCandidate`, `FootageProvider`, `passes_quality_floor`
  (Task 6); all provider classes (Tasks 7–9).
- Produces:
  - `normalize_query(query: str) -> str`.
  - `async def cached_search(provider, query, *, media_type, orientation,
    min_width, limit, ttl_s=86400) -> list[FootageCandidate]`.
  - `build_providers(enabled: Sequence[str]) -> list[FootageProvider]`.
  - `async def search_candidates(*, providers, query, media_type, orientation,
    min_width, min_duration_s, allowed_licenses, limit)
    -> list[FootageCandidate]` — ordered priority with early exit, skipping
    providers that raised a 429 during this call.

- [ ] **Step 1: Write the failing cache test**

Create `tests/test_apps/test_generation/test_stock/test_cache.py`:

```python
"""Tests for footage search caching."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.generation.clients.stock.cache import (
    cached_search,
    normalize_query,
)


def _candidate() -> FootageCandidate:
    return FootageCandidate(
        provider='pexels', external_id='1', media_type='video',
        download_url='https://e.test/v.mp4', thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p', width=1920, height=1080,
        duration_s=10.0, license='pexels', license_url='',
        author='A', attribution_required=False, title='t', tags=(),
    )


def test_normalize_query_is_stable() -> None:
    """Case and whitespace differences produce the same cache key."""
    assert normalize_query('  Ocean   WAVES ') == normalize_query('ocean waves')


@pytest.mark.asyncio
async def test_cache_miss_calls_provider_and_stores() -> None:
    """On a miss the provider runs and the result is written to Redis."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock(return_value=[_candidate()])

    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    with patch(
        'server.apps.generation.clients.stock.cache.get_redis',
        return_value=redis,
    ):
        results = await cached_search(
            provider, 'ocean waves', media_type='video',
            orientation='landscape', min_width=1280, limit=3,
        )

    assert len(results) == 1
    provider.search.assert_awaited_once()
    redis.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_hit_skips_the_provider() -> None:
    """A cached payload is returned without spending provider quota."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock()

    payload = json.dumps([attrs_asdict_of(_candidate())]).encode()
    redis = MagicMock()
    redis.get = AsyncMock(return_value=payload)
    redis.set = AsyncMock()

    with patch(
        'server.apps.generation.clients.stock.cache.get_redis',
        return_value=redis,
    ):
        results = await cached_search(
            provider, 'ocean waves', media_type='video',
            orientation='landscape', min_width=1280, limit=3,
        )

    assert len(results) == 1
    provider.search.assert_not_awaited()


def attrs_asdict_of(candidate: FootageCandidate) -> dict[str, object]:
    """Serialise a candidate the way the cache does."""
    import attrs

    data = attrs.asdict(candidate)
    data['tags'] = list(data['tags'])
    return data


@pytest.mark.asyncio
async def test_corrupt_cache_entry_falls_back_to_provider() -> None:
    """Unparseable cached bytes must not break the search."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock(return_value=[_candidate()])

    redis = MagicMock()
    redis.get = AsyncMock(return_value=b'not json')
    redis.set = AsyncMock()

    with patch(
        'server.apps.generation.clients.stock.cache.get_redis',
        return_value=redis,
    ):
        results = await cached_search(
            provider, 'ocean waves', media_type='video',
            orientation='landscape', min_width=1280, limit=3,
        )

    assert len(results) == 1
    provider.search.assert_awaited_once()
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_stock/test_cache.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: ...stock.cache`

- [ ] **Step 3: Implement the cache**

Create `server/apps/generation/clients/stock/cache.py`:

```python
"""Redis-backed caching for footage provider searches.

Provider quotas are small (Pexels allows 200 requests/hour) while a single
documentary fans out over ~60 scenes. Caching by normalised query means shard
retries, gate swaps, and stage reruns cost no additional quota.
"""

import asyncio
import json
import re
from typing import Any

import attrs
import structlog

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    FootageProvider,
    MediaType,
)
from server.common.redis_client import get_redis

logger = structlog.get_logger(__name__)

_WHITESPACE_RE = re.compile(r'\s+')
_DEFAULT_TTL_S = 86_400
_MAX_CONCURRENT_PER_PROVIDER = 4

# One semaphore per provider name, shared across all shards in this worker
# process. A 60-way scene fan-out would otherwise open 60 simultaneous
# connections to the same provider and trip rate limiting immediately.
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _semaphore(provider_name: str) -> asyncio.Semaphore:
    """Return the shared concurrency limiter for one provider."""
    if provider_name not in _SEMAPHORES:
        _SEMAPHORES[provider_name] = asyncio.Semaphore(
            _MAX_CONCURRENT_PER_PROVIDER,
        )
    return _SEMAPHORES[provider_name]


def normalize_query(query: str) -> str:
    """Return a canonical cache form of a search query."""
    return _WHITESPACE_RE.sub(' ', query.strip().casefold())


def _cache_key(
    provider_name: str,
    query: str,
    media_type: MediaType,
    orientation: str,
    limit: int,
) -> str:
    """Build the Redis key for one provider search."""
    normalized = normalize_query(query)
    return (
        f'footage:{provider_name}:{media_type}:'
        f'{orientation}:{limit}:{normalized}'
    )


def _serialize(candidates: list[FootageCandidate]) -> bytes:
    """Encode candidates as a JSON array."""
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        data = attrs.asdict(candidate)
        data['tags'] = list(data['tags'])
        payload.append(data)
    return json.dumps(payload).encode()


def _deserialize(raw: bytes) -> list[FootageCandidate] | None:
    """Decode cached bytes, returning None when the entry is unusable."""
    try:
        rows = json.loads(raw)
        return [
            FootageCandidate(**{**row, 'tags': tuple(row.get('tags', []))})
            for row in rows
        ]
    except (ValueError, TypeError) as exc:
        logger.warning('footage_cache_corrupt', error=str(exc))
        return None


async def cached_search(
    provider: FootageProvider,
    query: str,
    *,
    media_type: MediaType,
    orientation: str,
    min_width: int,
    limit: int,
    ttl_s: int = _DEFAULT_TTL_S,
) -> list[FootageCandidate]:
    """Search a provider, reading through a Redis cache."""
    key = _cache_key(provider.name, query, media_type, orientation, limit)
    redis = get_redis()
    raw = await redis.get(key)
    if raw:
        cached = _deserialize(raw)
        if cached is not None:
            return cached

    async with _semaphore(provider.name):
        results = await provider.search(
            query,
            media_type=media_type,
            orientation=orientation,
            min_width=min_width,
            limit=limit,
        )
    await redis.set(key, _serialize(results), ex=ttl_s)
    return results
```

The semaphore wraps only the provider call, not the cache read — a cache hit
must never queue behind in-flight network requests.

- [ ] **Step 4: Write the failing registry test**

Create `tests/test_apps/test_generation/test_stock/test_registry.py`:

```python
"""Tests for provider ordering, early exit, and 429 skip behaviour."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.generation.clients.stock.registry import (
    build_providers,
    search_candidates,
)
from server.common.exceptions import RetryableProviderError


def _candidate(provider: str, idx: int, width: int = 1920) -> FootageCandidate:
    return FootageCandidate(
        provider=provider, external_id=str(idx), media_type='video',
        download_url='https://e.test/v.mp4', thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p', width=width, height=1080,
        duration_s=10.0, license='pexels', license_url='',
        author='A', attribution_required=False, title='t', tags=(),
    )


def _provider(name: str, results: list[FootageCandidate]) -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.search = AsyncMock(return_value=results)
    return provider


def test_build_providers_preserves_order() -> None:
    """Provider priority order from config is preserved."""
    providers = build_providers(['wikimedia', 'pexels'])
    assert [p.name for p in providers] == ['wikimedia', 'pexels']


def test_build_providers_ignores_unknown_names() -> None:
    """An unrecognised provider name is skipped, not fatal."""
    providers = build_providers(['pexels', 'not_a_provider'])
    assert [p.name for p in providers] == ['pexels']


@pytest.mark.asyncio
async def test_early_exit_skips_lower_priority_providers() -> None:
    """Once the limit is met, later providers are never called."""
    first = _provider('pexels', [_candidate('pexels', i) for i in range(8)])
    second = _provider('pixabay', [_candidate('pixabay', 99)])

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=lambda p, *a, **k: p.search.return_value),
    ):
        results = await search_candidates(
            providers=[first, second], query='ocean', media_type='video',
            orientation='landscape', min_width=1280, min_duration_s=3.0,
            allowed_licenses=[], limit=8,
        )

    assert len(results) == 8
    assert {c.provider for c in results} == {'pexels'}


@pytest.mark.asyncio
async def test_falls_through_when_first_provider_is_thin() -> None:
    """A provider returning too few results falls through to the next."""
    first = _provider('pexels', [_candidate('pexels', 0)])
    second = _provider('pixabay', [_candidate('pixabay', i) for i in range(5)])

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=lambda p, *a, **k: p.search.return_value),
    ):
        results = await search_candidates(
            providers=[first, second], query='ocean', media_type='video',
            orientation='landscape', min_width=1280, min_duration_s=3.0,
            allowed_licenses=[], limit=6,
        )

    assert len(results) == 6
    assert {c.provider for c in results} == {'pexels', 'pixabay'}


@pytest.mark.asyncio
async def test_quality_floor_filters_results() -> None:
    """Candidates below the width floor never reach the caller."""
    provider = _provider('pexels', [
        _candidate('pexels', 0, width=640),
        _candidate('pexels', 1, width=1920),
    ])

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=lambda p, *a, **k: p.search.return_value),
    ):
        results = await search_candidates(
            providers=[provider], query='ocean', media_type='video',
            orientation='landscape', min_width=1280, min_duration_s=3.0,
            allowed_licenses=[], limit=8,
        )

    assert [c.external_id for c in results] == ['1']


@pytest.mark.asyncio
async def test_rate_limited_provider_is_skipped_not_fatal() -> None:
    """A 429 from one provider must not fail the whole search."""
    first = _provider('pexels', [])
    second = _provider('pixabay', [_candidate('pixabay', 0)])

    async def _side_effect(p: MagicMock, *args: object, **kw: object) -> object:
        if p.name == 'pexels':
            raise RetryableProviderError('rate', provider='pexels',
                                         status_code=429)
        return p.search.return_value

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=_side_effect),
    ):
        results = await search_candidates(
            providers=[first, second], query='ocean', media_type='video',
            orientation='landscape', min_width=1280, min_duration_s=3.0,
            allowed_licenses=[], limit=8,
        )

    assert [c.provider for c in results] == ['pixabay']


@pytest.mark.asyncio
async def test_non_rate_limit_error_propagates() -> None:
    """A 5xx is a real failure and must reach the stage's retry logic."""
    provider = _provider('pexels', [])

    async def _side_effect(p: MagicMock, *args: object, **kw: object) -> object:
        raise RetryableProviderError('boom', provider='pexels',
                                     status_code=503)

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=_side_effect),
    ):
        with pytest.raises(RetryableProviderError):
            await search_candidates(
                providers=[provider], query='ocean', media_type='video',
                orientation='landscape', min_width=1280, min_duration_s=3.0,
                allowed_licenses=[], limit=8,
            )
```

- [ ] **Step 5: Implement the registry**

Create `server/apps/generation/clients/stock/registry.py`:

```python
"""Provider registry and ordered multi-provider candidate search."""

from collections.abc import Sequence

import structlog
from django.conf import settings

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    FootageProvider,
    MediaType,
    passes_quality_floor,
)
from server.apps.generation.clients.stock.cache import cached_search
from server.apps.generation.clients.stock.archive_org import ArchiveOrgProvider
from server.apps.generation.clients.stock.openverse import OpenverseProvider
from server.apps.generation.clients.stock.pexels import PexelsProvider
from server.apps.generation.clients.stock.pixabay import PixabayProvider
from server.apps.generation.clients.stock.wikimedia import WikimediaProvider
from server.common.exceptions import RetryableProviderError

logger = structlog.get_logger(__name__)

_RATE_LIMIT_STATUS = 429


def build_providers(enabled: Sequence[str]) -> list[FootageProvider]:
    """Instantiate the named providers, preserving priority order."""
    factories = {
        'pexels': lambda: PexelsProvider(
            api_key=getattr(settings, 'PEXELS_API_KEY', ''),
        ),
        'pixabay': lambda: PixabayProvider(
            api_key=getattr(settings, 'PIXABAY_API_KEY', ''),
        ),
        'wikimedia': WikimediaProvider,
        'openverse': lambda: OpenverseProvider(
            token=getattr(settings, 'OPENVERSE_API_TOKEN', ''),
        ),
        'archive_org': ArchiveOrgProvider,
    }
    providers: list[FootageProvider] = []
    for name in enabled:
        factory = factories.get(name)
        if factory is None:
            logger.warning('footage_provider_unknown', provider=name)
            continue
        providers.append(factory())
    return providers


async def search_candidates(
    *,
    providers: Sequence[FootageProvider],
    query: str,
    media_type: MediaType,
    orientation: str,
    min_width: int,
    min_duration_s: float,
    allowed_licenses: Sequence[str],
    limit: int,
) -> list[FootageCandidate]:
    """Search providers in priority order, stopping once ``limit`` is met.

    A provider that reports rate limiting (HTTP 429) is skipped for this
    call so a single exhausted quota cannot fail the scene. Other provider
    errors propagate to the stage's retry handling.
    """
    collected: list[FootageCandidate] = []
    for provider in providers:
        if len(collected) >= limit:
            break
        try:
            found = await cached_search(
                provider,
                query,
                media_type=media_type,
                orientation=orientation,
                min_width=min_width,
                limit=limit,
            )
        except RetryableProviderError as exc:
            if exc.status_code == _RATE_LIMIT_STATUS:
                logger.warning(
                    'footage_provider_rate_limited',
                    provider=provider.name,
                    query=query,
                )
                continue
            raise
        collected.extend(
            candidate
            for candidate in found
            if passes_quality_floor(
                candidate,
                min_width=min_width,
                min_duration_s=min_duration_s,
                allowed_licenses=allowed_licenses,
            )
        )
    return collected[:limit]
```

- [ ] **Step 6: Run the full stock suite with coverage**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_generation/test_stock/ -v
docker compose exec web mypy server
docker compose exec web ruff check server/apps/generation/clients/stock/
docker compose exec web lint-imports
```
Expected: all PASS, coverage 100% for the `stock` package

- [ ] **Step 7: Commit**

```bash
git add server/apps/generation/clients/stock/cache.py \
        server/apps/generation/clients/stock/registry.py \
        tests/test_apps/test_generation/test_stock/
git commit -m "feat(generation): add cached rate-aware multi-provider search"
```

---

## Task 11: Full-suite verification gate

No new code. This task proves the foundations changed nothing.

- [ ] **Step 1: Run the entire suite with the coverage gate**

Run: `docker compose exec web pytest`
Expected: PASS with 100% coverage. Any coverage gap is in code added by Tasks
1–10 and needs a test, not a pragma.

- [ ] **Step 2: Run every static check**

Run:
```bash
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web mypy server
docker compose exec web lint-imports
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: all clean

- [ ] **Step 3: Prove `longform_v1` is untouched**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_pipelines/ -v
```
Expected: PASS. Confirm specifically that `test_assembly.py`, `test_motion.py`,
and `test_image_gen.py` required **no edits** during Tasks 1–10. If any needed
changing, the isolation goal was missed — document why in the commit.

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: verification pass for documentary foundations"
```

---

## Done criteria

- `resolve_role()` returns today's stage keys for every existing blueprint.
- `test_assembly.py`, `test_motion.py`, `test_image_gen.py` pass unedited.
- Three migrations applied and `lintmigrations`-clean.
- Four (or five, per Task 9) provider adapters, each tested against a **real
  captured** response fixture.
- Multi-provider search is cached, order-respecting, and 429-tolerant.
- Full suite green at 100% coverage; all static checks clean.
- Task 9's Openverse video finding is reported so the design doc can be
  corrected.
