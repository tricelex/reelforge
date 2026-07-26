# Documentary blueprint — Frontend Integration Brief

**Date:** 2026-07-26
**Status:** Written alongside the backend design; endpoints below are *planned*,
not yet built. Do not start against this until the backend lands.
**Pair this doc with:** the OpenAPI/swagger export from the ReelForge backend.
This doc is the "what changes and why" narrative; swagger is the source of truth
for exact request/response field types and the URL prefix.
**Backend design:** `2026-07-26-longform-documentary-blueprint-design.md`

## Context

A new pipeline blueprint, `longform_documentary_v1`, sources scene visuals from
stock and public-domain providers (Pexels, Pixabay, Wikimedia Commons,
Openverse/archive.org) instead of generating them with Flux. It reuses most of
the existing longform DAG; only the three visual stages differ:

| `longform_v1` (AI) | `longform_documentary_v1` (footage) |
|---|---|
| `visual_prompts` | `footage_queries` |
| `image_gen` | `footage_search` |
| `motion` | `footage_prep` |
| `cast_proposal`, `character_gate` | *absent — no AI cast* |

**The key framing for the UI:** a documentary run parks at the same
`storyboard_gate`, at the same point in the flow, with the same approval
endpoint. What changes is *what the operator reviews*. Instead of approving
generated images and editing prompts, they are confirming that a real clip
matches the scene — and swapping it when it does not.

Runs are discriminated by a new `profile` field on the storyboard response.
**Do not branch on blueprint name** — branch on `profile`. More blueprints are
planned, and the profile mechanism is how they will identify themselves.

## 1. New/changed API endpoints

### 1.1 Storyboard — changed response

```text
GET  /api/runs/{run_id}/storyboard/
```

The response gains a top-level discriminator:

```text
profile: "ai_visual" | "documentary_footage"
```

Existing runs and all `longform_v1` runs report `"ai_visual"` with today's exact
payload — **no changes needed for the current UI**.

Under `"documentary_footage"`, each scene row adds:

```text
media_type            "video" | "image"
source                provider name, or "ai_flux" when the AI fallback fired
license               e.g. "CC-BY-4.0", "pexels", "public-domain"
license_url           string | null
attribution_required  bool
author                string | null
source_url            link to the provider's page for this item
rerank_score          float | null   — confidence of the automatic pick
candidates[]          alternates already fetched, for swapping
```

Each entry in `candidates[]`:

```text
external_id, provider, thumb_url, preview_url,
width, height, duration_s, license, author, source_url
```

`candidates[]` is served from the stage output — it costs no provider quota to
render. Swapping is therefore instant and free; treat it as a cheap interaction.

Scene rows under this profile also **do not carry** `prompt` /
`negative_prompt` / cast fields. There is no character system in this blueprint.

### 1.2 Select a different candidate — new

```text
POST /api/runs/{run_id}/scenes/{scene_idx}/select-candidate/
     { "external_id": "..." }
```

Re-points the scene at a candidate already present in `candidates[]`,
re-downloads it, and re-runs `footage_prep` for that shard only. Sibling scenes
are untouched. No provider search is issued.

### 1.3 Manual re-search — new

```text
POST /api/runs/{run_id}/scenes/{scene_idx}/research-footage/
     { "query": "..." }
```

Runs `footage_search` again for one scene with an operator-supplied query. This
is the recovery path for a scene that exhausted the automatic cascade and parked
at `NEEDS_INPUT`. It *does* spend provider quota.

### 1.4 Credits preview — new

```text
GET  /api/runs/{run_id}/credits/
```

Returns the attribution block that will be appended to the YouTube description,
so an operator can verify it before publishing:

```text
entries[]  { provider, license, author, source_url, title,
             attribution_required, scene_idxs[] }
truncated  bool   — true when optional credits were dropped for length
```

YouTube caps descriptions at 5000 characters. Entries with
`attribution_required: true` are never dropped; optional ones (Pexels, Pixabay)
are dropped first. Surface `truncated` so operators know it happened.

### 1.5 Channel footage settings — changed

