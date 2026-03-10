# Reelforge — Full YouTube Automation Pipeline
## From Topic → Script → Images → Animation → Voice → Captions → Final Video

---

## Overview

```
Research Agent → Topic
       ↓
[1] Script Generation Agent
       ↓
[2] Scene Decomposition & Asset Planning
       ↓
[3] Image Generation (Flux Pro via fal.ai)
       ↓
[4] Image Animation (Kling 1.6 Pro via fal.ai)
       ↓
[5] Voiceover Generation (ElevenLabs / Kokoro)
       ↓
[6] Audio Processing & Timing Sync
       ↓
[7] Caption Generation (Whisper)
       ↓
[8] FFmpeg Video Compilation
       ↓
[9] YouTube Upload (OAuth2)
```

---

## STAGE 1 — Script Generation

### Purpose
Transform a raw topic (e.g., "5 AI Tools That Will Replace Your 9-to-5 in 2025") into a
fully structured, narration-ready script divided into scenes.

### System Prompt

```
You are a professional YouTube scriptwriter specialising in faceless, AI-narrated videos.
Your videos are engaging, fast-paced, and optimised for retention. You write for a general
audience interested in [NICHE: African personal finance / AI business tools].

Your scripts must follow this structure:
1. HOOK (0–15 seconds): An arresting question, fact, or bold claim.
2. INTRO (15–30 seconds): Brief context, tell the viewer what they will learn.
3. MAIN BODY: Between 5 and 8 numbered scenes, each making one focused point.
4. OUTRO (last 20 seconds): Summary + clear call-to-action.

Rules:
- Write in short, punchy sentences. Maximum 20 words per sentence.
- Each scene must have a NARRATION block and a VISUAL DESCRIPTION block.
- The VISUAL DESCRIPTION describes what should appear on screen as a still image.
  Be specific: describe lighting, setting, characters (if any), mood, colour palette.
- Never break the fourth wall (do not reference "this video").
- Avoid passive voice.
- Total word count: 900–1300 words for a 7–10 minute video.
- Output valid JSON only. No markdown, no prose outside the JSON.
```

### User Prompt

```
Topic: {topic}
Niche: {niche}
Target audience: {audience}
Tone: {tone}  (e.g., "authoritative but conversational")
Approximate length: {target_minutes} minutes

Generate a complete script following the system instructions.
Return JSON with this exact schema:

{
  "title": "YouTube video title (max 70 chars, SEO-optimised)",
  "description": "YouTube description (150–200 words, include 5 hashtags at end)",
  "tags": ["tag1", "tag2", ...],  // 10–15 tags
  "hook_text": "Text shown as on-screen hook in first 3 seconds",
  "scenes": [
    {
      "scene_id": 1,
      "scene_type": "hook|intro|body|outro",
      "title": "Internal title for this scene",
      "narration": "Full narration text for this scene only",
      "word_count": 120,
      "estimated_duration_seconds": 45,
      "visual_description": {
        "subject": "Main subject of the image",
        "setting": "Where the scene takes place",
        "mood": "Emotional tone / atmosphere",
        "lighting": "Lighting style",
        "colour_palette": ["#hex1", "#hex2"],
        "camera_angle": "eye-level / bird's eye / low angle / etc.",
        "style": "photorealistic / cinematic / flat illustration / etc.",
        "additional_details": "Any other specifics"
      }
    }
  ]
}
```

### Post-Processing
- Parse JSON response, validate all scenes are present.
- Compute `total_word_count` across all narration blocks.
- Estimate total runtime: `word_count / 140` (average narration WPM).
- Store script object to DB with `status = "script_ready"`.

---

## STAGE 2 — Scene Decomposition & Asset Planning

### Purpose
Take the approved script and build a deterministic asset manifest: which image to generate
for each scene, what motion to apply, how long each clip should be.

### Asset Manifest Schema (stored per video job)

```python
@dataclass
class SceneAsset:
    scene_id: int
    scene_type: str                  # hook | intro | body | outro
    narration: str
    estimated_duration_seconds: float
    image_prompt: str                # Built in Stage 3
    image_style_preset: str          # e.g. "cinematic_realism"
    image_path: str | None           # Populated after generation
    animation_prompt: str            # Built in Stage 4
    animation_path: str | None       # Populated after animation
    audio_path: str | None           # Populated after TTS
    audio_duration_seconds: float | None
    caption_segments: list[dict]     # Populated after Whisper
    clip_start_time: float           # Computed during compilation
    clip_end_time: float             # Computed during compilation
```

