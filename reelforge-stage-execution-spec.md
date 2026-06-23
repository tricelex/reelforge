# Reelforge Platform — Stage Execution & DAG Design Spec

**Version:** 1.0 · **Stack:** Django (ASGI) + TaskIQ/Redis + Postgres + RustFS (S3) + TanStack Start
**Scope:** Single-tenant internal platform. Long-form AI video automation + podcast clipping.

---

## 1. Django App Breakdown

Each app owns its models, services, and tasks. Service-layer pattern (HackSoft styleguide): views are thin, all logic lives in `services.py` / `selectors.py`.

| App | Responsibility | Key models |
|---|---|---|
| `core` | Base models (UUIDModel, TimeStampedModel), Redis pub/sub helpers, SSE consumers, enums, exceptions | — |
| `channels` | YouTube channels, niches, branding config, characters, OAuth credentials | `Channel`, `NicheConfig`, `Character`, `YouTubeCredential`, `ChannelBranding` |
| `prompts` | Versioned prompt templates, Jinja2 rendering, scoping (global → niche → channel) | `PromptTemplate`, `PromptVersion` |
| `pipelines` | The DAG engine: blueprints, runs, stage executions, orchestrator, review gates | `PipelineBlueprint`, `PipelineRun`, `StageExecution`, `CostRecord` |
| `assets` | Generated assets + reusable Asset Library, upload normalization, S3 storage | `Asset`, `LibraryAsset`, `AssetRendition` |
| `generation` | Provider service layer: LLM, fal.ai (Flux/Kontext/Kling), ElevenLabs, WhisperX. Each provider wrapped with retry classification + cost capture | provider configs only |
| `rendering` | FFmpeg service: filtergraph builders, scene rendering, Ken Burns, caption burn, assembly, thumbnail compositing | `RenderProfile` |
| `publishing` | YouTube Data API upload, scheduling, metadata, chapters | `PublishJob`, `UploadSchedule` |
| `clipping` | Podcast ingestion, diarization, highlight scoring, clip exports, campaigns, earnings | `SourceMedia`, `Transcript`, `Clip`, `ClipCampaign`, `Earning` |
| `analytics` | Cost-per-video reports, channel ROI dashboards (phase 2) | materialized views |

**Dependency direction (strict, no cycles):**
`core` ← everything · `pipelines` imports `generation`/`rendering`/`assets` services · `clipping` reuses `pipelines` engine with its own blueprint · `publishing` is a leaf consumed by pipeline stages.

---

## 2. The DAG Engine

### 2.1 Design principles

1. **Stages are code, wiring is data.** Stage implementations live in a code registry (typed, testable). Which stages run, their dependencies, and their config live in a DB `PipelineBlueprint` — so you can toggle Kling off for a cheap channel without deploying.
2. **Every stage is idempotent and resumable.** Inputs are hashed; if a stage runs twice with identical inputs it returns the cached output instead of re-spending API money.
3. **Fan-out is first-class.** Image gen for 200 scenes is 200 child executions under one parent — each retryable individually. One failed scene never restarts the run.
4. **Snapshot everything.** A run snapshots its blueprint JSON and every prompt version it used. Reproducibility = debuggability = prompt A/B testing.
5. **Money is a metric.** Every provider call writes a `CostRecord`. You always know cost-per-video, per-stage, per-channel.

### 2.2 Models

```python
# pipelines/models.py


class PipelineBlueprint(UUIDModel, TimeStampedModel):
    """Editable DAG definition. Channels point at one."""

    name = models.CharField(max_length=100)  # "longform_v2", "clipping_v1"
    kind = models.CharField(
        choices=PipelineKind.choices
    )  # LONGFORM | SHORTS | CLIPPING
    graph = models.JSONField()  # see §2.3
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)


class PipelineRun(UUIDModel, TimeStampedModel):
    channel = models.ForeignKey('channels.Channel', on_delete=models.PROTECT)
    blueprint = models.ForeignKey(PipelineBlueprint, on_delete=models.PROTECT)
    blueprint_snapshot = models.JSONField()  # frozen at start
    prompt_snapshot = models.JSONField(
        default=dict
    )  # {stage_key: prompt_version_id}
    topic = models.TextField()  # the video idea / seed
    status = models.CharField(
        choices=RunStatus.choices, default=RunStatus.PENDING
    )
    # PENDING → RUNNING → AWAITING_REVIEW → PUBLISHING → COMPLETED
    #                   ↘ FAILED / CANCELLED
    total_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)


class StageExecution(UUIDModel, TimeStampedModel):
    run = models.ForeignKey(
        PipelineRun, related_name='stages', on_delete=models.CASCADE
    )
    stage_key = models.CharField(max_length=64, db_index=True)  # "image_gen"
    parent = models.ForeignKey(
        'self', null=True, related_name='children', on_delete=models.CASCADE
    )  # fan-out children
    shard_index = models.PositiveIntegerField(
        null=True
    )  # scene number for children
    status = models.CharField(
        choices=StageStatus.choices, default=StageStatus.PENDING
    )
    # PENDING → QUEUED → RUNNING → SUCCEEDED
    #                            ↘ FAILED → (retry) → QUEUED
    #                            ↘ NEEDS_INPUT   (fatal provider error, human must edit)
    # SKIPPED · STALE (downstream of a re-run stage) · CANCELLED
    attempt = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    input_hash = models.CharField(
        max_length=64, db_index=True
    )  # sha256 of resolved inputs
    input_snapshot = models.JSONField(default=dict)
    output = models.JSONField(
        default=dict
    )  # {"asset_ids": [...], "data": {...}}
    error = models.JSONField(null=True)  # {type, message, provider, retryable}
    cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    queue = models.CharField(
        max_length=32, default='api'
    )  # "api" | "render" | "gpu"
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['run', 'stage_key', 'shard_index', 'attempt'],
                name='uq_stage_attempt',
            )
        ]


class CostRecord(UUIDModel, TimeStampedModel):
    stage_execution = models.ForeignKey(
        StageExecution, related_name='costs', on_delete=models.CASCADE
    )
    provider = models.CharField(
        max_length=32
    )  # "fal_flux", "kling", "elevenlabs", "openai"
    operation = models.CharField(
        max_length=64
    )  # "image_gen", "i2v_5s", "tts_chars"
    units = models.DecimalField(
        max_digits=12, decimal_places=4
    )  # images, seconds, chars, tokens
    unit_cost_usd = models.DecimalField(max_digits=10, decimal_places=6)
    total_usd = models.DecimalField(max_digits=10, decimal_places=4)
```

### 2.3 Blueprint graph format

```json
{
  "stages": [
    {"key": "research",        "depends_on": [],                          "queue": "api"},
    {"key": "outline",         "depends_on": ["research"],                "queue": "api"},
    {"key": "script",          "depends_on": ["outline"],                 "queue": "api"},
    {"key": "scene_breakdown", "depends_on": ["script"],                  "queue": "api"},
    {"key": "visual_prompts",  "depends_on": ["scene_breakdown"],         "queue": "api"},
    {"key": "image_gen",       "depends_on": ["visual_prompts"],          "queue": "api",
     "fan_out": "scenes", "config": {"model": "flux-kontext", "use_character_ref": true}},
    {"key": "motion",          "depends_on": ["image_gen"],               "queue": "render",
     "fan_out": "scenes", "config": {"hero_ratio": 0.15, "i2v_model": "kling-2.1",
                                     "fallback": "kenburns"}},
    {"key": "tts",             "depends_on": ["scene_breakdown"],         "queue": "api",
     "fan_out": "chapters", "config": {"provider": "elevenlabs"}},
    {"key": "alignment",       "depends_on": ["tts"],                     "queue": "gpu"},
    {"key": "music_plan",      "depends_on": ["scene_breakdown"],         "queue": "api"},
    {"key": "assembly",        "depends_on": ["motion", "alignment", "music_plan"],
     "queue": "render"},
    {"key": "thumbnail",       "depends_on": ["script"],                  "queue": "api",
     "config": {"candidates": 3}},
    {"key": "metadata",        "depends_on": ["script"],                  "queue": "api"},
    {"key": "review_gate",     "depends_on": ["assembly", "thumbnail", "metadata"],
     "conditional": "channel.publish_mode == 'review'"},
    {"key": "publish",         "depends_on": ["review_gate"],             "queue": "api"}
  ]
}
```

Notes: `tts`, `thumbnail`, `metadata` run **in parallel** with the visual branch — they only need the script. `review_gate` is skipped (status `SKIPPED`, counts as satisfied) on auto channels.

### 2.4 Stage registry & contract

```python
# pipelines/stages/base.py


@dataclass
class StageContext:
    run: PipelineRun
    execution: StageExecution
    channel: Channel
    config: dict  # merged: blueprint config + channel overrides
    upstream: dict[str, dict]  # {stage_key: output} for declared deps
    prompts: PromptRenderer  # renders versioned templates w/ run snapshot
    costs: CostRecorder  # ctx.costs.record("fal_flux", "image_gen", 1, 0.025)
    assets: AssetWriter  # persists files to S3, returns Asset rows


class Stage(ABC):
    key: ClassVar[str]
    queue: ClassVar[str] = 'api'
    max_retries: ClassVar[int] = 3
    timeout_s: ClassVar[int] = 600

    @abstractmethod
    async def run(self, ctx: StageContext) -> dict: ...

    def fan_out(self, ctx: StageContext) -> list[dict] | None:
        """Return per-shard inputs to spawn children, or None for single execution."""
        return None


STAGE_REGISTRY: dict[str, type[Stage]] = {}  # populated via @register decorator
```

### 2.5 Orchestrator (the heart)

The orchestrator is a single TaskIQ task, `advance_pipeline(run_id)`, invoked: (a) when a run starts, (b) every time any StageExecution reaches a terminal state. It is the **only** code that enqueues stage work.

```python
# pipelines/services/orchestrator.py


async def advance_pipeline(run_id: UUID) -> None:
    async with transaction.atomic():
        run = await PipelineRun.objects.select_for_update().aget(id=run_id)
        if run.status in (
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.COMPLETED,
        ):
            return
        graph = run.blueprint_snapshot['stages']
        states = await _stage_states(run)  # {stage_key: aggregate status}

        for node in graph:
            key = node['key']
            if states.get(key) not in (None, StageStatus.PENDING):
                continue
            if node.get('conditional') and not _eval_condition(node, run):
                await _mark_skipped(run, key)
                continue
            deps = node['depends_on']
            if all(
                states.get(d) in (StageStatus.SUCCEEDED, StageStatus.SKIPPED)
                for d in deps
            ):
                await _enqueue_stage(
                    run, node
                )  # creates StageExecution(QUEUED)
                # + kicks execute_stage task

        await _update_run_status(
            run, states
        )  # COMPLETED / FAILED / AWAITING_REVIEW
        await publish_sse(run.id, {'type': 'run.advanced', 'states': states})
```

**Concurrency safety:** `select_for_update` on the run row serializes concurrent `advance_pipeline` calls (e.g., two fan-out children finishing simultaneously). The unique constraint on `(run, stage_key, shard_index, attempt)` is the backstop against double-enqueue.

**Fan-out lifecycle:** when `_enqueue_stage` hits a node whose Stage class returns shard inputs from `fan_out()`, it creates one **parent** execution (status `RUNNING`) plus N child executions. Children execute independently on their queue. The parent's completion check runs inside `advance_pipeline`: parent → `SUCCEEDED` when all children succeed; → `FAILED` if any child exhausts retries. Parent `output` aggregates children: `{"scenes": [{shard: 0, asset_id: ...}, ...]}`.

**Aggregate status for fan-out** (`_stage_states`): the orchestrator treats the parent's derived status as the stage's status, so downstream deps wait on the slowest scene.

### 2.6 Stage worker

