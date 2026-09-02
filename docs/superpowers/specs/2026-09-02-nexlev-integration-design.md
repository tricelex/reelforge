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
- New `server/apps/nexlev` app owns the NexLev HTTP client, a DB-backed
  response cache, and a `NexLevService` with one read method per capability
  used (channel about/videos/outliers, YouTube search, video
  details/transcript/comments, similar channels, niche overview, async
  channel-analysis job create/poll).
- Cache-first: every `NexLevService` method checks the DB cache before
  calling the API. TTL scales with quota cost — 24h for 1-quota endpoints,
  7 days for 10-20 quota endpoints, 30 days for the 20-quota async
  channel-analysis job. `force_refresh: bool = False` param bypasses cache.
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
- Quota visibility, not enforcement: every call logs `quota_cost`,
  endpoint, and channel/video id (same cache table). No hard spend cap.
  Client-side throttle on `youtube/search` (20 req/min NexLev limit) to
  avoid 429s within a single agent run.

## `server/apps/nexlev` structure

- `models.py` — `NexLevCacheEntry` (endpoint, cache_key, payload JSON,
  quota_cost, fetched_at, expires_at).
- `clients/nexlev_client.py` — thin `httpx` wrapper, bearer auth, typed
  errors for 401/404/429/5xx.
- `logic/value_objects.py` — `msgspec.Struct` DTOs for only the fields each
  consumed endpoint actually returns and we actually use (not the full API
  surface).
- `services.py` — `NexLevService` (`@final @attrs.define(slots=True,
  frozen=True)`), one method per capability, each doing
  cache-check → client call → cache-store.
- `implemented.py` registration as DI singleton.

## Testing

Standard for this repo: `tests/test_apps/test_nexlev/` mirroring structure,
mocked `httpx` responses, factories for cache entries, 100% coverage.
No new public API endpoints beyond the channel_research "Deep Analysis"
trigger, which gets a DMR controller test.

## Non-goals

- Removing DataForSEO code or its settings.
- Per-channel/per-operator NexLev credentials.
- Calling NexLev from the recurring per-video pipeline stages.
- Hard quota-spend enforcement/alerting (visibility/logging only).
- Building UI for NexLev data beyond what "Deep Analysis" needs to expose.