### Duration Strategy
- **Hook scene**: lock to 8–12 seconds regardless of narration length.
- **Body scenes**: `max(narration_audio_duration + 1.5s_buffer, 6s)` — always at least 6 s.
- **Outro**: lock to 15–20 seconds.
- Final timeline is computed once all audio durations are known (Stage 6).

---

## STAGE 3 — Image Generation (Flux Pro via fal.ai)

### fal.ai Model
`fal-ai/flux-pro/v1.1` for maximum quality, or `fal-ai/flux/schnell` for speed/cost balance.

### Prompt Engineering

Each scene's `visual_description` object is transformed into a Flux prompt using this template:

```python
def build_image_prompt(scene: SceneAsset, visual: dict) -> str:
    style_map = {
        "cinematic_realism": (
            "cinematic photograph, 8K, shallow depth of field, "
            "professional colour grading, film grain, golden hour lighting"
        ),
        "flat_illustration": (
            "flat design illustration, bold geometric shapes, "
            "vibrant solid colours, minimal shadows, clean vector style"
        ),
        "dark_tech": (
            "dark futuristic tech aesthetic, neon accent lights, "
            "bokeh background, high contrast, cyberpunk mood"
        ),
        "corporate_clean": (
            "professional corporate photography, soft studio lighting, "
            "neutral background, business attire, high resolution"
        ),
    }

    style_suffix = style_map.get(scene.image_style_preset, style_map["cinematic_realism"])

    prompt = (
        f"{visual['subject']}, "
        f"{visual['setting']}, "
        f"{visual['mood']} mood, "
        f"{visual['lighting']}, "
        f"{visual['camera_angle']} shot, "
        f"{visual.get('additional_details', '')}, "
        f"{style_suffix}, "
        f"no text, no watermarks, no UI elements, "
        f"16:9 aspect ratio, ultra detailed"
    )
    return prompt.strip()
```

### Negative Prompt (Always Applied)

```
ugly, blurry, low quality, distorted faces, extra limbs, cartoon (if realism),
watermark, text overlay, logo, signature, username, out of frame, bad anatomy,
duplicate, error, jpeg artifacts, worst quality, low resolution
```

### fal.ai API Call (Python)

```python
import fal_client
import asyncio

async def generate_image(scene: SceneAsset) -> str:
    result = await fal_client.run_async(
        "fal-ai/flux-pro/v1.1",
        arguments={
            "prompt": scene.image_prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "image_size": "landscape_16_9",   # 1920×1080
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
            "num_images": 1,
            "safety_tolerance": "2",
            "output_format": "jpeg",
            "enable_safety_checker": True,
        }
    )
    image_url = result["images"][0]["url"]
    # Download and save locally
    image_path = await download_file(image_url, f"assets/images/scene_{scene.scene_id}.jpg")
    return image_path
```

### Parameters Reference

| Parameter | Value | Notes |
|---|---|---|
| `image_size` | `landscape_16_9` | 1920×1080 for YouTube |
| `num_inference_steps` | 28 | Quality/speed sweet spot |
| `guidance_scale` | 3.5 | Flux Pro recommended range |
| `output_format` | `jpeg` | Smaller file size |
| `safety_tolerance` | `2` | Moderate — allows dramatic imagery |

### Batch Generation Strategy
- Generate all scene images in parallel using `asyncio.gather()`.
- Implement exponential back-off on fal.ai 429 / 503 responses.
- After generation, store image paths to `SceneAsset.image_path`.

---

## STAGE 4 — Image Animation (Kling 1.6 Pro via fal.ai)

### fal.ai Model
`fal-ai/kling-video/v1.6/pro/image-to-video`

### Animation Design Principles

The goal is **subtle, cinematic motion** — not distracting movement. Each animation type is
paired to scene type:

| Scene Type | Motion Style | Why |
|---|---|---|
| Hook | Fast zoom in + slight shake | Urgency, attention grab |
| Intro | Slow pan left to right | Survey / establish |
| Body (stat/data) | Push in (slow dolly) | Emphasis, authority |
| Body (person/action) | Parallax float | Depth, professionalism |
| Body (concept) | Slow orbit / rotation | Intrigue |
| Outro | Gentle pull out + fade | Closure |

