# ReelForge Pipeline Hardening — Frontend Integration Brief

**Date:** 2026-07-08 (updated same day — three of the originally-flagged API gaps have
now been closed; see changelog at the bottom)
**Pair this doc with:** the OpenAPI/swagger export from the ReelForge backend. This
doc is the "what changed and why" narrative; swagger is the source of truth for exact
request/response field types. Where this doc names a field, cross-check it against
swagger before building — this doc summarizes verified backend state as of this date,
but the swagger export is always more current for exact shapes.

## Context

Three feature milestones landed on `main` (merged, tested, reviewed):

1. **Policy-risk mitigations** — reduce the risk of YouTube demonetization/termination
   for AI-generated channels (structural variety, mandated commentary, publish-cadence
   caps, AI-content disclosure, cross-run similarity checks, manual→auto graduation
   criteria, cross-channel differentiation warnings).
2. **Money-loop foundations** — ground ideation in real demand data, pull real
   YouTube performance data back into the system, and stop wasting spend (thumbnail
   A/B testing, category/caption/license fixes).
3. **Creative moat** — a pre-render narrative quality gate, a per-channel visual/audio
   "signature" system, stricter research sourcing, and retention-curve-informed pacing.

A follow-up bug-fix pass then fixed several correctness issues found in review (crashes,
a bug that silently discarded held publish runs, an empty music library for pre-existing
assets) and consolidated some duplicated logic. None of the fixes changed API shapes —
they don't need separate frontend treatment beyond what's described below.

A second follow-up pass (same day) closed three of the API gaps originally flagged in
this brief — see Section 1 for what's newly buildable, and the changelog at the bottom.

**Important framing for whoever builds the UI:** a few backend changes still exist at
the model/service layer with **no API endpoint**. These are called out explicitly in
[Section 4 — Remaining gaps](#4-remaining-gaps-backend-exists-no-api-endpoint-yet) so you
don't spend time building against something that isn't reachable over HTTP. Don't infer
an endpoint exists because a model field does — check the URLs listed here or the
swagger export.

---

## 1. New/changed API endpoints (ready to consume)

### 1.1 Channel graduation status

```
GET /api/channels/{channel_id}/graduation-status/
→ { clean_run_count: int, required_count: int, eligible: bool }
```

Every channel starts in `publish_mode=review` (a human approves each run before it
publishes). A channel becomes eligible to switch to `publish_mode=auto` after
accumulating enough "clean" runs in a row (no manual edits at review time, no
similarity-guard flags). This endpoint reports progress toward that.

**Note:** this endpoint only *reports* eligibility. The actual switch to
`publish_mode=auto` is a deliberate human action via the existing channel PATCH
endpoint (`publish_mode` field) — there is no auto-flip. This is intentional (see
Context in the plan docs — visible human judgment is treated as a policy safeguard,
not just friction).

**Suggested UI:** a "Graduation progress" card on the channel settings/detail page —
progress indicator (`clean_run_count / required_count`), and when `eligible: true`, a
prompt/CTA like "This channel is eligible for Auto mode" that links to the existing
publish-mode toggle. Not eligible yet → just show progress, no CTA.

### 1.2 Channel branding — new `warnings` field

The existing branding read/patch endpoints (`GET`/`PATCH
/api/channels/{channel_id}/branding/`) now return a `warnings: list[str]` field on
`ChannelBrandingPayload`. Populated when a channel's branding (watermark, fonts,
intro/outro, etc.) is close to identical to another channel's branding on the same
account — a soft nudge, not a block, to keep multi-channel operators from running
visually identical channels (a policy risk).

**Suggested UI:** if `warnings` is non-empty, show a dismissible warning banner/alert on
the branding settings page with the message(s). Non-blocking — the save/patch itself
always succeeds regardless of warnings.

### 1.3 Channel daily publish cap — `max_publishes_per_day` (newly exposed)

`max_publishes_per_day: int` is now a field on:

- `GET/PATCH /api/channels/{channel_id}/` (`ChannelDetailPayload` / patch body)
- `POST /api/channels/` (`ChannelCreatePayload`, defaults to `1` if omitted)

This is the cap that drives the `PUBLISH_HOLD` run status (Section 2.1) — once a
channel has this many `COMPLETED` publishes today, further runs park instead of
publishing until the next day. **`0` means unlimited** (no cap enforced).

