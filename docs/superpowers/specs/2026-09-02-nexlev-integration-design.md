# NexLev Integration Design

Date: 2026-09-02
Status: Approved

## Goal

Replace the paid DataForSEO YouTube-data tools used by the channel research
agent with NexLev (cheaper plan, richer YouTube-specific data), without
deleting the DataForSEO integration — disable it behind a flag so it can be
re-enabled later. Extend NexLev into story/script setup where it adds value,
without letting it run on every pipeline execution and burn quota.

## Context

There is no third-party keyword-SEO tool in this codebase. "SEO" refers to
DataForSEO (`server/apps/generation/clients/dataforseo.py`), used only as a
YouTube SERP data source and registered as agent tools
(`youtube_search`, `video_info`, `video_comments`, `video_subtitles`) in
`server/apps/channel_research/agent.py:270-353`, capped via `TOOL_CAPS`
(agent.py:28-36). `FootageSourcingConfig.enabled_providers` is unrelated
(stock-footage providers).

`channel_research` is a one-shot pydantic-ai agent app that produces a
`ChannelSpec`. `server/services/channel_spec_importer.py`
(`ChannelSpecImporter.import_spec`) turns that spec into `Channel`,
`NicheConfig`, `PromptTemplate`/`PromptVersion` (Jinja, rendered by
`server/apps/pipelines/services/prompt_renderer.py`), and seeded
`TopicIdea` rows. The recurring content-generation pipeline
(`server/apps/pipelines/stages/script.py`, `metadata.py`) later renders
those prompt versions per video run — this runs far more often than
channel research, so it must not call NexLev directly.

## Decisions

- Disable, don't remove, DataForSEO: a settings flag gates whether
  `_register_dataforseo_tools(agent)` runs; client and tool code untouched.
- New `server/apps/nexlev` app owns the NexLev HTTP client, persistent
  per-channel/per-video records (not a throwaway cache), a short-TTL blob
  cache for live search, and a `NexLevService` with one read method per
  capability used (channel about/videos/outliers, YouTube search, video
  details/transcript/comments, similar channels, niche overview, async
  channel-analysis job create/poll).
- Records-first, not cache-first: `NexLevChannelRecord` (one row per
  `channel_id`) stores structured fields per NexLev section — `about`,
  `outliers`/`videos`, `analytics`, `similar_channels`, `niche_overview` —
  each with its own `*_fetched_at` timestamp. A `NexLevService` read method
  checks that section's staleness before calling the API, refetches only
  the stale section, and merges the update into the same row — it never
  force-refreshes sections it wasn't asked for. Staleness windows scale
  with quota cost and volatility: `about`/`outliers` (1 quota) every 7-30
  days; `analytics`/`similar_channels`/`niche_overview` (10-20 quota)
  every 30-60 days. The `channel_analysis` Deep Analysis result (20 quota)
  is stored on the record too but is never auto-refreshed — only an
  explicit operator retrigger updates it. `force_refresh: bool = False`
  param bypasses staleness on any section.
- `NexLevVideoRecord` (one row per `video_id`) stores details/transcript/
  comments with a long staleness window (this content is effectively
  immutable once published) — reused across research runs that reference
  the same video.
- `youtube_search` results are the one section that stays a short-TTL
  cache blob (not a persistent record) since live rankings genuinely
  shift day to day and a search query isn't a stable entity to attach a
  record to.
- `channel_research/agent.py` gets `_register_nexlev_tools(agent)`,
  replacing DataForSEO tools 1:1 where equivalent
  (`youtube_search`→NexLev search, `video_info`→video details,
  `video_comments`, `video_subtitles`→transcript) plus new tools
  (`channel_about`, `channel_outliers`, `similar_channels`) that fit the
  Niche-Bending methodology better than raw SERP data. `TOOL_CAPS` extended
  for the new tools, capped tighter for expensive ones (1 call/run for
  20-quota tools).
- A "Deep Analysis" action lives in `channel_research`
  (`ChannelResearchService` + API), operator-triggered, not automatic. It
  creates/polls NexLev's async channel-analysis job and stores
  `script_blueprint` / `suggested_topics` / `title_format_strategy` for
  review. `ChannelSpecImporter._seed_character_and_ideas` optionally
  consumes `suggested_topics` when deep analysis was run for that channel.
- No NexLev calls from the recurring pipeline (`script.py`, `metadata.py`)
  in this pass — value flows through once, at channel setup, via the spec
  importer.
- Single global `NEXLEV_API_KEY` / `NEXLEV_BASE_URL` (settings, same
  pattern as `DATAFORSEO_LOGIN`/`PASSWORD`), no per-channel credentials.
- Quota visibility, not enforcement: every fetch increments `quota_spent`
  on the relevant `NexLevChannelRecord`/`NexLevVideoRecord` (or is logged
  against the search cache entry). No hard spend cap. Client-side throttle
  on `youtube/search` (20 req/min NexLev limit) to avoid 429s within a
  single agent run.

## `server/apps/nexlev` structure

- `models.py`:
  - `NexLevChannelRecord` — `channel_id` (unique), structured JSON fields
    per section (`about`, `outliers`, `analytics`, `similar_channels`,
    `niche_overview`, `channel_analysis`) each paired with its own
    `*_fetched_at` nullable timestamp, plus `quota_spent` running total for
    visibility.
  - `NexLevVideoRecord` — `video_id` (unique), `details`, `transcript`,
    `comments` JSON fields with their own `*_fetched_at` timestamps.
  - `NexLevSearchCacheEntry` — short-TTL blob cache for `youtube_search`
    only (query hash, payload, fetched_at, expires_at).
- `clients/nexlev_client.py` — thin `httpx` wrapper, bearer auth, typed
  errors for 401/404/429/5xx, client-side throttle for `youtube/search`.
- `logic/value_objects.py` — `msgspec.Struct` DTOs for only the fields each
  consumed endpoint actually returns and we actually use (not the full API
  surface).
- `services.py` — `NexLevService` (`@final @attrs.define(slots=True,
  frozen=True)`), one method per capability. Channel/video methods do
  staleness-check → refetch stale section only → merge into record →
  return; search does the simple blob cache-check → fetch → store.
- `implemented.py` registration as DI singleton.

## Testing

Standard for this repo: `tests/test_apps/test_nexlev/` mirroring structure,
mocked `httpx` responses, factories for channel/video records and the
search cache entry, 100% coverage. Cover staleness-boundary cases per
section (fresh, stale, missing, `force_refresh`).
No new public API endpoints beyond the channel_research "Deep Analysis"
trigger, which gets a DMR controller test.

## Non-goals

- Removing DataForSEO code or its settings.
- Per-channel/per-operator NexLev credentials.
- Calling NexLev from the recurring per-video pipeline stages.
- Hard quota-spend enforcement/alerting (visibility/logging only).
- Building UI for NexLev data beyond what "Deep Analysis" needs to expose.
