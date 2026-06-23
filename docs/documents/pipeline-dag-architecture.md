# ReelForge Pipeline DAG Architecture

## Table of Contents

1. [Overview](#1-overview)
2. [Core Data Models](#2-core-data-models)
3. [Blueprint Graph Format](#3-blueprint-graph-format)
4. [Stage Catalogue — LONGFORM](#4-stage-catalogue--longform)
5. [Stage Catalogue — SHORTS](#5-stage-catalogue--shorts)
6. [Stage Catalogue — CLIPPING](#6-stage-catalogue--clipping)
7. [Orchestration Engine](#7-orchestration-engine)
8. [Fan-Out Pattern](#8-fan-out-pattern)
9. [Gate Pattern](#9-gate-pattern)
10. [Conditional Stages](#10-conditional-stages)
11. [Idempotency & Retry Logic](#11-idempotency--retry-logic)
12. [Cost Tracking](#12-cost-tracking)
13. [Prompt System](#13-prompt-system)
14. [StoryFormat & Narrative Architecture](#14-storyformat--narrative-architecture)
15. [NicheConfig & Channel Configuration](#15-nicheconfig--channel-configuration)
16. [Snapshot Fields & Audit Trail](#16-snapshot-fields--audit-trail)
17. [End-to-End Walkthrough](#17-end-to-end-walkthrough)

---

## 1. Overview

ReelForge pipelines are **DAG-driven production systems** that turn a text topic into a
finished video (or a batch of short clips). The system has three pipeline kinds:

| Kind | What it produces | Default Blueprint |
|------|-----------------|-------------------|
| `LONGFORM` | Full-length YouTube video (5–20 min) | `longform_v1` |
| `SHORTS` | Short-form vertical video (30–90 s) | `shorts_v1` |
| `CLIPPING` | Social clips cut from existing footage | `clipping_v1` |

The fundamental design principle is **blueprint-driven execution**: a `PipelineBlueprint`
row holds a static JSON graph (DAG) that the orchestrator interprets at runtime. No code
changes are needed to add, remove, or reorder stages — only a new blueprint row.

---

## 2. Core Data Models

### 2.1 Model Hierarchy

```
PipelineBlueprint          — the recipe (versioned DAG definition)
    └── PipelineRun        — one execution of a blueprint for a topic
            ├── StageExecution   — one attempt at one DAG node
            │       └── CostRecord     — per-provider billing record
            ├── RunCast      — character assigned to this run
            ├── Asset        — generated file (video, audio, image)
            ├── ClipCandidate — identified clip moments
            └── PublishJob   — YouTube upload task
```

### 2.2 PipelineBlueprint

The immutable recipe. Stored once, referenced by many runs.

| Field | Type | Purpose |
|-------|------|---------|
| `name` | `CharField(100)` | Human slug, e.g. `longform_v1` |
| `kind` | `TextChoices` | `LONGFORM`, `SHORTS`, or `CLIPPING` |
| `graph` | `JSONField` | The DAG definition — see §3 |
| `is_active` | `BooleanField` | Whether new runs can use this blueprint |
| `version` | `PositiveIntegerField` | Monotone revision counter |

> **Key insight:** The `graph` field is the entire pipeline definition. Changing it on a
> live blueprint will affect future runs but never retroactively change running ones,
> because each `PipelineRun` snapshots the graph at creation time.

### 2.3 PipelineRun

One execution of a blueprint against a specific topic.

| Field | Type | Purpose |
|-------|------|---------|
| `channel` | `FK → Channel` | Which channel owns this run |
| `blueprint` | `FK → PipelineBlueprint` | Blueprint used (PROTECT) |
| `blueprint_snapshot` | `JSONField` | Frozen copy of `blueprint.graph` at run creation |
| `prompt_snapshot` | `JSONField` | Pinned active `PromptVersion` IDs at run creation |
| `topic` | `TextField` | The video topic / seed text |
| `status` | `RunStatus` | Current lifecycle state (see below) |
| `total_cost_usd` | `DecimalField` | Sum of all `CostRecord.total_usd` in this run |
| `started_at` / `finished_at` | `DateTimeField?` | Timing markers |
| `is_paused` | `BooleanField` | Orchestrator skips advancement when True |
| `source_idea` | `FK → TopicIdea?` | Link to the upstream backlog idea |

**RunStatus state machine:**

```
PENDING → RUNNING → AWAITING_REVIEW → PUBLISHING → COMPLETED
                 ↘              ↗
               BUDGET_HOLD
         ↘
          FAILED
         ↘
          CANCELLED
```

| Status | Meaning |
|--------|---------|
| `PENDING` | Created, orchestrator not yet evaluated |
| `RUNNING` | At least one stage is QUEUED or RUNNING |
| `AWAITING_REVIEW` | A gate stage is parked, waiting for human approval |
| `BUDGET_HOLD` | Run cost exceeded `channel.default_budget_usd` |
| `PUBLISHING` | Final publish stage is active |
| `COMPLETED` | All stages terminal (SUCCEEDED or SKIPPED) |
| `FAILED` | At least one stage FAILED with no remaining retries |
| `CANCELLED` | Manually cancelled; all active stages also cancelled |

### 2.4 StageExecution

One attempt at one node in the DAG. Multiple rows exist per stage if retried.

| Field | Type | Purpose |
|-------|------|---------|
| `run` | `FK → PipelineRun` | Parent run |
| `stage_key` | `CharField(64)` | Matches a `key` in the blueprint graph |
| `parent` | `FK → self?` | Null for top-level; set for fan-out shards |
| `shard_index` | `PositiveIntegerField?` | Which shard in a fan-out (null for parent row) |
| `status` | `StageStatus` | Current state (see below) |
| `attempt` | `PositiveIntegerField` | 0-based retry counter |
| `max_retries` | `PositiveIntegerField` | Default 3 |
| `input_hash` | `CharField(64)` | SHA-256 of serialised input (for idempotency) |
| `input_snapshot` | `JSONField` | Full input dict passed to `stage.run()` |
| `output` | `JSONField` | Stage result dict |
| `error` | `JSONField?` | Error metadata: `{type, message, retryable}` |
| `cost_usd` | `DecimalField` | Sum of child `CostRecord.total_usd` |
| `queue` | `CharField(32)` | Task queue: `api`, `render`, `gpu` |
| `started_at` / `finished_at` | `DateTimeField?` | Timing markers |

**StageStatus state machine:**

```
PENDING → QUEUED → RUNNING → SUCCEEDED
                          ↘  FAILED (retryable → new attempt with PENDING)
                          ↘  NEEDS_INPUT (fatal — requires manual intervention)
                          ↘  SKIPPED (conditional evaluated False)
                          ↘  STALE (upstream was rerun; this output is invalid)
                          ↘  CANCELLED (run was cancelled)
```

### 2.5 CostRecord

Per-call billing record attached to a `StageExecution`.

| Field | Purpose |
|-------|---------|
| `provider` | Service name: `elevenlabs`, `fal_flux`, `openai`, `anthropic` |
| `operation` | Call type: `tts_chars`, `image_gen`, `clip_analysis`, `completion` |
| `units` | Quantity consumed (characters, images, tokens) |
| `unit_cost_usd` | Price per unit at call time |
| `total_usd` | `units × unit_cost_usd` |

### 2.6 RunCast

Maps a `Character` to a `role` in one `PipelineRun`.

| Field | Purpose |
|-------|---------|
| `role` | String identifier: `narrator`, `interviewer`, `subject` |
| `is_ephemeral` | True if character is temporary (not saved to channel library) |
| `design_status` | `PROPOSED → APPROVED → DEMOTED` |

---

## 3. Blueprint Graph Format

The entire pipeline definition lives in `PipelineBlueprint.graph`, a JSON object with one
key: `"stages"` — an ordered list of stage node dicts.

### 3.1 Complete Node Schema

```json
{
  "key": "image_gen",
  "depends_on": ["visual_prompts"],
  "queue": "api",
  "fan_out": "scenes",
  "gate": false,
  "conditional": "channel.publish_mode == 'auto'",
  "config": {
    "model": "fal-ai/flux-kontext-pro",
    "use_character_ref": true
  }
}
```

| Field | Required | Type | Purpose |
|-------|----------|------|---------|
| `key` | Yes | string | Stage identifier — must match a registered `Stage.key` |
| `depends_on` | Yes | string[] | Keys of stages that must SUCCEED before this runs |
| `queue` | No | string | Task queue: `api` (default), `render`, `gpu` |
| `fan_out` | No | string | If set, calls `stage.fan_out()` to create parallel shards |
| `gate` | No | boolean | If true, parks run at AWAITING_REVIEW until externally approved |
| `conditional` | No | string | Python expression evaluated against run context; stage SKIPPED if False |
| `config` | No | object | Passed as `ctx.config` dict to the stage implementation |

### 3.2 Dependency Resolution Rules

- A stage can run when **all** its `depends_on` stages have reached `SUCCEEDED` or `SKIPPED`.
- A stage with `depends_on: []` runs immediately when the run is created.
- If a dependency FAILS, all stages that depend on it (directly or transitively) are blocked.
- The orchestrator iterates the `stages` list in order on every `advance_pipeline` call;
  the list order only matters for tie-breaking between equally-ready stages.

---

## 4. Stage Catalogue — LONGFORM

The `longform_v1` blueprint has 14 stages arranged in this DAG:

```
research
    └── outline
            └── script
                    └── scene_breakdown
                                ├── visual_prompts
                                │       └── image_gen [fan-out: scenes]
                                │               └── motion [fan-out: scenes]  ─────────────┐
                                ├── tts [fan-out: chapters]                                 │
                                │       └── alignment                          ─────────────┤
                                ├── music_plan                                 ─────────────┤
                                └── thumbnail                                               │
                    └── metadata (depends on: script + alignment)              ─────────────┤
                                                                                            │
                                                                             assembly ───────┘
                                                                             (depends on: motion, tts, alignment, music_plan)
                                                                                 └── qc
```

### Stage Details

#### `research`
- **Queue:** `api`
- **Depends on:** _(none — root stage)_
- **What it does:** Performs web search on the topic, synthesises a research brief using
  the LLM, identifies narrative angles and emotional hooks.
- **Output:**
  ```json
  {
    "brief": {"summary": "...", "key_facts": [...], "timeline": [...]},
    "sources": [{"title": "...", "url": "...", "relevance": 0.9}],
    "narrative_angles": ["angle1", "angle2"],
    "hooks": ["hook1", "hook2"]
  }
  ```
- **Prompt template key:** `research`

#### `outline`
- **Queue:** `api`
- **Depends on:** `research`
- **What it does:** Takes the research brief and structures a 6–10 chapter outline with
  retention devices (cliffhangers, callbacks, unanswered questions). Reads `StoryFormat.beats`
  from the niche config to align chapter structure with the chosen narrative format.
- **Output:**
  ```json
  {
    "chapters": [
      {"index": 0, "title": "...", "hook": "...", "key_beats": [...], "retention_device": "...", "target_seconds": 90}
    ],
    "total_target_seconds": 900
  }
  ```
- **Prompt template key:** `outline`

#### `script`
- **Queue:** `api`
- **Depends on:** `outline`
- **What it does:** Writes the complete narration script chapter-by-chapter. Uses the
  channel's `NicheConfig.lore_document` as a style guide, ensuring voice consistency.
  Every chapter ends with a `closing_line` to drive viewer retention.
- **Output:**
  ```json
  {
    "chapters": [
      {
        "index": 0,
        "title": "...",
        "narration": "Full narration text for this chapter...",
        "closing_line": "But what happened next would change everything."
      }
    ],
    "total_word_count": 3200
  }
  ```
- **Prompt template key:** `script`

#### `scene_breakdown`
- **Queue:** `api`
- **Depends on:** `script`
- **What it does:** Splits the script narration into 6–12 second visual scenes. Each
  scene specifies what the viewer sees on screen. Enforces hard constraints:
  `word_count` must be 10–35, `foreground_cast` must have ≤ 2 characters.
- **Output:**
  ```json
  {
    "scenes": [
      {
        "scene_index": 0,
        "chapter_index": 0,
        "narration_text": "In 476 AD, the last Roman emperor...",
        "visual_description": "Aerial wide shot of crumbling Roman colosseum at sunset",
        "foreground_cast": ["Dr. Marcus Webb"],
        "setting": "Ancient Rome ruins",
        "mood": "melancholic",
        "duration_hint_s": 8
      }
    ]
  }
  ```
- **Prompt template key:** `scene_breakdown`

#### `visual_prompts`
- **Queue:** `api`
- **Depends on:** `scene_breakdown`
- **What it does:** Generates a Flux-compatible image prompt for each scene. Incorporates
  the character's `appearance_prompt` from `RunCast` for visual consistency. Flags any
  scenes where the generated image might violate safety guidelines.
- **Output:**
  ```json
  {
    "prompts": [
      {
        "scene_index": 0,
        "prompt": "Photorealistic aerial drone shot of ancient Roman Colosseum, golden hour...",
        "negative_prompt": "modern buildings, cars, anachronisms...",
        "style_tags": ["cinematic", "documentary", "historical"],
        "safety_flagged": false
      }
    ]
  }
  ```
- **Prompt template key:** `visual_prompts`

#### `image_gen` _(fan-out: scenes)_
- **Queue:** `api`
- **Depends on:** `visual_prompts`
- **Fan-out:** Creates one child `StageExecution` per scene, each with a `shard_index`
  matching the scene index. All shards run in parallel.
- **Config keys:** `model` (Flux model slug), `use_character_ref` (bool)
- **What it does:** Calls the Fal-AI API with the scene's image prompt. Returns an S3
  `asset_id` for the generated image.
- **Output per shard:**
  ```json
  {"scene_idx": 3, "asset_id": "uuid", "seed": 42891234}
  ```

#### `tts` _(fan-out: chapters)_
- **Queue:** `api`
- **Depends on:** `scene_breakdown`
- **Fan-out:** Creates one child per chapter, running ElevenLabs API calls in parallel.
- **Config keys:** `provider` (`elevenlabs`)
- **What it does:** Converts each chapter's narration to audio using the channel's TTS
  config (`voice_id`, `stability`, `similarity_boost`, `wpm`). Returns an audio `asset_id`
  per chapter.
- **Output per shard:**
  ```json
  {"chapter_idx": 2, "asset_id": "uuid", "char_count": 1840}
  ```

#### `motion` _(fan-out: scenes)_
- **Queue:** `render`
- **Depends on:** `image_gen`
- **Fan-out:** One shard per scene, matching `image_gen` shard indices.
- **Config keys:** `hero_ratio` (face detection sensitivity), `i2v_model` (Kling/RunwayML slug)
- **What it does:** Takes the static image from `image_gen` and animates it with an
  image-to-video model (e.g. Fal-AI Kling). Produces a short video clip per scene.
- **Output per shard:**
  ```json
  {"scene_idx": 3, "asset_id": "uuid"}
  ```

#### `alignment`
- **Queue:** `gpu`
- **Depends on:** `tts`
- **What it does:** Runs WhisperX forced alignment over all TTS audio shards combined.
  Produces word-level timestamps and scene-boundary markers. Also generates an `.ass`
  subtitle file for burn-in captions. Consumes all `tts` shards via their aggregated output.
- **Output:**
  ```json
  {
    "scenes": [
      {"scene_index": 0, "start_s": 0.0, "end_s": 7.4, "words": [...]}
    ],
    "ass_asset_id": "uuid"
  }
  ```

#### `music_plan`
- **Queue:** `api`
- **Depends on:** `scene_breakdown`
- **What it does:** Uses the LLM to select background music tracks from the channel's
  `LibraryAsset` music pool, matching mood to each chapter. Reads `StoryFormat.music_mood_map`
  to align track choices with the narrative format.
- **Output:**
  ```json
  {
    "entries": [
      {"chapter_idx": 0, "library_asset_id": "uuid", "gain_db": -18, "mood": "epic"}
    ]
  }
  ```
- **Prompt template key:** `music_plan`

#### `thumbnail`
- **Queue:** `api`
- **Depends on:** `script`
- **Config keys:** `candidates` (number of concepts to generate, default 3)
- **What it does:** Generates N thumbnail image candidates using the first-chapter script
  context, channel branding palette, and character reference.
- **Output:**
  ```json
  {"candidate_ids": ["uuid1", "uuid2", "uuid3"], "count": 3}
  ```
- **Prompt template key:** `thumbnail`

#### `metadata`
- **Queue:** `api`
- **Depends on:** `script`, `alignment`
- **What it does:** Generates SEO-optimised YouTube metadata using the full script and
  word-level alignment timestamps (to populate description chapter markers).
- **Output:**
  ```json
  {
    "title": "The Fall of Rome: What Really Happened in 476 AD",
    "description": "For centuries historians have argued...\n\n00:00 Introduction\n01:45 ...",
    "tags": ["roman empire", "ancient history", "476 ad", ...],
    "category": "Education"
  }
  ```
- **Prompt template key:** `metadata`

#### `assembly`
- **Queue:** `render`
- **Depends on:** `motion`, `tts`, `alignment`, `music_plan`
- **What it does:** FFmpeg pipeline that:
  1. Stitches animated scene clips (`motion` shards) in order
  2. Overlays per-chapter VO audio (`tts` shards)
  3. Burns in ASS captions from `alignment`
  4. Mixes background music from `music_plan`
  5. Applies channel branding (intro, outro, watermark)
- **Output:**
  ```json
  {"asset_id": "uuid", "duration_sec": 847.2}
  ```

#### `qc`
- **Queue:** `render`
- **Depends on:** `assembly`
- **What it does:** Automated quality checks on the assembled video:
  - Audio levels within acceptable range
  - No black frames > 2 seconds
  - Captions legible (confidence score)
  - Duration matches outline target ± 20%
- **Output:**
  ```json
  {"passed": true, "issues": []}
  ```
  If `passed: false` with issues, the run transitions to `AWAITING_REVIEW` for a human
  to inspect and either approve or re-run upstream stages.

---

## 5. Stage Catalogue — SHORTS

The `shorts_v1` blueprint removes GPU-intensive stages to produce a fast, cost-efficient
vertical video for YouTube Shorts. No I2V animation, no background music, no thumbnail.

```
research
    └── outline
            └── script
                    └── scene_breakdown
                                ├── visual_prompts
                                │       └── image_gen [fan-out: scenes] ────────────┐
                                └── tts [fan-out: chapters]                         │
                                        └── alignment          ─────────────────────┤
                                                                                    │
                                                     metadata (script + alignment)  │
                                                                                    │
                                               assembly (image_gen, tts, alignment) ┘
                                                     └── qc
```

**Omitted vs LONGFORM:**

| Stage | Reason omitted |
|-------|----------------|
| `motion` | GPU/cost intensive; static images fine for Shorts |
| `music_plan` | No BGM in most Shorts formats |
| `thumbnail` | Shorts use auto-generated thumbnails |

**`assembly` config for Shorts:**
```json
{"format": "shorts", "target_duration_s": 60}
```
Assembly renders in 9:16 vertical format, crops images to centre, scales VO to target
duration.

---

## 6. Stage Catalogue — CLIPPING

The `clipping_v1` blueprint extracts viral clip candidates from existing source footage
(a long-form video file or YouTube URL).

```
clip_ingest
    └── clip_transcribe
            └── clip_analyze
                    └── clip_approval_gate [GATE — pauses run]
                                └── clip_render
                                        └── clip_distribute
```

#### `clip_ingest`
- **Queue:** `api`
- **What it does:** Downloads or copies the source video. Registers a `ClipSource` row.
  Computes duration.
- **Output:** `{"source_asset_id": "uuid", "duration_sec": 3612.0}`

#### `clip_transcribe`
- **Queue:** `gpu`
- **Depends on:** `clip_ingest`
- **What it does:** Runs Whisper on the source audio to produce a full word-level transcript
  with diarization and scene-cut detection.
- **Output:** `{"manifest_asset_id": "uuid", "word_count": 28400}`

#### `clip_analyze`
- **Queue:** `api`
- **Depends on:** `clip_transcribe`
- **Config keys:** `clips_requested` (default 5)
- **What it does:** LLM analysis of the transcript to identify high-impact moments for
  short-form clips. Scores each candidate on virality signals.
  Creates `ClipCandidate` rows (each auto-gets a `ClipLayoutConfig` and `ClipStyleConfig`
  via Django post-save signal).
- **Output:** `{"candidate_ids": ["uuid1", "uuid2", ...], "count": 5}`
- **Prompt template key:** `clip_analyze`

#### `clip_approval_gate` _(gate)_
- **Queue:** `api`
- **Depends on:** `clip_analyze`
- **`gate: true`** — parks the run at `AWAITING_REVIEW` until a human:
  1. Reviews `ClipCandidate` rows in the admin/UI
  2. Approves specific candidates
  3. Calls `approve_gate_impl(run_id, 'clip_approval_gate', {approved_candidate_ids: [...]})`
- **Gate output** (provided by human):
  ```json
  {"approved_candidate_ids": ["uuid1", "uuid3"]}
  ```

#### `clip_render`
- **Queue:** `gpu`
- **Depends on:** `clip_approval_gate`
- **What it does:** Renders each approved `ClipCandidate` using its `ClipLayoutConfig`
  (crop mode, format) and `ClipStyleConfig` (captions, watermark, music, hooks).
- **Output:** `{"asset_id": "uuid", "duration_sec": 67.3}`

#### `clip_distribute`
- **Queue:** `api`
- **Depends on:** `clip_render`
- **What it does:** Publishes rendered clips to configured platforms. Creates `ClipPost`
  rows tracking status, platform URLs, and engagement metrics.
- **Output:** `{"job_id": "uuid", "platform_urls": {"youtube_shorts": "https://..."}}`

---

## 7. Orchestration Engine

### 7.1 Entry Point: `advance_pipeline_impl(run_id)`

Called whenever the run state may have changed (after creation, after each stage
completes, after a gate is approved). The function:

1. Opens a database transaction and issues `SELECT FOR UPDATE` on the `PipelineRun` row.
   This prevents concurrent orchestrator calls from racing on the same run.
2. Calls `_get_stage_states(run)` — queries the latest `StageExecution` attempt for
   each `stage_key` in the run, returning a dict:
   ```python
   {"research": StageStatus.SUCCEEDED, "outline": StageStatus.QUEUED, ...}
   ```
3. Iterates the `blueprint_snapshot.stages` list in order. For each node:
   - **Skip entirely** if `conditional` evaluates False against the run context
   - **Park as gate** if `gate=True` and all deps are terminal
   - **Enqueue** if no current status and all deps are terminal (SUCCEEDED or SKIPPED)
   - **Do nothing** if already in flight or waiting for deps
4. Determines new `RunStatus` from aggregated stage states
5. Commits transaction
6. Outside transaction: dispatches enqueued `StageExecution` rows to the task queue

### 7.2 Dependency Resolution Logic

A stage node is **ready to run** when:
- It has no current `StageExecution` (never started or fully replaced by STALE)
- Every key in `depends_on` maps to `SUCCEEDED` or `SKIPPED` in the current states dict

A stage is **blocked** when:
- Any dependency is `PENDING`, `QUEUED`, or `RUNNING`

A stage is **stuck** when:
- Any dependency is `FAILED` or `NEEDS_INPUT` (run transitions to FAILED)

### 7.3 Run Status Transitions

After evaluating all nodes, the orchestrator applies these rules (first match wins):

| Condition | New RunStatus |
|-----------|---------------|
| Any stage is `FAILED` or `NEEDS_INPUT` | `FAILED` |
| Any stage is `gate: true` and RUNNING (parked) | `AWAITING_REVIEW` |
| Any stage is `QUEUED` or `RUNNING` | `RUNNING` |
| All stages `SUCCEEDED` or `SKIPPED` | `COMPLETED` |
| No stages active yet | `PENDING` |

---

## 8. Fan-Out Pattern

Fan-out allows a single stage to spawn parallel child executions — one per scene, chapter,
or any other iterable defined by the stage's `fan_out()` method.

### 8.1 Fan-Out Trigger

When the orchestrator enqueues a stage with `fan_out` set in its blueprint node, the
executor calls `stage.fan_out(ctx) → list[dict]` **before** calling `stage.run()`.

Each dict in the returned list becomes one **shard** — a child `StageExecution` with:
- `parent` = the parent execution
- `shard_index` = its position in the list
- `input_snapshot` = the individual shard dict

The parent row stays in `RUNNING` while children execute.

### 8.2 Example: `image_gen`

```
blueprint node: {"key": "image_gen", "fan_out": "scenes", ...}

stage.fan_out(ctx) returns:
  [{"scene_idx": 0, "prompt": "..."}, {"scene_idx": 1, "prompt": "..."}, ...]

Executor creates:
  StageExecution(stage_key="image_gen", parent=parent_exec, shard_index=0, ...)
  StageExecution(stage_key="image_gen", parent=parent_exec, shard_index=1, ...)
  StageExecution(stage_key="image_gen", parent=parent_exec, shard_index=2, ...)
  ... (one per scene)
```

All shards are enqueued simultaneously and run in parallel across the `api` queue workers.

### 8.3 Fan-Out Completion

When any shard transitions to a terminal state (SUCCEEDED, FAILED, SKIPPED), the executor:

1. Queries all sibling shards for the same `parent`
2. If **all terminal**: marks the parent `SUCCEEDED` with aggregated output:
   ```json
   {
     "shards": [
       {"shard_index": 0, "status": "SUCCEEDED"},
       {"shard_index": 1, "status": "SUCCEEDED"},
       {"shard_index": 2, "status": "SUCCEEDED"}
     ]
   }
   ```
3. Calls `advance_pipeline_impl()` to unblock downstream stages
4. If **any FAILED** and no in-flight siblings remain: marks parent `FAILED`

### 8.4 Downstream Reads of Shards

Stages that depend on a fan-out stage receive the full shard set via `ctx.upstream`.
For example, `motion` depends on `image_gen` and receives:
```python
ctx.upstream["image_gen"] == {
    "shards": [
        {"shard_index": 0, "status": "SUCCEEDED"},
        ...
    ]
}
```
The `motion` stage then queries `StageExecution` rows directly to get each shard's
`asset_id` output for its own fan-out.

---

## 9. Gate Pattern

Gates are review checkpoints that pause pipeline execution until a human provides input.

### 9.1 Blueprint Marker

```json
{"key": "clip_approval_gate", "depends_on": ["clip_analyze"], "gate": true}
```

Any node with `"gate": true` is a gate. The gate key must match a registered stage
implementation (e.g. `ClipApprovalGateStage`).

### 9.2 Gate Lifecycle

```
1. All gate dependencies SUCCEED
2. Orchestrator calls _park_gate_sync():
   - Creates StageExecution with status=RUNNING
   - Sets PipelineRun.status = AWAITING_REVIEW
3. Human reviews (admin UI, API call)
4. Human calls approve_gate_impl(run_id, gate_key, output_dict)
5. Gate StageExecution marked SUCCEEDED with the provided output_dict
6. advance_pipeline_impl() re-runs → downstream stages now unblocked
```

### 9.3 Gate Channel Configuration

`Channel.gates` is a PostgreSQL array of **armed gate keys**. If a gate key is NOT in
`channel.gates`, the orchestrator skips it (treats it as if it immediately SUCCEEDED with
empty output). This allows per-channel control over which review gates are active.

Example:
- `channel.gates = []` → all gates auto-pass, fully automated pipeline
- `channel.gates = ['clip_approval_gate']` → clip approval requires human sign-off
- `channel.gates = ['storyboard_gate', 'clip_approval_gate']` → both gates active

### 9.4 The `review_gate` Stage

The `review_gate` stage (available in LONGFORM blueprints) is a human review checkpoint
between `qc` and an optional `publish` stage. It presents the assembled video + storyboard
to the content owner for approval before upload.

---

## 10. Conditional Stages

A stage with a `conditional` field is evaluated at orchestrator time. If the expression
evaluates to `False`, the stage is marked `SKIPPED` and is treated as terminal.

### 10.1 Supported Expressions

```json
{"key": "review_gate", "conditional": "channel.publish_mode == 'review'"}
{"key": "auto_publish",  "conditional": "channel.publish_mode == 'auto'"}
```

The evaluator reads from the live `run.channel` object.

### 10.2 Practical Use

This allows the same blueprint to serve both `AUTO` and `REVIEW` publish modes:

```
                          ┌─ review_gate [conditional: publish_mode == 'review'] ─┐
qc ─────────────────────┤                                                          ├─ publish
                          └─ (SKIPPED if publish_mode == 'auto') ─────────────────┘
```

When `publish_mode = auto`:
- `review_gate` is instantly SKIPPED
- `publish` runs immediately after `qc`

When `publish_mode = review`:
- `review_gate` parks the run at AWAITING_REVIEW
- Human approves → `publish` runs

---

## 11. Idempotency & Retry Logic

### 11.1 Input Hash Caching

Before executing any stage, the executor computes:
```python
input_hash = sha256(json.dumps(input_snapshot, sort_keys=True)).hexdigest()
```

It then searches for a prior `StageExecution` with the same `(run, stage_key, shard_index,
input_hash)` that is `SUCCEEDED`. If found, it copies the prior output and marks the new
execution `SUCCEEDED` immediately — **zero API calls, zero cost**.

This means re-running an unchanged stage is free. Only genuinely new input triggers a
real API call.

### 11.2 Retry Mechanics

On stage failure, the executor checks `attempt < max_retries`:
- **If retries remain:** Creates a new `StageExecution` with `attempt+1` and `status=PENDING`.
  The orchestrator picks it up on next advance.
- **If retries exhausted:** Marks the execution `FAILED` permanently. The run transitions
  to `FAILED` status.

### 11.3 Error Categories

| Error Type | Behaviour |
|-----------|-----------|
| `RetryableProviderError` | Create new attempt (rate limits, 5xx, timeouts) |
| `FatalProviderError` | Mark `NEEDS_INPUT` — requires manual intervention |
| Asyncio timeout | Same as `RetryableProviderError` |
| Any other exception | Mark `FAILED` |

`NEEDS_INPUT` is a special state indicating the stage cannot proceed without human action
(e.g. API quota exhausted, content moderation block). The run transitions to `FAILED`
and a human must rerun the stage after resolving the issue.

---

## 12. Cost Tracking

Every external API call creates a `CostRecord` attached to the `StageExecution`.

### 12.1 Rollup Chain

```
CostRecord (per API call)
    → StageExecution.cost_usd (sum of its CostRecords)
        → PipelineRun.total_cost_usd (sum of all its StageExecution.cost_usd)
```

### 12.2 Provider Examples

| Provider | Operation | Units | Unit cost |
|----------|-----------|-------|-----------|
| `elevenlabs` | `tts_chars` | characters | $0.000030 |
| `fal_flux` | `image_gen` | images | $0.05 |
| `fal_kling` | `i2v` | seconds | $0.0045 |
| `openai` | `completion` | tokens | varies by model |
| `whisper` | `transcription` | audio_seconds | $0.000006 |

### 12.3 Budget Hold

If `PipelineRun.total_cost_usd` exceeds `Channel.default_budget_usd` during execution,
the orchestrator transitions the run to `BUDGET_HOLD` and stops enqueueing new stages.
A human can then approve continuation or cancel.

---

## 13. Prompt System

### 13.1 PromptTemplate

A named slot for a prompt, keyed by stage (e.g. `"research"`, `"outline"`). The `scope`
field controls where in the hierarchy the template applies:

| Scope | Meaning |
|-------|---------|
| `GLOBAL` | Used by all channels unless overridden |
| `NICHE` | Overrides GLOBAL for a specific niche config |
| `CHANNEL` | Overrides NICHE for a specific channel |

### 13.2 PromptVersion

One concrete version of a template. Fields:

| Field | Purpose |
|-------|---------|
| `version` | Monotone integer; unique per template |
| `system_prompt` | LLM system role (Jinja2 template string) |
| `user_prompt` | LLM user message (Jinja2 template string) |
| `model` | LLM model slug, e.g. `gpt-5.2` |
| `temperature` | Sampling temperature (default 1.0) |
| `max_tokens` | Max output tokens (default 8192) |
| `is_active` | Only one version per template should be active |

### 13.3 Jinja2 Rendering

The `PromptRenderer` service resolves the active `PromptVersion` for a given template key
and renders its `system_prompt` and `user_prompt` as Jinja2 templates with variables from
the stage context.

Common template variables available in prompts:

```
{{ topic }}                          — run.topic
{{ channel.name }}                   — channel name
{{ channel.kind }}                   — LONGFORM / SHORTS / CLIPPING
{{ niche.audience }}                 — NicheConfig.audience
{{ niche.angle }}                    — NicheConfig.angle
{{ niche.banned_topics }}            — list of banned topic strings
{{ lore }}                           — NicheConfig.lore_document
{{ format.name }}                    — StoryFormat.name
{{ format.beats }}                   — StoryFormat.beats list
{{ format.narration_pov }}           — StoryFormat.narration_pov
{{ format.music_mood_map }}          — StoryFormat.music_mood_map dict
{{ upstream.research.brief }}        — output of the research stage
{{ upstream.outline.chapters }}      — output of the outline stage
{{ upstream.script.chapters }}       — output of the script stage
{{ upstream.scene_breakdown.scenes }} — output of the scene_breakdown stage
{{ character.name }}                 — primary character name from RunCast
{{ character.appearance_prompt }}    — Flux character appearance string
{{ config }}                         — stage node's config dict from blueprint
```

### 13.4 Prompt Snapshot

At `PipelineRun` creation time, the service records the currently-active `PromptVersion`
IDs in `prompt_snapshot`. This pinning means the run always executes against the same
prompt versions even if an admin activates a new version mid-run.

---

## 14. StoryFormat & Narrative Architecture

A `StoryFormat` row defines the narrative architecture used by the LLM stages.

### 14.1 Fields

| Field | Purpose |
|-------|---------|
| `key` | Unique slug, e.g. `factual_documentary` |
| `fiction` | True for fictional narrative formats |
| `narration_pov` | `narrator`, `investigative_narrator`, `teacher`, `coach` |
| `beats` | Ordered list of beat dicts defining the narrative arc |
| `pacing` | Per-beat target duration in seconds |
| `music_mood_map` | Beat name → music mood tag |
| `prompt_overrides` | Per-template-key prompt suffix/prefix overrides |

### 14.2 beats Array

```json
[
  {"name": "hook",         "description": "Open with the most dramatic moment"},
  {"name": "context",      "description": "Establish the historical setting"},
  {"name": "evidence",     "description": "Present key facts and supporting detail"},
  {"name": "implications", "description": "Explain why this matters today"},
  {"name": "call_to_action","description": "Invite viewers to reflect and subscribe"}
]
```

The `outline` stage receives `format.beats` and structures chapters to follow this arc.

### 14.3 music_mood_map

```json
{
  "hook":          "tense",
  "context":       "atmospheric",
  "evidence":      "dramatic",
  "implications":  "reflective",
  "call_to_action":"uplifting"
}
```

The `music_plan` stage reads this map to select appropriate tracks from the channel's
music library for each narrative beat.

### 14.4 NicheConfig → StoryFormat Link

`NicheConfig.format` is a nullable FK to `StoryFormat`. When set, it injects the beats,
pacing, and music mood map into the stage context so every run on that channel follows the
chosen narrative structure.

---

## 15. NicheConfig & Channel Configuration

### 15.1 NicheConfig

One `NicheConfig` per channel (OneToOne). Controls:

| Field | Purpose |
|-------|---------|
| `audience` | Audience description — injected into research and script prompts |
| `angle` | Editorial angle — shapes how the LLM frames content |
| `banned_topics` | Array of topics to explicitly avoid |
| `lore_document` | Long-form style guide / world-lore injected into script prompt |
| `format` | FK to `StoryFormat` |

### 15.2 Channel TTS Config

| Field | Purpose |
|-------|---------|
| `voice_id` | ElevenLabs voice ID |
| `stability` | ElevenLabs stability (0.0–1.0) |
| `similarity_boost` | ElevenLabs similarity boost (0.0–1.0) |
| `wpm` | Words per minute target for TTS pacing |

### 15.3 Channel Production Config

| Field | Purpose |
|-------|---------|
| `publish_mode` | `auto` or `review` — controls conditional stage evaluation |
| `gates` | Array of gate keys that are armed for human review |
| `character_design_mode` | `interactive` (user picks), `auto` (pipeline picks), `none` |
| `default_budget_usd` | Cost ceiling before BUDGET_HOLD |

---

## 16. Snapshot Fields & Audit Trail

ReelForge uses immutable snapshots to ensure runs are reproducible and auditable even
after configuration changes.

| Snapshot | Location | What it captures |
|----------|----------|-----------------|
| `blueprint_snapshot` | `PipelineRun` | Full `graph` dict at run creation |
| `prompt_snapshot` | `PipelineRun` | Active `PromptVersion` IDs per template key |
| `input_snapshot` | `StageExecution` | Full input dict passed to `stage.run()` |
| `metadata_snapshot` | `PublishJob` | YouTube metadata at upload time |

These snapshots mean:
- Changing a blueprint does not break running runs
- Updating a prompt version does not change in-flight runs
- Stage inputs can be replayed exactly to reproduce any output
- Cost audits are possible even after CostRecord rows are aggregated

---

## 17. End-to-End Walkthrough

Here is a complete example for a LONGFORM run on the "History Explained" channel:

```
1. IDEATION
   TopicIdea("The Fall of Rome", score=0.92, status=BACKLOG)

2. PROMOTION
   User approves idea → IdeaStatus.PROMOTED
   PipelineRunService.create(channel_id, topic="The Fall of Rome", blueprint_name="longform_v1")
   → PipelineRun(status=PENDING, blueprint_snapshot={14 stages}, prompt_snapshot={9 templates})

3. INITIAL ADVANCE
   advance_pipeline_impl(run_id)
   → research: no deps → create StageExecution(status=QUEUED)
   → enqueue execute_stage_kiq(research_exec_id) → research runs

4. RESEARCH STAGE
   stage.run(ctx):
   - Calls web search API, synthesises brief with GPT-5.2
   - CostRecord(provider='openai', operation='completion', units=4200, total=$0.04)
   - StageExecution marked SUCCEEDED, output={brief, sources, angles, hooks}
   - advance_pipeline_impl() re-runs

5. ADVANCE #2
   → outline: deps=[research] ✓ → QUEUED

6. [outline → script → scene_breakdown: sequential, one at a time]

7. SCENE_BREAKDOWN SUCCEEDS
   advance_pipeline_impl():
   → visual_prompts: deps=[scene_breakdown] ✓ → QUEUED
   → tts: deps=[scene_breakdown] ✓ → QUEUED
   → music_plan: deps=[scene_breakdown] ✓ → QUEUED
   All three enqueued simultaneously

8. VISUAL_PROMPTS SUCCEEDS
   → image_gen: fan_out() returns 42 scene dicts
   → Creates 42 child StageExecution rows (shard_index 0–41)
   → 42 parallel Fal-AI calls

9. TTS SUCCEEDS (fan-out across 8 chapters)
   → alignment: deps=[tts] ✓ → QUEUED
   → WhisperX GPU job runs (~3 min)

10. ALL image_gen SHARDS SUCCEED
    → Parent image_gen marked SUCCEEDED
    → motion: fan_out() creates 42 shards → 42 Kling I2V calls (GPU queue)

11. MOTION + TTS + ALIGNMENT + MUSIC_PLAN ALL SUCCEED
    → assembly: deps all met → QUEUED
    → FFmpeg render job combines everything (~5 min)

12. ASSEMBLY SUCCEEDS → qc SUCCEEDS

13. RUN STATUS = COMPLETED (all 14 stages SUCCEEDED or SKIPPED)
    PipelineRun.total_cost_usd = sum($0.04 + ... + $2.85) = $3.21

14. HUMAN REVIEW
    Editor opens storyboard UI, approves metadata, uploads thumbnail
    PublishJob created → YouTube Data API upload
```

**Total wall-clock time** (typical): 8–12 minutes
(Most time: Fal-AI image gen ~2 min, Kling motion ~4 min, WhisperX alignment ~3 min)

**Key concurrency points:**
- `visual_prompts`, `tts`, and `music_plan` all run in parallel after `scene_breakdown`
- All 42 `image_gen` shards run in parallel
- All 42 `motion` shards run in parallel
- All 8 `tts` shards run in parallel
- Only `assembly` is a synchronisation point (needs all of the above)