**Suggested UI:** a numeric input on the channel settings page (e.g. "Max
publishes/day", with a note that `0` = unlimited). Pairs naturally with the
`PUBLISH_HOLD` status badge (2.1) — if you show recent runs, a channel sitting in
`PUBLISH_HOLD` is explained by this setting.

### 1.4 Library asset licensing — `license_type` / `license_note` (newly exposed)

Both fields are now on `LibraryAssetPayload` (every read of a library asset) and on
`LibraryAssetCreatePayload` (optional, `POST /api/assets/library-assets/`).
`license_type` is a string enum: `UNSPECIFIED | OWNED | LICENSED | CREATIVE_COMMONS |
ROYALTY_FREE_VERIFIED` (defaults to `UNSPECIFIED` if omitted at creation).

A **new endpoint** was added since none existed for editing a library asset after
upload:

```
PATCH /api/assets/library-assets/{asset_id}/
Body: { license_type?: string, license_note?: string }
→ LibraryAssetPayload
```

This PATCH endpoint currently only supports these two fields — it does not (yet) allow
editing `name`/`tags`/`is_active`/etc. Don't infer those are patchable from this route
existing.

Assets with `license_type=UNSPECIFIED` are silently excluded from the music pool the
assembly stage picks from — so an asset with no license set is effectively invisible to
render, not an error state. Worth surfacing that distinction in the UI copy.

**Suggested UI:** a license-type dropdown + optional note field on the asset
upload/edit form. Consider a visual flag (e.g. a muted/grey badge) on `UNSPECIFIED`
assets in any asset library/grid view, since those tracks are silently skipped by the
pipeline — a librarian should be able to spot "this won't actually get used" at a
glance.

### 1.5 Per-channel visual/audio signature — `AssemblyStyleConfig` (newly exposed)

This is the core "creative moat" feature — previously only editable via Django admin,
now has a real endpoint:

```
GET  /api/channels/{channel_id}/assembly-style/
PATCH /api/channels/{channel_id}/assembly-style/
```

```
AssemblyStyleConfigPayload {
  channel_id: string
  camera_movements: string[]      // pool the motion stage samples from
  transition_styles: string[]     // pool the assembly stage samples from
  sfx_pool_tags: string[]         // LibraryAsset tag filter for SFX cues
  min_cuts_per_minute: int
  max_cuts_per_minute: int
}
```

`GET` creates a row with sensible defaults on first call if none exists yet (you never
get a 404 for "not configured" — you get the defaults). `PATCH` accepts any subset of
the fields above; omitted fields are left unchanged.

This is what makes two channels *feel* different from each other rather than
interchangeable — camera movement style, cut transitions, and pacing rhythm are
randomized per-run from within the channel's own pool (never repeating the immediately
prior run's picks), so a channel has a consistent-but-not-identical identity across its
videos.

**Suggested UI:** a "Visual & audio style" settings panel — multi-select/tag-editor
inputs for `camera_movements` and `transition_styles` (probably from a fixed known
vocabulary — check current admin choices or seed data for the canonical list rather
than allowing arbitrary free text, since the render stages match against specific
known values), a tag-picker for `sfx_pool_tags` tied to the asset library, and a min/max
range input for cuts-per-minute. This is genuinely the highest-value new screen from
this whole brief — it's the one feature that's currently invisible to any non-admin
user despite being fully functional server-side.

---

## 2. New status/enum values the frontend must handle generically

These aren't new endpoints — they're new possible values in fields your UI already
reads. If your run/pipeline status handling has a fixed switch/map over known values,
it needs updating or it will silently mis-render (fall through to a default/unknown
state) for runs in these states.

### 2.1 `RunStatus.PUBLISH_HOLD`

A new run status (string field, same `status` field as always) meaning: every upstream
stage succeeded, but the channel already hit its daily publish cap
(`max_publishes_per_day`, Section 1.3), so the `publish` stage is deliberately not
enqueued yet. The run resumes automatically the next day. This is functionally similar
to the existing `BUDGET_HOLD` status — same "parked, will resume, not an error"
semantics.

**Suggested UI:** treat it like `BUDGET_HOLD` wherever that's already handled — a
distinct badge color (not error-red, not success-green; an amber "waiting" tone) and a
human-readable label like "Waiting — daily publish limit reached" rather than falling
through to a generic/unknown-status treatment.

### 2.2 New pipeline stage key: `narrative_qc`

If anything in the UI enumerates or visualizes pipeline stages by name (a progress
stepper, a stage icon map, a hardcoded list of expected stage keys per blueprint), there
is a new stage key `narrative_qc` that now runs after `scene_breakdown` and before the
expensive fan-out stages (`visual_prompts`/`image_gen`/`tts`/`motion`). It's a pre-render
LLM-judge quality gate (checks hook strength, retention-loop density, whether the
mandated `commentary` reads as genuine analysis, and structural similarity to the
channel's own recent videos) — same failure/retry semantics as any other stage
(`FAILED`/`NEEDS_INPUT` flow through the existing gate/review UI unchanged, just with a
new stage name attached).

**Suggested UI:** add `narrative_qc` to any stage-name→label/icon mapping. No new
payload shape — it's a normal `StageExecution` row like every other stage.

---

## 3. Fields that exist but aren't surfaced anywhere yet (informational, not actionable)

These changed at the data-model level as part of the milestones, but nothing in the
existing API surfaces them to a reviewer. They're mentioned here only so you know they
exist if a future ticket asks for them — no action needed today, and no endpoint exists
to fetch them.

- Script chapters now carry a `commentary` field (the analytical/opinionated take,
  distinct from narration `text`) — not exposed via any read endpoint (the storyboard
  review endpoint only returns scene-level fields, not chapter-level `commentary`).
- Script generation now also produces a `similarity_flag` when a new script is
  suspiciously close to the channel's last few — not exposed via the publish-metadata
  review endpoint.
- `TopicIdea.metadata` (already a generic `dict` field on the existing idea-list/detail
  endpoints — no schema change needed) now sometimes contains outlier-scan references
  when an idea was grounded in real trending-video data instead of pure LLM invention.
  If you want to show a "grounded in trending data" badge on ideas, this is already
  readable today via the existing generic `metadata` field — check for an
  `outlier_refs`-shaped key at runtime.

---

## 4. Remaining gaps: backend exists, no API endpoint yet

Three items from the original version of this brief (`AssemblyStyleConfig`,
`max_publishes_per_day`, asset licensing) have been closed — see Section 1. Two
categories remain deliberately un-built, for reasons worth stating explicitly rather
than just leaving them off a list:

### `PublishJobMetric` (performance dashboard) — deferred as its own design pass

Model + a scheduled daily pull from YouTube Analytics exist (`views`,
`avg_view_duration_s`, `avg_view_percentage`, `impressions`, `impressions_ctr`, and a
100-point `retention_curve`). This is genuinely valuable data — a real "how are my
videos performing" dashboard — but it is **not a blind CRUD passthrough** the way the
three items in Section 1 were. Before an endpoint gets built here, someone needs to
actually decide: per-video rows vs. per-channel/per-format/per-character rollups, what
time ranges matter, whether the raw retention curve gets returned wholesale or
pre-aggregated, and what the dashboard screen actually wants to show first. That's a
small brainstorm/design task in its own right, not a same-day addition — flag it as a
follow-up scoping conversation rather than assuming it'll show up alongside a swagger
diff.

### `NicheOutlierScan` and the `PublishJob` swap-history fields — deferred until a UI consumer exists

`NicheOutlierScan` (what's trending in a niche right now, feeding ideation) and
`PublishJob.thumbnail_tested`/`tested_candidate_ranks` (early-swap outcome history)
both have working backend logic with no API surface. Unlike Section 1's items, these
weren't built because there's no concrete screen asking for them yet — building API
surface with no consumer is the thing worth actively avoiding here. If a future ticket
wants "why was this idea suggested" or "thumbnail swap history" as an actual UI, that's
the trigger to add the endpoint — not before.

| Feature | Backend state | What's missing |
|---|---|---|
| **Video performance data** (`PublishJobMetric`) | Model + read-only Django admin exist; scheduled task pulls daily | No endpoint — needs its own design pass (see above), not a mechanical addition. |
| **Outlier/demand scan results** (`NicheOutlierScan`) | Model + read-only Django admin exist; results feed ideation prompts server-side | No endpoint — deferred until a UI screen actually needs it. |
| **Thumbnail/title early-swap outcome** (`PublishJob.thumbnail_tested`, `tested_candidate_ranks`) | Model fields exist, background task swaps automatically | The `publishing` app has no API layer at all — deferred until a UI screen actually needs it. |

---

## 5. Suggested new UI surfaces, summarized

- **Channel settings — "Graduation progress" card** (1.1): progress bar + eligibility
  CTA linking to the existing publish-mode toggle.
- **Channel branding page — warning banner** (1.2): render `warnings[]` if present.
- **Channel settings — daily publish cap input** (1.3): numeric field, `0` = unlimited.
- **Asset library — license picker** (1.4): dropdown + note on upload/edit; visual flag
  for `UNSPECIFIED` assets since the pipeline silently skips them.
- **Channel settings — "Visual & audio style" panel** (1.5): the highest-value new
  screen in this brief — camera-movement pool, transition-style pool, SFX tag pool,
  cuts-per-minute range. Currently the only way to touch this is Django admin.
- **Run/pipeline status displays — `PUBLISH_HOLD` handling** (2.1): new badge state,
  distinct from error/success, with a "waiting for tomorrow's publish window" message.
- **Pipeline stage visualizations — `narrative_qc` stage** (2.2): add to any stage-name
  maps; no new interaction pattern needed, it behaves like any other stage.
- **Not buildable yet:** a performance dashboard (`PublishJobMetric`) needs its own
  design/scoping pass first (Section 4); outlier-scan and thumbnail-swap-history views
  should wait until there's an actual ticket asking for them (Section 4).

---

## Changelog

- **2026-07-08 (later same day):** Closed three of the originally-flagged gaps —
  `max_publishes_per_day` added to channel DTOs, `license_type`/`license_note` added to
  asset DTOs plus a new asset PATCH endpoint, and a full `AssemblyStyleConfig`
  GET/PATCH endpoint added. `PublishJobMetric` intentionally deferred pending its own
  design pass; `NicheOutlierScan` and `PublishJob` swap-history fields intentionally
  deferred pending an actual UI consumer.
