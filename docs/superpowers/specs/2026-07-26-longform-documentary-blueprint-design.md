# Documentary blueprint: stock/archival footage instead of AI-generated images

Date: 2026-07-26
Status: Approved for implementation planning

## 1. Context

The `longform_v1` blueprint builds every visual from scratch: `visual_prompts`
writes Flux prompts per scene, `image_gen` renders one image per scene via
fal.ai, and `motion` animates each still (Kling I2V for hero scenes, Ken Burns
otherwise). Characters get consistency treatment through `cast_proposal`,
`character_gate`, and `Character.hero_ref` reference images.

That chain is wrong for documentary channels. A documentary about the Battle of
Midway or coral bleaching wants real footage and real archival photographs, not
a synthetic rendering of them. This design adds a sibling blueprint that sources
visuals from stock and public-domain providers, falling back to AI generation
only when nothing suitable exists.

The pipeline architecture already supports this well. A blueprint is a JSON DAG
of registered stage keys (`PipelineBlueprint.graph`), the orchestrator resolves
dependencies generically, and fan-out/gate/retry machinery is stage-agnostic.
Only the three visual stages need replacing; the ~15 stages around them are
reused unmodified.

**Scope boundary:** this is one new blueprint plus the extension mechanism that
makes future blueprints cheap. It is not a rewrite of the AI-visual path, and it
does not change how `longform_v1` behaves.

## 2. Goals

- A `longform_documentary_v1` blueprint that sources scene visuals from Pexels,
  Pixabay, Wikimedia Commons, and Openverse/archive.org.
- Scripts written to be *visually sourceable* — the LLM must not describe shots
  that cannot exist in a footage library.
- Automatic per-scene selection good enough to run unattended, with an armable
  human review gate for correction.
- Graceful degradation: broaden the query, then generate with AI, then park for
  a human — never silently ship a black frame.
- Correct attribution for CC-licensed material, enforced through to the
  published YouTube description.
- A generalized blueprint-profile mechanism so blueprint N+1 costs a profile
  registration and one review module, not edits to shared dispatch code.
- Zero behavior change to `longform_v1`, `clipping_v1`, and
  `clipping_v1_manual`.
- Preserve the repo constraints: 100% coverage, strict mypy, import-linter
  contracts, backward-compatible migrations.

## 3. Non-goals

- Paid providers (Storyblocks, Artgrid, Getty). The provider layer is a
  Protocol; adding one later is a new adapter file, not a design change.
- Video-to-video AI restyling of sourced footage.
- Replacing the AI-visual path or deprecating `longform_v1`.
- A general media-asset browser UI. The operator surface here is scene review
  and candidate swapping.

## 4. Design decisions

Four decisions were settled during design and drive everything below.

**Mixed channels, not one documentary type.** Modern/evergreen topics (nature,
science, tech) and historical/archival topics (WWII, ancient civilizations) need
different sources. Rather than two blueprints, one blueprint reads an ordered
provider priority list per channel.

**Footage-aware scripting, not a search-then-write loop.** The script and scene
breakdown are prompted to produce only sourceable visuals. This costs prompt
engineering rather than an extra search round-trip per topic, and the residual
risk (the LLM still occasionally writes an unfilmable scene) is absorbed by the
fallback cascade.

**Cascade on no-match: broaden → AI → park.** The AI fallback reuses the
existing fal.ai client and Ken Burns path, so autonomy is nearly free. Parking
is the last resort, not the first.

**Vision re-rank with an armable gate.** Stock-provider relevance ranking is
keyword-based and unreliable — the top hit for "1940s submarine" is often a
modern tourist sub. A vision model scores candidate thumbnails against the
scene's `visual_concept`. The gate is armed per channel via `Channel.gates`,
exactly like `storyboard_gate` today.

## 5. Architecture

### 5.1 Blueprint profiles

Blueprints declare a profile in their graph JSON:

```json
{"stages": [...], "profile": "documentary_footage"}
```

A registry in `server/apps/pipelines/logic/blueprint_profiles.py` (new; pure,
no ORM imports, `logic` layer) maps a profile to the stage keys that play each
visual role:

```python
AI_VISUAL = BlueprintProfile(
    key='ai_visual',
    roles={'prompt_stage': 'visual_prompts',
           'source_stage': 'image_gen',
           'segment_stage': 'motion'})

DOCUMENTARY_FOOTAGE = BlueprintProfile(
    key='documentary_footage',
    roles={'prompt_stage': 'footage_queries',
           'source_stage': 'footage_search',
           'segment_stage': 'footage_prep'})
```

