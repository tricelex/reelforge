# Clipping feature: fully-featured "mini CapCut" render + editor

Date: 2026-07-06
Status: Approved for implementation planning

## 1. Context

The clipping feature renders short vertical clips from a source video through a
10-stage synchronous ffmpeg pipeline (`ClipRenderPipeline`,
`server/apps/rendering/clip_stages/`), configured per `ClipCandidate` via
`ClipStyleConfig`, `ClipLayoutConfig`, and `ClipTimedOverlay`. A Next.js app in a
sibling repo (`reelforge-frontend`) is the operator-facing editor, generated
against this backend's OpenAPI schema via `orval`.

An audit of both repos surfaced that several style options already exposed in
the editor UI are silent no-ops in the renderer, and several `LibraryAssetKind`
values anticipated in the schema (`FONT`, `TRANSITION`, `SFX`, `LUT`) were never
wired up anywhere. This design fixes those gaps and, per an explicit request to
go all-in, expands the clipping feature to a full CapCut-parity style/effects
layer on top of the existing single-clip-candidate render pipeline.

**Scope boundary:** this is not a rewrite into a general multi-track NLE. Every
feature below is still "configure how this one clip candidate renders" — no
arbitrary multi-clip timelines, no drag-and-drop track editing. That would be a
different product built on a different architecture.

## 2. Goals

- Make every currently-exposed style option in the editor actually take effect
  in the rendered output (transitions, image overlays, caption animation).
- Add a real font system: a curated bundled set plus custom upload.
- Expand transitions to a full CapCut-style palette, including custom
  transition-video assets.
- Add video/picture-in-picture overlays, entrance/exit animation on overlays
  and the hook, a karaoke-highlight caption style, color grading + LUTs, speed
  ramp, blurred-background fit mode, and a sound-effect library.
- Close out every currently-unused `LibraryAssetKind` that belongs to this
  pipeline (`FONT`, `TRANSITION`, `SFX`, `LUT`).
- Keep the pipeline-blueprint DAG and the 100%-coverage/zero-downtime-migration
  constraints intact.

## 3. Non-goals

- General multi-track timeline editing, arbitrary multi-clip composition.
- TTS/voice cloning, AI-generated video effects.
- Pixel-level distortion effects (glitch, VHS scan lines, camera shake) — poor
  effort-to-value ratio versus everything else here; can be a later addition.
- `LibraryAssetKind.BACKGROUND` / `CHARACTER_REF` / `CAPTION_STYLE` — these
  belong to a different (longform/AI-generation) pipeline, not this renderer.
- Changing the pipeline-blueprint DAG shape (see §11 — not needed).

## 4. Font system

**Curated set.** Vendor ~16 OFL-licensed Google Fonts as `.ttf` files directly
in the repo at `server/apps/rendering/fonts/`: Montserrat Bold, Poppins Bold,
Inter Bold, Roboto Bold, Oswald Bold, Bebas Neue, Anton, Archivo Black,
Bangers, Permanent Marker, Caveat Bold, Lobster, Playfair Display Bold,
Righteous, Luckiest Guy, Pacifico. A new `CaptionFont` `TextChoices` enum (one
value per font) is shared by every font field below — one dropdown, four
places it's used. A small registry module,
`server/apps/rendering/clip_stages/fonts.py`, maps each choice to its bundled
file path and known internal family name.

**Custom upload.** Wires up the already-defined-but-unused
`LibraryAssetKind.FONT`. Users upload a `.ttf`/`.otf` as a `LibraryAsset`; at
ingest time (`assets/tasks.py`, alongside the existing music/video probing) we
extract the font's real internal family name via `fonttools` (new pure-Python
dependency, no system packages needed) and store it in `LibraryAsset.meta`.
Four new nullable FK fields — `caption_font_asset`, `hook_font_asset`,
`watermark_font_asset` on `ClipStyleConfig`, and `font_asset` on
`ClipTimedOverlay` — override the curated choice when set.

**Rendering mechanics — no Docker/fontconfig changes needed.**
- `drawtext`-based stages (hook, watermark text, overlay text) use `fontfile=`
  pointing straight at a file path — curated bundled file or a temp file
  written from the custom asset's bytes (same pattern already used for
  `watermark_image`/`intro_asset`/`outro_asset`). No name resolution involved.
