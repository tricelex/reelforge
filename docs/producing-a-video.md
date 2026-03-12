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

## The Pipeline at a Glance

```
INITIALIZING
    ↓
RESEARCHING     ← AI finds topics
    ↓
SCRIPTING       ← AI writes the script
    ↓
AWAITING_APPROVAL  ← you review the script
    ↓
SCENE_BREAKDOWN ← AI splits script into scenes
    ↓
GENERATING_ASSETS  ← voiceover + images + thumbnails (run in parallel)
    ↓
[CLIP_GENERATION]  ← optional: animate still images into video clips
    ↓
[AUDIO_MIX]    ← optional: blend voiceover with background music
    ↓
RENDERING       ← everything composited into a final video
    ↓
QA              ← 9 automated quality checks
    ↓
UPLOADING       ← video uploaded to YouTube
    ↓
PUBLISHED  ✓
```

Steps in `[ ]` are optional. If you skip them the pipeline still works —
it just uses still images and raw voiceover.

---

## Step 1 — Create a Channel

**Admin → Channels → Channels → Add Channel**

| Field | What to enter |
|---|---|
| **Name** | e.g. `Top Finance Facts` |
| **Slug** | auto-filled — leave it |
| **Niche Category** | pick the closest category |
| **Custom Niche** | optional, more specific description |
| **Target Audience** | e.g. `25–45 year olds interested in personal finance` |
| **TTS Provider** | `elevenlabs` (or `mock` for testing without API keys) |
| **TTS Voice ID** | copy from your ElevenLabs voice library |
| **LLM Provider** | leave blank to use the global default (OpenAI GPT-4o) |
| **Image Provider** | leave blank to use the global default (fal_ai) |

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

> A Pipeline Run is the job ticket for one video. Everything else hangs off it.

---

## Step 3 — Start Research

**Admin → Pipeline → Pipeline Runs → tick your run → Action: "▶ Start Pipeline" → Go**

This transitions the run to **RESEARCHING**, creates a `ResearchJob`, and dispatches
the AI research task to Celery.

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
If status is **FAILED** or it's been stuck on **RUNNING** for too long:

1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔁 Trigger Research (re-dispatch)"** → Go

This re-fires the research task without changing the FSM state. It is safe to run multiple times.

---

## Step 4 — Approve a Topic

**Admin → Research → Topic Ideas → filter by your channel**

Review the list. Each topic shows:
- Title idea
- Opportunity score (0–100, higher = better)
- Trend direction (RISING / STABLE / DECLINING)
- Competition level (LOW / MEDIUM / HIGH)

Click into a topic to read the full description, keywords, and thumbnail concept.

**When you find the one you want:**
1. Tick the topic
2. Action: **"✅ Approve Selected"** → Go

**How to know it worked:** Topic's **Approved** checkbox = ticked.

### No good topics?
Go back to the Pipeline Run → Action: **"🔁 Trigger Research (re-dispatch)"** → Go.
Research will run again and create more topics.

---

## Step 5 — Link the Topic and Start Scripting

You need to tell the Pipeline Run which topic to use.

**Admin → Pipeline → Pipeline Runs → open your run**

1. In the **Topic** field, select the approved topic you just approved
2. Click **Save**
3. Tick the run → Action: **"⏭ Advance to Scripting"** → Go

This transitions to **SCRIPTING**, creates a `ScriptJob`, and dispatches the script task.

**What happens in the background:**
- The Script Agent reads the topic, your channel niche, and your audience config
- Writes: hook, full script, TTS segments, B-roll suggestions, SEO title/description/tags/chapters
- Takes 2–10 minutes

**How to monitor:**
- Admin → Scripts → Script Jobs → open the job → watch **Status**

**How to know it worked:**
- ScriptJob status = **COMPLETED**
- Fields `Final Title`, `Script Text`, `Segments` are populated

### Retry Scripting
If status is **FAILED**:
1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔄 Retry Scripting"** → Go

If it's been **RUNNING** for too long (stuck):
1. Action: **"🔁 Trigger Scripting (re-dispatch)"** → Go

---

## Step 6 — Review and Approve the Script

**Admin → Scripts → Script Jobs → open the ScriptJob**

Check these fields:

| Field | What to look for |
|---|---|
| **Hook Score** | should be 7.0+ out of 10 |
| **Script Text** | read through the full script |
| **Final Title** | compelling, accurate |
| **SEO Tags** | relevant keywords |
| **Word Count / Est. Duration** | confirms video length |
| **Segments** | TTS chunks — these become the voiceover |