Resolution reads `blueprint_snapshot['profile']`, defaulting to `ai_visual`, and
allows a per-blueprint `roles` override map for one-off graphs.

Because absent means `ai_visual`, **the `longform_v1` graph JSON does not
change**, nor do the two clipping graphs or `seed_demo`'s inline graphs.

Adding a future blueprint means: register a profile, add a review module, seed
the graph. No shared dispatch code is edited.

### 5.2 The DAG

`longform_documentary_v1`, kind `LONGFORM`, seeded alongside the existing three
in `server/apps/pipelines/management/commands/seed_blueprints.py`:

```text
research → outline → script → scene_breakdown → script_gate → narrative_qc
                                                                   │
                                              ┌────────────────────┴──────────┐
                                              ↓                               ↓
                                       footage_queries                   music_plan
                                              ↓
                                     footage_search  ⟨fan_out: scenes⟩
                                              ↓
                                      storyboard_gate  ⟨gate⟩
                                         ┌────┴────┐
                                         ↓         ↓
                              footage_prep       tts  ⟨fan_out: chapters⟩
                              ⟨fan_out: scenes⟩    ↓
                                         │      alignment ← scene_breakdown
                                         │         ↓
                                         │      metadata ← script, footage_search
                                         │         ↓
                                         │      thumbnail
                                         └────→ assembly ← tts, alignment, music_plan
                                                   ↓
                                                  qc → final_gate ⟨gate⟩ → publish
```

Differences from `longform_v1` beyond the visual swap:

- `cast_proposal` and `character_gate` are **absent entirely** — there is no AI
  cast. `footage_queries` therefore depends on `narrative_qc`.
- `metadata` gains a `footage_search` dependency so it can build the attribution
  block.
- The review gate keeps the key `storyboard_gate`, so `Channel.gates` arming,
  `_active_gate_key`, and gate approval all work unchanged. Only its *payload*
  differs.

Reused unmodified: `research`, `outline`, `script`, `scene_breakdown`,
`script_gate`, `narrative_qc`, `tts`, `alignment`, `music_plan`, `metadata`,
`thumbnail`, `assembly`, `qc`, `final_gate`, `publish`.

### 5.3 Provider adapter layer

New package `server/apps/generation/clients/stock/`, matching how `fal`,
`elevenlabs`, and `search` are organized:

```text
stock/
  base.py       FootageProvider Protocol + FootageCandidate struct
  pexels.py  pixabay.py  wikimedia.py  openverse.py
  registry.py   name → provider; enabled set comes from channel config
```

One Protocol method:

```python
async def search(query, *, media_type, orientation, min_width, limit)
    -> list[FootageCandidate]
```

`FootageCandidate` carries what re-ranking and licensing both need: `provider`,
`external_id`, `media_type`, `download_url`, `thumb_url`, `width`, `height`,
`duration_s`, `license`, `license_url`, `author`, `source_page_url`,
`attribution_required`, `title`, `tags`.

API keys follow the existing `settings.EXA_API_KEY` pattern. Wikimedia and
Openverse work unauthenticated; Openverse accepts a token for higher limits.

**Rate limiting is a first-class constraint.** Pexels allows 200 requests/hour.
A 60-scene documentary querying four providers per scene is 240 requests — a
single run would exhaust the quota. Three mitigations:

1. Providers are queried in configured priority order with **early exit** once
   enough candidates clear the quality floor. Typical scenes hit one or two
   providers.
2. **Redis cache keyed on `(provider, normalized_query)`** with a TTL, so
   retries, shard reruns, and gate swaps do not re-spend quota.
3. Per-provider concurrency cap so a 60-way fan-out does not burst.

On HTTP 429 the provider is marked exhausted **for the remainder of the run**,
so later scenes skip it instead of hammering a closed door.

### 5.4 New stages

**`footage_queries`** — LLM, `api` queue, no fan-out.

Reads `scene_breakdown` and `narrative_qc`. Emits per scene: `primary_query`,
`fallback_queries[]`, `media_preference` (`video`/`image`/`any`), `orientation`,
`era_hint`, `negative_terms`, and `ai_fallback_prompt`.