- The caption stage (`subtitles=...`, libass) resolves fonts by family name
  against a `fontsdir` directory. Each render assembles a per-render fonts
  folder (bundled curated set + any custom asset referenced by this render's
  style config) under the existing `tmp/clip_renders/<render_id>/` scratch
  dir, and passes it as `fontsdir` in the `subtitles` filter string.

**Frontend.** Replace the free-text "Font" inputs in `CaptionsSection` and
`HookSection` with a new `FontPicker` component (grouped `EnumSelect` +
"Custom…" option that reveals the existing `LibraryAssetField` filtered to
`kindFilter="FONT"`). Add the same picker to `WatermarkSection` (new) and
`OverlaysPanel`'s text-overlay editor (new).

## 5. Transitions

**The bug.** `intro_transition`/`outro_transition` are a working dropdown in
`AudioPanel` (None/Crossfade/Fade to Black), persisted to the DB, but
`IntroConcatStage`/`OutroConcatStage` always do a hard concat regardless — the
selected value has never once affected output.

**The fix + expansion.** `TransitionStyle` grows to:

| Enum value | Mechanism |
|---|---|
| `NONE` | unchanged fast path — stream-copy concat, no re-encode |
| `CROSSFADE` | ffmpeg `xfade=fade` |
| `FADE_BLACK` | `xfade=fadeblack` |
| `FADE_WHITE` | `xfade=fadewhite` |
| `SLIDE_LEFT` / `SLIDE_RIGHT` / `SLIDE_UP` / `SLIDE_DOWN` | `xfade=slideleft/right/up/down` |
| `WIPE_LEFT` / `WIPE_RIGHT` | `xfade=wipeleft/wiperight` |
| `ZOOM_IN` | `xfade=zoomin` |
| `CUSTOM_ASSET` | composite an uploaded transition-video asset over the boundary (see below) |

Two new fields, `intro_transition_duration_sec` / `outro_transition_duration_sec`
(default 0.5s), surfaced as a `NumberField` beside each dropdown.

**Mechanics for the procedural transitions:** when not `NONE`/`CUSTOM_ASSET`,
probe both clips' durations with a new sync ffprobe helper
(`clip_stages/probe.py::sync_ffprobe_duration`, mirroring the existing pattern
in `assets/tasks.py::_ffprobe` since these stages run via `subprocess.run`, not
asyncio), compute the `xfade` `offset` (first clip's duration minus transition
duration), and run one `ffmpeg -filter_complex "xfade=...;acrossfade=..."`
call. **Edge case to guard explicitly:** clamp the transition duration to at
most ~90% of the shorter of the two clip durations, so a 2-second intro with a
configured 3-second crossfade can't produce a negative/invalid `xfade` offset.

**Custom transition assets — closes out `LibraryAssetKind.TRANSITION`.** New
nullable FKs `intro_transition_asset` / `outro_transition_asset` on
`ClipStyleConfig` (kind=`TRANSITION`). When `TransitionStyle.CUSTOM_ASSET` is
selected, the uploaded transition clip (e.g. a light-leak/film-burn overlay) is
composited over the boundary via a screen/blend filter instead of `xfade`.
This is the actual "Transitions" drawer CapCut ships.

**Frontend.** `INTRO_TRANSITION_OPTIONS`/`OUTRO_TRANSITION_OPTIONS` are
auto-derived from the OpenAPI-generated enum via `enumOptions()` — no manual
changes needed there once the client is regenerated. Add the two duration
`NumberField`s and, when `CUSTOM_ASSET` is selected, a `LibraryAssetField`
(`kindFilter="TRANSITION"`) to `AudioPanel`.

## 6. Overlays: image fix, video/PIP, animation

**Image overlays don't render (bug).** `ClipTimedOverlay` already supports
`overlay_type=IMAGE` with an `image_asset`, exposed in `OverlaysPanel` — but
`TimedOverlayStage.run()` only ever reads `overlay.text`, silently skipping
image overlays. Fix: branch on `overlay_type`, reusing the
scale+overlay+timed-`enable` approach `WatermarkStage._image_watermark`
already uses. Needs one new field, `width` (px, nullable int), since overlays
currently have no size control for images.