### Request Changes
If you want the script revised:
1. Fill in the **Change Request** field — describe what to fix, e.g.:
   > "Make the hook more dramatic, cut 2 minutes from the middle, simplify the intro"
2. Click **Save**
3. Admin → Scripts → Script Jobs → tick the job → Action: **"🔁 Rerun Script with Changes"** → Go

A new `ScriptRevision` will be created. Repeat until satisfied.

### Approve the Script
When happy:
1. Admin → Scripts → Script Jobs → tick the job → Action: **"✅ Approve Script"** → Go
2. Go back to Admin → Pipeline → Pipeline Runs → tick your run
3. Action: **"▶ Approve & Continue to Assets"** → Go

The run transitions to **SCENE_BREAKDOWN**, then automatically to **GENERATING_ASSETS**.

---

## Step 7 — Scene Breakdown

The pipeline creates a `SceneBreakdownJob` automatically when it enters **SCENE_BREAKDOWN**.

**Admin → Production → Scene Breakdown Jobs → open the job for your script**

**What happens:**
- Each script section is mapped to a timed scene
- Each scene gets an image prompt and animation type
- Estimated durations come from the script; actual durations are refined after voiceover

**How to know it worked:**
- SceneBreakdownJob status = **COMPLETED**
- **Scene Count** > 0

### Retry Scene Breakdown
If status is **FAILED** or the job was never created:
1. Admin → Production → Scene Breakdown Jobs → **Add Scene Breakdown Job**
2. Select your **Script Job** → Save
3. The task auto-dispatches on save

If it failed and you want to re-run it:
1. Admin → Production → Scene Breakdown Jobs → tick the job
2. Action: **"▶ Run Scene Breakdown"** → Go

---

## Step 8 — Generate Assets

This is the main generation stage. Three things run **in parallel** automatically:

| Asset | What it produces |
|---|---|
| **Voiceover** | full narration audio, -16 LUFS normalized (YouTube standard) |
| **Images** | one 1920×1080 image per scene |
| **Thumbnails** | 3 thumbnail options |

**Admin → Assets → Asset Jobs → open the AssetJob for your run**

The inlines at the bottom show `VoiceoverRun`, `ImageGenerationRun`, `ThumbnailRun` rows —
each should move from PENDING → RUNNING → COMPLETED.

---

### 8a — Voiceover

**Admin → Assets → Voiceover Runs → open the run**

**How to know it worked:**
- VoiceoverRun status = **COMPLETED**
- **Total Duration Sec** is populated (this tells you how long the audio is)
- The voiceover segments (shown as an inline) each have `duration_sec` filled in

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
The first thumbnail option is selected by default.
To change it:
- Admin → Assets → Thumbnail Options → find options for your AssetJob
- Set `is_selected = True` on the one you prefer
- Set `is_selected = False` on the others

#### Retry Thumbnails
1. Admin → Assets → Asset Jobs → tick your AssetJob
2. Action: **"Start new thumbnail run"** → Go
3. Once COMPLETED, Admin → Assets → Thumbnail Runs → tick the new run
4. Action: **"Select as active thumbnail run"** → Go

---

## Step 9 — Video Clips (Optional)

Animates your still images into short cinematic video clips (via Kling AI).
**Skip this step** if you're happy with still images — the renderer falls back automatically.

**Requires: Voiceover must be COMPLETED first** (clips use its duration data).

**Admin → Assets → Asset Jobs → tick your AssetJob → Action: "Generate video clips (requires completed image run)" → Go**

**What happens:**
- Each image is uploaded to fal.ai CDN
- All images are animated in parallel (Ken Burns or Kling motion)
- Each clip is 5 or 10 seconds depending on scene length
- Takes 5–30 minutes for 10 clips

**How to know it worked:**
- VideoClipGenerationRun status = **COMPLETED**
- **Clips Count** = number of images

### Retry Video Clips
1. Admin → Assets → Asset Jobs → tick your AssetJob
2. Action: **"Generate video clips (requires completed image run)"** → Go (creates a fresh run)
3. Once COMPLETED, Admin → Assets → Video Clip Generation Runs → tick the new run
4. Action: **"Select as active video clip run"** → Go

---

## Step 10 — Audio Mix (Optional)

Blends voiceover with background music.
**Skip this step** if you want voiceover-only audio.

**Admin → Production → Audio Mix Jobs → Add Audio Mix Job**

| Field | What to enter |
|---|---|
| **Asset Job** | select your AssetJob |
| **Voiceover Run** | select the active (COMPLETED) VoiceoverRun |
| **Music File** | upload or select a background music MP3 |
| **Music Volume (%)** | default `0.08` = music is ~22 dB quieter than voiceover |
| **Music Style** | label only, e.g. `ambient` or `upbeat_corporate` |