Generating `ai_fallback_prompt` here means the fallback path inside
`footage_search` needs no second LLM call.

Coverage validation mirrors `visual_prompts`: if the set of emitted `scene_idx`
values does not equal the set from `scene_breakdown`, raise `FatalProviderError`
with `error_code='prompt_coverage'`.

**`footage_search`** — fan-out over scenes, `api` queue.

Per shard:

```text
primary_query → providers in priority order (early exit)
    ↓ filter: min resolution, min duration, allowed licenses
    ↓ ≥1 candidate?  → re-rank → download best → ffprobe-validate
    ↓                  validation fails → next-ranked candidate, repeat
    ↓ 0 candidates   → retry fallback_queries (broadened)
    ↓ still 0        → AI gen via fal using ai_fallback_prompt
    ↓ still 0, or AI disabled → FatalProviderError → NEEDS_INPUT
```

Re-rank mode is node config: `vision` (send candidate thumbnails to a vision
model with the scene's `visual_concept`), `metadata` (score on title/tags/
resolution/duration only), or `none`. Vision is the default; the other modes
exist as cost levers, since vision re-rank is roughly one call per scene.

Re-ranking covers up to `candidates_per_scene` candidates (§6.2, default 8).
`ffprobe` validation runs on the downloaded winner, not on every candidate — one
probe per scene in the common case.

If the vision call fails, the stage **degrades to metadata ranking** rather than
failing the scene. One flaky vision call must not kill a run.

The winner downloads to a new `AssetKind.FOOTAGE` asset. Shard output retains
the top candidates inline so the gate can offer swaps without re-searching:

```python
{'scene_idx', 'asset_id', 'media_type', 'source', 'license',
 'attribution', 'source_url', 'rerank_score', 'candidates': [...]}
```

`source` is a provider name or `ai_flux` when the fallback fired.

**`footage_prep`** — fan-out over scenes, `render` queue.

Normalizes mixed media into uniform segments:

- **Video**: trim to the scene duration, scale/crop to 1920×1080, force 30fps,
  strip audio. Trimming takes the window **from the start of the clip** —
  deterministic, so a rerun of the same shard produces the same segment. When
  the clip is shorter than the scene (`min_clip_duration_s` is 3.0 against
  6–12s scenes, so this is common), it loops to fill, with the final repetition
  cut at the scene boundary.
- **Image**: Ken Burns, via the extracted `rendering/ffmpeg.ken_burns()`.

Output shape is **byte-identical to `motion`'s** — `scene_idx`, `asset_id`,
`duration_s`, `method` (`clip_trim` / `clip_loop` / `ken_burns`) — which is why
`assembly` needs nothing beyond role resolution.

### 5.5 Isolation strategy

Documentary review logic goes in a **new package that wraps existing modules**
rather than parameterizing them:

```text
server/apps/pipelines/review/
  dispatch.py      profile → adapter
  ai_visual.py     delegates to existing storyboard_selectors / run_review
  documentary.py   new payload builder + scene-edit sync
```

This is also better design independent of risk: the documentary storyboard
payload genuinely differs (candidates, license, media_type), so forcing one
function to serve both shapes would be worse regardless.

Full change surface on existing code:

| File | Change | Risk |
|---|---|---|
| `storyboard_selectors.py` | **none** — wrapped | none |
| `run_review.py` | **none** — wrapped | none |
| API views (2 call sites) | point at `review.dispatch` | trivial |
| `stage_output_selectors.py` | add 3 keys to `_KNOWN_STAGE_KEYS` | additive |
| `run_asset_selectors.py` | add keys to `_SCENE_LABEL_STAGES` | additive |
| `pipeline_run.py` | resolve prompt snapshot from format | see §6.3 |
| `assembly.py` | one line: role-resolve `stage_key='motion'` | see below |
| `motion.py` | delegate to extracted `ken_burns()` | see below |
| `.importlinter` | `ignore_imports` for new stage→client edges | config |

**`assembly.py` is the one unavoidable shared edit.** `_build_scene_asset_map`
hardcodes `stage_key='motion'` deep in the render path; it cannot be wrapped. It
becomes a call to `resolve_role(snapshot, 'segment_stage')` defaulting to
`'motion'`. The alternative — duplicating ~500 lines of ffmpeg orchestration
into a `documentary_assembly` stage — would leave two render paths to drift
apart, a materially worse outcome than one defaulted line.

