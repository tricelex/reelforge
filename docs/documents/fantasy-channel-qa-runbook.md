# Fantasy Storytelling Video QA — Manual Setup Runbook

Configure a fantasy storytelling channel entirely through **Django admin** (and the API only where admin cannot start a pipeline). No seed commands. Every step is reproducible for one channel or a hundred.

**Success criterion:** `PipelineRun` status = `COMPLETED`, final MP4 downloadable from run assets.

**Out of scope:** YouTube upload, OAuth, publish stage.

---

## How to use this runbook

Each step lists:

- **Where:** Django admin path (or API if admin cannot do it)
- **Field:** exact admin field name
- **Value:** copy-paste ready content

Admin base URL: `/admin/` (Unfold theme). Paths below are relative to that.

Related reference: [pipeline-dag-architecture.md](./pipeline-dag-architecture.md)

---

## Step 0 — Verify prerequisites (do not seed)

Before creating your channel, confirm these already exist in the deployed system. If any are missing, create them manually in admin following the same patterns.

| Admin path | What to verify |
|------------|----------------|
| **Pipelines → Pipeline blueprints** | Active blueprint named `longform_v1` with kind `LONGFORM` |
| **Prompts → Prompt templates** | Active v1 versions for: `research`, `outline`, `script`, `scene_breakdown`, `visual_prompts`, `music_plan`, `metadata`, `thumbnail`, `narrative_qc` |
| **Assets → Library assets** | At least 5 MUSIC tracks with `license_type` ≠ `UNSPECIFIED` (Step 7) |
| Infrastructure | Web + worker containers running; env vars set (see Step 0b) |

### Step 0b — Environment (ops, not admin)

These must be configured on the server/worker — not in Django admin:

| Variable | Required for |
|----------|--------------|
| `OPENAI_API_KEY` | All LLM stages |
| `FAL_KEY` | Image gen + motion |
| `ELEVENLABS_API_KEY` | TTS |
| `AWS_*` / R2 | File storage |
| `EXA_API_KEY` | Web research (optional but improves research stage) |

Start the worker stack:

```bash
docker compose up -d
docker compose -f docker-compose.yml -f docker-compose.worker.yml up -d worker-api worker-render
```

---

## Step 1 — Create Story Format (narrative architecture)

**Where:** Admin → **Prompts → Story formats → Add**

This is the single most important structural input after `lore_document`. It drives outline beats, chapter pacing, and music mood selection.

### Basic fields

| Field | Value |
|-------|-------|
| **Key** | `fantasy_lore` |
| **Name** | `Fantasy Lore` |
| **Fiction** | ✅ checked |
| **Narration POV** | `narrator` |
| **Is active** | ✅ checked |

### Beats (JSON field)

```json
[
  {
    "name": "world_setup",
    "description": "Establish the world: its rules, its factions, the tension that defines daily life in this place. Name the realm, its magic system constraints, and what ordinary people fear."
  },
  {
    "name": "characters",
    "description": "Introduce the key figures — their goals, flaws, and the relationships that will drive the conflict. Give each a visible want and a hidden wound."
  },
  {
    "name": "conflict",
    "description": "The event that disrupts the equilibrium. Forces collide. Stakes become clear and irreversible. No turning back."
  },
  {
    "name": "climax",
    "description": "The decisive confrontation or revelation that resolves the central conflict — for better or worse. Pay off foreshadowing from earlier beats."
  },
  {
    "name": "denouement",
    "description": "The aftermath: how the world and characters are changed. Leave one thread unresolved to invite the next episode."
  }
]
```

### Pacing (JSON field)

Target ~10 minutes total. Values are **seconds per beat**:

```json
{
  "world_setup": 90,
  "characters": 90,
  "conflict": 180,
  "climax": 180,
  "denouement": 60
}
```

### Music mood map (JSON field)

Must align with tags you will use on library music (Step 7):

```json
{
  "world_setup": "mystical",
  "characters": "adventurous",
  "conflict": "ominous",
  "climax": "epic",
  "denouement": "bittersweet"
}
```

### Prompt overrides

Leave `{}` unless you later add niche-specific research/script tweaks.

**Save.** In admin you'll select this format by name on NicheConfig.

---

## Step 2 — Create Channel

**Where:** Admin → **Channels → Channels → Add**

### Main tab

