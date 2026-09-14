# ElevenLabs v3 TTS + captions (manual tool)

Turns an exported script (`docs/script.md` from an editor package, or
a `script.json` list of `{idx, title, text}`) into per-chapter audio
and a captions SRT. Runs outside the Django app and the pipeline —
no CLI flags, no editor-package integration. You run it by hand.

## Usage

1. Export `ELEVENLABS_API_KEY` in your shell.
2. Open `run_tts.py` and edit the config block at the top:
   `SCRIPT_PATH`, `VOICE_ID`, and optionally `RUN_NAME`, `OUT_DIR`,
   `MODEL_ID`, `STABILITY`, `SIMILARITY_BOOST`, `CHUNK_WORDS`.
3. Run: `python scripts/elevenlabs/run_tts.py`

## Output

```
scripts/elevenlabs/runs/<run-name>/
  audio/ch_001.mp3, ch_002.mp3, ...
  captions/captions.srt   # full-timeline, chapter-offset
  captions/words.json     # raw word-level timings, for manual fine-tuning
  manifest.json           # source script, voice/model/settings, char counts
```

Narration text should already contain ElevenLabs v3 audio tags (e.g.
`[sighs]`, `[whispers]`) where wanted — this tool sends the text as-is
to TTS, then strips tags before forced-aligning the resulting audio so
captions stay clean.