**Both `assembly.py` and `motion.py` changes land as isolated commits** ahead of
any documentary code, each proven green by the existing `test_assembly.py` and
`test_motion.py`, so a regression is trivially revertable.

## 6. Configuration

### 6.1 Channel selection

No new code. `resolve_blueprint_name()` already consults
`channel.default_blueprint_name`; a documentary channel sets it to
`longform_documentary_v1`. Per-run override via `payload.blueprint_name` also
works as-is.

### 6.2 `FootageSourcingConfig`

New `OneToOneField` on `Channel` in `server/apps/channels/models.py`, following
the `NicheConfig` / `AssemblyStyleConfig` pattern:

```python
enabled_providers      ArrayField  # ordered priority
sourcing_mode          stock_first | archival_first | balanced
ai_fallback_enabled    bool = True
rerank_mode            vision | metadata | none
candidates_per_scene   int = 8
min_clip_width         int = 1280
min_clip_duration_s    float = 3.0
allowed_licenses       ArrayField
require_attribution    bool = True
```

Provider ordering is what makes mixed channels work without a code branch: an
archival channel orders `['wikimedia', 'openverse', 'pexels']`, a modern one
`['pexels', 'pixabay']`.

### 6.3 Format-driven prompts

**The gap this closes:** `prompt_snapshot` is `{}` for every longform run today,
so `PromptRenderer` falls back to the globally-active `PromptVersion` per
`stage_key`. A documentary channel and an AI-visual channel would share one
`script` template. Footage-aware scripting is impossible without fixing this.

`StoryFormat.prompt_overrides` (JSONField) already exists for exactly this
purpose and is currently read by nothing.

It maps **stage key → template key**, not to `PromptVersion` UUIDs:

```python
{'script': 'script_documentary',
 'scene_breakdown': 'scene_breakdown_documentary'}
```

Template keys are readable in the admin and survive version bumps. At run
creation, `pipeline_run.py` resolves each to the currently-active
`PromptVersion` id and writes it into `prompt_snapshot`. This preserves existing
semantics exactly — the run stays pinned to an immutable version, so reruns are
reproducible.

Resolved prompts nest under `prompt_snapshot['prompts']`, with `PromptRenderer`
falling back to the flat lookup. `prompt_snapshot` currently holds clipping
metadata (`source_title`, `source_id`, `clip_options`) flat in the same dict
that `PromptRenderer` probes by stage key; nesting removes that collision class.
No existing longform run has flat stage entries, so nothing needs migrating.

**Backward compatibility:** existing `StoryFormat` rows default
`prompt_overrides={}`, which resolves to an empty snapshot — byte-identical to
today. This is explicitly regression-tested.

### 6.4 Story formats and prompt templates

Two `StoryFormat` rows — `documentary_stock` and `documentary_archival` — seeded
by a new idempotent `seed_story_formats` command. Both `fiction=False`,
`narration_pov='narrator'`, with beats following documentary structure (cold
open → thesis → context → escalating evidence → turn → resolution → reflection).

Three new prompt templates, seeded active:

- **`script_documentary`** — the footage-aware rules. Narration may name
  specifics; the *visual* must be archetypal and findable. "A destroyer's deck
  in heavy seas," not "HMS Hood at 05:52." Bias toward motifs that recur across
  a video (maps, documents, machinery, landscapes, crowds) so a limited
  inventory carries 20 minutes without visible repetition.
- **`scene_breakdown_documentary`** — the same constraint at scene granularity,
  plus `era_hint` emission and anachronism avoidance. Drops the cast-emission
  instructions from the base template, since there is no cast.
- **`footage_queries`** — the new stage's own template.

`research`, `outline`, `narrative_qc`, `metadata`, and the rest fall through to
the existing global templates unchanged.

`build_prompt_variables` gains a `footage` namespace (`providers`,
`sourcing_mode`, `ai_fallback_enabled`, `min_width`, `attribution_required`),
guarded with `getattr` defaults so channels without the config still render —
matching the defensive style of the existing `_niche_dict` / `_format_dict`
helpers.

## 7. Licensing and attribution

Wikimedia and Openverse serve CC-BY material. Publishing it on a monetized
channel without credit is a license violation and a copyright-strike vector.
Pexels and Pixabay do not require attribution, so they are treated differently.