| Field | Value | Why it matters |
|-------|-------|----------------|
| **Name** | `Eldertale Chronicles` | Display name only |
| **Kind** | `Long-form` | Selects `longform_v1` blueprint |
| **Publish mode** | `Review` | Safer for QA; does not block pipeline |
| **Is active** | ✅ | Required |
| **Gates** | *(leave empty)* | No human gates for video-only QA |
| **Character design mode** | `Auto` | Pipeline picks cast from approved characters |
| **Default budget usd** | `25.00` | Prevents runaway cost on first QA |
| **Default blueprint name** | `longform_v1` | Explicit; same as kind default |
| **Provider daily caps** | `[]` | Optional |
| **Config overrides** | See JSON below | Fine-tunes render quality |

**Config overrides JSON:**

```json
{
  "motion": { "hero_ratio": 0.20 },
  "thumbnail": { "candidates": 3 },
  "image_gen": { "use_character_ref": true }
}
```

`hero_ratio: 0.20` = 20% of scenes get Kling I2V motion (hero shots); rest use Ken Burns.

### TTS tab

| Field | Value | Why it matters |
|-------|-------|----------------|
| **Voice id** | Your ElevenLabs voice ID | Warm, mature narrator from ElevenLabs dashboard |
| **Stability** | `0.55` | Slightly expressive — not robotic |
| **Similarity boost** | `0.80` | Consistent voice character |
| **Wpm** | `145` | Slower than documentary default; suits epic narration |

**Save** before filling inlines.

---

## Step 3 — Niche Config (critical for video quality)

**Where:** Same channel edit page → **Niche config** inline tab  
(or Admin → **Channels → Niche configs → Add**)

| Field | Value |
|-------|-------|
| **Channel** | `Eldertale Chronicles` |
| **Format** | `Fantasy Lore` (Story Format from Step 1) |
| **Audience** | See below |
| **Angle** | See below |
| **Banned topics** | See below |
| **Lore document** | See below (full style guide) |

### Audience

```
Fantasy fans aged 18–40 who love immersive world-building, mythic quests, and
cinematic narration. They watch lore channels for 10–20 minutes and expect
internal consistency — magic rules, character motivations, and tone must not
shift mid-video. They dislike filler, modern slang, and stories that reset at
the end with no lasting change.
```

Injected into `research` and `script` prompts.

### Angle

```
Epic but intimate — every legend is told through a character's eyes, not an
omniscient lecture. Magic always costs something. Treat each video as one
chapter in a connected anthology of realms. The narrator (Lyra) is a witness,
not an omnipotent god-voice.
```

Shapes research angles and script commentary.

### Banned topics (add one per line in ArrayWidget)

```
real-world partisan politics
graphic sexual content
torture porn
modern celebrity gossip
AI-slop bait titles
real-world religious debates presented as fact
```

### Lore document (channel bible)

```
ELDERTALE CHRONICLES — CHANNEL STYLE GUIDE

VOICE & TONE
Our narrator is a seasoned lorekeeper — warm, reverent, never campy. Speak as if
recounting a tale passed down for generations. Use vivid sensory language: mist,
iron, candlelight, distant thunder. Vary rhythm: hushed whispers for secrets,
measured cadence for battle, long breaths for world-building.

SENTENCE CRAFT
- Prefer concrete images over abstract nouns ("torchlit hall" not "darkness").
- Limit adjectives to two per noun — let verbs carry emotion.
- Use anaphora sparingly for ritual moments ("They came. They saw. They broke.").
- Never open a chapter with "In this video" or "Today we explore."

WORLD RULES
- Magic has a cost (blood, memory, time, or sacrifice) — state the cost when magic is used.
- No deus ex machina — every resolution must be foreshadowed in an earlier beat.
- Technology is pre-industrial unless this episode explicitly states otherwise.
- Names must feel linguistically consistent within each realm (Ashmere ≠ Tokyo).
- All stories are fiction — never claim historical or scientific fact.

STORYTELLING PRINCIPLES
1. Open with a mystery, prophecy, or impossible sight — not a geography lesson.
2. Introduce the protagonist's want before the world's macro-problem.
3. Every chapter ends with a story question that demands the next chapter.
4. Climax must permanently change the status quo — someone wins, someone loses, something breaks.
5. Denouement leaves one thread unresolved for future episodes.

VISUAL IDENTITY (for scene_breakdown and visual_prompts)
Cinematic fantasy realism: misty forests, torchlit halls, weathered armor, ancient
runes, floating embers. Avoid cartoon proportions, neon colors, or sci-fi UI.
Color grade: deep teals, amber highlights, violet shadows. Hero character Lyra
Valehart may appear in opening/closing frames as the storyteller.

THINGS WE NEVER DO
- Break the fourth wall without narrative purpose.
- Explain magic systems in exposition longer than 30 seconds of narration.
- Use modern slang, memes, or internet references.
- Kill named characters off-screen without emotional weight.
- End with "and that's why you should subscribe" or similar CTAs in narration.
- Reduce complex conflicts to a single villain with no motivation.
```