### Animation Prompt Templates

```python
ANIMATION_PROMPTS = {
    "hook": (
        "Dramatic push-in camera move, slight camera shake at start, "
        "subject comes sharply into focus, high energy motion, "
        "cinematic lens flare, 1.5x speed, no scene cuts"
    ),
    "intro": (
        "Smooth horizontal pan from left to right, slow and steady, "
        "slight parallax on foreground elements, "
        "cinematic depth of field shift, ambient atmosphere"
    ),
    "body_stat": (
        "Slow cinematic dolly push-in toward subject, "
        "subtle camera breathing (organic motion), "
        "foreground elements drift slightly, subject stays centred, "
        "moody atmospheric haze"
    ),
    "body_person": (
        "Gentle floating parallax, subject has micro-movements, "
        "background drifts softly opposite to foreground, "
        "slight vignette pulse, photorealistic motion blur on edges"
    ),
    "body_concept": (
        "Slow 3D orbit around the subject, "
        "particle dust motes floating in light beams, "
        "subtle colour temperature shift warm to cool, "
        "dreamlike yet grounded"
    ),
    "outro": (
        "Slow pull-out camera move, scene softly de-focuses, "
        "warm colour grade intensifies, "
        "gentle fade to slight overexposure at clip end"
    ),
}
```

### fal.ai API Call (Python)

```python
async def animate_image(scene: SceneAsset) -> str:
    anim_prompt = ANIMATION_PROMPTS.get(scene.scene_type, ANIMATION_PROMPTS["body_stat"])

    # Kling needs duration matched to scene length
    # Kling 1.6 Pro supports 5s or 10s clips
    clip_duration = 5 if scene.estimated_duration_seconds <= 7 else 10

    result = await fal_client.run_async(
        "fal-ai/kling-video/v1.6/pro/image-to-video",
        arguments={
            "image_url": scene.image_path,            # local path or public URL
            "prompt": anim_prompt,
            "negative_prompt": (
                "shaky cam, jump cuts, strobing, fast motion, "
                "morphing faces, distortion, unnatural movement, "
                "glitch, flickering"
            ),
            "duration": clip_duration,                # 5 or 10 seconds
            "aspect_ratio": "16:9",
            "cfg_scale": 0.5,                         # 0–1, higher = more prompt adherence
        }
    )

    video_url = result["video"]["url"]
    animation_path = await download_file(
        video_url, f"assets/animations/scene_{scene.scene_id}.mp4"
    )
    return animation_path
```

### Parameters Reference

| Parameter | Value | Notes |
|---|---|---|
| `duration` | `5` or `10` | Only two valid values for Kling 1.6 Pro |
| `aspect_ratio` | `"16:9"` | YouTube landscape |
| `cfg_scale` | `0.5` | Balanced adherence to motion prompt |
| `negative_prompt` | See above | Prevents jarring motion artifacts |

### Handling Duration Mismatch
If a scene needs 8 seconds but Kling only outputs 5 or 10:
- Choose 10s clip, then **trim in FFmpeg** to exact audio duration.
- For scenes < 5s, generate 5s and trim.
- Never loop animations — it looks cheap. Instead, use a slow enough motion preset so
  the animation fills the scene naturally.

---

## STAGE 5 — Voiceover Generation

### Provider Strategy
- **Primary**: ElevenLabs (highest quality, most natural)
- **Fallback / Cost control**: Kokoro TTS (open source, self-hostable)

### ElevenLabs API Call

```python
from elevenlabs import ElevenLabs, VoiceSettings

client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

def generate_voiceover(scene: SceneAsset, voice_id: str) -> str:
    audio = client.text_to_speech.convert(
        voice_id=voice_id,
        model_id="eleven_turbo_v2_5",   # Fastest high-quality model
        text=scene.narration,
        voice_settings=VoiceSettings(
            stability=0.55,             # 0–1: lower = more expressive
            similarity_boost=0.80,      # Voice consistency
            style=0.35,                 # Stylistic exaggeration
            use_speaker_boost=True,     # Enhances clarity
        ),
        output_format="mp3_44100_128",  # 44.1kHz, 128kbps
    )

    audio_path = f"assets/audio/scene_{scene.scene_id}.mp3"
    with open(audio_path, "wb") as f:
        for chunk in audio:
            f.write(chunk)

    return audio_path
```

### Voice Configuration Recommendations