Click **Save**. The audio mix task auto-dispatches.

**How to know it worked:**
- AudioMixJob status = **COMPLETED**
- **Mixed Audio File** field has a path
- **Is Active** = ticked

### Retry Audio Mix
The simplest approach is to fix the issue (e.g. wrong music file path) and create a new AudioMixJob with corrected values. The new one will auto-set itself as active when it completes.

If the job is stuck (RUNNING too long):
1. Admin → Production → Audio Mix Jobs → tick your job
2. Action: **"▶ Run Audio Mix"** → Go

---

## Step 11 — Render the Video

**Admin → Pipeline → Pipeline Runs → tick your run → Action: "🎬 Begin Rendering" → Go**

This transitions to **RENDERING**, creates a `ProductionJob`, and dispatches the render
task to the `rendering` Celery queue.

**What happens:**
- Video clips (or still images with Ken Burns) assembled in scene order
- Voiceover (or mixed audio if AudioMixJob is active) laid on top
- Subtitles generated via OpenAI Whisper and burned in
- Main video: 1920×1080, 30fps, H.264 (libx264, CRF 18)
- Shorts variant: 1080×1920 (9:16 crop from center)
- Can take **15 minutes to 2 hours** depending on length

**How to monitor:**
- Admin → Production → Production Jobs → open the job → watch **Status**
- Flower → http://localhost:5555 → `rendering` queue

**How to know it worked:**
- ProductionJob status = **COMPLETED**
- **Processed Video File** field has a path
- **Video Duration Sec** is populated

### Retry Rendering
1. Admin → Pipeline → Pipeline Runs → tick your run
2. Action: **"🔄 Retry Rendering"** → Go

If the rendering worker ran out of memory or hit a time limit:
- Check Flower logs for the specific error
- Admin → Production → Production Jobs → open the job → read the **Notes** field

---

## Step 12 — QA Check

QA runs **automatically** after rendering completes. You don't need to trigger it manually.

**Admin → Production → Production Jobs → open your job**

The **QA Results** section shows 9 checks:

| Check | What it verifies |
|---|---|
| file_exists | rendered file is on disk |
| duration_within_range | within ±20% of expected duration |
| no_black_frames | no pure black frames detected |
| audio_present | audio track exists |
| resolution_correct | 1920×1080 for main video |
| frame_rate_correct | 30fps |
| file_size_reasonable | not suspiciously small |
| not_corrupted | file can be probed by ffmpeg |
| shorts_exists | Shorts variant was also produced |

**How to know it worked:** `qa_passed = True`, **QA Pass Rate = 100%**

The pipeline automatically advances to **UPLOADING** when QA passes.

### If QA Fails
1. Open the ProductionJob → read **QA Results** and **QA Notes** JSON for which checks failed
2. Fix the underlying issue (wrong resolution, missing audio, etc.)
3. Admin → Pipeline → Pipeline Runs → tick your run
4. Action: **"🔄 Retry Rendering"** → Go (re-renders and re-runs QA)

---

## Step 13 — Upload to YouTube

If QA passed, the pipeline advances automatically to **UPLOADING** and dispatches the upload task.

You can also trigger it manually:

**Admin → Pipeline → Pipeline Runs → tick your run → Action: "📤 Begin Upload" → Go**

**Requires:** YouTube OAuth credentials configured on the Channel.
If not set up: Admin → Channels → Channels → open your channel → **Setup YouTube OAuth** action.

**What happens:**
- Main video uploaded (title, description, tags, thumbnail set automatically)
- Shorts uploaded if `channel.upload_shorts = True`
- `final_video_url` stored on the PipelineRun

**How to know it worked:**
- PipelineRun status = **PUBLISHED**
- **Final Video URL** field shows the YouTube link

### Retry Upload
If the upload failed (OAuth expired, network error, etc.):
1. Check the DistributionJob for the error details:
   Admin → Distribution → Distribution Jobs → open the job → read **Notes**
2. If OAuth expired: Admin → Channels → open your channel → **Setup YouTube OAuth** row action
3. Admin → Pipeline → Pipeline Runs → tick your run
4. Action: **"🔄 Retry Upload"** → Go

---

## Done ✓

The PipelineRun status shows **PUBLISHED**. Your video is live on YouTube.

The system will automatically poll YouTube Analytics at 1 day, 7 days, and 30 days
post-upload and store views, CTR, watch time, and revenue data on the DistributionJob.

---

## Quick Reference — The Full Pipeline