**Video / picture-in-picture overlays (new).** `OverlayType` gains `VIDEO`.
New nullable `video_asset` FK and `shape` field (`RECTANGLE` / `CIRCLE` /
`ROUNDED`) on `ClipTimedOverlay`. Rendered as a secondary clip composited over
the main one for its active time window, masked via an alpha mask (`geq` or a
precomputed circular/rounded-rect mask) for the circle/rounded shapes —
the classic reaction-cam bubble.

**Overlay animation (new).** New `animation` field on `ClipTimedOverlay`
(`NONE` / `FADE` / `POP` / `SLIDE_LEFT` / `SLIDE_RIGHT` / `SLIDE_UP` /
`SLIDE_DOWN`), a short (~0.3s) entrance/exit effect at the edges of the
overlay's active window:
- Text: `drawtext`'s `alpha` and `x`/`y` options accept time-based
  expressions, so fade/slide is expressed directly in the same filter, gated
  on `t` relative to `start_sec`/`end_sec`.
- Image/video: two chained `fade` filters (`alpha=1`) on the overlay stream
  before compositing, for the in/out window.

**Hook entrance animation (new).** New `hook_animation` field on
`ClipStyleConfig`, reusing the exact technique above — the hook currently just
snaps on/off.

## 7. Captions: animation wiring, karaoke-highlight, uppercase

**Caption animation is a no-op (bug).** `caption_animation`
(`POP`/`FADE`/`NONE`) is selectable and persisted but `ASSGenerator` never
reads it. Fix in `ASSGenerator._dialogue()`: prefix dialogue text with an ASS
override tag — `\fad(t1,t2)` for `FADE`, a `\t()` scale-bounce tag for `POP`.
Small, isolated change.

**Karaoke-highlight caption style (new).** A 5th `CaptionStyle`,
`KARAOKE_HIGHLIGHT`: the full sentence stays on screen with the
currently-spoken word highlighted in an accent color (the "bouncing highlight"
look from CapCut/Opus Clip). Implemented as overlapping ASS dialogue lines —
one per word-time-window, each showing the full segment text with one word's
color overridden via an inline `\c` tag. New `caption_highlight_color` field.

**Uppercase toggle (new).** `caption_uppercase` boolean on `ClipStyleConfig` —
trivial `.upper()` on caption text at ASS-generation time.

## 8. Watermark: color, font, position

