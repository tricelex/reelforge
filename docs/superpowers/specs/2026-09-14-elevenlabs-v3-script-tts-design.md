# ElevenLabs v3 audio tags in scripts + standalone TTS/captions tool

Date: 2026-09-14

## Context

The `script` pipeline stage writes narration text that flows straight
into TTS synthesis (`tts.py` stage) with no intermediate editing. It
currently writes plain narration with no delivery guidance beyond
prose. ElevenLabs' `eleven_v3` model understands inline `[tag]` audio
cues (emotion, delivery) and responds to punctuation/capitalization for
pacing, but does not support SSML `<break>` tags. Using these features
requires the script itself to be written with v3 in mind.

Separately, the newly added `longform_scene_export_v1` blueprint stops
after `script_gate` / editor-package export — it does not run `tts` or
`alignment`. Operators take the exported `docs/script.md` and produce
audio + captions manually today. There's no tool for that step.

## Goals

1. `script` stage output includes ElevenLabs v3 audio tags and
   pacing guidance, applied globally (all blueprints, all channels).
2. Everything downstream that consumes narration text as a literal
   transcript (forced alignment) keeps working once tags appear in it.
3. A standalone, dependency-light tool under `scripts/elevenlabs/`
   turns an exported script into per-chapter audio + a captions SRT,
   run manually, config edited in code (no CLI flags).

## Non-goals

- No changes to `scene_breakdown`, image-gen, or caption burn-in logic
  — traced and confirmed they consume aligned *words*, not raw
  narration text, so tags don't leak into viewer-facing output there.
- No per-channel opt-in/opt-out mechanism for audio tags — the user
  confirmed a global change, including bumping the automated `tts.py`
  stage to `eleven_v3`.
- No CLI argument parsing for the standalone tool — configuration is
  edited in code before each run.
- No audio concatenation/mixing in the standalone tool — per-chapter
  files only, matching the existing pipeline's convention.

## A. Script prompt — v3 audio tag guidance

New `server/apps/prompts/logic/script_prompts.py`, following the
existing `editor_brief_prompts.py` pattern (a git-tracked source of
truth for a versioned `PromptVersion` row):

```python
SCRIPT_TEMPLATE_KEY = 'script'
SCRIPT_TEMPLATE_NAME = 'Narration Script'
SCRIPT_TEMPLATE_DESCRIPTION = (
    'Writes the full per-chapter narration script. Used by the script '
    'stage across all pipeline blueprints.'
)

SCRIPT_SYSTEM_PROMPT = """\
You are a professional documentary script writer. No greetings. Short
sentences. Curiosity gaps at chapter ends. First 30s hooks must restate
the core payoff.

This script is synthesized with ElevenLabs' eleven_v3 text-to-speech
model, which reads inline audio tags and responds to punctuation and
capitalization. Write narration that reads naturally as prose AND
performs well as spoken audio:

- Use audio tags sparingly, in square brackets, only for genuine
  emotional or delivery beats the narrator would actually perform —
  e.g. [sighs], [whispers], [laughs softly], [exhales], [curious],
  [excited]. Do not use sound-effect tags ([gunshot], [applause],
  [music]) — this is narration, not a sound-design script.
- Average no more than one or two tags per chapter. Overusing tags
  destabilizes the voice. Every tag must match a restrained,
  documentary-narrator delivery — never invent a tag that would sound
  out of character for a calm narrator (no [singing], no accents, no
  shouting) unless the chapter explicitly calls for a character
  performing that beat.
- eleven_v3 does not support SSML <break> tags. Control pacing with
  punctuation instead: ellipses ("...") for a hesitant pause, an em
  dash for an abrupt cut-off, a short sentence on its own line for a
  natural breath. Never write "<break time=.../>" or "[pause]" as a
  tag — use punctuation.
- Capitalize a word for emphasis (e.g. "It was NEVER about that.")
  instead of a tag when you want emphasis, not an emotional beat.
- Tags and pacing punctuation ARE the spoken performance, not stage
  directions for a reader — don't describe an action in prose ("he
  paused here") when a tag or punctuation can perform it instead.
"""

SCRIPT_USER_PROMPT = """\
Write the full script for "{{ topic }}".

Chapters: {{ upstream.outline.chapters }}
Research: {{ upstream.research.brief }}
Target WPM: {{ wpm }}.

Include a closing_line per chapter for continuity. For every chapter
also write commentary: 1-3 sentences of genuine analysis or a stated
opinion — not a restatement of the narration — that reflects a real
editorial point of view on the material.
"""
```