| Niche | Voice Type | Recommended ElevenLabs Voice |
|---|---|---|
| African personal finance | Deep, confident male | "Antoni" or "Arnold" |
| AI business tools | Clear, energetic male | "Adam" or "Josh" |
| Lifestyle / motivation | Warm female | "Rachel" or "Bella" |

### Voice Settings Tuning

```
stability:        0.45–0.65  →  factual/neutral content
                  0.25–0.45  →  dramatic/emotional scenes
similarity_boost: 0.75–0.85  →  always keep high for consistency
style:            0.2–0.4    →  subtle expressiveness
```

### Kokoro Fallback (Self-hosted)

```python
import kokoro
pipeline = kokoro.KPipeline(lang_code="a")   # "a" = American English

def generate_voiceover_kokoro(scene: SceneAsset) -> str:
    generator = pipeline(
        scene.narration,
        voice="af_heart",    # Options: af_heart, af_bella, am_adam, am_michael
        speed=0.95,          # Slightly slower for clarity
        split_pattern=r"\n+" # Split on paragraph breaks
    )
    audio_path = f"assets/audio/scene_{scene.scene_id}.wav"
    samples = []
    for _, _, audio in generator:
        samples.append(audio)
    # Concatenate and save
    import soundfile as sf
    import numpy as np
    sf.write(audio_path, np.concatenate(samples), 24000)
    return audio_path
```

---

## STAGE 6 — Audio Processing & Timeline Sync

### Purpose
- Measure exact duration of each audio clip.
- Apply audio normalization (loudnorm) and light compression.
- Build the final scene timeline.

### Get Audio Duration

```python
import subprocess, json

def get_audio_duration(audio_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", audio_path],
        capture_output=True, text=True
    )
    info = json.loads(result.stdout)
    return float(info["streams"][0]["duration"])
```

### Audio Normalization (EBU R128 Loudnorm)

YouTube applies its own normalization to -14 LUFS. Pre-normalize to prevent compression.

```python
def normalize_audio(input_path: str, output_path: str):
    # Pass 1: measure
    result = subprocess.run([
        "ffmpeg", "-i", input_path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"
    ], capture_output=True, text=True)

    # Parse the measured values from stderr (loudnorm outputs to stderr)
    stats = json.loads(result.stderr.split("\n{\n")[1].split("\n}\n")[0])

    # Pass 2: apply measured values
    subprocess.run([
        "ffmpeg", "-i", input_path, "-af",
        (
            f"loudnorm=I=-16:TP=-1.5:LRA=11"
            f":measured_I={stats['input_i']}"
            f":measured_TP={stats['input_tp']}"
            f":measured_LRA={stats['input_lra']}"
            f":measured_thresh={stats['input_thresh']}"
            f":linear=true:print_format=summary"
        ),
        "-ar", "44100", output_path
    ])
```

### Build Final Timeline

```python
def build_timeline(scenes: list[SceneAsset]) -> list[SceneAsset]:
    cursor = 0.0
    for scene in scenes:
        # Real clip duration = audio duration + 1.5s buffer
        # But clipped to animation clip length
        actual_duration = get_audio_duration(scene.audio_path)
        scene.audio_duration_seconds = actual_duration
        scene.clip_start_time = cursor
        scene.clip_end_time = cursor + actual_duration + 1.5
        cursor = scene.clip_end_time
    return scenes
```

---

## STAGE 7 — Caption Generation (Whisper)

### Purpose
Burn accurate word-level captions into the video for watch-time retention
(85%+ of viewers watch with sound off on mobile).

### Transcription

```python
import whisper

model = whisper.load_model("base")   # or "small" for better accuracy

def transcribe_audio(scene: SceneAsset) -> list[dict]:
    result = model.transcribe(
        scene.audio_path,
        word_timestamps=True,
        fp16=False,
        language="en",
    )

    # Flatten to word-level segments
    segments = []
    for segment in result["segments"]:
        for word_info in segment.get("words", []):
            segments.append({
                "word": word_info["word"].strip(),
                "start": word_info["start"],
                "end": word_info["end"],
            })

    scene.caption_segments = segments
    return segments
```

### SRT File Generation