```text
GET   /api/channels/{channel_id}/
PATCH /api/channels/{channel_id}/
```

Gains a `footage_sourcing` sub-object:

```text
enabled_providers      string[]  — ORDERED priority, order is meaningful
sourcing_mode          "stock_first" | "archival_first" | "balanced"
ai_fallback_enabled    bool
rerank_mode            "vision" | "metadata" | "none"
candidates_per_scene   int
min_clip_width         int
min_clip_duration_s    float
allowed_licenses       string[]
require_attribution    bool
```

`enabled_providers` order drives which provider is queried first and is the main
lever distinguishing an archival channel from a modern one. The editor must
preserve order — a set-style multi-select loses the meaning.

### 1.6 Scene edit — behavior change, same endpoint

```text
PATCH /api/runs/{run_id}/scenes/{scene_idx}/
```

On documentary runs the response's `stale_from` is `"footage_queries"` rather
than `"visual_prompts"`.

**If the current frontend hardcodes `"visual_prompts"` anywhere, that must
become profile-driven.** This is the one place existing code is likely to break.

### 1.7 Unchanged endpoints worth noting

These need no changes and should be reused as-is:

- `POST /api/runs/{run_id}/gates/storyboard_gate/approve/` — same gate key, same
  approval flow.
- `POST /api/runs/{run_id}/stages/{stage_key}/rerun/` — already accepts
  `shard_indices`, so re-running a single scene works today.
- `GET /api/runs/{run_id}/events/` — SSE stream, unchanged.
- `GET /api/blueprints/` — `longform_documentary_v1` appears automatically once
  seeded.

## 2. UI work

### 2.1 Documentary storyboard variant

A sibling to the existing storyboard grid, selected on `profile`. Per scene:

- **Video preview, not a still.** Most scenes are real clips; a static thumbnail
  hides whether the motion actually suits the narration. Hover-to-play on the
  card with click-to-expand is enough.
- **Candidate strip** — the alternates from `candidates[]`, click to swap. Since
  swapping costs nothing, make it a one-click action, not a modal flow.
- **License badge** with an explicit marker when `attribution_required` is true.
- **Source link** out to the provider page.

### 2.2 Provenance badges

Each scene shows whether it came from stock, archival, or the AI fallback, plus
a run-level summary ("7 of 62 scenes fell back to AI"). This is the single most
useful signal for an operator: a documentary where a third of the scenes are AI
renders has a script problem upstream, not a footage problem, and they should
know that before approving rather than after publishing.

### 2.3 Failed-scene recovery

Scenes that exhausted the cascade need a visible failed state with an inline
query input wired to §1.3. Unlike candidate swapping, this one costs quota and
takes seconds — show a pending state.

### 2.4 Channel settings

A `footage_sourcing` panel: drag-ordered provider priority list, sourcing mode,
AI-fallback toggle, rerank mode, quality floors, license allowlist. Worth a
short inline explanation of provider ordering, since it is the least obvious and
most consequential setting.

### 2.5 Credits preview at the final gate

Surface §1.4 in the final review step, with the `truncated` flag called out.
This is a legal-compliance surface, not a nicety — CC-BY material published
without credit is a license violation and a copyright-strike risk.

## 3. Sequencing

The backend lands in the order given in §12 of the design doc. Useful checkpoints
for frontend work:

1. **`profile` on the storyboard response** — build the discriminator and verify
   `ai_visual` runs are unaffected. Safe to do first; it is additive.
2. **Storyboard variant + candidate swapping** — once `footage_search` and
   `select-candidate` land.
3. **Channel settings panel** — independent of the run UI, can proceed in
   parallel once the migration lands.
4. **Credits preview + failed-scene recovery** — last, alongside the attribution
   work.

## 4. Open items

- Exact URL prefix and field casing come from swagger once the endpoints exist.
  Paths above follow the existing `pipelines_api` routing conventions
  (`runs/<uuid:run_id>/...`) but are not yet registered.
- `preview_url` availability varies by provider — Wikimedia serves stills for
  some video items. The UI should tolerate a null `preview_url` and fall back to
  `thumb_url`.