New idempotent `server/apps/prompts/management/commands/seed_script_prompt.py`,
structurally identical to `seed_editor_brief_prompt.py`: upsert the
`PromptTemplate`, create a new `PromptVersion` only if no existing
version already has this exact text, and activate it.

`server/apps/pipelines/stages/script.py`'s in-code fallback (used only
when no `PromptVersion` exists at all) stays its own independent,
condensed string — matching the existing convention in this codebase
(`editor_brief.py`'s fallback is likewise a short hand-written string,
not an import of `editor_brief_prompts.py`'s constants). It gets a
one-line addition covering the essentials — "Use ElevenLabs v3 audio
tags like [sighs]/[whispers] sparingly for genuine emotion; use
ellipses/punctuation for pacing, not <break> tags or [pause]" — so an
unseeded environment still gets baseline v3-aware behavior without
duplicating the full seeded-prompt text.

## B. Companion correctness fixes

Two changes are required for the global prompt change to not silently
degrade existing automated pipelines:

**1. TTS model bump.** `server/apps/generation/clients/elevenlabs.py`
`synthesize()`'s default `model_id` changes from
`'eleven_multilingual_v2'` to `'eleven_v3'`. Confirmed via the
ElevenLabs API reference that `eleven_v3` is a valid `model_id` for
`/v1/text-to-speech/{voice_id}` and `voice_settings` keeps the same
numeric `stability` / `similarity_boost` fields — no request-shape
change needed. No test pins the old model string.

**2. Strip tags before forced alignment.** `/v1/forced-alignment`
matches audio to a literal transcript. Audio tags like `[sighs]` are
never spoken, so submitting the raw chapter text (once it contains
tags) as the alignment transcript will try to align a word that
doesn't exist in the audio. New `server/apps/pipelines/logic/audio_tags.py`:

```python
import re

_TAG_RE = re.compile(r'\[[^\]\n]{1,60}\]')
_WS_RE = re.compile(r'[ \t]{2,}')


def strip_audio_tags(text: str) -> str:
    """Remove [bracket] audio/emotion tags, collapsing extra whitespace."""
    without_tags = _TAG_RE.sub('', text)
    lines = [_WS_RE.sub(' ', line).strip() for line in without_tags.splitlines()]
    return '\n'.join(line for line in lines if line)
```

`alignment.py::_align_one_chapter` calls
`strip_audio_tags(transcript_text)` and uses the stripped text for the
`force_align()` call (and for `_segment_from_alignment`'s `text`
field). Caption *cues* already come from aligned words
(`_subtitle_segments_from_scenes` prefers `scene['words']`), so this
one change is sufficient — traced and confirmed no tag leakage into
`scene_breakdown` narration text or burned-in captions.

## C. Standalone `scripts/elevenlabs/` tool

Decoupled from Django — no settings bootstrap, no app imports. Run
manually, one config edit per run, `python scripts/elevenlabs/run_tts.py`.

```
scripts/elevenlabs/
  __init__.py
  audio_tags.py       # strip_audio_tags() — standalone duplicate of B.2
  client.py            # raw httpx: synthesize(), force_align()
  captions.py           # word timings -> chunked SRT cues
  script_source.py      # parses a script file into ordered chapters
  run_tts.py             # config block + orchestration, no CLI args
  README.md
  runs/                   # gitignored — created at runtime
```

**`script_source.py`** — `ScriptChapter(idx, title, text)` frozen
dataclass; `load_chapters(path)` supports:
- `.json`: a list of `{idx, title, text}` objects.
- `.md` / `.txt`: `## Chapter N: Title` headers (matches the exact
  format `package_zip.py`'s `_script_markdown()` already emits to
  `docs/script.md`), body text collected until the next header/EOF.
  A file with no matching headers is treated as one chapter.

**`client.py`** — `async def synthesize(*, text, voice_id, api_key,
model_id, stability, similarity_boost) -> bytes` and `async def
force_align(*, audio_bytes, text, api_key) -> dict` against
`https://api.elevenlabs.io/v1`. No retry logic (manual tool — just
re-run on failure); raises `RuntimeError` with status + response body
snippet on a non-2xx response.

**`captions.py`** — `chunk_words_into_cues(words, chunk_size=4)` and
`build_srt(cues) -> bytes`, same ~4-word cue chunking and SRT
time-format convention as `alignment.py`.

**`run_tts.py`** — top-of-file config block (edited before each run,
no CLI parsing):

```python
# --- Configure before running ---
SCRIPT_PATH = Path('run_0b0237ce_longform_editor_package/docs/script.md')
VOICE_ID = ''
RUN_NAME: str | None = None   # None -> derived from script filename + timestamp
OUT_DIR = Path('scripts/elevenlabs/runs')
MODEL_ID = 'eleven_v3'
STABILITY = 0.5
SIMILARITY_BOOST = 0.75
CHUNK_WORDS = 4
# ---------------------------------
```

`ELEVENLABS_API_KEY` still comes from the environment (never a code
constant — matches the absolute no-committed-secrets rule).

Per-chapter flow, sequential (no concurrency — this is a manual,
low-volume tool): synthesize the tagged chapter text → save
`audio/ch_{idx:03d}.mp3` → `strip_audio_tags()` the chapter text →
`force_align()` the stripped text against the new audio → offset word
timings by the running chapter-duration cursor → append to the
master word list and SRT cues.

Output, one self-contained subdirectory per run:

```
scripts/elevenlabs/runs/<run-name>/
  audio/ch_001.mp3, ch_002.mp3, ...
  captions/captions.srt   # full-timeline, chapter-offset
  captions/words.json     # raw word-level timings, for manual fine-tuning
  manifest.json           # source script path, voice/model/settings, per-chapter char counts, generated_at
```

`.gitignore` gets a `scripts/elevenlabs/runs/` entry.

## Testing

TDD throughout. New tests:

- `tests/test_apps/test_pipelines/test_logic/test_audio_tags.py` —
  `strip_audio_tags` cases (no tags, single tag, multiple tags,
  adjacent tags, tag-only line collapses away, whitespace cleanup).
- `tests/test_apps/test_pipelines/test_stages/test_alignment.py` —
  new case asserting `force_align` is called with tag-stripped text.
- `tests/test_apps/test_generation/test_clients.py` — assert
  `synthesize()`'s default `model_id` is `eleven_v3`.
- `tests/test_apps/test_prompts/...` — `seed_script_prompt` command
  behaves like `seed_editor_brief_prompt` (idempotent create/activate).
- `tests/test_scripts/test_elevenlabs/` (new) — unit tests for
  `audio_tags.py`, `captions.py`, `script_source.py` (both `.md` and
  `.json` parsing), and `run_tts.py`'s orchestration with `client.py`
  mocked (no live HTTP calls).

## Open questions / follow-ups (not blocking)

- The exact numeric `stability` value ElevenLabs' UI presets
  ("Creative"/"Natural"/"Robust") map to isn't published in the API
  reference; kept the existing 0.5 default (already mid-range/
  "Natural"-ish) rather than guessing exact boundaries.