| Step | Status After | Admin Location | Action / What To Do |
|---|---|---|---|
| 1. Create Channel | — | Channels → Channels | Add Channel |
| 2. Create Pipeline Run | INITIALIZING | Pipeline → Pipeline Runs | Add Pipeline Run |
| 3. Start Research | RESEARCHING | Pipeline Runs | Action: ▶ Start Pipeline |
| 4. Approve Topic | — | Research → Topic Ideas | Action: ✅ Approve Selected |
| 5. Link Topic + Script | SCRIPTING | Pipeline Runs | Set topic FK → Action: ⏭ Advance to Scripting |
| 6. Approve Script | SCENE_BREAKDOWN | Scripts → Script Jobs | Action: ✅ Approve Script → Pipeline Runs: ▶ Approve & Continue to Assets |
| 7. Scene Breakdown | auto | Production → Scene Breakdown Jobs | Auto-runs. Retry: ▶ Run Scene Breakdown |
| 8a. Voiceover | auto | Assets → Voiceover Runs | Auto-runs. Retry: new VoiceoverRun from AssetJob |
| 8b. Images | auto | Assets → Image Generation Runs | Auto-runs. Retry: new ImageGenerationRun from AssetJob |
| 8c. Thumbnails | auto | Assets → Thumbnail Runs | Auto-runs. Retry: new ThumbnailRun from AssetJob |
| 9. Video Clips (opt) | — | Assets → Asset Jobs | Action: Generate video clips |
| 10. Audio Mix (opt) | — | Production → Audio Mix Jobs | Add AudioMixJob → auto-dispatches |
| 11. Render | RENDERING | Pipeline Runs | Action: 🎬 Begin Rendering |
| 12. QA | QA → auto | Production → Production Jobs | Auto-runs after render. Retry: re-render |
| 13. Upload | UPLOADING → PUBLISHED | Pipeline Runs | Auto-runs after QA. Manual: 📤 Begin Upload |

---

## Quick Retry Reference

| Something went wrong at... | Go to... | Do this |
|---|---|---|
| Research | Pipeline Runs | Action: **🔁 Trigger Research (re-dispatch)** |
| No good topics | Pipeline Runs | Action: **🔁 Trigger Research (re-dispatch)** again |
| Script generation | Pipeline Runs | Action: **🔄 Retry Scripting** |
| Script quality | ScriptJob | Fill `change_request` → Action: **🔁 Rerun Script with Changes** |
| Scene Breakdown | Scene Breakdown Jobs | Action: **▶ Run Scene Breakdown** |
| Voiceover | AssetJob | Action: **Start new voiceover run** → select it |
| Images | AssetJob | Action: **Start new image generation run** → select it |
| Thumbnails | AssetJob | Action: **Start new thumbnail run** → select it |
| Video Clips | AssetJob | Action: **Generate video clips** again → select it |
| Audio Mix | AudioMixJob | Action: **▶ Run Audio Mix** or create new job |
| Rendering | Pipeline Runs | Action: **🔄 Retry Rendering** |
| QA failed | Pipeline Runs | Action: **🔄 Retry Rendering** (re-renders + re-QAs) |
| Upload | Pipeline Runs | Action: **🔄 Retry Upload** |
| Everything is stuck | Pipeline Runs | Action: **⏸ Pause Pipeline** → fix in Flower → **▶ Resume → [stage]** |

---

## Skipping Steps

| Want to skip... | Do this |
|---|---|
| Skip research (you already have a topic) | Pipeline Runs → set **Topic** FK → Action: **⏭ Skip to Scripting (use existing topic)** |
| Skip research + scripting (you have a script) | Pipeline Runs → set **Script Job** FK → Action: **⏭ Skip to Assets (use existing script)** |
| Skip video clips (use still images) | Don't run Step 9. Renderer uses stills automatically. |
| Skip audio mix (voiceover only) | Don't run Step 10. Renderer uses raw voiceover automatically. |

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
| Final video | `renders/processed/{production_job_id}_processed.mp4` |
| Shorts video | `renders/shorts/{production_job_id}_shorts.mp4` |
| Captions (.srt) | `captions/srt/{production_job_id}.srt` |
| Captions (.ass) | `captions/ass/{production_job_id}.ass` |

---

## Monitoring Tips

- **Flower** (http://localhost:5555) shows every background task, its arguments, whether it succeeded or failed, and the full error traceback if it failed. This is the first place to look when something goes wrong.
- **Notes field** on any job model (ResearchJob, ScriptJob, AssetJob, etc.) contains the error message and traceback if the job failed. Open the job in admin and scroll to the bottom.
- **Pipeline Events** inline on the PipelineRun shows a full audit log of every state change — useful to understand where the pipeline stalled.