Provenance persists in two places: full detail on `Asset.meta` at download time,
plus a **`FootageCredit`** row per selected asset (`asset` FK, `run`,
`scene_idx`, `provider`, `license`, `author`, `source_url`,
`attribution_required`). The dedicated row makes "which videos used this image"
one query and one admin list, instead of a JSON scan across thousands of assets
during a dispute.

The `metadata` stage appends a credits block to the YouTube description. It
dedupes, groups by provider, and **prioritizes `attribution_required=True`**
entries — YouTube caps descriptions at 5000 characters, and a 60-scene archival
documentary can produce more credits than fit. Required attributions are never
truncated; optional ones are dropped first.

## 8. Error handling

| Failure | Handling |
|---|---|
| Provider HTTP error | `RetryableProviderError` → normal stage retry |
| HTTP 429 | Respect `Retry-After`, mark provider exhausted for the run |
| Vision re-rank fails | Degrade to metadata ranking; do not fail the scene |
| Corrupt/unplayable download | `ffprobe`-validate before accepting; fall to next candidate |
| Cascade exhausted | `FatalProviderError` → shard `NEEDS_INPUT` → run parks at `AWAITING_REVIEW` |

Budget handling is unchanged: provider searches are free; AI fallback and vision
re-rank record through `ctx.costs.record`, so `_over_budget` / `BUDGET_HOLD`
work as they do today.

## 9. Migrations

Three migrations, all backward-compatible:

1. `assets` — add `AssetKind.FOOTAGE`, widening the `assets_asset_kind_valid`
   `CheckConstraint`. Widening a constraint is backward-compatible (existing
   values stay valid), but this is the one migration to run `lintmigrations`
   against **early** rather than at the end.
2. `assets` — add the `FootageCredit` model. Pure addition.
3. `channels` — add `FootageSourcingConfig`. Pure addition, nullable relation.

## 10. Testing

Against the 100%-coverage bar (`--cov-fail-under=100`):

- One test module per provider adapter, with mocked `httpx` responses built from
  each provider's real JSON shape (mirroring how `test_research.py` handles the
  Exa client).
- `footage_search` parametrized per cascade branch: direct hit,
  broaden-then-hit, AI fallback, full exhaustion → `NEEDS_INPUT`, provider 429,
  corrupt-media-then-next-candidate, vision-failure degradation.
- `footage_prep` runs real ffmpeg against tiny fixtures, following
  `test_motion.py` / `test_assembly.py`.
- **New graph-structure test across every seeded blueprint**: each `key` exists
  in `STAGE_REGISTRY`, every `depends_on` resolves, no cycles.
  `test_blueprint_validation.py` today covers only name resolution, so this
  catches a class of typo that currently reaches production.
- **Seam regression tests**: with `profile` absent, `assembly`, the review
  dispatcher, and scene-edit sync must resolve to `motion` / `image_gen` /
  `visual_prompts`.
- **Prompt-snapshot regression**: a channel whose format has
  `prompt_overrides={}` produces an empty snapshot, identical to today.
- Idempotency tests for the extended `seed_blueprints` and new
  `seed_story_formats`.

## 11. Frontend

The operator UI is a separate repo (`***REMOVED***-frontend`, generated against this
backend's OpenAPI schema via `orval`). API and UI work is specified in the
companion brief:

`docs/superpowers/specs/2026-07-26-longform-documentary-frontend-brief.md`

Summary of what changes: the storyboard response gains a `profile` discriminator
and footage fields; three new endpoints (candidate select, manual re-search,
credits preview); a `footage_sourcing` sub-object on channel GET/PATCH; and a
documentary storyboard variant with candidate swapping, provenance badges, and
license display.

## 12. Implementation order

1. `blueprint_profiles.py` + role resolution, with defaults proven by existing
   tests.
2. `assembly.py` role resolution — isolated commit, `test_assembly.py` green.
3. `ken_burns()` extraction to `rendering/ffmpeg.py` — isolated commit,
   `test_motion.py` green.
4. Migrations (`AssetKind.FOOTAGE`, `FootageCredit`, `FootageSourcingConfig`),
   `lintmigrations` verified.
5. Provider adapter layer + caching + rate limiting.
6. `footage_queries`, `footage_search`, `footage_prep`.
7. `prompt_overrides` wiring + `seed_story_formats` + prompt templates.
8. Blueprint seeding + graph-structure test.
9. `review/` dispatch package + API endpoints.
10. Attribution block in `metadata` + credits endpoint.
