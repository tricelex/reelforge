# ElevenLabs v3 Script Audio Tags + Standalone TTS Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `script` pipeline stage write ElevenLabs v3 audio tags into narration, keep the automated TTS/alignment pipeline correct once tags appear, and ship a standalone `scripts/elevenlabs/` tool that turns an exported script into per-chapter audio + a captions SRT.

**Architecture:** Two independent halves. (A) Django-side: a new versioned prompt (`script_prompts.py` + `seed_script_prompt` command) carries v3 tag guidance; the ElevenLabs client defaults to `eleven_v3`; the `alignment` stage strips tags before forced alignment so captions stay clean. (B) A dependency-light standalone tool under `scripts/elevenlabs/` (raw httpx, no Django imports) that a human runs manually against an exported `docs/script.md`, config edited in code, one output subdirectory per run.

**Tech Stack:** Python 3.13, Django 6.0, httpx (already a transitive dependency, used the same way in `server/apps/generation/clients/elevenlabs.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-elevenlabs-v3-script-tts-design.md`

## Global Constraints

- `ruff` uses single quotes, 80-char line length, Google-style docstrings on every function (public and private — matches this codebase's existing convention even though pydocstyle would not strictly require it on private functions).
- `mypy` strict mode applies to `server/` (not `scripts/`, per this repo's `mypy server` command) — still write full type hints in `scripts/` for consistency.
- Never hardcode the ElevenLabs API key — read `ELEVENLABS_API_KEY` from the environment only (absolute no-committed-secrets rule).
- No CLI argument parsing in `scripts/elevenlabs/run_tts.py` — all run parameters are module-level constants edited in code before each run.
- No changes to `scene_breakdown.py`, image-gen, or caption burn-in logic — confirmed out of scope in the spec (captions already derive from aligned *words*, not raw narration text).
- Tests follow this repo's TDD convention: write the failing test, run it, implement, run again, commit.

---

### Task 1: `strip_audio_tags()` shared helper (Django side)

**Files:**
- Create: `server/apps/pipelines/logic/audio_tags.py`
- Test: `tests/test_apps/test_pipelines/test_logic/test_audio_tags.py`

**Interfaces:**
- Produces: `strip_audio_tags(text: str) -> str` — removes `[bracket]` audio/emotion tags and collapses the resulting extra whitespace. Used by Task 2 (`alignment.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for strip_audio_tags()."""

from server.apps.pipelines.logic.audio_tags import strip_audio_tags


def test_strip_audio_tags_no_tags_returns_text_unchanged() -> None:
    """Text with no tags passes through untouched."""
    assert strip_audio_tags('Rome was great once.') == 'Rome was great once.'


def test_strip_audio_tags_removes_single_tag() -> None:
    """A single bracket tag is removed."""
    result = strip_audio_tags('[sighs] Rome was great once.')
    assert result == 'Rome was great once.'


def test_strip_audio_tags_removes_multiple_tags() -> None:
    """Multiple tags across the text are all removed."""
    result = strip_audio_tags(
        '[whispers] Rome was great once. [sighs] Then it fell.',
    )
    assert result == 'Rome was great once. Then it fell.'


def test_strip_audio_tags_removes_adjacent_tags() -> None:
    """Back-to-back tags with no text between them collapse cleanly."""
    result = strip_audio_tags('[sighs][exhales] Rome fell.')
    assert result == 'Rome fell.'


def test_strip_audio_tags_drops_tag_only_line() -> None:
    """A line that is only a tag disappears entirely, not a blank line."""
    result = strip_audio_tags('Rome was great once.\n[Pause]\nThen it fell.')
    assert result == 'Rome was great once.\nThen it fell.'


def test_strip_audio_tags_collapses_extra_whitespace() -> None:
    """Removing a tag mid-sentence doesn't leave doubled spaces."""
    result = strip_audio_tags('Rome was great once.  [sighs]  Then it fell.')
    assert result == 'Rome was great once. Then it fell.'


def test_strip_audio_tags_empty_string_returns_empty_string() -> None:
    """Empty input returns empty output."""
    assert strip_audio_tags('') == ''
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_audio_tags.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'server.apps.pipelines.logic.audio_tags'`

- [ ] **Step 3: Write the implementation**

```python
"""Strip ElevenLabs v3 [bracket] audio/emotion tags from narration text."""

import re

_TAG_RE = re.compile(r'\[[^\]\n]{1,60}\]')
_WS_RE = re.compile(r'[ \t]{2,}')


def strip_audio_tags(text: str) -> str:
    """Remove [bracket] audio/emotion tags, collapsing extra whitespace.

    ElevenLabs v3 audio tags (e.g. ``[sighs]``, ``[whispers]``) are never
    spoken aloud, so a transcript submitted for forced alignment must not
    contain them — the aligner would try to match a word that isn't in
    the audio.
    """
    without_tags = _TAG_RE.sub('', text)
    lines = [
        _WS_RE.sub(' ', line).strip() for line in without_tags.splitlines()
    ]
    return '\n'.join(line for line in lines if line)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_audio_tags.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add server/apps/pipelines/logic/audio_tags.py tests/test_apps/test_pipelines/test_logic/test_audio_tags.py
git commit -m "feat(pipelines): add strip_audio_tags() for clean forced-alignment transcripts"
```

---

### Task 2: Strip tags before forced alignment in `alignment.py`

**Files:**
- Modify: `server/apps/pipelines/stages/alignment.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_alignment.py`

**Interfaces:**
- Consumes: `strip_audio_tags(text: str) -> str` from Task 1 (`server.apps.pipelines.logic.audio_tags`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_apps/test_pipelines/test_stages/test_alignment.py` (uses the existing `_make_ctx()` and `_fake_fa_result()` helpers already in this file):

```python
def test_alignment_strips_audio_tags_before_force_align() -> None:
    """force_align() receives tag-stripped text, not the raw script text."""
    ctx = _make_ctx()
    ctx.upstream['script']['chapters'][0]['text'] = (
        '[whispers] Rome was great once. [sighs] Then it fell.'
    )

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.alignment.load_tts_chapter_shards',
                new=AsyncMock(
                    return_value=[
                        {'chapter_idx': 0, 'asset_id': 'audio-0'},
                    ],
                ),
            ),
            patch(
                'server.apps.pipelines.stages.alignment._fetch_audio_bytes',
                new=AsyncMock(return_value=b'fake-audio'),
            ),
            patch(
                'server.apps.pipelines.stages.alignment.elevenlabs_client.force_align',
                new=AsyncMock(return_value=_fake_fa_result()),
            ) as mock_force_align,
            patch(
                'server.apps.pipelines.stages.alignment.settings.ELEVENLABS_API_KEY',
                'test-key',
            ),
        ):
            await AlignmentStage().run(ctx)

        _, kwargs = mock_force_align.call_args
        assert kwargs['text'] == 'Rome was great once. Then it fell.'

    asyncio.run(_inner())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_alignment.py::test_alignment_strips_audio_tags_before_force_align -v`
Expected: FAIL — `kwargs['text']` is `'[whispers] Rome was great once. [sighs] Then it fell.'` (untouched), not the stripped string.

- [ ] **Step 3: Implement the fix**

In `server/apps/pipelines/stages/alignment.py`, add the import:

```python
from server.apps.pipelines.logic.audio_tags import strip_audio_tags
```

Then in `_align_one_chapter`, change:

```python
    chapter = script_chapters.get(shard['chapter_idx'], {})
    transcript_text = chapter.get('text', '')
    if not transcript_text.strip():
```

to:

```python
    chapter = script_chapters.get(shard['chapter_idx'], {})
    transcript_text = strip_audio_tags(chapter.get('text', ''))
    if not transcript_text.strip():
```

(`transcript_text` is already used for both the `force_align()` call and `_segment_from_alignment`'s `text` field further down, so this one edit covers both.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_alignment.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add server/apps/pipelines/stages/alignment.py tests/test_apps/test_pipelines/test_stages/test_alignment.py
git commit -m "fix(pipelines): strip audio tags before submitting text for forced alignment"
```

---

### Task 3: Bump ElevenLabs TTS client default model to `eleven_v3`

**Files:**
- Modify: `server/apps/generation/clients/elevenlabs.py:27`
- Test: `tests/test_apps/test_generation/test_clients.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_apps/test_generation/test_clients.py`:

```python
def test_elevenlabs_synthesize_defaults_to_v3_model() -> None:
    """synthesize() sends model_id=eleven_v3 when the caller doesn't override it."""
    import httpx

    from server.apps.generation.clients.elevenlabs import synthesize

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.content = b'fake-mp3-data'

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ) as mock_post:
            await synthesize('Hello world', voice_id='xyz', api_key='key')
            _, kwargs = mock_post.call_args
            return kwargs['json']

    body = asyncio.run(_inner())
    assert body['model_id'] == 'eleven_v3'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_clients.py::test_elevenlabs_synthesize_defaults_to_v3_model -v`
Expected: FAIL — `body['model_id'] == 'eleven_multilingual_v2'`

- [ ] **Step 3: Implement the fix**

In `server/apps/generation/clients/elevenlabs.py`, change:

```python
async def synthesize(
    text: str,
    voice_id: str,
    api_key: str,
    model_id: str = 'eleven_multilingual_v2',
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bytes:
```

to:

```python
async def synthesize(
    text: str,
    voice_id: str,
    api_key: str,
    model_id: str = 'eleven_v3',
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bytes:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_clients.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add server/apps/generation/clients/elevenlabs.py tests/test_apps/test_generation/test_clients.py
git commit -m "feat(generation): default ElevenLabs TTS synthesis to eleven_v3"
```

---

### Task 4: `script_prompts.py` constants + `script.py` fallback update

**Files:**
- Create: `server/apps/prompts/logic/script_prompts.py`
- Modify: `server/apps/pipelines/stages/script.py`

**Interfaces:**
- Produces: `SCRIPT_TEMPLATE_KEY`, `SCRIPT_TEMPLATE_NAME`, `SCRIPT_TEMPLATE_DESCRIPTION`, `SCRIPT_SYSTEM_PROMPT`, `SCRIPT_USER_PROMPT` (module-level `str` constants in `server.apps.prompts.logic.script_prompts`) — consumed by Task 5's `seed_script_prompt` command.

There is no dedicated test for this task. Both `_sys` (the system-prompt hook) and the `_generate_script` fallback already run — unasserted — under the existing `test_script.py` suite, whose `_make_ctx()` sets `ctx.prompts.render = AsyncMock(return_value=('', ''))`. This mirrors the established convention in `editor_brief.py`, where the in-code fallback string is likewise a separate, untested-by-content literal (`# pragma: no cover` on the system-prompt hook). Verification for this task is running the existing suite to confirm nothing breaks.

- [ ] **Step 1: Create the prompt constants file**

```python
"""Canonical script PromptVersion text (seed + management command)."""

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

Save as `server/apps/prompts/logic/script_prompts.py`.

- [ ] **Step 2: Update `script.py`'s fallback strings**

In `server/apps/pipelines/stages/script.py`, in the `_agent()` function's `_sys` hook, change:

```python
        return sys or (
            'You are a professional documentary script writer. '
            'No greetings. Short sentences. Curiosity gaps at chapter ends. '
            'First 30s hooks must restate the core payoff.'
        )
```

to:

```python
        return sys or (
            'You are a professional documentary script writer. '
            'No greetings. Short sentences. Curiosity gaps at chapter ends. '
            'First 30s hooks must restate the core payoff. Synthesis uses '
            'ElevenLabs v3 — use [sighs]/[whispers]-style audio tags '
            'sparingly for genuine emotion, and ellipses/punctuation for '
            'pacing instead of <break> tags or [pause].'
        )
```

In `_generate_script`, change:

```python
    base_user_prompt = usr or (
        f'Write the full script for "{ctx.run.topic}".\n'
        f'Chapters: {chapters}\n'
        f'Research: {research.get("brief", {})}\n'
        f'Target WPM: {wpm}. '
        f'Include a closing_line per chapter for continuity. '
        f'For every chapter also write commentary: 1-3 sentences of '
        f'genuine analysis or a stated opinion — not a restatement of '
        f'the narration — that reflects a real editorial point of view '
        f'on the material.'
    )
```

Leave this fallback as-is — it already delegates emotional-delivery guidance to the system prompt above, and the spec's Task 5 seed command is what makes the full guidance the *active* prompt in any real environment.

- [ ] **Step 3: Run the existing script stage suite to confirm no regression**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_script.py -v`
Expected: PASS (all tests, unchanged count)

- [ ] **Step 4: Commit**

```bash
git add server/apps/prompts/logic/script_prompts.py server/apps/pipelines/stages/script.py
git commit -m "feat(prompts): add ElevenLabs v3 audio-tag guidance to the script prompt"
```

---

### Task 5: `seed_script_prompt` management command

**Files:**
- Create: `server/apps/prompts/management/commands/seed_script_prompt.py`
- Test: `tests/test_apps/test_prompts/test_seed_script_prompt.py`

**Interfaces:**
- Consumes: `SCRIPT_TEMPLATE_KEY`, `SCRIPT_TEMPLATE_NAME`, `SCRIPT_TEMPLATE_DESCRIPTION`, `SCRIPT_SYSTEM_PROMPT`, `SCRIPT_USER_PROMPT` from Task 4.

This command is a structural copy of `server/apps/prompts/management/commands/seed_editor_brief_prompt.py` with the editor_brief names swapped for script — same idempotent create/version/activate behavior.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for seed_script_prompt management command."""

import pytest
from django.core.management import call_command

from server.apps.generation.logic.model_resolver import STAGE_MODEL_DEFAULTS
from server.apps.prompts.logic.script_prompts import (
    SCRIPT_SYSTEM_PROMPT,
    SCRIPT_TEMPLATE_KEY,
    SCRIPT_USER_PROMPT,
)
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
)


@pytest.mark.django_db
def test_seeds_active_script_version() -> None:
    call_command('seed_script_prompt')
    template = PromptTemplate.objects.get(key=SCRIPT_TEMPLATE_KEY)
    active = PromptVersion.objects.filter(template=template, is_active=True)
    assert active.count() == 1
    version = active.get()
    assert version.system_prompt == SCRIPT_SYSTEM_PROMPT
    assert version.user_prompt == SCRIPT_USER_PROMPT
    assert '{{ topic }}' in version.user_prompt
    assert 'eleven_v3' in version.system_prompt
    assert version.model == STAGE_MODEL_DEFAULTS['script']


@pytest.mark.django_db
def test_command_is_idempotent() -> None:
    call_command('seed_script_prompt')
    call_command('seed_script_prompt')
    assert (
        PromptTemplate.objects.filter(key=SCRIPT_TEMPLATE_KEY).count() == 1
    )
    assert (
        PromptVersion.objects.filter(
            template__key=SCRIPT_TEMPLATE_KEY,
            system_prompt=SCRIPT_SYSTEM_PROMPT,
        ).count()
        == 1
    )
    assert (
        PromptVersion.objects.filter(
            template__key=SCRIPT_TEMPLATE_KEY,
            is_active=True,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_creates_new_version_when_old_text_differs() -> None:
    template = PromptTemplate.objects.create(
        key=SCRIPT_TEMPLATE_KEY,
        name='Narration Script',
        scope=PromptScope.GLOBAL,
    )
    PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='old system',
        user_prompt='old user',
        is_active=True,
    )
    call_command('seed_script_prompt')
    assert PromptVersion.objects.filter(template=template).count() == 2
    active = PromptVersion.objects.get(template=template, is_active=True)
    assert active.version == 2
    assert active.system_prompt == SCRIPT_SYSTEM_PROMPT
    old = PromptVersion.objects.get(template=template, version=1)
    assert old.is_active is False
```

Save as `tests/test_apps/test_prompts/test_seed_script_prompt.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_apps/test_prompts/test_seed_script_prompt.py -v`
Expected: FAIL with `CommandError: Unknown command: 'seed_script_prompt'`

- [ ] **Step 3: Write the command**

```python
"""Create/activate the script PromptVersion (idempotent)."""

from typing import override

from django.core.management.base import BaseCommand
from django.db import transaction

from server.apps.generation.logic.constants import DEFAULT_LLM_MODEL
from server.apps.generation.logic.model_resolver import STAGE_MODEL_DEFAULTS
from server.apps.prompts.logic.script_prompts import (
    SCRIPT_SYSTEM_PROMPT,
    SCRIPT_TEMPLATE_DESCRIPTION,
    SCRIPT_TEMPLATE_KEY,
    SCRIPT_TEMPLATE_NAME,
    SCRIPT_USER_PROMPT,
)
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
)


class Command(BaseCommand):
    """Ensure script has an active PromptVersion operators can edit."""

    help = (
        'Create (if needed) and activate the script PromptVersion for '
        'narration script generation.'
    )

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Upsert template and activate matching prompt text."""
        template, created = PromptTemplate.objects.update_or_create(
            key=SCRIPT_TEMPLATE_KEY,
            defaults={
                'name': SCRIPT_TEMPLATE_NAME,
                'scope': PromptScope.GLOBAL,
                'description': SCRIPT_TEMPLATE_DESCRIPTION,
            },
        )
        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(f'{action} template: {template.key}'),
        )

        matching = (
            PromptVersion.objects
            .filter(
                template=template,
                system_prompt=SCRIPT_SYSTEM_PROMPT,
                user_prompt=SCRIPT_USER_PROMPT,
            )
            .order_by('-version')
            .first()
        )
        if matching is not None:
            self._activate(template, matching)
            self.stdout.write(
                self.style.SUCCESS(
                    f'Activated existing {template.key} v{matching.version} '
                    f'(id={matching.id}).',
                ),
            )
            return

        latest = (
            PromptVersion.objects
            .filter(template=template)
            .order_by('-version')
            .values_list('version', flat=True)
            .first()
        )
        next_version = (latest or 0) + 1
        model = STAGE_MODEL_DEFAULTS.get(SCRIPT_TEMPLATE_KEY, DEFAULT_LLM_MODEL)
        with transaction.atomic():
            PromptVersion.objects.filter(template=template).update(
                is_active=False,
            )
            version = PromptVersion.objects.create(
                template=template,
                version=next_version,
                system_prompt=SCRIPT_SYSTEM_PROMPT,
                user_prompt=SCRIPT_USER_PROMPT,
                model=model,
                temperature=1.0,
                max_tokens=8192,
                is_active=True,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f'Created and activated {template.key} v{version.version} '
                f'(id={version.id}).',
            ),
        )

    def _activate(
        self,
        template: PromptTemplate,
        version: PromptVersion,
    ) -> None:
        """Deactivate all versions of this template, then activate one."""
        with transaction.atomic():
            PromptVersion.objects.filter(template=template).update(
                is_active=False,
            )
            version.is_active = True
            version.save(update_fields=['is_active'])
```

Save as `server/apps/prompts/management/commands/seed_script_prompt.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_apps/test_prompts/test_seed_script_prompt.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add server/apps/prompts/management/commands/seed_script_prompt.py tests/test_apps/test_prompts/test_seed_script_prompt.py
git commit -m "feat(prompts): add seed_script_prompt management command"
```

This completes the Django-side half (Sections A and B of the spec). The
remaining tasks build the standalone tool (Section C) and have no
dependency on Tasks 1-5.

---

### Task 6: `scripts/elevenlabs/audio_tags.py` (standalone)

**Files:**
- Create: `scripts/elevenlabs/__init__.py`
- Create: `scripts/elevenlabs/audio_tags.py`
- Test: `tests/test_scripts/test_elevenlabs/__init__.py`
- Test: `tests/test_scripts/test_elevenlabs/test_audio_tags.py`

**Interfaces:**
- Produces: `strip_audio_tags(text: str) -> str` in `scripts.elevenlabs.audio_tags` — a standalone duplicate of Task 1's function (deliberately not imported from `server.apps...`, so the tool has zero Django dependency). Consumed by Task 10 (`run_tts.py`).

- [ ] **Step 1: Create empty package markers**

```bash
mkdir -p scripts/elevenlabs
touch scripts/elevenlabs/__init__.py
mkdir -p tests/test_scripts/test_elevenlabs
touch tests/test_scripts/test_elevenlabs/__init__.py
```

- [ ] **Step 2: Write the failing tests**

```python
"""Tests for the standalone strip_audio_tags()."""

from scripts.elevenlabs.audio_tags import strip_audio_tags


def test_strip_audio_tags_no_tags_returns_text_unchanged() -> None:
    """Text with no tags passes through untouched."""
    assert strip_audio_tags('Rome was great once.') == 'Rome was great once.'


def test_strip_audio_tags_removes_single_tag() -> None:
    """A single bracket tag is removed."""
    result = strip_audio_tags('[sighs] Rome was great once.')
    assert result == 'Rome was great once.'


def test_strip_audio_tags_removes_multiple_tags() -> None:
    """Multiple tags across the text are all removed."""
    result = strip_audio_tags(
        '[whispers] Rome was great once. [sighs] Then it fell.',
    )
    assert result == 'Rome was great once. Then it fell.'


def test_strip_audio_tags_drops_tag_only_line() -> None:
    """A line that is only a tag disappears entirely, not a blank line."""
    result = strip_audio_tags('Rome was great once.\n[Pause]\nThen it fell.')
    assert result == 'Rome was great once.\nThen it fell.'
```

Save as `tests/test_scripts/test_elevenlabs/test_audio_tags.py`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_audio_tags.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.elevenlabs.audio_tags'`

- [ ] **Step 4: Write the implementation**

```python
"""Strip ElevenLabs v3 [bracket] audio/emotion tags from narration text.

Standalone copy of server/apps/pipelines/logic/audio_tags.py — this
module intentionally has zero Django dependency so scripts/elevenlabs/
can run without bootstrapping the Django app.
"""

import re

_TAG_RE = re.compile(r'\[[^\]\n]{1,60}\]')
_WS_RE = re.compile(r'[ \t]{2,}')


def strip_audio_tags(text: str) -> str:
    """Remove [bracket] audio/emotion tags, collapsing extra whitespace."""
    without_tags = _TAG_RE.sub('', text)
    lines = [
        _WS_RE.sub(' ', line).strip() for line in without_tags.splitlines()
    ]
    return '\n'.join(line for line in lines if line)
```

Save as `scripts/elevenlabs/audio_tags.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_audio_tags.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add scripts/elevenlabs/__init__.py scripts/elevenlabs/audio_tags.py tests/test_scripts/test_elevenlabs/
git commit -m "feat(scripts): add standalone elevenlabs tag-stripping helper"
```

---

### Task 7: `scripts/elevenlabs/captions.py`

**Files:**
- Create: `scripts/elevenlabs/captions.py`
- Test: `tests/test_scripts/test_elevenlabs/test_captions.py`

**Interfaces:**
- Produces:
  - `normalize_words(words_raw: list[dict[str, object]]) -> list[dict[str, object]]` — maps ElevenLabs forced-alignment `words` entries to `{word, start, end}`, dropping whitespace-only tokens.
  - `chunk_words_into_cues(words: list[dict[str, object]], chunk_size: int = 4) -> list[dict[str, object]]` — groups words into `{start, end, text}` cues.
  - `fmt_srt_time(seconds: float) -> str` — `HH:MM:SS,mmm`.
  - `build_srt(cues: list[dict[str, object]]) -> bytes` — SRT file bytes.
  All consumed by Task 10 (`run_tts.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for scripts/elevenlabs/captions.py."""

from scripts.elevenlabs.captions import (
    build_srt,
    chunk_words_into_cues,
    fmt_srt_time,
    normalize_words,
)


def test_normalize_words_maps_text_field_to_word() -> None:
    raw = [{'text': 'Rome', 'start': 0.0, 'end': 0.4, 'loss': 0.1}]
    assert normalize_words(raw) == [
        {'word': 'Rome', 'start': 0.0, 'end': 0.4},
    ]


def test_normalize_words_drops_whitespace_only_tokens() -> None:
    raw = [
        {'text': 'Rome', 'start': 0.0, 'end': 0.4},
        {'text': ' ', 'start': 0.4, 'end': 0.42},
        {'text': 'fell', 'start': 0.42, 'end': 0.8},
    ]
    result = normalize_words(raw)
    assert [w['word'] for w in result] == ['Rome', 'fell']


def test_chunk_words_into_cues_groups_by_chunk_size() -> None:
    words = [
        {'word': 'Rome', 'start': 0.0, 'end': 0.4},
        {'word': 'was', 'start': 0.4, 'end': 0.6},
        {'word': 'great', 'start': 0.6, 'end': 1.0},
        {'word': 'once', 'start': 1.0, 'end': 1.4},
        {'word': 'Then', 'start': 1.4, 'end': 1.6},
    ]
    cues = chunk_words_into_cues(words, chunk_size=4)
    assert len(cues) == 2
    assert cues[0] == {'start': 0.0, 'end': 1.4, 'text': 'Rome was great once'}
    assert cues[1] == {'start': 1.4, 'end': 1.6, 'text': 'Then'}


def test_fmt_srt_time_formats_hours_minutes_seconds_millis() -> None:
    assert fmt_srt_time(3725.123) == '01:02:05,123'


def test_fmt_srt_time_carries_rounding_overflow() -> None:
    assert fmt_srt_time(1.9996) == '00:00:02,000'


def test_build_srt_produces_numbered_blocks() -> None:
    cues = [
        {'start': 0.0, 'end': 1.4, 'text': 'Rome was great once'},
        {'start': 1.4, 'end': 1.6, 'text': 'Then'},
    ]
    srt = build_srt(cues).decode()
    assert srt == (
        '1\n00:00:00,000 --> 00:00:01,400\nRome was great once\n\n'
        '2\n00:00:01,400 --> 00:00:01,600\nThen'
    )
```

Save as `tests/test_scripts/test_elevenlabs/test_captions.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_captions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.elevenlabs.captions'`

- [ ] **Step 3: Write the implementation**

```python
"""Word timings -> chunked SRT caption cues.

Mirrors the cue-chunking and SRT time-format conventions used by
server/apps/pipelines/stages/alignment.py, kept as a standalone
duplicate so this tool has zero Django dependency.
"""

from typing import Any

_DEFAULT_CHUNK_WORDS = 4


def normalize_words(
    words_raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map ElevenLabs forced-alignment words to {word, start, end}.

    Whitespace-only tokens are dropped — forced alignment emits them
    between words.
    """
    mapped: list[dict[str, Any]] = []
    for w in words_raw:
        token = str(w.get('text', w.get('word', '')))
        if not token.strip():
            continue
        mapped.append({
            'word': token,
            'start': float(w.get('start', 0)),
            'end': float(w.get('end', 0)),
        })
    return mapped


def chunk_words_into_cues(
    words: list[dict[str, Any]],
    chunk_size: int = _DEFAULT_CHUNK_WORDS,
) -> list[dict[str, Any]]:
    """Split word timings into short subtitle cues (start/end/text)."""
    cues: list[dict[str, Any]] = []
    for start_i in range(0, len(words), chunk_size):
        chunk = words[start_i : start_i + chunk_size]
        texts = [str(w.get('word', '')).strip() for w in chunk]
        text = ' '.join(t for t in texts if t)
        if not text:
            continue
        cues.append({
            'start': float(chunk[0]['start']),
            'end': float(chunk[-1]['end']),
            'text': text,
        })
    return cues


def fmt_srt_time(seconds: float) -> str:
    """Format seconds as SRT's HH:MM:SS,mmm, carrying rounding overflow."""
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}'


def build_srt(cues: list[dict[str, Any]]) -> bytes:
    """Build a standard SRT file from a list of {start, end, text} cues."""
    blocks: list[str] = []
    for i, cue in enumerate(cues, start=1):
        start = fmt_srt_time(float(cue['start']))
        end = fmt_srt_time(float(cue['end']))
        text = str(cue['text']).strip()
        blocks.append(f'{i}\n{start} --> {end}\n{text}')
    return '\n\n'.join(blocks).encode()
```

Save as `scripts/elevenlabs/captions.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_captions.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/elevenlabs/captions.py tests/test_scripts/test_elevenlabs/test_captions.py
git commit -m "feat(scripts): add caption cue chunking and SRT builder"
```

---

### Task 8: `scripts/elevenlabs/script_source.py`

**Files:**
- Create: `scripts/elevenlabs/script_source.py`
- Test: `tests/test_scripts/test_elevenlabs/test_script_source.py`

**Interfaces:**
- Produces:
  - `ScriptChapter` — frozen dataclass with `idx: int`, `title: str`, `text: str`.
  - `load_chapters(path: Path) -> list[ScriptChapter]` — parses `.json` (list of `{idx, title, text}`) or `.md`/`.txt` (`## Chapter N: Title` headers, matching `server/apps/pipelines/stages/package_zip.py::_script_markdown()`'s output format exactly).
  Both consumed by Task 10 (`run_tts.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for scripts/elevenlabs/script_source.py."""

import json
from pathlib import Path

from scripts.elevenlabs.script_source import ScriptChapter, load_chapters


def test_load_chapters_from_markdown(tmp_path: Path) -> None:
    script_path = tmp_path / 'script.md'
    script_path.write_text(
        '# Script\n\n'
        '## Chapter 1: Night Opening\n\n'
        'You are tired of holding yourself against the world.\n\n'
        '## Chapter 2: Teaching Parable\n\n'
        '[sighs] Nothing is softer than water.\n',
    )
    chapters = load_chapters(script_path)
    assert chapters == [
        ScriptChapter(
            idx=1,
            title='Night Opening',
            text='You are tired of holding yourself against the world.',
        ),
        ScriptChapter(
            idx=2,
            title='Teaching Parable',
            text='[sighs] Nothing is softer than water.',
        ),
    ]


def test_load_chapters_from_markdown_with_no_headers_is_one_chapter(
    tmp_path: Path,
) -> None:
    script_path = tmp_path / 'script.txt'
    script_path.write_text('Just plain narration, no chapter headers.')
    chapters = load_chapters(script_path)
    assert chapters == [
        ScriptChapter(
            idx=1,
            title='',
            text='Just plain narration, no chapter headers.',
        ),
    ]


def test_load_chapters_from_json(tmp_path: Path) -> None:
    script_path = tmp_path / 'script.json'
    script_path.write_text(
        json.dumps([
            {'idx': 1, 'title': 'Night Opening', 'text': 'You are tired.'},
            {'idx': 2, 'title': 'Parable', 'text': '[sighs] Water.'},
        ]),
    )
    chapters = load_chapters(script_path)
    assert chapters == [
        ScriptChapter(idx=1, title='Night Opening', text='You are tired.'),
        ScriptChapter(idx=2, title='Parable', text='[sighs] Water.'),
    ]
```

Save as `tests/test_scripts/test_elevenlabs/test_script_source.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_script_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.elevenlabs.script_source'`

- [ ] **Step 3: Write the implementation**

```python
"""Parse an exported script file into ordered chapters."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

_CHAPTER_RE = re.compile(r'^##\s*Chapter\s+(\d+)\s*:\s*(.*)$', re.MULTILINE)


@dataclass(frozen=True)
class ScriptChapter:
    """One chapter of narration text, ready for TTS."""

    idx: int
    title: str
    text: str


def load_chapters(path: Path) -> list[ScriptChapter]:
    """Load ordered chapters from a .json or .md/.txt script file."""
    if path.suffix.lower() == '.json':
        return _load_json_chapters(path)
    return _load_markdown_chapters(path)


def _load_json_chapters(path: Path) -> list[ScriptChapter]:
    """Load chapters from a JSON list of {idx, title, text} objects."""
    data = json.loads(path.read_text(encoding='utf-8'))
    return [
        ScriptChapter(
            idx=int(item['idx']),
            title=str(item.get('title', '')),
            text=str(item['text']),
        )
        for item in data
    ]


def _load_markdown_chapters(path: Path) -> list[ScriptChapter]:
    """Load chapters from '## Chapter N: Title' markdown headers.

    A file with no matching headers is treated as a single chapter.
    """
    content = path.read_text(encoding='utf-8')
    matches = list(_CHAPTER_RE.finditer(content))
    if not matches:
        text = content.strip()
        return [ScriptChapter(idx=1, title='', text=text)] if text else []

    chapters: list[ScriptChapter] = []
    for i, match in enumerate(matches):
        idx = int(match.group(1))
        title = match.group(2).strip()
        body_start = match.end()
        body_end = (
            matches[i + 1].start() if i + 1 < len(matches) else len(content)
        )
        text = content[body_start:body_end].strip()
        chapters.append(ScriptChapter(idx=idx, title=title, text=text))
    return chapters
```

Save as `scripts/elevenlabs/script_source.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_script_source.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/elevenlabs/script_source.py tests/test_scripts/test_elevenlabs/test_script_source.py
git commit -m "feat(scripts): add script.md/script.json chapter parser"
```

---

### Task 9: `scripts/elevenlabs/client.py`

**Files:**
- Create: `scripts/elevenlabs/client.py`
- Test: `tests/test_scripts/test_elevenlabs/test_client.py`

**Interfaces:**
- Produces:
  - `async def synthesize(*, text: str, voice_id: str, api_key: str, model_id: str = 'eleven_v3', stability: float = 0.5, similarity_boost: float = 0.75) -> bytes`
  - `async def force_align(*, audio_bytes: bytes, text: str, api_key: str) -> dict[str, object]`
  Both consumed by Task 10 (`run_tts.py`). Raises `RuntimeError` on a non-2xx response from either call.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for scripts/elevenlabs/client.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scripts.elevenlabs.client import force_align, synthesize


def test_synthesize_returns_audio_bytes_on_success() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.content = b'fake-mp3-data'

    async def _inner() -> bytes:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await synthesize(
                text='Hello world',
                voice_id='xyz',
                api_key='key',
            )

    assert asyncio.run(_inner()) == b'fake-mp3-data'


def test_synthesize_sends_v3_model_by_default() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.content = b'audio'

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ) as mock_post:
            await synthesize(text='Hi', voice_id='xyz', api_key='key')
            _, kwargs = mock_post.call_args
            return kwargs['json']

    body = asyncio.run(_inner())
    assert body['model_id'] == 'eleven_v3'


def test_synthesize_raises_runtime_error_on_failure() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 422
    mock_resp.text = 'invalid voice_id'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await synthesize(text='Hi', voice_id='bad', api_key='key')

    with pytest.raises(RuntimeError, match='422'):
        asyncio.run(_inner())


def test_force_align_returns_parsed_json_on_success() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'words': [{'text': 'Hi', 'start': 0.0, 'end': 0.3}]}

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await force_align(
                audio_bytes=b'fake-audio',
                text='Hi',
                api_key='key',
            )

    result = asyncio.run(_inner())
    assert result == {'words': [{'text': 'Hi', 'start': 0.0, 'end': 0.3}]}


def test_force_align_raises_runtime_error_on_failure() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 500
    mock_resp.text = 'server error'

    async def _inner() -> None:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            await force_align(audio_bytes=b'x', text='Hi', api_key='key')

    with pytest.raises(RuntimeError, match='500'):
        asyncio.run(_inner())
```

Save as `tests/test_scripts/test_elevenlabs/test_client.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.elevenlabs.client'`

- [ ] **Step 3: Write the implementation**

```python
"""Raw httpx client for ElevenLabs TTS + forced alignment (standalone).

Mirrors server/apps/generation/clients/elevenlabs.py's approach (raw
HTTP, no SDK) but kept independent so this tool has zero Django
dependency and no retry/queueing behavior — it's a manual, low-volume
tool; just re-run it on failure.
"""

import httpx

_BASE = 'https://api.elevenlabs.io/v1'


async def synthesize(
    *,
    text: str,
    voice_id: str,
    api_key: str,
    model_id: str = 'eleven_v3',
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bytes:
    """Synthesize text to audio via ElevenLabs. Returns raw MP3 bytes."""
    async with httpx.AsyncClient(timeout=120.0) as http_client:
        resp = await http_client.post(
            f'{_BASE}/text-to-speech/{voice_id}',
            headers={
                'xi-api-key': api_key,
                'Content-Type': 'application/json',
                'Accept': 'audio/mpeg',
            },
            json={
                'text': text,
                'model_id': model_id,
                'voice_settings': {
                    'stability': stability,
                    'similarity_boost': similarity_boost,
                },
            },
        )
    _raise_for_status(resp)
    return resp.content


async def force_align(
    *,
    audio_bytes: bytes,
    text: str,
    api_key: str,
) -> dict[str, object]:
    """Force-align audio to a known transcript via ElevenLabs.

    Returns {words: [{text, start, end, loss}, ...], characters: [...],
    loss}.
    """
    async with httpx.AsyncClient(timeout=600.0) as http_client:
        resp = await http_client.post(
            f'{_BASE}/forced-alignment',
            headers={'xi-api-key': api_key},
            data={'text': text},
            files={'file': ('audio.mp3', audio_bytes, 'audio/mpeg')},
        )
    _raise_for_status(resp)
    result: dict[str, object] = resp.json()
    return result


def _raise_for_status(resp: httpx.Response) -> None:
    """Raise RuntimeError with status + body snippet on a bad response."""
    if not resp.is_success:
        msg = f'ElevenLabs {resp.status_code}: {resp.text[:300]}'
        raise RuntimeError(msg)
```

Save as `scripts/elevenlabs/client.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_client.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/elevenlabs/client.py tests/test_scripts/test_elevenlabs/test_client.py
git commit -m "feat(scripts): add standalone ElevenLabs TTS + forced-alignment client"
```

---

### Task 10: `scripts/elevenlabs/run_tts.py` orchestration + README + `.gitignore`

**Files:**
- Create: `scripts/elevenlabs/run_tts.py`
- Create: `scripts/elevenlabs/README.md`
- Modify: `.gitignore`
- Test: `tests/test_scripts/test_elevenlabs/test_run_tts.py`

**Interfaces:**
- Consumes:
  - `strip_audio_tags(text: str) -> str` (Task 6)
  - `normalize_words`, `chunk_words_into_cues`, `build_srt` (Task 7)
  - `ScriptChapter`, `load_chapters(path: Path) -> list[ScriptChapter]` (Task 8)
  - `synthesize(*, text, voice_id, api_key, model_id, stability, similarity_boost) -> bytes`, `force_align(*, audio_bytes, text, api_key) -> dict[str, object]` (Task 9)
- Produces: `main() -> None` (async), the run's output directory layout described below. This is the final task — nothing depends on it.

Output per run:
```
scripts/elevenlabs/runs/<run-name>/
  audio/ch_001.mp3, ch_002.mp3, ...
  captions/captions.srt
  captions/words.json
  manifest.json
```

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for scripts/elevenlabs/run_tts.py."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.elevenlabs import run_tts


def _fa_result() -> dict[str, object]:
    """A 2-word forced-alignment result, chapter-relative (starts at 0).

    ElevenLabs aligns each chapter's audio file independently, so every
    raw result starts near 0 regardless of where the chapter sits in
    the full run — run_tts.py's own offset_s bookkeeping is what places
    it on the master timeline. Both mocked chapters reuse this same
    chapter-relative result on purpose.
    """
    return {
        'words': [
            {'text': 'word', 'start': 0.0, 'end': 0.4},
            {'text': 'two', 'start': 0.4, 'end': 0.8},
        ],
    }


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test sets its own config; nothing leaks between tests."""
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setattr(run_tts, 'VOICE_ID', 'voice-123')
    monkeypatch.setattr(run_tts, 'RUN_NAME', 'test-run')


def test_main_writes_audio_captions_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = tmp_path / 'script.md'
    script_path.write_text(
        '## Chapter 1: Opening\n\nFirst chapter text.\n\n'
        '## Chapter 2: Middle\n\nSecond chapter text.\n',
    )
    out_dir = tmp_path / 'runs'
    monkeypatch.setattr(run_tts, 'SCRIPT_PATH', script_path)
    monkeypatch.setattr(run_tts, 'OUT_DIR', out_dir)

    async def _inner() -> None:
        with (
            patch.object(
                run_tts,
                'synthesize',
                new=AsyncMock(side_effect=[b'audio-ch1', b'audio-ch2']),
            ),
            patch.object(
                run_tts,
                'force_align',
                new=AsyncMock(
                    side_effect=[_fa_result(), _fa_result()],
                ),
            ),
        ):
            await run_tts.main()

    asyncio.run(_inner())

    run_dir = out_dir / 'test-run'
    assert (run_dir / 'audio' / 'ch_001.mp3').read_bytes() == b'audio-ch1'
    assert (run_dir / 'audio' / 'ch_002.mp3').read_bytes() == b'audio-ch2'

    words = json.loads((run_dir / 'captions' / 'words.json').read_text())
    assert [w['word'] for w in words] == ['word', 'two', 'word', 'two']
    # Chapter 2's words are offset past chapter 1's 0.8s span.
    assert words[2]['start'] == pytest.approx(0.8)

    srt = (run_dir / 'captions' / 'captions.srt').read_text()
    assert 'word two word two' in srt

    manifest = json.loads((run_dir / 'manifest.json').read_text())
    assert manifest['voice_id'] == 'voice-123'
    assert manifest['model_id'] == 'eleven_v3'
    assert manifest['chapter_char_counts'] == {
        'ch_001': len('First chapter text.'),
        'ch_002': len('Second chapter text.'),
    }


def test_main_raises_without_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    monkeypatch.setattr(run_tts, 'SCRIPT_PATH', tmp_path / 'script.md')
    (tmp_path / 'script.md').write_text('Some text.')

    with pytest.raises(RuntimeError, match='ELEVENLABS_API_KEY'):
        asyncio.run(run_tts.main())


def test_main_raises_without_voice_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_tts, 'VOICE_ID', '')
    monkeypatch.setattr(run_tts, 'SCRIPT_PATH', tmp_path / 'script.md')
    (tmp_path / 'script.md').write_text('Some text.')

    with pytest.raises(RuntimeError, match='VOICE_ID'):
        asyncio.run(run_tts.main())
```

Save as `tests/test_scripts/test_elevenlabs/test_run_tts.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_run_tts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.elevenlabs.run_tts'`

- [ ] **Step 3: Write the implementation**

```python
"""Manual ElevenLabs v3 TTS + captions tool.

Run directly: `python scripts/elevenlabs/run_tts.py`. Edit the config
block below before each run — there are no CLI flags. Reads
ELEVENLABS_API_KEY from the environment (never hardcode it here).
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from scripts.elevenlabs.audio_tags import strip_audio_tags
from scripts.elevenlabs.captions import (
    build_srt,
    chunk_words_into_cues,
    normalize_words,
)
from scripts.elevenlabs.client import force_align, synthesize
from scripts.elevenlabs.script_source import ScriptChapter, load_chapters

# --- Configure before running ---
SCRIPT_PATH = Path('run_0b0237ce_longform_editor_package/docs/script.md')
VOICE_ID = ''
RUN_NAME: str | None = None  # None -> derived from script filename + time
OUT_DIR = Path('scripts/elevenlabs/runs')
MODEL_ID = 'eleven_v3'
STABILITY = 0.5
SIMILARITY_BOOST = 0.75
CHUNK_WORDS = 4
# ---------------------------------


def _resolve_run_dir() -> Path:
    """Return this run's output directory, deriving a name if unset."""
    name = RUN_NAME or (
        f'{SCRIPT_PATH.stem}_{datetime.now(UTC):%Y%m%d%H%M%S}'
    )
    return OUT_DIR / name


async def _process_chapter(
    chapter: ScriptChapter,
    *,
    api_key: str,
    run_dir: Path,
    offset_s: float,
) -> tuple[list[dict[str, object]], float, int]:
    """Synthesize + align one chapter.

    Returns (offset word timings, this chapter's duration in seconds,
    character count of the tagged narration sent to TTS).
    """
    audio_bytes = await synthesize(
        text=chapter.text,
        voice_id=VOICE_ID,
        api_key=api_key,
        model_id=MODEL_ID,
        stability=STABILITY,
        similarity_boost=SIMILARITY_BOOST,
    )
    audio_path = run_dir / 'audio' / f'ch_{chapter.idx:03d}.mp3'
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(audio_bytes)

    clean_text = strip_audio_tags(chapter.text)
    alignment = await force_align(
        audio_bytes=audio_bytes,
        text=clean_text,
        api_key=api_key,
    )
    raw_words = alignment.get('words', [])
    words = normalize_words(raw_words if isinstance(raw_words, list) else [])
    offset_words = [
        {**w, 'start': w['start'] + offset_s, 'end': w['end'] + offset_s}
        for w in words
    ]
    span = max((float(w['end']) for w in words), default=0.0)
    return offset_words, span, len(chapter.text)


async def main() -> None:
    """Run the configured chapters through TTS + forced alignment."""
    api_key = os.environ.get('ELEVENLABS_API_KEY', '')
    if not api_key:
        msg = 'ELEVENLABS_API_KEY environment variable is not set'
        raise RuntimeError(msg)
    if not VOICE_ID:
        msg = 'Set VOICE_ID in the config block before running'
        raise RuntimeError(msg)

    chapters = load_chapters(SCRIPT_PATH)
    if not chapters:
        msg = f'No chapters found in {SCRIPT_PATH}'
        raise RuntimeError(msg)

    run_dir = _resolve_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    all_words: list[dict[str, object]] = []
    offset_s = 0.0
    char_counts: dict[str, int] = {}
    for chapter in chapters:
        offset_words, span, char_count = await _process_chapter(
            chapter,
            api_key=api_key,
            run_dir=run_dir,
            offset_s=offset_s,
        )
        all_words.extend(offset_words)
        offset_s += span
        char_counts[f'ch_{chapter.idx:03d}'] = char_count

    captions_dir = run_dir / 'captions'
    captions_dir.mkdir(parents=True, exist_ok=True)
    cues = chunk_words_into_cues(all_words, chunk_size=CHUNK_WORDS)
    (captions_dir / 'captions.srt').write_bytes(build_srt(cues))
    (captions_dir / 'words.json').write_text(json.dumps(all_words, indent=2))

    manifest = {
        'script_path': str(SCRIPT_PATH),
        'voice_id': VOICE_ID,
        'model_id': MODEL_ID,
        'stability': STABILITY,
        'similarity_boost': SIMILARITY_BOOST,
        'chapter_char_counts': char_counts,
        'generated_at': datetime.now(UTC).isoformat(),
    }
    (run_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'Wrote run to {run_dir}')  # noqa: T201


if __name__ == '__main__':
    asyncio.run(main())
```

Save as `scripts/elevenlabs/run_tts.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest tests/test_scripts/test_elevenlabs/test_run_tts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Add the README**

```markdown
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
```

Save as `scripts/elevenlabs/README.md`.

- [ ] **Step 6: Add the `.gitignore` entry**

Add to `.gitignore` (near the other generated-output entries):

```
scripts/elevenlabs/runs/
```

- [ ] **Step 7: Commit**

```bash
git add scripts/elevenlabs/run_tts.py scripts/elevenlabs/README.md tests/test_scripts/test_elevenlabs/test_run_tts.py .gitignore
git commit -m "feat(scripts): add run_tts.py orchestration, README, and .gitignore entry"
```

---

## Final verification

- [ ] Run the full Django suite: `docker compose exec web pytest`
  Expected: PASS, 100% coverage maintained.
- [ ] Run the standalone tool's tests explicitly (already part of the
  full suite above, called out for visibility):
  `docker compose exec web pytest tests/test_scripts/ -v`
  Expected: PASS.
- [ ] `docker compose exec web ruff check .`
  Expected: no errors (fix any flagged in `scripts/elevenlabs/*.py` —
  the most likely findings are missing trailing commas or line length;
  fix inline, don't suppress).
- [ ] `docker compose exec web ruff format --check .`
  Expected: no errors.
- [ ] `docker compose exec web mypy server`
  Expected: no errors (scope is `server/`, so `scripts/` isn't
  strict-checked, but it should still type-check cleanly if run
  ad-hoc — not required by CI).
- [ ] `docker compose exec web python manage.py seed_script_prompt`
  Expected: `Created and activated script v1 (id=...).` (or, on a repo
  that already has a script prompt with different text, `Created and
  activated script v<n+1>`).