**No dedicated color (bug).** `_text_watermark` falls back to `caption_color`
(there's a comment in the code admitting this). New `watermark_color` field
closes it.

**No font choice (gap).** New `watermark_font` (`CaptionFont` choice) +
`watermark_font_asset` FK, reusing the font system in §4.

**More positions (new).** `WatermarkPosition` gains `CENTER` and `TILED`.
`TILED` computes a grid of repeated instances spanning the frame (derived from
watermark size + frame size), each at reduced opacity — the common
"anti-repost" watermark pattern, done via multiple chained `overlay=` filter
instances (modest count, fine for short-form clip durations).

## 9. Color grading & filters (new)

New `color_filter` field on `ClipStyleConfig` — a preset enum (`NONE`,
`VIVID`, `MOODY`, `WARM`, `COOL`, `BLACK_WHITE`, `VINTAGE`), each a fixed
combination of ffmpeg `eq`/`curves` parameters. Plus manual `brightness`,
`contrast`, `saturation` float fields (default 0 = no change) that always
layer on top of whichever preset is active, including `NONE` — the preset
sets baseline `eq`/`curves` values and the manual fields add deltas on top of
them in the same filter. New stage runs immediately after trim/crop, before
any text is burned in, so grading never affects caption/watermark legibility
choices made downstream.

**Custom LUT — closes out `LibraryAssetKind.LUT`.** New nullable `lut_asset`
FK (kind=`LUT`). When set, a `.cube` file is applied via ffmpeg's `lut3d`
filter, taking precedence over `color_filter`/manual adjustments.

## 10. Speed ramp (new)

New `playback_speed` float field on `ClipStyleConfig` (range 0.25–4.0, default
1.0). Folded into the trim/crop stage's existing ffmpeg command: `setpts` for
video, chained `atempo` calls for audio (a single `atempo` instance is limited
to the 0.5–2.0 range, so speeds outside that need 2+ chained instances).

**Critical correctness note, called out explicitly so it doesn't become a
silent bug like the transitions were:** the Whisper transcript timestamps are
for the original-speed audio. Caption and hook timing must be scaled by
`1 / playback_speed` before being burned in, or captions will drift out of
sync the moment speed ≠ 1.0. This scaling happens once, early, wherever the
transcript JSON is prepared for the caption/hook stages — not per-stage.

## 11. Sound effects (new)

Closes out `LibraryAssetKind.SFX` (also currently unused, despite
`MusicMixStage` already special-casing it in `assets/tasks.py`'s ingest
branch). New model, `ClipTimedSfx` (`candidate` FK, `sfx_asset` FK, `start_sec`,
`volume_db`) — one-shot audio drops layered in alongside background music.
Rendered in the existing music-mix stage, generalized to also mix in zero or
more discrete SFX one-shots at their timestamps (same `amix` approach,
extended with more inputs).

## 12. Blueprint / DAG impact — none required

The pipeline-blueprint DAG (`clipping_v1` / `clipping_v1_manual`, currently
defined only in one-off data migrations `0003_add_clipping_v1_blueprint.py`
and `0006_add_clipping_v1_manual_blueprint.py`) has a single opaque
`clip_render` node that internally invokes `ClipRenderPipeline`. The DAG has
no visibility into how many ffmpeg sub-stages that pipeline runs — growing it
from 10 to 11 stages does not change the DAG's nodes or edges. Verified this
by checking every caller of `ClipRenderPipeline.run()`'s `pause_after_stages`/
`start_from_stage` params (used for internal stage-level gating) — nothing
outside `clip_render_pipeline.py` references them, so the approval gate
(`clip_approval_gate`) pauses at the orchestrator/DAG level, not by internal
ffmpeg stage number. No cross-cutting coupling to worry about.

What *is* worth fixing: `clipping_v1`/`clipping_v1_manual` only exist because
of those one-off migrations — unlike `longform_v1`, there's no idempotent,
rerunnable way to reseed or update them. Extend
`server/apps/pipelines/management/commands/seed_blueprints.py` to also seed
both clipping blueprint graphs (identical `_CLIPPING_V1_GRAPH` /
`_CLIPPING_V1_MANUAL_GRAPH` shape to what the migrations already created),
using the same `update_or_create`-by-`name` idempotent pattern already used
for `longform_v1`. This gives one reusable place to manage all three
blueprints going forward, without editing historical migrations.

## 13. Render pipeline shape (new stage order)

Final order (renumbered; nothing outside this file depends on specific
integers — see §12):

1. **trim_and_crop** — existing, extended with `playback_speed` and
   `fit_mode` (`CROP` / `BLUR_FILL` — blurred, scaled full-bleed background
   behind a centered uncropped copy, CapCut's signature vertical-conversion
   look, on `ClipLayoutConfig`)
2. **color_grade** — new (§9)
3. **intro_concat** — existing, extended with transitions (§5)
4. **hook** — existing, extended with font + `hook_animation` (§4, §6)
5. **caption_translation** — unchanged
6. **captions** — existing, extended with font system, animation,
   karaoke-highlight, uppercase (§4, §7)
7. **watermark** — existing, extended with color, font, center/tiled position
   (§4, §8)
8. **timed_overlays** — existing, extended with image fix, video/PIP,
   animation, font (§4, §6)
9. **progress_bar** — unchanged
10. **outro_concat** — existing, extended with transitions (§5)
11. **music_and_sfx_mix** — existing `MusicMixStage`, generalized to also mix
    `ClipTimedSfx` one-shots (§11)

## 14. Data model changes (consolidated)

`ClipStyleConfig` adds: `watermark_color`, `watermark_font`,
`watermark_font_asset` (FK), `caption_font_asset` (FK), `hook_font_asset`
(FK), `intro_transition_duration_sec`, `outro_transition_duration_sec`,
`intro_transition_asset` (FK), `outro_transition_asset` (FK), `hook_animation`,
`caption_highlight_color`, `caption_uppercase`, `color_filter`, `brightness`,
`contrast`, `saturation`, `lut_asset` (FK), `playback_speed`.
`caption_font`/`hook_font` change from freeform `CharField` to the new
`CaptionFont` choice field. `TransitionStyle` gains 9 values.
`WatermarkPosition` gains `CENTER`, `TILED`. New `CaptionStyle.KARAOKE_HIGHLIGHT`.

`ClipLayoutConfig` adds: `fit_mode`.

`ClipTimedOverlay` adds: `font` (choice), `font_asset` (FK), `width`,
`animation`, `video_asset` (FK), `shape`.

New model: `ClipTimedSfx` (`candidate` FK, `sfx_asset` FK, `start_sec`,
`volume_db`).

New `TextChoices`: `CaptionFont` (~16 values), `OverlayAnimation`,
`ColorFilterPreset`, `FitMode`, `OverlayShape`.

All new fields are nullable or carry defaults, per the project's zero-downtime
migration requirement.

## 15. API / OpenAPI / frontend regeneration workflow

Standard round-trip for each new field: value objects
(`ClipStyleConfigPayload`/`PatchPayload`, `ClipLayoutConfigPayload`/
`PatchPayload`, `ClipTimedOverlay*Payload`, new `ClipTimedSfx*Payload`) →
`_apply_patch_fields` tuples + `_to_*_payload` mappers in `services.py` → new
DMR routes for `ClipTimedSfx` CRUD (mirroring the existing
`ClipTimedOverlay` endpoints) → OpenAPI schema (automatic, DMR generates it
from the msgspec Structs).

This backend repo produces the schema via
`manage.py dump_openapi_schema -o schema.yaml`; the frontend's
`orval.config.ts` reads a local `schema.yaml` and regenerates
`src/api/generated/**` via `npm run api:generate`. That regeneration step is
yours to run once the backend changes land — the frontend components below
are written against the field names the backend will produce, so they'll
type-check as soon as the client is regenerated.

## 16. Frontend component plan

- New `FontPicker` component (curated dropdown + "Custom…" →
  `LibraryAssetField` with `kindFilter="FONT"`), used in `CaptionsSection`,
  `HookSection`, new watermark font row, new overlay font row.
- `CaptionsSection`: add karaoke-highlight to style options, highlight-color
  field, uppercase toggle.
- `HookSection`: add animation dropdown.
- `WatermarkSection`: add color field, font picker, center/tiled positions.
- `AudioPanel`: add transition duration fields, custom-transition-asset
  picker (shown when `CUSTOM_ASSET` selected) for both intro and outro.
- `OverlaysPanel`: add `VIDEO` to the type selector (with asset picker +
  shape selector), width field for image/video, animation dropdown, font
  picker for text.
- New `EffectsPanel` (or a new tab) for color grading (preset dropdown,
  brightness/contrast/saturation sliders, LUT asset picker) and speed
  (slider/number field).
- New `SfxPanel` (or a section within `AudioPanel`) — list + add/edit/delete
  for `ClipTimedSfx`, mirroring `OverlaysPanel`'s list/detail pattern.
- `EffectStackRail`: add entries for the new sections so they're visible in
  the effect-stack summary strip.

## 17. Testing strategy

This repo enforces 100% coverage (`--cov-fail-under=100`), so every new
branch — each transition type, the image/video overlay paths, curated-vs-
custom font resolution, tiled watermark, each color-filter preset, the speed/
transcript-scaling interaction — needs an explicit test, mirroring
`tests/test_apps/test_rendering/test_clip_stages/`. Command-construction unit
tests can't catch a malformed ffmpeg filter graph, so at least one real
end-to-end render through the docker stack is required to validate the new
`xfade`, `lut3d`, and mask filter graphs actually execute.

## 18. Rollout notes

- New dependency: `fonttools` (pure Python, no system packages) — add to
  `pyproject.toml` main group (needed at asset-ingest time in the worker, and
  potentially at API-time for validation).
- No Docker image changes needed for fonts (see §4 — everything goes through
  `fontfile=`/`fontsdir=`, not system fontconfig).
- Bundled font files (`server/apps/rendering/fonts/*.ttf`) are OFL-licensed
  and checked into git like any other static asset.
- `seed_blueprints.py` changes are additive and idempotent — safe to run
  against any environment, including ones where the historical migrations
  already created these rows.