Injected into the **script** prompt as `{{ lore }}` — highest-leverage field for tone and visuals.

**Save** the channel with Niche Config inline.

---

## Step 4 — Channel Branding inline

**Where:** Channel edit → **Channel branding** tab

| Field | Value |
|-------|-------|
| **Intro / Outro / Watermark** | Optional for first QA |
| **Watermark position** | `bottom_right` |
| **Watermark opacity** | `0.45` |
| **Music pool tags** | `mystical`, `epic`, `adventurous`, `orchestral`, `ominous`, `bittersweet`, `atmospheric` |
| **Thumbnail palette** | JSON below |

```json
{
  "primary": "#0D1B2A",
  "secondary": "#1B263B",
  "accent": "#E0A458",
  "text": "#F8F9FA",
  "text_shadow": "#000000"
}
```

`music_pool_tags` must overlap with library track tags (Step 7) and Story Format `music_mood_map`.

---

## Step 5 — Assembly Style inline

**Where:** Channel edit → **Assembly style config** tab

| Field | Value |
|-------|-------|
| **Camera movements** | `push_in`, `pan_left`, `pan_right`, `slow_zoom`, `static_hold` |
| **Transition styles** | `cross_dissolve`, `hard_cut`, `fade_to_black` |
| **Sfx pool tags** | `ambient`, `magic`, `sword`, `wind`, `fire` |
| **Min cuts per minute** | `3` |
| **Max cuts per minute** | `7` |

Slower cut rate suits fantasy pacing.

---

## Step 6 — Character

**Where:** Admin → **Channels → Characters → Add**

| Field | Value |
|-------|-------|
| **Channel** | `Eldertale Chronicles` |
| **Name** | `Lyra Valehart` |
| **Status** | `Approved` |
| **Origin** | `Library` |
| **Hero ref** | Optional (Character Studio later) |
| **Total creation cost usd** | `0.0000` |

**Appearance prompt:**

```
Lyra Valehart, an elven lorekeeper in her early thirties with silver-white hair
braided with small amber beads. Pale luminous skin, sharp green eyes that catch
torchlight. Wearing a deep teal hooded cloak over layered leather armor with
bronze clasps shaped like ravens. Standing in an ancient stone library lit by
floating amber orbs, shelves of scrolls fading into mist behind her. Cinematic
fantasy realism, shallow depth of field, 85mm portrait lens, cool shadows with
warm rim light. Expression: knowing, slightly haunted, about to reveal a forbidden
truth.
```

**Persona:**

```
Lyra is the channel's recurring guide — not the hero of every tale, but the voice
who has witnessed centuries of kingdoms rise and fall. She speaks with quiet
authority and occasional grief for what was lost. She never mocks the listener;
she invites them to lean closer. When she offers an opinion, she frames it as
"the old texts say" or "those who survived the siege believed." Her warmth makes
dark lore feel safe to explore. She appears on screen only for chapter transitions
and the opening/closing frames — the story itself is shown through cinematic scenes.
```

---

## Step 7 — Library music assets

**Where:** Admin → **Assets → Library assets → Add**

Create **at least 5 tracks**, one per mood in `music_mood_map`:

| Name | Tags | License type |
|------|------|--------------|
| Mystical Forest Ambience | `mystical`, `atmospheric`, `orchestral` | Royalty free verified |
| Adventurer's March | `adventurous`, `epic`, `orchestral` | Royalty free verified |
| Ominous Siege Drums | `ominous`, `tense`, `dramatic` | Royalty free verified |
| Epic Clash Crescendo | `epic`, `dramatic`, `orchestral` | Royalty free verified |
| Bittersweet Dawn | `bittersweet`, `reflective`, `atmospheric` | Royalty free verified |

For each: upload MP3, **Kind** = `Music`, **Is active** = ✅, **License type** ≠ `Unspecified`.

**Recommended:** Licensed music improves BGM quality, but runs complete without it —
`music_plan` returns empty entries and `assembly` produces voiceover-only video.

---

## Step 8 — Topic idea

**Where:** Admin → **Ideas → Topic ideas → Add**

| Field | Value |
|-------|-------|
| **Channel** | `Eldertale Chronicles` |
| **Niche** | NicheConfig for Eldertale Chronicles |
| **Title** | `The Last Dragon of Ashmere` |
| **Score** | `0.91` |
| **Status** | `Backlog` |

