# Producing a Video with Reelforge

A plain-English walkthrough for operators. Follow these steps in order.
Every action is done from the Django admin at **http://localhost:8000/admin/**
unless stated otherwise.

---

## Before You Start — Start the Stack

```bash
just up
```

Wait ~30 seconds, then confirm these URLs respond:

| Service | URL | What it is |
|---|---|---|
| Admin | http://localhost:8000/admin/ | Where you do everything |
| Flower | http://localhost:5555 | Watch background tasks run |

If running without Docker:

```bash
# Terminal 1
uv run python manage.py runserver

# Terminal 2
uv run celery -A config.celery_app worker -l info
```

---

## How the Pipeline Advances

**Important — read this first.** The pipeline does not advance automatically on its own.

- **You advance each stage manually** by selecting the Pipeline Run in the admin list and clicking an action.
- Once you trigger an action, the background Celery task runs — you wait for the job to complete, then click the next action.
- **The exception:** once you kick off rendering, the pipeline chains automatically: `render → captions → QA → upload`. You don't click anything else.

Every state change is logged to **Pipeline Events** (visible as an inline on the PipelineRun detail page) — an immutable audit trail.

---

## The Pipeline at a Glance

```
INITIALIZING
    ↓  (▶ Start Pipeline)
RESEARCHING         ← AI finds topics
    ↓  (⏭ Advance to Scripting)
SCRIPTING           ← AI writes the script
    ↓  (auto, when script agent finishes)
AWAITING_APPROVAL   ← you review and approve the script
    ↓  (▶ Approve & Continue to Assets)
SCENE_BREAKDOWN     ← AI maps script sections to timed scenes (auto)
    ↓  (auto, chains immediately on completion)
GENERATING_ASSETS   ← voiceover + images + thumbnails (run in parallel)
    ↓  optional stages (see Steps 9 & 10)
[CLIP_GENERATION]   ← animate still images into video clips
[AUDIO_MIX]         ← blend voiceover with background music
    ↓  (🎬 Begin Rendering)
RENDERING           ← video composited + captions generated (automatic)
    ↓  (automatic after render)
QA                  ← 9 automated quality checks (automatic)
    ↓  (automatic if QA passes)
UPLOADING           ← video uploaded to YouTube (automatic)
    ↓
PUBLISHED  ✓
```

Stages in `[ ]` are optional. Skip them and the renderer falls back to still images and raw voiceover automatically.