```python
def build_srt(scenes: list[SceneAsset], output_path: str):
    idx = 1
    lines = []
    WORDS_PER_CAPTION = 4    # How many words per caption block

    for scene in scenes:
        words = scene.caption_segments
        # Group into chunks of N words
        for i in range(0, len(words), WORDS_PER_CAPTION):
            chunk = words[i:i + WORDS_PER_CAPTION]
            if not chunk:
                continue
            # Offset timestamps by scene start time
            start = scene.clip_start_time + chunk[0]["start"]
            end = scene.clip_start_time + chunk[-1]["end"]
            text = " ".join(w["word"] for w in chunk).upper()

            lines.append(str(idx))
            lines.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
            lines.append(text)
            lines.append("")
            idx += 1

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
```

### Caption Style (Burned-In via FFmpeg ASS Filter)

Use ASS subtitles instead of SRT for full style control:

```python
ASS_STYLE = """
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,4,2,2,80,80,120,1
"""
# PrimaryColour = white, bold, 72pt, with black outline (4px) and drop shadow
# Alignment = 2 = bottom centre
# MarginV = 120 keeps captions off the very bottom edge
```

---

## STAGE 8 — FFmpeg Video Compilation

### Overview of FFmpeg Filter Graph

```
For each scene:
  [animation_clip_N.mp4]  →  trim to scene duration
                          →  scale to 1920×1080 (pad if needed)
                          →  apply Ken Burns if needed (fallback for < 5s clips)
                          ↓
  [audio_N.mp3]           →  trim to scene duration
                          →  fade in 0.1s / fade out 0.2s
                          ↓
  [scene_N_mux.mp4]  ←  merge video + audio

All scene clips → concat filter → master_no_captions.mp4
master_no_captions.mp4 + background_music.mp3 → amix → master_no_captions_music.mp4
master_no_captions_music.mp4 + captions.ass → subtitles filter → final_output.mp4
```

### Step 1: Per-Scene Clip Preparation

```python
def prepare_scene_clip(scene: SceneAsset, output_path: str):
    scene_duration = scene.clip_end_time - scene.clip_start_time
    audio_duration = scene.audio_duration_seconds

    subprocess.run([
        "ffmpeg", "-y",
        "-i", scene.animation_path,
        "-i", scene.audio_path,
        "-filter_complex",
        (
            # Video: trim, scale, pad black bars
            f"[0:v]trim=duration={scene_duration},"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,"
            # Fade in 0.1s at start, fade out 0.3s at end of video
            f"fade=t=in:st=0:d=0.1,"
            f"fade=t=out:st={scene_duration - 0.3}:d=0.3[v];"
            # Audio: trim to audio length, normalize fade
            f"[1:a]atrim=duration={audio_duration},"
            f"afade=t=in:st=0:d=0.05,"
            f"afade=t=out:st={audio_duration - 0.15}:d=0.15[a]"
        ),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-r", "30", "-pix_fmt", "yuv420p",
        output_path
    ], check=True)
```

### Step 2: Concatenate All Scenes

```python
def concatenate_scenes(scene_clips: list[str], output_path: str):
    # Build the concat filter
    inputs = []
    filter_parts = []

    for i, clip in enumerate(scene_clips):
        inputs += ["-i", clip]
        filter_parts.append(f"[{i}:v][{i}:a]")

    concat_filter = (
        "".join(filter_parts) +
        f"concat=n={len(scene_clips)}:v=1:a=1[vout][aout]"
    )

    subprocess.run([
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", concat_filter,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ], check=True)
```

### Step 3: Add Background Music

```python
def mix_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.08   # 8% — subtle, narration must dominate
):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        (
            # Loop music to video length, then fade out last 3 seconds
            f"[1:a]aloop=loop=-1:size=2e+09,"
            f"atrim=duration={get_video_duration(video_path)},"
            f"volume={music_volume},"
            f"afade=t=out:st={get_video_duration(video_path) - 3}:d=3[music];"
            # Mix narration (already in video) with music
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        ),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        output_path
    ], check=True)
```

### Step 4: Burn Captions (ASS Subtitles)

```python
def burn_captions(video_path: str, ass_path: str, output_path: str):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",  # slower = better quality for final
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path
    ], check=True)
```

### Step 5: Add Intro/Outro Overlays (Optional)

For branding (channel logo, subscribe animation, endcard):