```python
# pipelines/tasks.py


@broker.task(retry_on_error=False)  # we manage retries ourselves
async def execute_stage(execution_id: UUID) -> None:
    exec_ = await StageExecution.objects.select_related('run__channel').aget(
        id=execution_id
    )
    stage_cls = STAGE_REGISTRY[exec_.stage_key]
    ctx = await build_context(exec_)

    # Idempotency short-circuit
    cached = await find_cached_output(
        exec_.run, exec_.stage_key, exec_.shard_index, ctx.input_hash
    )
    if cached:
        await complete(exec_, cached.output, cost=0)
        return await kick_advance(exec_)

    await mark_running(exec_)
    try:
        async with asyncio.timeout(stage_cls.timeout_s):
            output = await stage_cls().run(ctx)
        await complete(exec_, output)
    except RetryableProviderError as e:  # 429 / 5xx / timeout
        if exec_.attempt < stage_cls.max_retries:
            delay = min(300, 2**exec_.attempt * 10) + random.uniform(0, 5)
            await schedule_retry(exec_, delay, error=e)
        else:
            await fail(exec_, e)
    except FatalProviderError as e:  # content policy, bad prompt
        await mark_needs_input(exec_, e)  # surfaces in review UI
    except Exception as e:
        await fail(exec_, e)
    finally:
        await kick_advance(exec_)  # always re-evaluate DAG
        await publish_sse(exec_.run_id, stage_event(exec_))
```

**Error classification lives in `generation/`** — each provider client maps its HTTP/SDK errors to `RetryableProviderError` vs `FatalProviderError`. Kling and fal.ai 429s and queue timeouts are retryable; Flux safety-filter rejections are `NEEDS_INPUT` (a human edits the visual prompt and clicks rerun).

### 2.7 Rerun & staleness semantics (prompt-editing loop)

When you edit a prompt (or shard input) and click **"Rerun stage"**:

1. New `attempt` row created for that StageExecution (old attempts kept for diffing outputs).
2. `prompt_snapshot[stage_key]` updated to the new `PromptVersion` → changes `input_hash` → cache miss → real regeneration.
3. All transitive downstream stages flip to `STALE`. They re-enter `PENDING` and re-execute when reached — **but** any downstream stage whose `input_hash` is unchanged (e.g., you reran scene 4's image; scenes 1–3 motion inputs are identical) hits the idempotency cache and completes instantly at zero cost.
4. Shard-level rerun: rerunning child `image_gen[4]` only stales `motion[4]` + `assembly`. This is what makes iterating on a 200-scene video affordable.

### 2.8 SSE progress

Workers publish JSON events to Redis channel `pipeline:{run_id}`. A Django ASGI view (`StreamingHttpResponse`, `text/event-stream`) subscribes and forwards. Event types: `run.started`, `stage.queued|running|succeeded|failed|needs_input`, `shard.progress` (e.g., `{"stage": "image_gen", "done": 142, "total": 203}`), `run.completed`. TanStack Query invalidates on terminal events; the progress UI renders purely from SSE.

---

## 3. The Long-Form Stage Catalog (how the video actually gets made)

This mirrors how real automation creators produce 20–30 min faceless videos (documentary/history/finance style): **script is king, visuals are a scene-by-scene slideshow with motion, retention is engineered in the script stage.**

### 3.1 `research`
- Input: `run.topic` + `NicheConfig` (audience, angle, banned topics).
- Exa/Tavily search → fetch top sources → LLM condenses into a **research brief**: key facts (each with source URL), narrative angles, surprising hooks, numbers/dates. Stored as structured JSON, not prose.
- Output: `{"brief": {...}, "sources": [...]}` — facts carry through so the script stage can't hallucinate freely.

### 3.2 `outline`
- LLM produces chapter structure: 6–10 chapters, each with title, thesis, target duration, and **retention device** (open loop, payoff, pattern interrupt). Total target duration is channel config (e.g., 22 min — past the 8-min midroll threshold with margin).
- Output: `{"chapters": [{"idx", "title", "thesis", "target_seconds", "device"}]}`

### 3.3 `script`
- One LLM call **per chapter** (parallel-safe, fits context, retryable per chapter), receiving the brief + outline + previous chapter's closing line for continuity.
- Channel prompt template enforces voice/style; system prompt bakes in retention writing: first 30s hook restates the payoff, no greetings, short sentences, curiosity gaps at chapter ends.
- Word budget: `target_seconds × (WPM/60)` per chapter; channel WPM config ≈ 150–165 for ElevenLabs at 1.0 speed.
- Output: full script JSON, per-chapter, with word counts.

### 3.4 `scene_breakdown` — the critical translation layer
- LLM splits each chapter's narration into **scenes of 6–12s of narration** (≈15–30 words each). A 22-min video → ~140–200 scenes.
- Each scene: `{"idx", "chapter_idx", "narration_text", "visual_concept", "shot_type", "est_seconds", "is_hero"}`.
- `is_hero` flags ~15% of scenes (hooks, chapter opens, climaxes) for image-to-video; the rest get Ken Burns. This single flag is your cost lever: at ~$0.35–0.70 per 5s Kling clip vs ~$0 for Ken Burns, hero_ratio controls whether a video costs $8 or $80.

### 3.5 `visual_prompts`
- Per scene, LLM composes the final image prompt: scene's `visual_concept` + channel **style guide** (a versioned prompt fragment: art style, palette, lighting, aspect 16:9) + character injection if the scene references a `Character` (canonical description + `reference_asset_id`).
- Negative-prompt and safety pre-check (LLM flags prompts likely to trip Flux filters → auto-rewrites once before failing to `NEEDS_INPUT`).

### 3.6 `image_gen` (fan-out per scene)
- Flux via fal.ai; **Flux Kontext** when `use_character_ref` and the scene has a character — passes reference image so the character stays consistent across scenes and across videos.
- 1920×1080 native (no upscaling step needed for YouTube), seed recorded in output for reproducibility.
- Concurrency cap per provider (semaphore in the client, e.g., 8 in-flight) so a 200-scene fan-out doesn't 429-storm.

### 3.7 `motion` (fan-out per scene)
- Hero scenes → Kling I2V (5s or 10s, prompt = camera movement description generated in scene_breakdown).
- Standard scenes → **Ken Burns via FFmpeg `zoompan`**: deterministic variety by cycling presets (zoom-in-center, zoom-out, pan-L→R, pan-R→L, diagonal) seeded by scene idx; subtle 1.0→1.08 zoom over the scene duration. Rendered at exact `est_seconds` (corrected later by alignment).
- Output per scene: a normalized video segment (see §5.3 mezzanine spec).

### 3.8 `tts` (fan-out per chapter)
- ElevenLabs, channel-configured `voice_id`, `stability/similarity` settings in channel config. Chapter-level requests keep prosody natural across sentences (per-scene TTS sounds choppy).
- Output: per-chapter WAV (48 kHz) + character-count cost record.

### 3.9 `alignment`
- **WhisperX forced alignment** of each chapter WAV against its known script → word-level timestamps.
- Two products: (a) **ASS subtitle file** using the channel's caption style (font from Asset Library, karaoke-style word highlighting optional); (b) **scene timing map** — actual narration duration per scene (replacing estimates), which assembly uses to trim/extend each visual segment so picture and voice never drift.

### 3.10 `music_plan`
- LLM tags each chapter with mood (tense, hopeful, mysterious…) → selector queries `LibraryAsset(kind=MUSIC)` by mood/genre tags + channel's allowed music pool → plan: `[{chapter_idx, library_asset_id, gain_db}]`. Music loops/crossfades per chapter; loudness pre-analysis (§4.3) makes gain math trivial.

### 3.11 `assembly` — see §5.

### 3.12 `thumbnail`
- N candidates (config, default 3): Flux generates the base art (its own prompt template — exaggerated emotion/contrast, rule-of-thirds subject), then **Pillow** composites 2–4 word text using channel branding fonts/colors + stroke/shadow. Deterministic text layer = always-readable text (never trust the image model with typography).
- All candidates saved; review UI picks one; auto channels take candidate 0.

### 3.13 `metadata`
- LLM: title (≤60 chars, hook-style), description with chapter timestamps (computed from alignment), tags, category. Timestamps in the description give you free YouTube chapters.

### 3.14 `review_gate` / `publish`
- Gate: run → `AWAITING_REVIEW`; dashboard shows final video, thumbnail candidates, metadata, per-stage costs; approve → resumes. Any "edit + rerun" stales downstream per §2.7, gate re-arms after re-assembly.
- Publish: YouTube Data API v3 resumable upload (videos.insert, then thumbnails.set), `publishAt` for scheduling, playlist assignment, self-declared made-for-kids flag from channel config. Quota note: an upload costs 1600 quota units of the 10k/day default — fine for ~6 uploads/day/project; request quota increase or use one GCP project per channel cluster when you scale.

---

## 4. Asset Library (`assets` app)

### 4.1 Two asset classes

```python
class Asset(UUIDModel, TimeStampedModel):
    """Pipeline-generated, run-owned, immutable."""

    run = models.ForeignKey(
        'pipelines.PipelineRun', null=True, on_delete=models.SET_NULL
    )
    stage_execution = models.ForeignKey(
        'pipelines.StageExecution', null=True, on_delete=models.SET_NULL
    )
    kind = models.CharField(choices=AssetKind.choices)
    # IMAGE | VIDEO_SEGMENT | AUDIO_VO | SUBTITLE | FINAL_VIDEO | THUMBNAIL | TRANSCRIPT | DOC
    file = models.FileField(storage=s3_storage, upload_to=asset_path)
    mime = models.CharField(max_length=64)
    checksum = models.CharField(max_length=64, db_index=True)
    meta = models.JSONField(
        default=dict
    )  # ffprobe: duration, w, h, fps, codec, loudness


class LibraryAsset(UUIDModel, TimeStampedModel):
    """Reusable, human-curated, versioned."""

    kind = models.CharField(choices=LibraryAssetKind.choices)
    # WATERMARK | INTRO | OUTRO | OVERLAY | TRANSITION | MUSIC | SFX | FONT |
    # BACKGROUND | CHARACTER_REF | CAPTION_STYLE | LUT
    name = models.CharField(max_length=120)
    file = models.FileField(storage=s3_storage)
    tags = ArrayField(
        models.CharField(max_length=40), default=list
    )  # mood, genre, theme
    channel = models.ForeignKey(
        'channels.Channel', null=True, blank=True, on_delete=models.CASCADE
    )  # null = global library
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    meta = models.JSONField(
        default=dict
    )  # probe data + loudness (music) + safe-area (overlays)


class AssetRendition(UUIDModel, TimeStampedModel):
    """Pre-transcoded variants so assembly never transcodes branding assets per run."""

    source = models.ForeignKey(
        LibraryAsset, related_name='renditions', on_delete=models.CASCADE
    )
    profile = models.CharField(
        max_length=40
    )  # "1080p30_h264", "9x16_1080", "mezz"
    file = models.FileField(storage=s3_storage)
```

### 4.2 ChannelBranding (in `channels`, references the library)

```python
class ChannelBranding(UUIDModel):
    channel = models.OneToOneField(Channel, on_delete=models.CASCADE)
    intro = models.ForeignKey(
        LibraryAsset, null=True, related_name='+', on_delete=models.SET_NULL
    )
    outro = models.ForeignKey(
        LibraryAsset, null=True, related_name='+', on_delete=models.SET_NULL
    )
    watermark = models.ForeignKey(
        LibraryAsset, null=True, related_name='+', on_delete=models.SET_NULL
    )
    watermark_position = models.CharField(
        default='bottom_right'
    )  # + opacity, margin px
    watermark_opacity = models.FloatField(default=0.6)
    caption_style = models.ForeignKey(
        LibraryAsset, null=True, related_name='+', on_delete=models.SET_NULL
    )  # ASS style template
    fonts = models.ManyToManyField(LibraryAsset, related_name='+', blank=True)
    music_pool_tags = ArrayField(models.CharField(max_length=40), default=list)
    thumbnail_palette = models.JSONField(default=dict)  # colors, font refs
```

### 4.3 Upload normalization pipeline (the part everyone skips, then regrets)

Every `LibraryAsset` upload triggers an ingest task:

1. **ffprobe** → persist codec/duration/dimensions/fps/channel-layout to `meta`.
2. **Validation** per kind: watermarks must be PNG with alpha; intros/outros must contain an audio stream (silent track injected if missing — concat fails on stream-count mismatch otherwise).
3. **Loudness analysis** (music/SFX): EBU R128 integrated loudness stored in `meta` → the music_plan stage computes gain to hit −18 LUFS bed under −14 LUFS dialogue without trial and error.
4. **Rendition generation**: transcode to the platform mezzanine profile (§5.3) for each target format (16:9 1080p, 9:16 1080×1920). Assembly then **only ever concats identical-spec streams** — this single rule eliminates 90% of FFmpeg concat failures.

---

## 5. FFmpeg Assembly Design (`rendering`)

### 5.1 Segment-then-concat, never one giant filtergraph

A 200-scene filtergraph is undebuggable and OOMs. Instead:

1. **Per-scene render** (parallelizable on the `render` queue): take the scene's motion segment (Kling clip or Ken Burns render), trim/tempo-fit to the **actual** narration duration from alignment (±5% `setpts`/`atempo` tolerance; beyond that, hold last frame), mux with that scene's slice of the chapter VO.
2. **Chapter concat**: concat demuxer (`-f concat -c copy` when specs match — near-instant) per chapter; `xfade` transitions only at chapter boundaries (cheap: only N−1 re-encoded joints).
3. **Final pass** (single re-encode):
   - `[v] overlay` watermark (positioned/opacity from branding, rendition pre-scaled),
   - intro/outro concat (renditions, so `-c copy`),
   - `subtitles=captions.ass:fontsdir=/fonts` burn-in,
   - audio: chapter music beds mixed with `amix` + `sidechaincompress` keyed on VO (auto-ducking), then **two-pass `loudnorm`** to −14 LUFS / −1 dBTP (YouTube's normalization target — uploading at −14 means YouTube doesn't touch your levels).

### 5.2 Output profile
`libx264 -preset slow -crf 18 -pix_fmt yuv420p -profile high -g 60`, AAC 384k 48kHz, +faststart. (NVENC `p5` if you put a GPU box on the render queue later — config flag, not a code change.)

### 5.3 Mezzanine spec (every intermediate segment, no exceptions)
1920×1080 (or 1080×1920), 30 fps CFR, h264 CRF 16 fast, yuv420p, AAC 48 kHz stereo. Identical specs ⇒ concat demuxer stream-copies ⇒ assembly of a 25-min video is minutes, not an hour.

---

## 6. Clipping Pipeline = Same Engine, Different Blueprint

`clipping_v1` blueprint: `ingest → transcribe_diarize → highlight_scoring → clip_candidates(fan_out per clip) → smart_crop → caption_burn → brand(campaign watermark/intro from LibraryAsset) → export`.

- `SourceMedia` replaces `topic` as the run seed (yt-dlp URL / upload / RSS item).
- `highlight_scoring`: transcript chunked into overlapping windows; LLM scores each candidate on hook (first 3s grabs?), self-containment, emotional intensity, quotability → ranked list with word-timestamp-snapped boundaries; top-K (config) become fan-out shards.
- `smart_crop`: your MediaPipe approach — face boxes per active speaker (diarization tells you who's talking), crop keyframes smoothed with EMA to avoid jitter, cut framing on speaker change.
- Review UI = Konva crop editor + WaveSurfer boundary trim (phase 2; phase 1 ships with start/end nudge buttons).
- `Clip` rows link to `ClipCampaign`; `Earning` rows give you revenue-per-source-podcast analytics.

The payoff of one engine: cost tracking, retries, SSE progress, review gates, and prompt versioning all work for clipping on day one.

---

## 7. Queue Topology & Infra

| Queue | Workload | Concurrency | Where |
|---|---|---|---|
| `api` | LLM/fal.ai/ElevenLabs calls | high (32+, async) | small VPS |
| `render` | FFmpeg scene renders, assembly | nproc-bound (1–2 per core) | Hetzner dedicated (e.g., AX42) |
| `gpu` | WhisperX + diarization | 1–2 | same box (CPU int8 fine) or small GPU instance |
| `orchestrator` | advance_pipeline | serialized per run | anywhere |

- Postgres + Redis colocated or managed; RustFS on Coolify as you run today; presigned URLs for the frontend player.
- Logfire spans per StageExecution (`run_id`/`stage_key` attributes) → one trace per video; Phoenix for the LLM stages (script/scene_breakdown/highlight_scoring quality debugging).
- Nightly janitor task: delete intermediate `Asset` rows + S3 objects for completed runs older than N days (keep finals, scripts, prompts — they're tiny; the per-scene videos are the storage hog).

---

## 8. Build Sequence (revised for this spec)

1. `core` + `channels` + `prompts` + `assets` models, admin, S3 storage, upload-normalization task.
2. `pipelines` engine: registry, orchestrator, executor, idempotency, SSE. Test with a 3-stage dummy blueprint.
3. Port generation stages (research → metadata) one by one; each is independently testable via admin "run single stage" action.
4. `rendering` assembly + mezzanine discipline.
5. `publishing` + review dashboard in TanStack Start.
6. `clipping` blueprint.
7. `analytics` once you have 20+ runs of cost data.

---

# Addendum v1.1 — Character Studio, Cost Gates, Story Formats

## 9. Character Studio (interactive, *outside* the DAG)

The character workflow you describe — reference image + prompt → T2I → iterate → lock → reuse — is fundamentally **interactive pre-production**, not a pipeline stage. Modeling it as a stage would burn API money on every video. Instead it's its own flow in the `channels` app, and the pipeline only ever consumes **approved** characters.

### 9.1 Models

```python
class Character(UUIDModel, TimeStampedModel):
    channel = models.ForeignKey(
        Channel, null=True, blank=True, on_delete=models.CASCADE
    )  # null = shared across channels
    name = models.CharField(max_length=100)
    status = models.CharField(
        choices=[
            ('DRAFT', 'Draft'),
            ('APPROVED', 'Approved'),
            ('RETIRED', 'Retired'),
        ],
        default='DRAFT',
    )
    appearance_prompt = (
        models.TextField()
    )  # the WINNING prompt, locked on approval
    persona = models.TextField(
        blank=True
    )  # personality/role — used by script stage
    hero_ref = models.ForeignKey(
        'assets.LibraryAsset',
        null=True,
        related_name='+',
        on_delete=models.SET_NULL,
    )  # canonical image
    total_creation_cost_usd = models.DecimalField(
        max_digits=8, decimal_places=4, default=0
    )


class CharacterSheetItem(UUIDModel):
    """Angle/expression/outfit variants — Kontext picks the best-matching ref per scene."""

    character = models.ForeignKey(
        Character, related_name='sheet', on_delete=models.CASCADE
    )
    asset = models.ForeignKey('assets.LibraryAsset', on_delete=models.PROTECT)
    label = models.CharField(
        max_length=60
    )  # "front", "profile_left", "angry", "armor_v2"


class CharacterGenerationSession(UUIDModel, TimeStampedModel):
    """One iteration loop. Every round logged: prompt, refs, model, candidates, cost."""

    character = models.ForeignKey(
        Character, related_name='sessions', on_delete=models.CASCADE
    )
    rounds = models.JSONField(default=list)
    # [{"prompt", "ref_asset_ids", "model", "n", "candidate_asset_ids", "cost_usd",
    #   "picked": null | asset_id}]
```

### 9.2 The flow (Character Studio UI)

1. **Seed**: upload reference image(s) and/or write a description. Pick a generation model preset (`flux-dev` for from-scratch, `flux-kontext` when iterating on a reference).
2. **Generate round**: batch of 4 candidates per round (one API call pattern, ~$0.10–0.20/round). Grid UI: pick one as the new reference, edit the prompt, go again — or **approve**.
3. **Approve & lock**: winning image → `hero_ref` (stored as `LibraryAsset(kind=CHARACTER_REF)`); winning prompt → `appearance_prompt` (frozen — pipeline scenes inject it verbatim so wording drift can't change the character).
4. **Sheet expansion** (optional, recommended for main characters): one guided batch generates labeled variants via Kontext from the hero ref — profile, back, 2–3 emotions, alternate outfit. ~$0.50 once, then hundreds of videos reuse it free.
5. Session history shows exactly what every iteration cost and which prompt produced the keeper — your prompt library for the next character compounds from this.

### 9.3 How the pipeline consumes characters

- `scene_breakdown` output gains `"characters": ["king_alaric"]` per scene (LLM matches scene content against the channel's roster).
- `visual_prompts` composes: scene visual concept + `appearance_prompt` + style guide; selects the sheet ref whose label best matches the shot (`profile_left` for a side shot, etc. — simple label-matching first, LLM-picked later).
- `image_gen` calls Kontext with that ref. Consistency is now anchored to an image you already approved, not to luck.
- Scene media mix: `motion` stage already splits hero (I2V) vs still (Ken Burns) — both consume the same Kontext output, matching the "some animated, some stills" pattern.

---

## 10. Cost-Control Gates & Budget Guards

The principle: **place human checkpoints exactly before the expensive irreversible spend, and make fixing things upstream of that point nearly free.**

Rough per-stage economics for a ~180-scene video make the gate placement obvious:

| Stage | Approx cost | Fixable for |
|---|---|---|
| research/outline/script/scene_breakdown/visual_prompts | $0.50–1.50 (LLM) | pennies |
| image_gen (180 × Flux) | $4–7 | $0.03/scene |
| **motion** (27 hero × Kling) | **$10–20** | $0.40–0.70/scene |
| tts (ElevenLabs ~3.5k chars/chapter) | $3–6 | $0.50/chapter |
| render/assembly | ~$0 (your CPU) | free |

### 10.1 Configurable gates in the blueprint

Gates are just zero-cost stages with `"gate": true`; the orchestrator parks the run at `AWAITING_REVIEW` when one is reached and armed:

```json
{"key": "script_gate",     "depends_on": ["scene_breakdown"], "gate": true},
{"key": "storyboard_gate", "depends_on": ["image_gen"],       "gate": true},
{"key": "final_gate",      "depends_on": ["assembly","thumbnail","metadata"], "gate": true}
```

`Channel.gates = ["storyboard_gate", "final_gate"]` — which gates are armed is per-channel config; unarmed gates auto-`SKIP`. The crucial one is **storyboard_gate**: it sits after the cheap images and *before* motion + tts. The review UI shows a storyboard grid (image + narration text + est. duration per scene); you regenerate bad scenes at $0.03 each, reorder/edit prompts, then approve — and only then does the run spend on Kling and ElevenLabs.

Note the blueprint dependency change this implies: `tts` now depends on `storyboard_gate`, not directly on `scene_breakdown`, so VO money isn't spent on a script you might still edit.

### 10.2 Budget guards

- `Channel.default_budget_usd` and per-run override. Before enqueueing any fan-out, the orchestrator computes **projected cost** (shard count × provider unit price from a `ProviderPrice` table) and adds it to actual spend so far; if projection > budget → run parks at `BUDGET_HOLD` with the breakdown shown. Approve-overage or edit (lower hero_ratio, trim scenes) to continue.
- **Draft mode** per run: a config overlay that swaps expensive providers for cheap ones (`flux-schnell`, `hero_ratio: 0`, skip tts → use edge-tts/free TTS as scratch VO). Lets you validate a new niche's full pipeline end-to-end for <$1, then re-run "production mode" — idempotency keys include the provider config, so the production run regenerates media but reuses every LLM stage output untouched.
- Hard global guard: daily spend cap per provider (Redis counter checked in the provider clients) — a runaway retry loop can never eat the month's budget overnight.

---

## 11. Story Format System (multi-niche, beyond documentaries)

The documentary structure in §3 is just **one format**. The generalization: outline/script stages don't hardcode "chapters with theses" — they render from a **StoryFormat**, a data-defined narrative architecture.

### 11.1 Model

```python
class StoryFormat(UUIDModel, TimeStampedModel):
    key = models.CharField(max_length=60, unique=True)  # "true_crime_case"
    name = models.CharField(max_length=100)
    fiction = models.BooleanField(default=False)  # drives research-stage mode
    narration_pov = models.CharField(
        default='narrator'
    )  # narrator | first_person | character
    beats = models.JSONField()  # the narrative skeleton, see below
    pacing = models.JSONField(
        default=dict
    )  # {"wpm": 158, "scene_seconds": [6,12],
    #  "hero_ratio": 0.15}
    prompt_overrides = models.JSONField(
        default=dict
    )  # {stage_key: prompt_template_id}
    music_mood_map = models.JSONField(default=dict)  # beat → allowed moods
```

Beats example, `true_crime_case`:

```json
[
 {"key":"cold_open",     "pct":0.05,"purpose":"aftermath teaser, withhold the who/why","device":"open_loop"},
 {"key":"victim_world",  "pct":0.12,"purpose":"humanize the victim, normal life","device":"contrast_setup"},
 {"key":"the_night",     "pct":0.18,"purpose":"minute-by-minute timeline","device":"tension_build"},
 {"key":"investigation", "pct":0.25,"purpose":"leads, dead ends, red herrings","device":"pattern_interrupt"},
 {"key":"the_twist",     "pct":0.15,"purpose":"the break in the case","device":"payoff"},
 {"key":"resolution",    "pct":0.15,"purpose":"arrest, trial, aftermath","device":"closure"},
 {"key":"reflection",    "pct":0.10,"purpose":"what it means, open question to comments","device":"engagement_cta"}
]
```

Versus `fantasy_story` (fiction=true, pov=first_person, hero's-journey beats: ordinary_world → call → trials → dark_moment → transformation → return), or `history_epic`, `reddit_revenge`, `scary_story` (slow-burn beats, whisper-adjacent pacing config), `listicle` (N interchangeable item-beats). Formats are rows, not code — adding a niche format is an admin task.

### 11.2 How formats flow through the pipeline

- **`research`** runs in a mode chosen by `format.fiction`:
  - non-fiction → factual research brief with sources (as §3.1);
  - fiction → **premise development**: LLM generates world/character/conflict bible from the topic seed + the channel's persistent **lore document** (a versioned prompt fragment per channel — recurring fictional universes across videos are a retention superpower).
- **`outline`** maps beats → concrete sections: each beat gets content, target seconds (`pct × total`), and its retention device carried through.
- **`script`** prompt = format narrative voice + beat purpose + channel style. First-person fantasy and third-person true-crime come out of the same stage, different templates.
- **`visual_prompts`** pulls the niche **style guide** (versioned fragment: "gritty photoreal, desaturated, 35mm" vs "painterly dark fantasy, volumetric light") — so the same engine produces visually distinct channels.
- **`music_plan`** uses `music_mood_map` per beat instead of per chapter.
- **NicheConfig composes it all**: `format` + style guide + character roster + voice_id + music pool + thumbnail palette. Spinning up a new channel = pick a format, write/clone a style guide, create characters in the Studio, done.

### 11.3 Originality & monetization safety (worth encoding as config, not vibes)

- **Reused-content risk** is the #1 monetization killer for AI channels. The mitigations that matter are already structural here: unique generated visuals (not stock loops), scripted original narration (not article TTS), and human review gates. Add a `min_human_touch` channel policy if you want: runs can't publish unless at least one gate was actively reviewed.
- Per-format **disclosure flag**: YouTube requires the "altered/synthetic content" disclosure for realistic AI media — make it a `publish` stage config per channel (realistic true-crime imagery: yes; stylized fantasy art: generally no).
- Keep `sources` from the research brief in the run record for non-fiction — if a claim is ever challenged, you have provenance.


---

# Addendum v1.2 — Character Cardinality, API-First Operations, QC

## 12. Characters: zero, one, or many

Characters become a **per-run cast (0..N)**, not a channel assumption.

### 12.1 Cast resolution

```python
class RunCast(UUIDModel):
    run = models.ForeignKey(
        PipelineRun, related_name='cast', on_delete=models.CASCADE
    )
    character = models.ForeignKey(
        'channels.Character', on_delete=models.PROTECT
    )
    role = models.CharField(
        max_length=60
    )  # "protagonist", "detective", "narrator_avatar"
    is_ephemeral = models.BooleanField(default=False)
```

- **Zero characters** (historical facts, geography, finance explainers): `scene_breakdown` emits `characters: []` for every scene → `visual_prompts` composes pure environment/object/archival-style prompts → `image_gen` uses plain Flux, **no Kontext call at all** (cheaper and better — Kontext with no meaningful ref degrades output). The pipeline must be excellent at zero-character content because that's most of the volume in many niches.
- **One character**: as designed in §9.
- **Multiple characters**: cast attached at run creation (picked from the channel roster, or auto-proposed by the premise stage for fiction). `scene_breakdown` tags each scene with which cast members appear.

### 12.2 Multi-character scenes (the honest technical constraints)

Reference-guided consistency degrades as refs per image grow. Encode the strategy as config, in preference order:

1. **≤ `max_refs_per_scene` (default 2)**: fal.ai Kontext multi-image input — pass each character's best-matching sheet ref + both frozen `appearance_prompt`s composed into the scene prompt.
2. **Crowded scenes (3+)**: pick the narratively primary character as the single ref; remaining characters described by `appearance_prompt` text only, framed as background/secondary ("in the background, a tall grey-bearded king…"). The scene_breakdown prompt is taught to *prefer writing scenes with ≤2 foreground characters* — fixing this at the writing layer is free; fixing it at the image layer costs retries.
3. **Shot-splitting fallback**: a flagged "conversation" scene can be split into alternating single-character shots (shot/reverse-shot) — film grammar that both looks better and sidesteps multi-ref drift entirely.

### 12.3 Ephemeral characters (fiction one-offs)

For a fantasy story's one-off villain, full Studio treatment is overkill. Ephemeral flow: the premise/outline stage proposes the character with a generated `appearance_prompt`; the character's **first scene render becomes its reference** — that output image is auto-attached as the in-run `hero_ref`, and every later scene in the run uses it via Kontext (**first-appearance anchoring** — exactly the manual creator trick, automated). Storyboard gate is where you veto a bad first appearance cheaply. A "Promote to Library" action converts a good ephemeral into a persistent Studio character.

---

## 13. API-First Operations (the frontend IS the product)

Django admin = emergency CRUD hatch only. Everything below is DRF + drf-spectacular → Orval-generated TanStack Query client. Auth: Knox tokens, a handful of team accounts with a simple `role` field (operator / reviewer).

### 13.1 Resource surface

```
# Configuration plane
GET/POST   /api/channels/                          PATCH /api/channels/{id}/
GET/PUT    /api/channels/{id}/branding/
GET/POST   /api/formats/        /api/niches/
GET/POST   /api/prompt-templates/                  GET/POST .../{id}/versions/
POST       /api/prompt-templates/{id}/versions/{v}/activate/

# Character Studio
GET/POST   /api/characters/
POST       /api/characters/{id}/sessions/                       # start iteration loop
POST       /api/characters/{id}/sessions/{sid}/rounds/          # {prompt, ref_ids, n} → generates
POST       /api/characters/{id}/approve/                        # {winning_asset_id} → locks
POST       /api/characters/{id}/sheet/expand/                   # guided variant batch

# Asset Library  (uploads via presigned S3 PUT — API never proxies bytes)
POST       /api/uploads/presign/            # {filename, mime} → {url, key}
GET/POST   /api/library-assets/             # POST registers key → triggers ingest task
GET        /api/library-assets/?kind=MUSIC&tags=tense&channel={id}

# Execution plane
POST       /api/runs/                       # {channel, topic, cast[], format_override?,
                                            #  budget_usd?, draft_mode?, config_overrides{}}
GET        /api/runs/?status=AWAITING_REVIEW&channel=...        # the work queue
GET        /api/runs/{id}/                  # full tree: stages, shards, costs, snapshots
GET        /api/runs/{id}/events/           # SSE stream
POST       /api/runs/{id}/cancel/
POST       /api/runs/{id}/gates/{gate_key}/approve/
POST       /api/runs/{id}/budget/approve/
GET        /api/runs/{id}/storyboard/       # §13.2 contract
PATCH      /api/runs/{id}/scenes/{idx}/     # edit narration / visual prompt / is_hero / cast
POST       /api/runs/{id}/stages/{key}/rerun/        # {shard_indices?: [4,17], prompt_version?}
GET        /api/runs/{id}/preview/          # presigned URL of latest assembly
POST       /api/runs/{id}/publish/          # {thumbnail_asset_id, schedule_at?, metadata_patch?}

# Ideation (mass production needs a topic backlog)
POST       /api/niches/{id}/ideas/generate/ # cheap LLM batch → N scored topic candidates
GET/PATCH  /api/ideas/?status=BACKLOG       # approve idea → POST /runs/ prefilled

# Clipping
POST /api/sources/   GET /api/sources/{id}/clips/   PATCH /api/clips/{id}/
POST /api/clips/{id}/export/   GET/POST /api/campaigns/   GET /api/earnings/?campaign=...
```

### 13.2 Storyboard contract (the most important screen's data)

```json
GET /api/runs/{id}/storyboard/
{
  "run": {"id": "...", "status": "AWAITING_REVIEW", "gate": "storyboard_gate",
          "spent_usd": 6.41, "projected_next_usd": 14.20, "budget_usd": 30.0},
  "scenes": [
    {"idx": 0, "chapter": 0, "beat": "cold_open",
     "narration": "The lights of Willow Creek went dark at 11:42pm…",
     "visual_prompt_version": 3, "visual_prompt": "...",
     "image": {"asset_id": "...", "url": "https://…presigned", "seed": 42817},
     "status": "SUCCEEDED", "is_hero": true,
     "cast": ["detective_mara"], "est_seconds": 8.5,
     "attempts": 2, "cost_usd": 0.06}
  ]
}
```

Frontend renders a grid; per-scene actions map 1:1 to `PATCH scene` + `POST rerun {shard_indices}`; SSE `shard.progress` events flip cards live as regenerations land. Approve button → `POST gates/storyboard_gate/approve/`.

### 13.3 The operating loop (day-in-the-life)

1. **Dashboard**: runs in flight (live DAG chips via SSE), gates waiting on you, today's spend vs caps, publish calendar.
2. **Morning batch**: review generated topic ideas per niche → promote 5–10 to runs (one tap each; channel defaults fill everything). Runs fan out across the worker fleet.
3. **Gates trickle in**: script gates are a 2-minute read; storyboard gates ~5 minutes (scan grid, regen 3–4 weak scenes at $0.03, approve → unlocks the expensive half).
4. **Final reviews**: watch preview at 2×, pick thumbnail candidate, tweak title, schedule publish slot.
5. **Clipping lane**: paste podcast URLs → candidates appear ranked → trim boundaries → batch export per campaign.

The platform's job is that steps 3–4 are the *only* mandatory human minutes per video, and each one is spent at a point of maximum leverage.

---

## 14. QC Stage — "perfect output" is verified, not hoped for

A `qc` stage runs after `assembly`, before `final_gate`/`publish`. Pure FFmpeg/ffprobe analysis, ~zero cost, catches the failure modes that actually ship broken videos:

| Check | Tool | Fail condition |
|---|---|---|
| Duration drift | ffprobe vs script timing map | > ±3% of expected |
| Loudness | `loudnorm` print_format json | integrated outside −14 ±0.7 LUFS, TP > −1 dB |
| Dead air | `silencedetect` | any silence > 1.8s (excl. intro/outro) |
| Black/frozen frames | `blackdetect`, `freezedetect` | any event > 0.5s |
| A/V sync & stream sanity | ffprobe streams | fps≠30, missing audio, variable fps |
| Caption coverage | ASS vs alignment map | < 99% of words within video bounds |
| Scene gaps | timing map vs concat list | any scene missing / out of order |

Output: structured QC report on the run. Any failure → `NEEDS_INPUT` with the offending timestamp/scene pinpointed, so the fix is a one-shard rerun, not forensic debugging. Publish is **hard-blocked** on QC pass — that's the actual meaning of "the pipeline is perfect": every video that reaches YouTube has passed the same machine inspection.

---

# Addendum v1.3 — Task Queue Decision: TaskIQ vs Celery

## 15. Verdict: TaskIQ (with three specific mitigations)

### 15.1 Why this app specifically favors TaskIQ

The deciding factor is not preference — it's that **your entire generation layer is async-native** (PydanticAI, async fal client, httpx, async ElevenLabs/OpenAI SDKs) and the engine design depends on **shared in-process state across concurrent tasks**:

1. **Event-loop concurrency is the whole point of the `api` queue.** One TaskIQ worker process holds 32–64 in-flight provider calls on a single event loop for a few hundred MB of RAM. Celery has still not shipped native asyncio task support — you'd wrap every task in `asyncio.run()`, which means **a fresh event loop per task invocation**, so nothing can be shared between tasks in a worker.
2. **That breaks the per-provider concurrency caps (§3.6).** The design uses a shared `asyncio.Semaphore` + shared `httpx.AsyncClient` per provider inside each worker — that's what stops a 200-scene fan-out from 429-storming fal.ai, and what gives you connection pooling. Under Celery prefork/threads + `asyncio.run()`, semaphores and clients can't be shared; you'd need an external Redis-based rate limiter — more moving parts to replicate something TaskIQ gives you for free.
3. **You already operate TaskIQ in production** (FlowIQ). Known failure modes beat theoretical maturity.
4. **Celery's killer features go unused here.** Canvas (chains/chords/groups) is Celery's real differentiator — but this design deliberately does its own DAG via the orchestrator + DB, because we need persistence, gates, staleness, and shard-level rerun that canvas can't express. django-celery-beat's DB schedules aren't needed (publish timing is YouTube `publishAt`; the rest is a handful of static crons). Flower isn't needed (your runs dashboard *is* the pipeline monitor, and Logfire traces every stage).

### 15.2 The three mitigations (the honest costs of TaskIQ + Django)

**(a) Django has no async transactions.** `async with transaction.atomic()` does not exist. So the orchestrator — the one piece needing `select_for_update` — is written as a **sync function** and called from async tasks via `asgiref.sync_to_async(thread_sensitive=True)`:

```python
# pipelines/services/orchestrator.py
def _advance_pipeline_sync(run_id: UUID) -> list[UUID]:
    """All locking + state transitions inside one sync transaction.
    Returns execution IDs to enqueue (side effects happen OUTSIDE the txn)."""
    with transaction.atomic():
        run = PipelineRun.objects.select_for_update().get(id=run_id)
        ...
        return ready_execution_ids


@broker.task
async def advance_pipeline(run_id: UUID) -> None:
    ready = await sync_to_async(_advance_pipeline_sync, thread_sensitive=True)(
        run_id
    )
    for eid in ready:
        await execute_stage.kiq(eid)  # enqueue after commit, never inside it
    await publish_sse(run_id, ...)
```

Stage `run()` bodies stay fully async (they're I/O, not transactions) and use the async ORM (`aget`, `acreate`, `aupdate`) for their simple writes.

**(b) Broker delivery guarantees.** `taskiq-redis`'s list broker is effectively at-most-once — a worker killed mid-task loses the message. Two-layer answer:
- Use **`taskiq-aio-pika` (RabbitMQ)** as the broker for at-least-once delivery with acks; keep Redis for results/SSE pub-sub. (RabbitMQ is one more container on Coolify — cheap insurance when one lost message is a $0.70 Kling call or a stalled run.)
- Regardless of broker: a **watchdog cron** (every 2 min) requeues `StageExecution`s stuck in `QUEUED` beyond 5 min or `RUNNING` beyond `timeout_s × 1.5`. Because the DB is the source of truth and stages are idempotent (§2.2), redelivery and requeue are always safe. This watchdog is your real reliability layer — it makes the broker choice almost unimportant.

**(c) Scheduling.** `taskiq-scheduler` handles the static crons (watchdog, nightly janitor, daily idea generation, earnings sync). They're code-defined schedules — you don't need DB-editable crons.

### 15.3 Worker topology (concrete)

```bash
# api queue — async I/O, one process, high in-flight concurrency
taskiq worker ***REMOVED***.broker:broker --queue api --max-async-tasks 48 --workers 1

# render queue — FFmpeg subprocesses, bind concurrency to cores
taskiq worker ***REMOVED***.broker:broker --queue render --max-async-tasks 3 --workers 2

# gpu queue — WhisperX (int8 CPU or CUDA box later)
taskiq worker ***REMOVED***.broker:broker --queue gpu --max-async-tasks 1 --workers 1

# scheduler
taskiq scheduler ***REMOVED***.broker:scheduler
```

Render stages call FFmpeg via `asyncio.create_subprocess_exec` — the event loop just awaits the subprocess, so `max_async_tasks 3` = 3 parallel FFmpeg jobs per worker process without threads.

### 15.4 When the answer would be Celery instead

For completeness: if the codebase were sync Django + sync SDKs, or you wanted DB-driven beat schedules and Flower as the ops surface, or you needed canvas-style ad-hoc workflows without a custom orchestrator — Celery wins. None of those hold here. And the escape hatch is real: stages talk to an abstract "enqueue + run" contract; swapping the broker layer later touches `tasks.py` and deployment, not the engine or any stage.

---

# Addendum v1.4 — Script-First Character Design

## 16. Characters are derived from the script, not picked from a backlog

Corrected mental model: the script comes first; the cast emerges from it. Character design is therefore a **mid-pipeline interactive step**, not run-creation input. The Studio (§9) survives intact — it just gets invoked *inside* a run, after the script exists.

### 16.1 Revised pipeline order (visual branch)

```
script → scene_breakdown ─┬→ cast_proposal → character_gate → visual_prompts → image_gen → …
                          └→ (tts waits on storyboard_gate as before)
```

- **`scene_breakdown`** additionally emits a raw `cast` list: every distinct character the script implies, with `{name, role, importance: main|secondary|background, appearance_brief}` — the appearance brief is extracted/inferred from the script itself ("the script describes a scarred mercenary in her forties…"), which is exactly your "based off the script" requirement.
- **`cast_proposal`** (cheap LLM stage) refines this into design-ready specs: for each character, a draft `appearance_prompt` composed from the script brief + the niche style guide, plus a **library match check** — it compares proposed characters against existing `Character` rows for this channel (name + embedding similarity on appearance) and flags probable matches, because a *series* channel (recurring hero across episodes) should reuse, not redesign. Output: `{"cast": [{name, role, importance, draft_prompt, library_match: char_id|null}]}`.
- **`character_gate`** — an interactive gate, like storyboard_gate but earlier and cheaper. The run parks at `AWAITING_REVIEW`; the frontend shows the proposed cast and for each character you either:
  1. **Accept the library match** (recurring character → its frozen refs are used, zero cost),
  2. **Design it now**: opens the Studio loop *scoped to this run* — generate 4 candidates from the draft prompt (± a reference image you upload), iterate prompts, approve. Same `CharacterGenerationSession` machinery, now with a `run` FK,
  3. **Demote to background**: no ref needed; the character is text-described only in scene prompts,
  4. **Edit the script instead** (the character shouldn't exist / should differ) — which stales scene_breakdown downstream per §2.7, exactly as any upstream edit does.
- Gate approval requires every `importance: main` character to be APPROVED (designed or matched). Then `visual_prompts`/`image_gen` proceed with locked refs for all ~180 scenes — the design spend happens **once, before** the fan-out spend.

### 16.2 Model deltas

```python
class Character(...):
    origin = models.CharField(
        choices=[('LIBRARY', 'Library'), ('RUN', 'Run')], default='RUN'
    )
    source_run = models.ForeignKey(
        'pipelines.PipelineRun',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # "Promote to Library" flips origin → LIBRARY (for characters worth a series)


class RunCast(...):  # now created BY cast_proposal, not at run creation
    importance = models.CharField(
        choices=[
            ('MAIN', 'Main'),
            ('SECONDARY', 'Secondary'),
            ('BACKGROUND', 'Background'),
        ]
    )
    design_status = models.CharField(
        choices=[
            ('PROPOSED', 'Proposed'),
            ('DESIGNING', 'Designing'),
            ('APPROVED', 'Approved'),
            ('TEXT_ONLY', 'Text only'),
        ]
    )
    draft_prompt = (
        models.TextField()
    )  # from cast_proposal; editable in the gate UI
```

### 16.3 Automation dial per channel

`Channel.character_design_mode`:
- **`interactive`** (default for new niches/fiction): character_gate arms, you design mains by hand.
- **`auto`** (trusted formats / auto channels): no gate — mains get one automatic Studio round, top candidate auto-approved; secondaries use first-appearance anchoring (§12.3); backgrounds are text-only. Storyboard_gate (if armed) remains your veto point.
- **`none`** (zero-character niches — historical facts, explainers): cast_proposal still runs (it's pennies) but an empty/background-only cast auto-skips the gate, and the run flows straight through. The common case stays zero-touch.

### 16.4 API deltas

```
GET   /api/runs/{id}/cast/                       # proposed cast + design statuses
PATCH /api/runs/{id}/cast/{cast_id}/             # edit draft_prompt / importance / accept match
POST  /api/runs/{id}/cast/{cast_id}/sessions/    # start in-run Studio loop (same endpoints as §13.1)
POST  /api/runs/{id}/cast/{cast_id}/approve/     # {winning_asset_id}
POST  /api/characters/{id}/promote/              # RUN → LIBRARY
POST  /api/runs/{id}/gates/character_gate/approve/
```

SSE adds `cast.proposed` so the dashboard pings you the moment a run is waiting on character design.

### 16.5 What this preserves

The economics and ordering logic don't change: character design still happens **before** the image fan-out (so consistency refs exist for every scene), still costs ~$0.10–0.50 per designed character, and the library still exists — it's just *populated by runs* (promote the keepers) rather than being a prerequisite. Script-first is also simply better creatively: the character looks like what the story needs, not what the backlog had.

---

# Addendum v1.5 — PydanticAI Integration: Where Tools Earn Their Place

## 17. Verdict: yes, it fits — but as the exception, not the default

The idea is sound; the discipline is knowing where. A pipeline wants **determinism, bounded cost, and reproducibility** — an agent tool-loop is variable in all three. So the rule:

> **Default: retrieve-then-generate.** The stage code runs deterministic DB queries (selectors), injects results into the prompt, makes ONE structured-output PydanticAI call.
> **Tools only when** the lookup depends on the model's *intermediate reasoning*, or the search space is too large to inject into context.

### 17.1 Stage-by-stage assignment

| Stage | Pattern | Why |
|---|---|---|
| `outline`, `script`, `scene_breakdown`, `visual_prompts`, `metadata` | **Single structured call** | Everything needed (brief, format beats, style guide, cast) is known upfront — pre-fetch and inject. Tool loops here add cost variance for zero benefit. |
| `cast_proposal` library matching | **Pre-fetch now, tool later** | A channel roster is <50 characters — inject `{name, appearance_prompt}` summaries and let one call do the matching. If the library ever outgrows context, swap in a `search_characters(description)` pgvector tool — PydanticAI tools are plain functions, so it's a drop-in change, not a redesign. |
| `research` | **Agent with tools** | Genuinely iterative: search → read → decide what to search next. Tools: `web_search`, `fetch_page`, plus `list_published_topics(channel)` so it angles away from videos you've already made. Cap with `UsageLimits(request_limit=8)`. |
| `music_plan` | **Agent with one tool** (or pre-fetch while library is small) | `search_music(mood, genre, min_seconds, exclude_recent=True)` — the mood decision per beat drives the query, and a 500-track library doesn't belong in context. `exclude_recent` queries last-N-runs usage so channels don't sound repetitive. |
| `highlight_scoring` (clipping) | **Single structured call** per window | Deterministic chunking outside the model; scoring is pure judgment, no lookups. |
| topic ideation | **Single call + pre-fetch** | Inject recent titles + niche config; dedupe is a selector, not a tool. |

### 17.2 Engine integration contract (applies to BOTH patterns)

```python
# generation/llm.py
scene_breakdown_agent = Agent(
    deps_type=StageDeps,  # selectors, channel, format — DI like FlowIQ
    output_type=SceneBreakdownResult,  # the typed contract downstream stages rely on
)


@scene_breakdown_agent.output_validator
async def validate(ctx, result: SceneBreakdownResult):
    # "pipeline perfection" enforced at generation time, not discovered at assembly:
    errs = []
    if not covers_all_beats(result, ctx.deps.format.beats):
        errs.append('missing beats')
    if any(not (10 <= s.word_count <= 35) for s in result.scenes):
        errs.append('scene length')
    if any(len(s.foreground_cast) > 2 for s in result.scenes):
        errs.append('>2 foreground chars')
    if errs:
        raise ModelRetry(f'Fix and re-emit: {errs}')
    return result
```

Rules every LLM stage follows:

1. **System prompt + model settings come from the versioned `PromptVersion`** — they're inputs, so they're covered by the stage's `input_hash` (§2.2). Editing a prompt → cache miss → regeneration, exactly as designed.
2. **Bounded agency**: every Agent gets `UsageLimits` (request + token caps). Hitting the limit raises → normal retry/`NEEDS_INPUT` flow. An agent can never free-run your budget.
3. **`result.usage()` → `CostRecord`** per call, attributed to the stage execution — agentic stages just produce more rows.
4. **Tool transcript persisted**: for agentic stages, the full tool-call sequence is stored in `StageExecution.output["trace"]`. Reproducibility for agents means *auditability* — you can always see which searches produced which brief. (Logfire's PydanticAI instrumentation gives you the same view in traces, tagged with `run_id`/`stage_key`.)
5. **Output validators are the quality gate**: `ModelRetry` on violated invariants (beat coverage, pacing bounds, cast limits, banned-topic checks from NicheConfig) means malformed creative output gets self-corrected in-call — typically the difference between a pipeline that needs babysitting and one that doesn't.
6. **Tools are read-only.** Pipeline tools query (`selectors.py`); they never mutate. All writes go through stage outputs so the DAG remains the only state machine.

### 17.3 The asset-referencing idea, scoped correctly

"Reference other assets we have" is valuable in exactly two places: music selection (above) and **B-roll/background reuse** — a future `search_library_assets(kind=BACKGROUND, tags=...)` tool letting `visual_prompts` say "reuse establishing shot X instead of regenerating it" for recurring locations in a series. Worth doing *after* you have a populated library and real per-video cost data showing regeneration waste; premature now. The architecture already supports it the day you want it: add the selector, register it as a tool on one agent, bump the prompt version.

---

# Addendum v1.6 — Integrating the Working Clipping MVP (first-class, not afterthought)

## 18. Principle: keep the domain, replace the orchestration

The MVP's domain layer (candidates, layout/style configs, overlays, templates, per-stage render results, distribution posts) is battle-tested and survives nearly untouched. What gets replaced is the **orchestration shell**: the Celery-chained FSM on `ClippingJob` becomes a `clipping_v1` blueprint on the unified engine, so clipping inherits cost tracking, idempotency, watchdog recovery, budget guards, SSE, and the same gate semantics as long-form — one engine, two products.

### 18.1 Job-level mapping: ClippingJob FSM → PipelineRun

```
clipping_v1 blueprint:
ingest → transcribe → analyze → clip_approval_gate → render(fan_out: approved candidates) → distribute(fan_out)
```

| MVP FSM state | New representation |
|---|---|
| INITIALIZING / DOWNLOADING | `ingest` stage (yt-dlp / upload / RSS → `SourceMedia` + probe) |
| TRANSCRIBING | `transcribe` stage (WhisperX + diarization → `Transcript` asset) |
| ANALYZING | `analyze` stage (highlight scoring → creates `ClipCandidate` rows, PROPOSED) |
| AWAITING_CLIP_APPROVAL | `clip_approval_gate` — standard engine gate; run parks at `AWAITING_REVIEW` |
| RENDERING | `render` parent + one shard per APPROVED candidate |
| DISTRIBUTING | `distribute` parent + shards per (render × platform) |
| FAILED (retry from transcription/analysis) | engine-native: rerun stage (§2.7) — strictly more granular than the MVP's two retry entry points |
| PAUSED | `POST /api/runs/{id}/pause/` — generalize to all blueprints (small engine addition: orchestrator stops enqueueing; in-flight shards finish) |

`ClippingJob` itself is **retired**: `source_url/file` → `SourceMedia` (the run seed), transcript + analysis manifest → `Asset` rows on their stages, status → run status. **`skip-to-candidates` is preserved** as `POST /api/runs/ {mode: "manual"}` — a blueprint conditional marks `analyze` SKIPPED and `ingest` seeds one full-length manual candidate; this "bypass the AI, I'll cut it myself" path is too useful to lose.

### 18.2 The 10-stage render pipeline: deliberately NOT flattened

Decision: the inner `ClipRenderPipeline` (10 stages, `ClipRenderStageResult` records, `start_from_stage`, `render_gates` + `GatePausedException`) **stays intact as the implementation of one render shard**. Reasons:

1. It works in production today — rewriting a working FFmpeg pipeline into 10×N DAG rows buys uniformity, not capability.
2. It already has the properties the engine wants: per-stage records, resumability, gates. It's a micro-engine; we federate it instead of dissolving it.
3. The seam is clean: `ClipRender` gains a `stage_execution` FK (the shard that ran it). Shard `output` = `{render_id, stage_results: [...], final_asset_id}`.

**Status bridging** (the only glue code): `PAUSED_AT_GATE` → shard reports a new engine shard-status `PAUSED` → parent `render` stage holds → run shows `AWAITING_REVIEW` with the paused shard pinpointed. `POST /renders/{id}/resume/` keeps working verbatim and kicks `advance_pipeline` on completion. `rerun/{stage_order}` likewise — it's an *intra-shard* rerun, invisible to the DAG, exactly like editing one scene's image.

Only Celery→TaskIQ changes the task wrappers: the pipeline runs via `asyncio.create_subprocess_exec`-based FFmpeg helpers on the `render` queue; `ClipRenderPipeline.run()` itself stays sync inside `sync_to_async` if porting it async isn't worth it on day one.

### 18.3 Model dispositions

| MVP model | Disposition |
|---|---|
| `ClipCandidate` | **Keep.** Candidate lifecycle (PROPOSED→APPROVED/REJECTED) stays; RENDERING→DISTRIBUTED tail of its status enum is dropped — render/distribution state now lives on shards + `ClipRender`/`ClipPost` (one source of truth per concern). Add `run` FK replacing `job` FK. 30–180s + overlap validation stay as model `clean()` rules. |
| `ClipLayoutConfig` / `ClipStyleConfig` | **Keep**, including auto-creation (move from signals to the candidate-creation service per styleguide — same behavior, explicit call site). Pre-seeding from template unchanged. |
| `ClipTimedOverlay` | **Keep** as-is. |
| `ClipRender` + `ClipRenderStageResult` | **Keep** (per §18.2), + `stage_execution` FK, + `CostRecord` rows for any AI-assisted stages. |
| `ClipRenderTemplate` | **Keep**, add `channel` FK alignment with `ChannelBranding` (branding = identity assets; template = clip styling defaults; a template references branding's watermark/caption style rather than duplicating). |
| `ClipMediaAsset` / `ClipMusicAsset` | **Migrate → `LibraryAsset`** (kinds INTRO/OUTRO/MUSIC) via data migration; clipping render stages read renditions (§4.3) and gain loudness-aware music gain for free. Old endpoints become thin aliases over `/api/library-assets/?kind=…` until the frontend swaps. |
| `ClipPost` | **Keep** in `clipping` for now; flagged as the seed of a future shared `distribution` app (long-form Shorts derivatives will want the same platform-post + analytics-sync machinery). |

### 18.4 API reconciliation

Candidate, layout-config, style-config, overlay, render, template, and post endpoints **survive unchanged** — the frontend work there is preserved. Job-level endpoints remap:

| MVP | Unified |
|---|---|
| `POST /clipping/jobs/` | `POST /runs/ {blueprint: "clipping_v1", source: {...}}` |
| `GET /jobs/{id}/` | `GET /runs/{id}/` (+ `GET /runs/{id}/candidates/` convenience) |
| `POST /jobs/{id}/approve-all/` | `POST /runs/{id}/candidates/approve-all/` |
| `POST /jobs/{id}/start-render/` | `POST /runs/{id}/gates/clip_approval_gate/approve/` (same semantics: render all APPROVED) |
| `POST /jobs/{id}/retry/` | `POST /runs/{id}/stages/{key}/rerun/` |
| `POST /jobs/{id}/skip-to-candidates/` | `POST /runs/` with `mode: "manual"` |
| `GET /jobs/{id}/stream/` | `GET /runs/{id}/events/` (event names preserved: `analysis_complete`, `render_paused`, `preview_ready`, … emitted as engine SSE payload types) |

### 18.5 What the engine adopts FROM the MVP (it earned these)

1. **`render_gates` as data** (list of pause points chosen per candidate) → generalized: gates configurable per *run*, not only per channel. Long-form gains "extra-careful run" for new formats.
2. **Preview generation as a first-class light action** (`trigger-preview` / `preview-status` / `preview_ready` SSE) → adopted for long-form storyboard (cheap layout previews before committing).
3. **Per-platform output defaults** (TikTok 9:16 SMART_CROP, YouTube 16:9 CENTER_CROP, IG 1:1) → moved into `RenderProfile` rows in `rendering`, shared by both products.
4. **`PAUSED` as a run-level state** and **manual mode** → engine-wide features, per §18.1.

### 18.6 Migration sequence (single-tenant = hard cutover is fine)

1. Data migration: media/music assets → `LibraryAsset` (+ rendition backfill task).
2. Stand up `clipping_v1` blueprint + the three stage wrappers (`ingest`/`transcribe`/`analyze` port their Celery task bodies; `render` wraps `ClipRenderPipeline`).
3. Status-bridge glue (§18.2) + SSE payload-type mapping.
4. Flip the frontend job screens to run endpoints (candidate/render screens untouched).
5. Delete `ClippingJob` FSM + Celery wiring. Done — in-flight jobs just finish on the old path before step 5; no dual-write needed for a team of two.

---

# Addendum v1.7 — wemake-django-template + django-modern-rest, and a second look at TaskIQ

## 19. Stack realignment

The wemake template (Django 6.0, Python 3.13, uv, ruff, mypy strict, **django-modern-rest preinstalled**, Caddy, Docker, GitLab CI) replaces the implied DRF stack everywhere in this spec. Most decisions survive — the change is at the API edge and in a few cross-cutting wins.

### 19.1 What this changes (and why most of the spec doesn't change)

| Concern | Before (DRF) | Now (DMR + wemake template) |
|---|---|---|
| API style | ViewSets + Serializers + `@action` | **Controllers** (typed classes) with typed `async def get/post/...` methods |
| Request/response schemas | DRF serializers | **Pydantic models** (or msgspec) — the same models PydanticAI uses for `output_type` |
| OpenAPI | drf-spectacular (extra layer) | **Built into DMR** — generated from controller type hints; Orval consumes the spec as before |
| Async support | Sync views in a threadpool under ASGI; `async def` views needing `sync_to_async` for ORM | **Native async views**, no `sync_to_async` wrappers needed inside controllers |
| Routing | `DefaultRouter` | `dmr.routing.Router` |
| Auth | Knox/SimpleJWT | DMR's JWT extra (`pyjwt`) or any Django auth; pick JWT |
| Linting/quality | (ad hoc) | wemake-python-styleguide + ruff + mypy strict + django-stubs — **enforces** the HackSoft-style service layer the spec already assumed |
| Dep management | poetry/pip | **uv** |
| Testing | pytest + factory-boy | pytest + **hypothesis** + **schemathesis** (property-based + spec-driven against the OpenAPI doc) + polyfactory for Pydantic fixtures |
| Reverse proxy | (nginx assumed) | **Caddy** (template default) — auto-HTTPS, fine on Coolify |

Engine internals (§§2–6, 12, 16, 18) are framework-agnostic and unchanged. The endpoint listings in §13 keep their shapes but the implementations look different.

### 19.2 The schema-unification win (this is the big one)

DMR Pydantic schemas == PydanticAI `output_type` == ORM-adjacent DTOs. A `SceneBreakdownResult` you defined in §17 to validate a stage's LLM output is now *also* the response model for `GET /api/runs/{id}/scene-breakdown/`. One source of truth: the model, its validators, its constraints (≤2 foreground chars, scene word counts, beat coverage). Edit it once, three places update — agent contracts, API responses, and tests (polyfactory generates valid examples; schemathesis fuzzes the live API against the schema). Eliminates a class of drift bug that DRF + Pydantic-on-the-side designs always have.

### 19.3 Controller shape (one canonical example)

```python
# pipelines/api/runs.py
from typing import Annotated
from dmr import Body, Controller, PathParam
from dmr.plugins.pydantic import PydanticSerializer
from pipelines.schemas import RunCreate, RunDetail, GateApprove, RerunRequest
from pipelines import services, selectors


class RunController(Controller[PydanticSerializer]):
    async def post(self, parsed_body: Body[RunCreate]) -> RunDetail:
        run = await services.create_run(parsed_body)  # async service
        return RunDetail.from_run(run)

    async def get(self, run_id: PathParam[UUID]) -> RunDetail:
        return RunDetail.from_run(await selectors.get_run(run_id))


class RunGateController(Controller[PydanticSerializer]):
    async def post(
        self,
        run_id: PathParam[UUID],
        gate_key: PathParam[str],
        parsed_body: Body[GateApprove],
    ) -> RunDetail:
        run = await services.approve_gate(run_id, gate_key, parsed_body)
        return RunDetail.from_run(run)
```

URL wiring:

```python
# config/urls.py
router = Router(
    'api/',
    [
        path('runs/', RunController.as_view(), name='runs'),
        path('runs/<uuid:run_id>/', RunController.as_view(), name='run-detail'),
        path(
            'runs/<uuid:run_id>/gates/<str:gate_key>/approve/',
            RunGateController.as_view(),
            name='run-gate-approve',
        ),
        # ...
    ],
)
```

The SSE endpoint (`/api/runs/{id}/events/`) stays a plain async Django view returning `StreamingHttpResponse` — DMR controllers expect typed responses, and streaming sits outside that contract. That's the only deliberate carve-out.

### 19.4 wemake-python-styleguide implications (worth knowing up front)

The styleguide enforces what the spec already prescribed and rules out a few common Django shortcuts. It will reject business logic in views (forcing the `services.py`/`selectors.py` split), shallow inheritance over composition, and most "magic" patterns. Concrete consequences for this build: (a) Signal-based auto-creation of `ClipLayoutConfig`/`ClipStyleConfig` (§18.3) needs to move to an explicit service call inside `candidate_create_service` — same behavior, explicit call site, passes linting. (b) Each app needs the `services.py` + `selectors.py` + `schemas.py` + `api.py` split rather than a fat `views.py`. (c) Pre-commit hooks will fail PRs that break typing; budget for that.

### 19.5 App layout under the wemake template

The template puts apps under `server/apps/<name>/`. Translating §1:

```
server/apps/
  core/        channels/   prompts/    pipelines/
  assets/      generation/ rendering/  publishing/
  clipping/    analytics/
```

Each app: `models.py`, `schemas.py` (Pydantic, shared by API + agents), `services.py`, `selectors.py`, `api.py` (controllers), `tasks.py` (TaskIQ task definitions), `tests/`. Stage implementations live under `pipelines/stages/` and import freely from `generation`/`rendering`/`assets` services.

---

## 20. TaskIQ vs Celery — second look in light of DMR

### 20.1 Verdict: TaskIQ. The case is stronger now, not weaker.

The original §15 reasoning relied on the generation layer being async-native. With DMR, **the entire stack is async-native** — controllers, ORM (via `a*` methods), HTTP clients, fal/ElevenLabs SDKs, PydanticAI, and now SSE views. Celery becomes the single sync island in an otherwise uniformly async runtime. The friction shows up in three concrete places:

1. **API → worker handoff.** With TaskIQ, a controller does `await execute_stage.kiq(execution_id)` directly — same event loop, no thread hop, no `asyncio.run`. With Celery, an async controller calling `.delay()` works (Celery's enqueue is sync but cheap), but every place inside the worker that calls an async PydanticAI agent or async fal client requires its own `asyncio.run(...)` — and **each call gets a fresh event loop**, so per-provider semaphores, httpx connection pools, and PydanticAI agent state can't be shared across tasks in a worker. That's the §15 §2 point, unchanged: it's the structural argument, not a preference.

2. **Single mental model.** Async everywhere means one concurrency model to reason about, one timeout primitive (`asyncio.timeout`), one cancellation story, one debugger. Mixing gevent/prefork workers (Celery's idiomatic deployment for I/O) into an otherwise-async stack is real cognitive tax for a solo/small team.

3. **Stack alignment.** Both DMR and TaskIQ come from the modern typed-Python movement (DMR ships with pydantic/msgspec/attrs plugins; TaskIQ ships with the same family of schedulers and brokers). Celery integrates cleanly with Django but predates this generation of tooling — you'll be the integration point.

### 20.2 The honest costs of TaskIQ (and the mitigations, unchanged from §15.2)

1. **No async transactions in Django.** Orchestrator stays sync inside `transaction.atomic()`, called from async tasks via `sync_to_async(thread_sensitive=True)`. Same pattern as §15.2(a). DMR doesn't change this — it lives at the API edge; the ORM is the same async-shimmed ORM under any framework.
2. **At-most-once on `taskiq-redis`.** Use `taskiq-aio-pika` (RabbitMQ) for the broker; Redis for results + SSE pub/sub. The DB-as-source-of-truth + watchdog cron pattern (§15.2(b)) is the actual reliability layer; the broker choice barely matters under it.
3. **Smaller community.** Real risk: fewer Stack Overflow answers, fewer integration recipes, occasional rough edges in less-trafficked features. You already operate TaskIQ on FlowIQ, so the floor is known. The escape hatch is preserved: stages talk to an abstract enqueue+run contract, swapping engines later touches `tasks.py` and deployment, not the engine code or any stage.

### 20.3 When Celery would still win

For honesty: if any of these were true, Celery would be the better answer despite the async friction. None hold here, but you should be able to identify them in your own gut-check:

- **A sync-Django + sync-SDK codebase.** Not us — fal-client, openai, elevenlabs all ship async.
- **Need for DB-driven cron schedules with non-technical edits** (`django-celery-beat`'s admin UI). Our schedules are code (watchdog, janitor, daily ideation, earnings sync) — handled by `taskiq-scheduler`.
- **Need for Flower as the ops UI.** Our runs dashboard IS the ops UI for stage state; Logfire traces stage executions end-to-end; the queue itself is a transport detail.
- **Need for Celery Canvas** (chains/chords/groups) for ad-hoc workflows. Replaced deliberately by the DB-backed orchestrator (§2.5), which gives us gates, staleness, and shard rerun that Canvas cannot express.

### 20.4 Concrete worker topology (refresh of §15.3 unchanged but worth restating)

```bash
# uvicorn — API + SSE
uv run gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker -w 4

# taskiq workers
uv run taskiq worker ***REMOVED***.broker:broker --queue api    --max-async-tasks 48 --workers 1
uv run taskiq worker ***REMOVED***.broker:broker --queue render --max-async-tasks 3  --workers 2
uv run taskiq worker ***REMOVED***.broker:broker --queue gpu    --max-async-tasks 1  --workers 1
uv run taskiq scheduler ***REMOVED***.broker:scheduler
```

Containers on Coolify: uvicorn × 1, taskiq-api × 1, taskiq-render × 1 (the beefy host), taskiq-gpu × 1, taskiq-scheduler × 1, ***REMOVED***, redis, rabbitmq. Caddy reverse-proxies the lot.

---

# Addendum v1.8 — Schema Layer Choice + DMR API Pattern

## 21. Pydantic primary, msgspec as a sharp tool

### 21.1 Verdict: Pydantic for schemas

The decisive constraint is that **PydanticAI binds the schema layer to Pydantic** — agent `output_type=Foo` only works with Pydantic models (or dataclasses/TypedDict, neither of which gives us §17.2's validator pattern). The §19.2 "one model, four roles" win — agent output, API response, OpenAPI source, polyfactory/hypothesis fixture — only holds if the API layer speaks the same dialect. Splitting it (msgspec for API, Pydantic for agents) re-introduces exactly the translation layer the schema-unification design was built to eliminate.

The performance argument for msgspec was real in Pydantic v1's era. Pydantic v2's core is Rust; on realistic payloads the gap is roughly 2–3× on serialization, not 10×, and the API layer is *not* the bottleneck here. The throughput floor is fal.ai/Kling/ElevenLabs round-trips measured in seconds-to-minutes. Saving 30 ms on a request that's about to spawn $15 of Kling clips isn't a meaningful optimization.

### 21.2 Where msgspec genuinely earns its place

Don't ban it — deploy it surgically in three places where the PydanticAI binding doesn't apply:

1. **TaskIQ message bodies.** TaskIQ supports msgspec encoders out of the box. Run/execution IDs + small payloads serialize meaningfully faster than pickle, messages are high-frequency, and they never touch agent output. Net win, zero coupling.
2. **SSE event payloads.** `pipeline.advanced`, `shard.progress`, `stage.succeeded` fire at high frequency into Redis pub/sub. msgspec Structs encoded with a reused `msgspec.json.Encoder` are faster and lower-allocation than per-call Pydantic dumps. Again — these are transport events, not domain models, and never cross into the agent layer.
3. **Bulk read responses if/when they get hot.** `GET /api/cost-records/?run=...` returning thousands of rows for an analytics view is the case where msgspec response models would be a drop-in optimization. Premature now.

Boundary rule: `schemas.py` is Pydantic (everything agents and the API both touch). `events.py` is msgspec Structs (transport-only). The two files never import each other's types.

### 21.3 Two notes worth internalizing

- msgspec.Struct has no equivalent to Pydantic's `@field_validator` / `@model_validator` / `computed_field`. Anything in §17.2's "output validator" pattern must be Pydantic.
- DMR supports both plugins; the choice is per-controller. Don't mix within a single domain — pick one schema language per app and stick with it.

---

## 22. The API in DMR (implementation pattern for §13)

Important framing: **§13's URL catalog and semantics are unchanged**. The resource paths, the storyboard contract (§13.2), the gate-approval/rerun verbs — all of that stands. This section replaces the *implementation idiom* (ViewSet + DRF serializer) with the DMR equivalent. Read §13 as the resource catalog; read this section as the template for building it.

### 22.1 File layout per app (concretizing §19.5)

```
server/apps/pipelines/
  models.py
  schemas.py      # Pydantic — shared with stages/agents
  events.py       # msgspec Structs — transport only
  selectors.py    # async read queries
  services.py     # async mutations + orchestration kicks
  api.py          # DMR Controllers (one per URL pattern)
  sse.py          # plain Django async views (streaming)
  tasks.py        # TaskIQ task definitions
  stages/         # Stage implementations
  tests/
```

### 22.2 Controller-per-endpoint, not ViewSet-per-resource

DMR's model is **one Controller class per URL pattern**, with typed `async def get/post/patch/...` methods. Where DRF gave you a `RunViewSet` with `@action`s, DMR gives you a handful of small focused classes — more files, each fully typed and individually OpenAPI-documented. The Orval-generated TanStack client gets a focused hook per controller, which is what the frontend actually wants to consume.

```python
# server/apps/pipelines/api.py
from typing import Annotated
from uuid import UUID
from dmr import Body, Controller, PathParam, QueryParam, Headers
from dmr.plugins.pydantic import PydanticSerializer
from . import schemas, selectors, services
from server.apps.core.auth import AuthHeader, require_user


class RunListController(Controller[PydanticSerializer]):
    async def get(
        self,
        parsed_headers: Headers[AuthHeader],
        status: QueryParam[schemas.RunStatus | None] = None,
        channel: QueryParam[UUID | None] = None,
        cursor: QueryParam[str | None] = None,
    ) -> schemas.PaginatedRuns:
        await require_user(parsed_headers)
        return await selectors.list_runs(
            status=status, channel=channel, cursor=cursor
        )

    async def post(
        self,
        parsed_headers: Headers[AuthHeader],
        parsed_body: Body[schemas.RunCreate],
    ) -> schemas.RunDetail:
        user = await require_user(parsed_headers)
        return await services.create_run(parsed_body, actor=user)


class RunDetailController(Controller[PydanticSerializer]):
    async def get(
        self,
        run_id: PathParam[UUID],
        parsed_headers: Headers[AuthHeader],
    ) -> schemas.RunDetail:
        await require_user(parsed_headers)
        return await selectors.get_run(run_id)


class RunGateApproveController(Controller[PydanticSerializer]):
    async def post(
        self,
        run_id: PathParam[UUID],
        gate_key: PathParam[str],
        parsed_headers: Headers[AuthHeader],
        parsed_body: Body[schemas.GateApprove] | None = None,
    ) -> schemas.RunDetail:
        user = await require_user(parsed_headers)
        return await services.approve_gate(
            run_id, gate_key, parsed_body, actor=user
        )


class RunStageRerunController(Controller[PydanticSerializer]):
    async def post(
        self,
        run_id: PathParam[UUID],
        stage_key: PathParam[str],
        parsed_headers: Headers[AuthHeader],
        parsed_body: Body[schemas.RerunRequest],
    ) -> schemas.RunDetail:
        user = await require_user(parsed_headers)
        return await services.rerun_stage(
            run_id, stage_key, parsed_body, actor=user
        )


class RunStoryboardController(Controller[PydanticSerializer]):
    async def get(
        self,
        run_id: PathParam[UUID],
        parsed_headers: Headers[AuthHeader],
    ) -> schemas.Storyboard:
        await require_user(parsed_headers)
        return await selectors.get_storyboard(run_id)


class SceneDetailController(Controller[PydanticSerializer]):
    async def patch(
        self,
        run_id: PathParam[UUID],
        scene_idx: PathParam[int],
        parsed_headers: Headers[AuthHeader],
        parsed_body: Body[schemas.ScenePatch],
    ) -> schemas.Scene:
        user = await require_user(parsed_headers)
        return await services.patch_scene(
            run_id, scene_idx, parsed_body, actor=user
        )
```

URL wiring uses `dmr.routing.Router`:

```python
# config/urls.py
from django.urls import include, path
from dmr.routing import Router
from server.apps.pipelines import api as runs_api
from server.apps.pipelines.sse import run_events

router = Router(
    'api/',
    [
        path('runs/', runs_api.RunListController.as_view()),
        path('runs/<uuid:run_id>/', runs_api.RunDetailController.as_view()),
        path(
            'runs/<uuid:run_id>/cancel/', runs_api.RunCancelController.as_view()
        ),
        path(
            'runs/<uuid:run_id>/gates/<str:gate_key>/approve/',
            runs_api.RunGateApproveController.as_view(),
        ),
        path(
            'runs/<uuid:run_id>/stages/<str:stage_key>/rerun/',
            runs_api.RunStageRerunController.as_view(),
        ),
        path(
            'runs/<uuid:run_id>/storyboard/',
            runs_api.RunStoryboardController.as_view(),
        ),
        path(
            'runs/<uuid:run_id>/scenes/<int:scene_idx>/',
            runs_api.SceneDetailController.as_view(),
        ),
        # ... rest of §13 mapped 1:1
    ],
)

urlpatterns = [
    path(router.prefix, include((router.urls, '***REMOVED***'), namespace='api')),
    # SSE lives outside DMR (streaming response, not typed):
    path('api/runs/<uuid:run_id>/events/', run_events, name='run-events'),
]
```

Same pattern carries through to every other resource family in §13 (channels, prompts, characters, library-assets, candidates, layout-configs, style-configs, overlays, renders, render-templates, posts, sources, clips, campaigns, earnings). Mechanical translation; the URL paths are the contract.

### 22.3 The schema layer: one model, four roles

```python
# server/apps/pipelines/schemas.py
from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, model_validator


class Scene(BaseModel):
    idx: int
    chapter_idx: int
    beat: str
    narration: str
    word_count: int = Field(ge=1)
    visual_concept: str
    shot_type: str
    is_hero: bool
    foreground_cast: list[str] = []
    est_seconds: float = Field(gt=0)


class SceneBreakdownResult(BaseModel):
    """Used as:
    1) PydanticAI agent output_type
    2) API response body at GET /api/runs/{id}/scene-breakdown/
    3) OpenAPI schema source (DMR auto-generates)
    4) Polyfactory/hypothesis fixture for tests
    """

    scenes: list[Scene]
    chapters: list['Chapter']

    @model_validator(mode='after')
    def enforce_invariants(self) -> 'SceneBreakdownResult':
        # Same invariants enforced at agent generation (ModelRetry on violation)
        # AND at API ingress — never serve a malformed result to the frontend.
        for s in self.scenes:
            if not (10 <= s.word_count <= 35):
                raise ValueError(
                    f'scene {s.idx} word count {s.word_count} out of [10,35]'
                )
            if len(s.foreground_cast) > 2:
                raise ValueError(f'scene {s.idx} has >2 foreground characters')
        return self


class RunCreate(BaseModel):
    channel: UUID
    blueprint: Literal['longform_v1', 'clipping_v1'] = 'longform_v1'
    topic: str | None = None  # required for longform_v1
    source: 'SourceMediaInput | None' = None  # required for clipping_v1
    format_override: UUID | None = None
    budget_usd: float | None = Field(default=None, ge=0)
    draft_mode: bool = False
    mode: Literal['normal', 'manual'] = 'normal'
    gates_override: list[str] | None = None

    @model_validator(mode='after')
    def check_blueprint_seed(self) -> 'RunCreate':
        if self.blueprint == 'longform_v1' and not self.topic:
            raise ValueError('topic is required for longform_v1')
        if self.blueprint == 'clipping_v1' and not self.source:
            raise ValueError('source is required for clipping_v1')
        return self
```

The agent declaration (in `generation/agents.py`) reads the same type:

```python
scene_breakdown_agent = Agent(
    deps_type=StageDeps,
    output_type=schemas.SceneBreakdownResult,  # same model
)
```

And `ModelRetry` fires when `enforce_invariants` raises during agent output validation — the LLM gets the validation error and corrects in-call, exactly as §17.2 prescribed.

### 22.4 Events layer: msgspec, transport-only

```python
# server/apps/pipelines/events.py
import msgspec
from typing import Literal


class _BaseEvent(msgspec.Struct, tag_field='type', tag=str.lower):
    run_id: str
    timestamp: float


class StageQueued(_BaseEvent):
    stage_key: str
    shard_index: int | None = None


class StageRunning(_BaseEvent):
    stage_key: str
    shard_index: int | None = None


class StageSucceeded(_BaseEvent):
    stage_key: str
    shard_index: int | None = None
    cost_usd: float = 0.0


class StageFailed(_BaseEvent):
    stage_key: str
    shard_index: int | None = None
    error: str
    retryable: bool


class ShardProgress(_BaseEvent):
    stage_key: str
    done: int
    total: int


class RunCompleted(_BaseEvent):
    final_asset_id: str | None = None


class GateArmed(_BaseEvent):
    gate_key: str


# Reuse a single encoder across the process — the perf point of msgspec.
EVENT_ENCODER = msgspec.json.Encoder()


def encode(event: _BaseEvent) -> bytes:
    return EVENT_ENCODER.encode(event)
```

Publishing happens from services / stage executor:

```python
# in services.py or tasks.py
from server.apps.core.redis import pubsub  # async redis client
from . import events


async def publish_event(event: events._BaseEvent) -> None:
    await pubsub.publish(f'pipeline:{event.run_id}', events.encode(event))
```

### 22.5 SSE view — deliberately outside DMR

DMR controllers return typed responses; streaming sits outside that contract. SSE is a plain Django async view, hand-written, three dozen lines:

```python
# server/apps/pipelines/sse.py
import asyncio
import redis.asyncio as redis
from django.conf import settings
from django.http import StreamingHttpResponse, HttpRequest


async def run_events(
    request: HttpRequest, run_id: str
) -> StreamingHttpResponse:
    client = redis.from_url(settings.REDIS_URL)
    pubsub = client.pubsub()
    await pubsub.subscribe(f'pipeline:{run_id}')

    async def stream():
        try:
            # initial keepalive + immediate snapshot push happens in service
            yield ': connected\n\n'
            async for msg in pubsub.listen():
                if msg['type'] != 'message':
                    continue
                yield f'data: {msg["data"].decode()}\n\n'
        finally:
            await pubsub.unsubscribe(f'pipeline:{run_id}')
            await pubsub.aclose()

    return StreamingHttpResponse(
        stream(),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
```

Wired in `config/urls.py` outside the DMR router (shown in §22.2 above).

### 22.6 Auth: JWT, explicit, per-controller

`pip install django-modern-rest[jwt]`. A single `core/auth.py` exposes `AuthHeader` (Pydantic header model) and `require_user(headers) -> User`. Every controller calls `require_user` at the top — explicit, lint-passing, and the OpenAPI schema reflects the bearer requirement because the header is declared on the controller method.

A `LoginController` mints access + refresh tokens (short-lived access, ~15 min; refresh stored as HttpOnly cookie for the frontend). Roles (`operator` / `reviewer`) gate sensitive mutations via tiny `require_role(user, "operator")` calls inside services — keep authz close to the operation, not middleware.

### 22.7 Testing strategy this unlocks

The Pydantic-everywhere choice makes the test pyramid concrete:

- **schemathesis** runs against the OpenAPI doc DMR auto-generates from controllers — property-based fuzzing of the live API for free, no schema duplication.
- **polyfactory** generates valid instances of any schema (e.g., `SceneBreakdownResultFactory.build()` for a realistic random result).
- **hypothesis** strategies plug into the same models for property tests — e.g., assert that for any `SceneBreakdownResult` violating `enforce_invariants`, validation raises. That same model is the agent's `output_type`, so the test guards both surfaces at once.

A single `test_scene_breakdown_invariants.py` file using these three tools effectively tests the agent contract, the API response, and the OpenAPI schema simultaneously. That's the leverage you bought by making schema choice carefully.