At any point, a run can enter **FAILED** or **PAUSED** — see the [Control Actions](#control-actions) section.

---

## Step 1 — Create a Channel

**Admin → Channels → Channels → Add Channel**

| Field | What to enter |
|---|---|
| **Name** | e.g. `Top Finance Facts` |
| **Slug** | auto-filled — leave it |
| **Niche Category** | pick the closest category (FINANCE, HEALTH, TECH, etc.) |
| **Custom Niche** | optional, fill if you chose CUSTOM |
| **Target Audience Description** | e.g. `25–45 year olds interested in personal finance` |
| **TTS Provider** | `elevenlabs` (or `mock` for testing without API keys) |
| **TTS Voice ID** | copy from your ElevenLabs voice library |
| **LLM Provider** | leave blank to use the global default |
| **Image Provider** | leave blank to use the global default |
| **Video Provider** | leave blank to use the global default |

Click **Save**.

**How to know it worked:** Channel appears in the list with status **Active**.

> **Note — testing without API keys:** Set TTS Provider to `mock`, Image Provider to `mock`.
> You will get silent audio and placeholder images, but the whole pipeline will run end-to-end.

---

## Step 2 — Create a Pipeline Run

**Admin → Pipeline → Pipeline Runs → Add Pipeline Run**

| Field | What to enter |
|---|---|
| **Channel** | select the channel you just created |
| Everything else | leave as default |

Click **Save**.

**How to know it worked:** Run appears with status **INITIALIZING**.

> A Pipeline Run is the job ticket for one video. Every job and asset hangs off it.

---

## Step 3 — Start Research

**Admin → Pipeline → Pipeline Runs → tick your run → Action: "▶ Start Pipeline" → Go**

This transitions the run to **RESEARCHING**, creates a `ResearchJob`, and dispatches the AI research task to Celery.

**What happens in the background:**
- The Research Agent searches YouTube, Google Trends, and the web
- Discovers and scores multiple topic ideas
- Takes 5–40 minutes depending on your LLM provider

**How to monitor:**
- Admin → Research → Research Jobs → open the job → watch the **Status** field
- Flower → http://localhost:5555 → `research` queue

**How to know it worked:**
- ResearchJob status = **COMPLETED**
- "Topics Discovered" count > 0

### Retry Research

If status is **FAILED** or the task is stuck on **RUNNING** too long:

1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔁 Trigger Research (re-dispatch)"** → Go

This re-fires the research task without changing the FSM state. Safe to run multiple times.

If the run transitioned to **FAILED**:

1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔄 Retry Research"** → Go

---

## Step 4 — Approve a Topic

**Admin → Research → Topic Ideas → filter by your channel**

Review the list. Each topic shows:
- Title idea
- Opportunity score (0–10, higher = better)
- Trend direction (RISING / STABLE / DECLINING)
- Competition level (LOW / MEDIUM / HIGH)

Click into a topic to read the full description, keywords, thumbnail concept, and why it works.

**When you find the one you want:**
1. Tick the topic
2. Action: **"✅ Approve Selected"** → Go

**How to know it worked:** Topic's **Approved** checkbox = ticked.

You can also reject topics you don't want:
1. Tick the topics to reject
2. Action: **"❌ Reject Selected"** → Go

### No good topics?

Go back to the Pipeline Run → Action: **"🔁 Trigger Research (re-dispatch)"** → Go.
Research will run again and create more topics.

---

## Step 5 — Link the Topic and Start Scripting

You need to tell the Pipeline Run which topic to use.

**Admin → Pipeline → Pipeline Runs → open your run**

1. In the **Topic** field, select the approved topic
2. Click **Save**
3. Tick the run → Action: **"⏭ Advance to Scripting"** → Go

This transitions to **SCRIPTING**, creates a `ScriptJob`, and dispatches the script task.

**What happens in the background:**
- The Script Agent reads the topic, channel niche, and audience config
- Gathers research data and sources
- Generates multiple hook options and selects the best
- Writes the full script with sections, B-roll suggestions, and TTS segments
- Produces SEO title, description, tags, chapters, and pinned comment
- Self-reviews for quality before marking complete
- Takes 2–10 minutes

**How to monitor:**
- Admin → Scripts → Script Jobs → open the job → watch **Status**

**How to know it worked:**
- ScriptJob status = **COMPLETED**
- `Final Title`, `Script Text`, `Segments` are populated
- `Ready for Production` = ticked

Run then auto-transitions to **AWAITING_APPROVAL**.

### Retry Scripting

If ScriptJob status is **FAILED**:
1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔄 Retry Scripting"** → Go

If it's stuck on **RUNNING** too long (task died silently):
1. Action: **"🔁 Trigger Scripting (re-dispatch)"** → Go

---

## Step 6 — Review and Approve the Script

**Admin → Scripts → Script Jobs → open the ScriptJob**

Check these fields:

| Field | What to look for |
|---|---|
| **Ready for Production** | should be ticked |
| **Hook Score** | 7.0+ out of 10 |
| **Script Text** | read through the full script |
| **Final Title** | compelling and accurate |
| **SEO Tags** | relevant keywords |
| **Word Count / Est. Duration** | confirms video length |
| **Segments** | TTS chunks — these become the voiceover |
| **B-Roll Suggestions** | scene ideas for image generation |

### Request Changes

If you want the script revised:
1. Fill in the **Change Request** field in the "Script Revision Request" section, e.g.:
   > "Make the hook more dramatic, cut 2 minutes from the middle, add more statistics"
2. Click **Save**
3. Admin → Scripts → Script Jobs → tick the job → Action: **"🔁 Rerun Script with Changes"** → Go

A new `ScriptRevision` will be created (version history). Repeat until satisfied.

### Approve the Script

When happy:

1. Admin → Scripts → Script Jobs → tick the job → Action: **"✅ Approve Script"** → Go
2. Go to Admin → Pipeline → Pipeline Runs → tick your run
3. Action: **"▶ Approve & Continue to Assets"** → Go

The run transitions to **SCENE_BREAKDOWN**, a `SceneBreakdownJob` is created and dispatched automatically. Once it completes, the pipeline chains to **GENERATING_ASSETS** and kicks off voiceover, image, and thumbnail generation in parallel — no further action needed.

---

## Step 7 — Scene Breakdown

The scene breakdown runs **automatically** after you click "▶ Approve & Continue to Assets". A `SceneBreakdownJob` is created and dispatched immediately. Once it completes, the pipeline transitions to **GENERATING_ASSETS** automatically.

**Admin → Production → Scene Breakdown Jobs → open the job for your script** to monitor progress.

**What happens:**
- Each script section is mapped to a timed scene
- Each scene gets a detailed image generation prompt, animation type, mood, and visual keywords
- Estimated durations come from the script — they are refined later when voiceover completes
- The breakdown output is used by both image generation and video clip generation

**How to know it worked:**
- SceneBreakdownJob status = **COMPLETED**
- **Scene Count** > 0
- PipelineRun status advances to **GENERATING_ASSETS** automatically

### Retry Scene Breakdown

If the job failed (pipeline stuck in **SCENE_BREAKDOWN**):

1. Admin → Production → Scene Breakdown Jobs → tick the job
2. Action: **"▶ Run Scene Breakdown"** → Go

Note: the retry action re-runs the breakdown task but does not auto-chain to assets. Once the job shows **COMPLETED**, manually trigger assets:
1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔁 Trigger Assets (re-dispatch)"** → Go

---

## Step 8 — Generate Assets

This is the main generation stage. Three things run **in parallel** automatically when the pipeline enters GENERATING_ASSETS:

| Asset | What it produces |
|---|---|
| **Voiceover** | full narration audio, -16 LUFS normalized (YouTube standard) |
| **Images** | one 1920×1080 image per scene |
| **Thumbnails** | 3 thumbnail options at 1280×720 |

**Admin → Assets → Asset Jobs → open the AssetJob for your run**

The inlines at the bottom show `VoiceoverRun`, `ImageGenerationRun`, `ThumbnailRun` rows —
each should move from PENDING → RUNNING → COMPLETED.

If the whole asset job seems stuck, re-fire all sub-tasks:
1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔁 Trigger Assets (re-dispatch)"** → Go

---

### 8a — Voiceover

**Admin → Assets → Voiceover Runs → open the run**

**How to know it worked:**
- VoiceoverRun status = **COMPLETED**
- **Total Duration Sec** is populated (tells you how long the audio is)
- Voiceover segments inline shows each segment with `duration_sec` filled in

**Note:** After the voiceover completes, the SceneBreakdownJob durations are automatically refined using actual TTS timing data. This makes video clip generation more accurate.

#### Retry Voiceover

1. Admin → Assets → Asset Jobs → tick your AssetJob
2. Action: **"Start new voiceover run"** → Go (creates a fresh run and dispatches it)
3. Once COMPLETED, Admin → Assets → Voiceover Runs → tick the new run
4. Action: **"Select as active voiceover run"** → Go

---

### 8b — Images

**Admin → Assets → Image Generation Runs → open the run**

**How to know it worked:**
- ImageGenerationRun status = **COMPLETED**
- **Images Count** = number of scenes

Image prompts come from the SceneBreakdownJob if completed, or fall back to B-roll suggestions from the ScriptJob. Individual image failures are logged as warnings but don't fail the whole run.

#### Retry Images

1. Admin → Assets → Asset Jobs → tick your AssetJob
2. Action: **"Start new image generation run"** → Go
3. Once COMPLETED, Admin → Assets → Image Generation Runs → tick the new run
4. Action: **"Select as active image run"** → Go

---

### 8c — Thumbnails

**Admin → Assets → Thumbnail Runs → open the run**

**How to know it worked:**
- ThumbnailRun status = **COMPLETED**
- **Options Count** = 3

#### Pick a Different Thumbnail

The first thumbnail option is selected by default (option 0).
To change it:
- Admin → Assets → Thumbnail Options → find options for your AssetJob
- Open the option you prefer → set `is_selected = True` → Save
- Open the previously selected option → set `is_selected = False` → Save

#### Retry Thumbnails

1. Admin → Assets → Asset Jobs → tick your AssetJob
2. Action: **"Start new thumbnail run"** → Go
3. Once COMPLETED, Admin → Assets → Thumbnail Runs → tick the new run
4. Action: **"Select as active thumbnail run"** → Go

---

## Step 9 — Video Clips (Optional)

Animates your still images into short cinematic video clips.
**Skip this step** if you're happy with still images — the renderer falls back automatically.

**Requirements before running:**
- Image run must be **COMPLETED** and selected
- Voiceover run must be **COMPLETED** and selected (needed for accurate clip durations)

**Admin → Assets → Asset Jobs → tick your AssetJob → Action: "Start new video clip run (requires completed image run)" → Go**

**What happens:**
- Each scene image is animated using the animation type from the SceneBreakdownJob
- Clips are generated in parallel via the configured video provider (fal.ai / Kling)
- Each clip is timed to match the scene duration from the voiceover
- Takes 5–30 minutes for 10 clips

**How to know it worked:**
- VideoClipGenerationRun status = **COMPLETED**
- **Clips Count** = number of images

### Retry Video Clips

1. Admin → Assets → Asset Jobs → tick your AssetJob
2. Action: **"Start new video clip run (requires completed image run)"** → Go (creates a fresh run)
3. Once COMPLETED, Admin → Assets → Video Clip Generation Runs → tick the new run
4. Action: **"Select as active clip run"** → Go

---

## Step 10 — Audio Mix (Optional)

Blends voiceover with background music.
**Skip this step** if you want voiceover-only audio — the renderer uses the raw voiceover.

**Admin → Production → Audio Mix Jobs → Add Audio Mix Job**

| Field | What to enter |
|---|---|
| **Asset Job** | select your AssetJob |
| **Voiceover Run** | select the active (COMPLETED) VoiceoverRun |
| **Music File** | upload or select a background music MP3 |
| **Music Volume (%)** | default `0.08` = music is ~22 dB quieter than voiceover |
| **Music Style** | label only, e.g. `ambient` or `inspiring_cinematic` |

Click **Save**. The audio mix task auto-dispatches.

**What happens:**
- Voiceover and music are mixed with the specified volume ratio
- The mix is normalized to -16 LUFS (YouTube standard)
- The new mix automatically becomes the active mix for this AssetJob
- Any previous mixes for this AssetJob are deactivated

**How to know it worked:**
- AudioMixJob status = **COMPLETED**
- **Mixed Audio File** field has a path
- **Is Active** = ticked

### Retry Audio Mix

If the job is stuck on **RUNNING** too long:
1. Admin → Production → Audio Mix Jobs → tick your job
2. Action: **"▶ Run Audio Mix"** → Go

If it failed and you want to fix the settings (e.g. wrong music file), create a new AudioMixJob with corrected values. The new one will auto-deactivate the previous mix when it completes.

---

## Step 11 — Render the Video

**Admin → Pipeline → Pipeline Runs → tick your run → Action: "🎬 Begin Rendering" → Go**

This transitions to **RENDERING**, creates a `ProductionJob`, and dispatches the render task to the `rendering` Celery queue.

**What happens (fully automatic from here):**

1. **Captions** — OpenAI Whisper transcribes the voiceover and generates SRT + ASS subtitle files (Montserrat ExtraBold, 72pt, white with black stroke)
2. **Video render** — Video clips (or still images with Ken Burns) assembled in scene order; audio (mixed or raw voiceover) laid on top; subtitles burned in
   - Main video: 1920×1080, 30fps, H.264 (libx264, CRF 18, preset slow)
   - Shorts variant: 1080×1920 (9:16 crop from center)
3. **QA** — 9 automated checks run immediately after render
4. **Upload** — if QA passes, video is uploaded to YouTube automatically

Can take **15 minutes to 2 hours** depending on video length.

**How to monitor:**
- Admin → Production → Production Jobs → open the job → watch **Status**
- Flower → http://localhost:5555 → `rendering` queue

**How to know rendering worked:**
- ProductionJob status = **COMPLETED**
- **Processed Video File** field has a path
- **Video Duration Sec** is populated

### Retry Rendering

If rendering failed (PipelineRun status = FAILED):
1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔄 Retry Rendering"** → Go

This re-renders and automatically re-runs QA if successful.

Check the ProductionJob **Notes** field for the specific error. Check Flower for the full traceback.

---

## Step 12 — QA Check (Automatic)

QA runs **automatically** after rendering completes. You don't trigger it.

**Admin → Production → Production Jobs → open your job**

The **QA Results** section shows 9 checks:

| Check | What it verifies |
|---|---|
| `file_exists` | rendered file is on disk |
| `duration_within_range` | within ±20% of expected duration |
| `no_black_frames` | no pure black frames detected |
| `audio_present` | audio track exists |
| `resolution_correct` | 1920×1080 for main video |
| `frame_rate_correct` | 30fps |
| `file_size_reasonable` | not suspiciously small |
| `not_corrupted` | file can be probed by ffmpeg |
| `shorts_exists` | Shorts variant was also produced |

**How to know it worked:** `qa_passed = True`, **QA Pass Rate = 100%**

When QA passes, the pipeline **automatically** transitions to **UPLOADING** and dispatches the upload task — no action needed from you.

### If QA Fails

1. Open the ProductionJob → read **QA Results** and **QA Notes** for which checks failed
2. Fix the underlying issue (wrong resolution, missing audio, etc.)
3. Admin → Pipeline → Pipeline Runs → tick your run
4. Action: **"🔄 Retry Rendering"** → Go (re-renders and re-runs QA)

---

## Step 13 — Upload to YouTube (Automatic)

If QA passed, the pipeline advances automatically to **UPLOADING** and dispatches the upload task.

You can also trigger it manually if the auto-dispatch didn't fire:

**Admin → Pipeline → Pipeline Runs → tick your run → Action: "📤 Begin Upload" → Go**

**Requires:** YouTube OAuth credentials configured on the Channel.
If not set up: Admin → Channels → Channels → open your channel → **Setup YouTube OAuth** action.

**What happens:**
- Main video uploaded with title, description, tags, and thumbnail set automatically
- Chapters added to the video description
- Pinned comment posted
- Shorts uploaded if `channel.upload_shorts = True`
- `final_video_url` stored on the PipelineRun and DistributionJob

**How to know it worked:**
- PipelineRun status = **PUBLISHED**
- **Final Video URL** field shows the YouTube link

### Retry Upload

If the upload failed (OAuth expired, network error, etc.):
1. Check the DistributionJob for the error details:
   Admin → Distribution → Distribution Jobs → open the job → read **Notes**
2. If OAuth expired: Admin → Channels → open your channel → **Setup YouTube OAuth** action
3. Admin → Pipeline → Pipeline Runs → tick your run
4. Action: **"🔄 Retry Upload"** → Go

---

## Done ✓

The PipelineRun status shows **PUBLISHED**. Your video is live on YouTube.

The system automatically polls YouTube Analytics at 1 day, 7 days, and 30 days
post-upload and stores views, CTR, watch time, and revenue data on the DistributionJob
as `AnalyticsSnapshot` records.

---

## Control Actions

These actions are available at any time on the Pipeline Run.

### Pause

**Action: "⏸ Pause Pipeline"**

Transitions to **PAUSED**. Use when you need to stop everything and investigate without losing state. The run stays paused until you resume it.

### Resume from Pause

After fixing the issue, resume to the appropriate stage:

| Resume to... | Action |
|---|---|
| Asset Generation | **"▶ Resume → Assets"** |
| Rendering | **"▶ Resume → Rendering"** |
| Upload | **"▶ Resume → Upload"** |

### Reject

**Action: "❌ Reject Run"**

Transitions to **FAILED** with reason "Rejected by operator". Use when you want to abandon this run entirely. Not reversible via a single action — you would need to create a new Pipeline Run.

---

## Skipping Steps

| Want to skip... | Do this |
|---|---|
| Skip research (you already have a topic) | Pipeline Runs → set **Topic** FK → Action: **"⏭ Skip to Scripting (use existing topic)"** |
| Skip research + scripting (you have a script) | Pipeline Runs → set **Script Job** FK → Action: **"⏭ Skip to Assets (use existing script)"** |
| Skip video clips (use still images) | Don't run Step 9. Renderer uses stills automatically. |
| Skip audio mix (voiceover only) | Don't run Step 10. Renderer uses raw voiceover automatically. |

---

## Quick Reference — The Full Pipeline

| Step | Status After | Admin Location | Action / What To Do |
|---|---|---|---|
| 1. Create Channel | — | Channels → Channels | Add Channel |
| 2. Create Pipeline Run | INITIALIZING | Pipeline → Pipeline Runs | Add Pipeline Run |
| 3. Start Research | RESEARCHING | Pipeline Runs | Action: ▶ Start Pipeline |
| 4. Approve Topic | — | Research → Topic Ideas | Action: ✅ Approve Selected |
| 5. Link Topic + Script | SCRIPTING | Pipeline Runs | Set Topic FK → Action: ⏭ Advance to Scripting |
| 6. Approve Script | AWAITING_APPROVAL | Scripts → Script Jobs | Action: ✅ Approve Script → Pipeline Runs: ▶ Approve & Continue to Assets |
| 7. Scene Breakdown | auto | Production → Scene Breakdown Jobs | Auto-runs. Retry: ▶ Run Scene Breakdown → then Trigger Assets |
| 8a. Voiceover | auto | Assets → Voiceover Runs | Auto-runs. Retry: new VoiceoverRun from AssetJob |
| 8b. Images | auto | Assets → Image Generation Runs | Auto-runs. Retry: new ImageGenerationRun from AssetJob |
| 8c. Thumbnails | auto | Assets → Thumbnail Runs | Auto-runs. Retry: new ThumbnailRun from AssetJob |
| 9. Video Clips (opt) | — | Assets → Asset Jobs | Action: Start new video clip run |
| 10. Audio Mix (opt) | — | Production → Audio Mix Jobs | Add AudioMixJob → auto-dispatches |
| 11. Render | RENDERING | Pipeline Runs | Action: 🎬 Begin Rendering |
| 12. QA | auto → UPLOADING | Production → Production Jobs | Auto-runs after render. Retry: re-render |
| 13. Upload | auto → PUBLISHED | Pipeline Runs | Auto-runs after QA passes. Manual: 📤 Begin Upload |

---

## Quick Retry Reference

| Something went wrong at... | Go to... | Do this |
|---|---|---|
| Research failed | Pipeline Runs | Action: **🔄 Retry Research** |
| Research task died (stuck RUNNING) | Pipeline Runs | Action: **🔁 Trigger Research (re-dispatch)** |
| No good topics | Pipeline Runs | Action: **🔁 Trigger Research (re-dispatch)** again |
| Script generation failed | Pipeline Runs | Action: **🔄 Retry Scripting** |
| Script task died (stuck RUNNING) | Pipeline Runs | Action: **🔁 Trigger Scripting (re-dispatch)** |
| Script quality | ScriptJob | Fill `change_request` → Action: **🔁 Rerun Script with Changes** |
| Scene Breakdown | Scene Breakdown Jobs | Action: **▶ Run Scene Breakdown** |
| Assets stuck (all sub-tasks) | Pipeline Runs | Action: **🔁 Trigger Assets (re-dispatch)** |
| Voiceover failed | AssetJob | Action: **Start new voiceover run** → select it |
| Images failed | AssetJob | Action: **Start new image generation run** → select it |
| Thumbnails failed | AssetJob | Action: **Start new thumbnail run** → select it |
| Video Clips failed | AssetJob | Action: **Start new video clip run** again → select it |
| Audio Mix failed | AudioMixJob | Action: **▶ Run Audio Mix** or create new job |
| Rendering failed | Pipeline Runs | Action: **🔄 Retry Rendering** |
| QA failed | Pipeline Runs | Action: **🔄 Retry Rendering** (re-renders + re-QAs) |
| Upload failed | Pipeline Runs | Action: **🔄 Retry Upload** |
| Everything is stuck | Pipeline Runs | Action: **⏸ Pause Pipeline** → fix in Flower → **▶ Resume → [stage]** |

---

## Where Are the Files?

All output files live under your `MEDIA_ROOT` (configured in your `.env`).

| File | Path |
|---|---|
| Voiceover segments | `audio/segments/{asset_job_id}/seg_{n}.mp3` |
| Full voiceover | `audio/full/{asset_job_id}/voiceover.mp3` |
| Mixed audio | `audio/mixed/{asset_job_id}/mixed.mp3` |
| Scene images | `images/{asset_job_id}/{scene_id}.jpg` |
| Video clips | `animations/{asset_job_id}/scene_{scene_id}.mp4` |
| Thumbnail options | `thumbnails/options/{asset_job_id}/thumb_{n}.jpg` |
| Subtitles (.srt) | `captions/srt/{production_job_id}.srt` |
| Subtitles (.ass) | `captions/ass/{production_job_id}.ass` |
| Final video | `renders/processed/{production_job_id}_processed.mp4` |
| Shorts video | `renders/shorts/{production_job_id}_shorts.mp4` |

---

## Monitoring Tips

- **Flower** (http://localhost:5555) shows every background task, its arguments, whether it succeeded or failed, and the full error traceback. This is the first place to look when something goes wrong.
- **Notes field** on any job model (ResearchJob, ScriptJob, AssetJob, SceneBreakdownJob, AudioMixJob, ProductionJob, DistributionJob) contains the error message and traceback if the job failed. Open the job in admin and scroll to the bottom.
- **Pipeline Events** inline on the PipelineRun detail page shows a full audit log of every FSM state change — useful to understand where the pipeline stalled and what transitions happened.
- **Voiceover Segments** inline on the VoiceoverRun shows per-segment status and duration. If some segments failed, you can see which ones here.
- **Generated Images** inline on the ImageGenerationRun shows which images succeeded and which failed individually.