```python
def add_branding_overlays(
    video_path: str,
    logo_path: str,
    output_path: str,
    video_duration: float
):
    subscribe_start = video_duration - 20  # last 20 seconds

    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", logo_path,
        "-filter_complex",
        (
            # Logo watermark: top-right, 60% opacity, always visible
            f"[1:v]scale=120:-1,format=rgba,colorchannelmixer=aa=0.6[logo];"
            f"[0:v][logo]overlay=W-w-30:30[vout]"
        ),
        "-map", "[vout]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "17",
        "-c:a", "copy",
        output_path
    ], check=True)
```

---

## STAGE 9 — YouTube Upload

### Upload with YouTube Data API v3

```python
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_path: str,
    credentials: Credentials
):
    youtube = build("youtube", "v3", credentials=credentials)

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22",     # People & Blogs; use 28 for Science & Tech
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus": "private",   # Start private, review before publishing
                "selfDeclaredMadeForKids": False,
            }
        },
        media_body=MediaFileUpload(
            video_path,
            chunksize=50 * 1024 * 1024,   # 50MB chunks
            resumable=True,
            mimetype="video/mp4"
        )
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]

    # Upload custom thumbnail
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    ).execute()

    return video_id
```

---

## Celery Task Graph (Django + Celery)

```python
from celery import chain, group

def run_video_pipeline(job_id: str):
    pipeline = chain(
        generate_script.s(job_id),
        decompose_scenes.s(job_id),
        group(
            generate_image.s(scene_id, job_id)
            for scene_id in get_scene_ids(job_id)
        ),
        group(
            animate_image.s(scene_id, job_id)
            for scene_id in get_scene_ids(job_id)
        ),
        group(
            generate_voiceover.s(scene_id, job_id)
            for scene_id in get_scene_ids(job_id)
        ),
        group(
            transcribe_audio.s(scene_id, job_id)
            for scene_id in get_scene_ids(job_id)
        ),
        build_timeline.s(job_id),
        compile_video.s(job_id),
        upload_to_youtube.s(job_id),
    )
    pipeline.apply_async()
```

---

## Error Handling & Retry Strategy

| Stage | Retry | Fallback |
|---|---|---|
| Script generation | 3× with exponential back-off | Raise to user for review |
| Image generation | 3× (fal.ai transient errors) | Switch to `flux/schnell` |
| Animation | 2× (Kling is slow, avoid hammering) | Use Ken Burns pan/zoom in FFmpeg |
| Voiceover | 3× | Switch to Kokoro TTS |
| Whisper | 1× (local, reliable) | Use basic timing estimate |
| FFmpeg | 1× (deterministic, should not fail) | Log full stderr for diagnosis |
| YouTube upload | Resumable upload handles connection drops automatically | Set to private draft |

### Ken Burns Fallback (when animation fails)

```python
def ken_burns_zoom(image_path: str, duration: float, output_path: str):
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-vf",
        (
            f"scale=8000:-1,"
            f"zoompan=z='min(zoom+0.0010,1.3)':d={int(duration * 30)}:s=1920x1080,"
            f"setsar=1"
        ),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path
    ], check=True)
```

---

## Cost Estimation Per Video (10-minute, 7 scenes)

| Service | Usage | Est. Cost (USD) |
|---|---|---|
| OpenAI GPT-4o (script) | ~1500 tokens | $0.015 |
| Flux Pro (7 images) | 7 generations | $0.35 |
| Kling 1.6 Pro (7 clips × 10s) | 70s of video | $1.40 |
| ElevenLabs (1300 words) | ~8500 chars | $0.085 |
| Whisper (10 min audio) | local / free | $0.00 |
| **Total** | | **~$1.85/video** |

At $1.85/video, a channel posting 5 videos/week costs ~$9.25/week or ~$40/month.

---

## File Structure

```
reelforge/
├── jobs/
│   └── {job_id}/
│       ├── script.json
│       ├── assets/
│       │   ├── images/        # scene_1.jpg … scene_N.jpg
│       │   ├── animations/    # scene_1.mp4 … scene_N.mp4
│       │   ├── audio/         # scene_1.mp3 … scene_N.mp3 (normalized)
│       │   └── music/         # background_track.mp3
│       ├── captions/
│       │   ├── captions.srt
│       │   └── captions.ass
│       ├── clips/             # Per-scene muxed clips
│       ├── final/
│       │   ├── master_raw.mp4
│       │   ├── master_music.mp4
│       │   └── final_output.mp4  ← uploaded to YouTube
│       └── thumbnail.jpg
```

---

*Document generated for Reelforge — YouTube Content Automation SaaS*