**Topic:**

```
When the final dragon of Ashmere refuses to die after three centuries, a young
scribe named Elen discovers the creature guards not treasure but a sealed pact
between the kingdom's founders and the dragon — a pact that is unravelling.
Elen must decide whether to break the seal and free the dragon, or preserve a
lie that has kept the realm stable for generations. Set in the mist-shrouded
kingdom of Ashmere where dragonfire once forged the royal crown. Magic costs
memory — every spell erases a day from the caster's past.
```

A strong topic includes: named protagonist, specific setting, stated magic rules, irreversible stakes, ~80–120 words.

**Alternatives for backlog:**

| Title | Premise |
|-------|---------|
| The Hollow Crown of Vael | Cursed crown; five rulers; each hears a different prophecy |
| The Whispering Gate | Portal opens when someone speaks a true secret |

---

## Step 9 — Start the pipeline run

Admin cannot auto-start the orchestrator on PipelineRun save. Use:

**Option A — Swagger** (`/api/docs/`): `POST /api/ideas/{idea_id}/promote/`

**Option B — Direct run:**

```http
POST /api/pipelines/runs/
Content-Type: application/json

{
  "channel_id": "<eldertale-channel-uuid>",
  "topic": "<topic text from Step 8>"
}
```

**Option C — Django shell** (if API unavailable):

```python
from server.apps.pipelines.logic.value_objects import RunCreatePayload
from server.common.container import container
from server.apps.pipelines.services.pipeline_run import PipelineRunService

svc = container.resolve(PipelineRunService)
svc.create(RunCreatePayload(channel_id='<uuid>', topic='<topic>'))
```

---

## Step 10 — Monitor the run

**Where:** Admin → **Pipelines → Pipeline runs** → **Stage executions** inline

```
research → outline → script → scene_breakdown → narrative_qc
  → visual_prompts ∥ tts ∥ music_plan
  → image_gen → motion → alignment → assembly → qc → COMPLETED
```

~8–15 minutes wall clock.

| Stage | Pass criteria | If it fails |
|-------|---------------|-------------|
| research | Angles/hooks; fiction as creative lore | Check `EXA_API_KEY`; simplify topic |
| outline | 6–10 chapters matching beats | Verify Story Format on NicheConfig |
| script | Matches lore tone | Expand `lore_document` |
| narrative_qc | Score ≥ 0.5 | Re-run from script |
| music_plan | Track per chapter | Add licensed music (Step 7) |
| assembly | Final video asset | Worker logs, R2 credentials |
| qc | FFmpeg checks pass | Read qc stage output JSON |

Live progress: `GET /api/pipelines/runs/{id}/events/`

---

## Step 11 — Review the finished video

`GET /api/pipelines/runs/{run_id}/assets/` — download final MP4 presigned URL.

Also review:

| Source | Content |
|--------|---------|
| `GET .../storyboard/` | Scene visuals + narration |
| `GET .../publish-metadata/` | Title, description, tags |
| `GET .../transcript/` | Full narration |
| Admin → `assembly` stage output | `asset_id` |
| Admin → `thumbnail` stage output | Candidate asset IDs |

### Quality checklist

- [ ] Opening is visual/mysterious — not a lecture
- [ ] Fantasy lore tone, not documentary
- [ ] Magic costs referenced when spells appear
- [ ] Lyra in appropriate scenes only
- [ ] Music moods shift with beats
- [ ] Captions sync
- [ ] No modern anachronisms
- [ ] Climax pays off opening mystery
- [ ] Runtime ~8–12 minutes

---

## Niche tuning (if output isn't good enough)

1. **Lore document** — add naming rules, magic costs, visual palette
2. **Topic premise** — clearer protagonist, stakes, setting
3. **Angle + audience** — sharpen POV if script feels encyclopedic
4. **Story Format beats** — add examples per beat
5. **Character persona** — sample phrases Lyra would/wouldn't say
6. **WPM + voice_id** — try `135` wpm or different ElevenLabs voice
7. **Config overrides** — raise `hero_ratio` to `0.25` for more motion
8. **Banned topics** — block patterns from bad output

---

## Scaling to many channels

Per channel: Story Format (or reuse) → Channel → NicheConfig → Branding → Character → Topic ideas → promote via API.

Shared infrastructure (blueprints, prompt templates) is created once per deployment.

---

## Deferred — YouTube upload

When ready: `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`, OAuth connect API, blueprint with `final_gate` + `publish`, channel `gates: ["final_gate"]`.
