# Policy-Risk Mitigations (Milestone 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `longform_v1`/`shorts_v1` pipeline resistant to YouTube's "inauthentic
content" enforcement (structural variety, mandated commentary, cadence limits, AI
disclosure, similarity detection, a review→auto graduation gate, and a cross-channel
differentiation check) before real-world QA/publishing ramps up.

**Architecture:** Every change extends the existing DAG pipeline
(`server/apps/pipelines/`) and its stage/orchestrator/service patterns — no new
subsystems. New DB fields are added via `just run makemigrations`, never hand-authored.

**Tech Stack:** Django 6.0, `pydantic-ai` (LLM agents), `msgspec` (API DTOs), `attrs`
(service classes), `pytest` + `pytest-django`.

**Full design context:** `/Users/chuckz/.claude/plans/the-clipping-feature-is-misty-rossum.md`
(sections 1.1–1.7) — read this if you need the "why," not just the "what." This plan
implements only Milestone 1 from that document; Milestones 2 (money-loop) and 3
(differentiation/creative moat) get their own plans after this one ships.

## Global Constraints

- Python 3.13.x, Django 6.0.x. `ruff` uses single quotes, 80-char line length. `mypy`
  runs in strict mode — every public function needs type annotations.
- 100% test coverage required (`pytest --cov-fail-under=100`). Every new branch needs a
  covering test.
- Migrations must be backward-compatible (zero-downtime) — generate them with
  `just run makemigrations <app_label>`, never hand-write migration files. Run
  `just run lintmigrations` and `just run check_migrations --exclude-apps=axes` after
  generating.
- `@final` on every concrete class; `@attrs.define(slots=True, frozen=True)` for service
  objects; `msgspec.Struct(frozen=True)` for API DTOs — follow the exact conventions
  already used in the files each task touches.
- Never add `from __future__ import annotations` to any file registered with punq
  (nothing in this plan needs it).
- **Tasks must be implemented in order 1 → 7.** Tasks 3, 5, and 6 each add a migration to
  `server/apps/pipelines/migrations/` (currently ends at `0006`); Task 1 adds one to
  `server/apps/prompts/migrations/` (ends at `0002`); Task 3 also adds one to
  `server/apps/channels/migrations/` (ends at `0004`). Running tasks out of order will
  produce migration-dependency conflicts.
- Run `docker compose exec web pytest tests/test_apps/test_pipelines/ tests/test_apps/test_channels/ tests/test_apps/test_prompts/ --no-cov` after every task's implementation step, then the full-coverage run once before the final commit of that task.
- Run `docker compose exec web ruff check .`, `docker compose exec web ruff format --check .`, and `docker compose exec web mypy server` before every commit.

---

### Task 1: Structural format variety in the outline stage

**Files:**
- Modify: `server/apps/prompts/models.py:76-97` (`StoryFormat`)
- Create migration: run `just run makemigrations prompts` (expect `server/apps/prompts/migrations/0003_storyformat_niches.py`)
- Modify: `server/apps/pipelines/schemas.py:47-52` (`OutlineOutput`)
- Modify: `server/apps/pipelines/stages/outline.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_outline.py`
- Test: `tests/test_apps/test_prompts/test_models.py`

**Interfaces:**
- Produces: `OutlineOutput.format_key: str` (new field, default `''`) — read by later
  tasks/stages that want to know which `StoryFormat` a run used.
- Produces: `server.apps.pipelines.stages.outline._pick_format(pool, recent_keys) -> tuple[list[dict], str]`
  and `server.apps.pipelines.stages.outline._recent_format_keys(channel_id, exclude_run_id) -> set[str]`
  (pure/DB-only split, kept internal — no other task calls these directly).

- [ ] **Step 1: Add the `StoryFormat.niches` M2M field**

In `server/apps/prompts/models.py`, in the `StoryFormat` class body, add the field right
after `music_mood_map`:

```python
    music_mood_map = models.JSONField(default=dict)
    niches = models.ManyToManyField(
        'channels.NicheConfig',
        related_name='format_pool',
        blank=True,
    )
    is_active = models.BooleanField(default=True)
```

(`is_active` already exists — just inserting `niches` above it.) `NicheConfig.format`
(the existing singular FK in `server/apps/channels/models.py`) is untouched and remains
the fallback when a niche's `format_pool` has 0 or 1 entries.

- [ ] **Step 2: Generate and check the migration**

Run:
```bash
docker compose exec web python manage.py makemigrations prompts
```
Expected: creates `server/apps/prompts/migrations/0003_storyformat_niches.py` adding the
M2M field (through table, no data migration needed — additive and nullable-equivalent).

Run:
```bash
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: both exit 0.

- [ ] **Step 3: Test `StoryFormat.niches` relation**

Add to `tests/test_apps/test_prompts/test_models.py` (check the existing file first and
follow its import/fixture style; if it already has a `pytest.mark.django_db` test for
`StoryFormat`, add this test in the same section):

```python
@pytest.mark.django_db
def test_story_format_niches_reverse_relation() -> None:
    """A StoryFormat can be attached to multiple NicheConfigs via format_pool."""
    from server.apps.channels.models import Channel, ChannelKind, NicheConfig
    from server.apps.prompts.models import StoryFormat

    channel = Channel.objects.create(name='Niches Ch', kind=ChannelKind.LONGFORM)
    niche = NicheConfig.objects.create(channel=channel)
    fmt_a = StoryFormat.objects.create(key='fmt_a', name='Format A', beats=[])
    fmt_b = StoryFormat.objects.create(key='fmt_b', name='Format B', beats=[])
    fmt_a.niches.add(niche)
    fmt_b.niches.add(niche)

    pool_keys = {f.key for f in niche.format_pool.all()}
    assert pool_keys == {'fmt_a', 'fmt_b'}
```

Run: `docker compose exec web pytest tests/test_apps/test_prompts/test_models.py -v --no-cov`
Expected: the new test passes (model field already exists from Step 1, so this is
confirmatory, not strict TDD-red-first — that's fine for a pure schema addition).

- [ ] **Step 4: Add `format_key` to `OutlineOutput`**

In `server/apps/pipelines/schemas.py`, change:
```python
class OutlineOutput(BaseModel):
    """Full output of the outline stage."""

    chapters: list[Chapter]
    total_target_seconds: int = Field(gt=0)
```
to:
```python
class OutlineOutput(BaseModel):
    """Full output of the outline stage."""

    chapters: list[Chapter]
    total_target_seconds: int = Field(gt=0)
    format_key: str = ''
```

- [ ] **Step 5: Write the failing tests for format selection**

Add to `tests/test_apps/test_pipelines/test_stages/test_outline.py`:

```python
def test_pick_format_excludes_recent_keys() -> None:
    """_pick_format avoids formats used in the last N runs when alternatives exist."""
    from server.apps.pipelines.stages.outline import _pick_format

    fmt_a = MagicMock(key='fmt_a', beats=[{'name': 'a'}])
    fmt_b = MagicMock(key='fmt_b', beats=[{'name': 'b'}])
    beats, key = _pick_format([fmt_a, fmt_b], recent_keys={'fmt_a'})
    assert key == 'fmt_b'
    assert beats == [{'name': 'b'}]


def test_pick_format_falls_back_when_all_recent() -> None:
    """_pick_format still returns a format when every pool entry was recently used."""
    from server.apps.pipelines.stages.outline import _pick_format

    fmt_a = MagicMock(key='fmt_a', beats=[{'name': 'a'}])
    _beats, key = _pick_format([fmt_a], recent_keys={'fmt_a'})
    assert key == 'fmt_a'


def test_pick_format_empty_pool_returns_empty() -> None:
    from server.apps.pipelines.stages.outline import _pick_format

    beats, key = _pick_format([], recent_keys=set())
    assert beats == []
    assert key == ''
```

```python
@pytest.mark.django_db
def test_recent_format_keys_reads_last_two_successful_outlines() -> None:
    """_recent_format_keys returns format_key from the channel's last 2 SUCCEEDED outline runs."""
    import asyncio

    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.stages.outline import _recent_format_keys

    channel = Channel.objects.create(name='Fmt Ch', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='fmt_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    runs = [
        PipelineRun.objects.create(
            channel=channel, blueprint=bp, blueprint_snapshot={}, topic=f'topic {i}',
        )
        for i in range(3)
    ]
    for i, run in enumerate(runs):
        StageExecution.objects.create(
            run=run,
            stage_key='outline',
            status=StageStatus.SUCCEEDED,
            input_hash='',
            output={'format_key': f'fmt_{i}'},
            finished_at=django.utils.timezone.now(),
        )

    keys = asyncio.run(
        _recent_format_keys(str(channel.id), exclude_run_id=str(runs[-1].id)),
    )
    assert keys == {'fmt_1', 'fmt_0'} or len(keys) == 2
```

Add `import django.utils.timezone` and `import pytest` at the top of the test file if not
already present (check first — `pytest` is likely already imported for the module-level
fixtures; the module currently has no `import pytest` since it uses plain functions, so
add it).

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_outline.py -v --no-cov`
Expected: FAIL — `_pick_format` / `_recent_format_keys` do not exist yet.

- [ ] **Step 6: Implement format selection in `outline.py`**

In `server/apps/pipelines/stages/outline.py`, add near the top (after the existing
imports) two module-level helpers:

```python
import random
from typing import Any


def _pick_format(
    pool: list[Any],
    recent_keys: set[str],
) -> tuple[list[dict[str, Any]], str]:
    """Weighted-random pick from pool, excluding recently-used keys when possible."""
    if not pool:
        return [], ''
    candidates = [f for f in pool if f.key not in recent_keys] or list(pool)
    chosen = random.choice(candidates)
    return chosen.beats, chosen.key


async def _recent_format_keys(
    channel_id: str,
    exclude_run_id: str,
    limit: int = 2,
) -> set[str]:
    """format_key values from the channel's last `limit` SUCCEEDED outline runs."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    keys: set[str] = set()
    async for exec_ in (
        StageExecution.objects.filter(
            run__channel_id=channel_id,
            stage_key='outline',
            status=StageStatus.SUCCEEDED,
        )
        .exclude(run_id=exclude_run_id)
        .order_by('-finished_at')[:limit]
    ):
        key = exec_.output.get('format_key', '')
        if key:
            keys.add(key)
    return keys
```

Then replace the existing niche/beats block inside `OutlineStage.run` (currently):
```python
        research = ctx.upstream.get('research', {})
        brief = research.get('brief', {})
        niche = getattr(ctx.channel, 'niche_config', None)
        beats: list[dict[str, Any]] = []
        if niche and getattr(niche, 'format', None):
            beats = getattr(niche.format, 'beats', [])
        total_s = ctx.config.get('total_target_seconds', 1320)
```
with:
```python
        research = ctx.upstream.get('research', {})
        brief = research.get('brief', {})
        niche = getattr(ctx.channel, 'niche_config', None)
        beats: list[dict[str, Any]] = []
        format_key = ''
        if niche:
            pool = list(niche.format_pool.filter(is_active=True))
            if len(pool) > 1:
                recent_keys = await _recent_format_keys(
                    str(ctx.channel.id),
                    str(ctx.run.id),
                )
                beats, format_key = _pick_format(pool, recent_keys)
            elif pool:
                beats, format_key = pool[0].beats, pool[0].key
            elif getattr(niche, 'format', None):
                beats = getattr(niche.format, 'beats', [])
                format_key = getattr(niche.format, 'key', '')
        total_s = ctx.config.get('total_target_seconds', 1320)
```

Finally, where `run()` currently does `return output.model_dump()` at the end, change to:
```python
        result = output.model_dump()
        result['format_key'] = format_key
        return result
```

- [ ] **Step 7: Fix the existing `_make_ctx()` fixture so old tests still pass**

`niche.format_pool.filter(is_active=True)` is called unconditionally now. The existing
`_make_ctx()` in `test_outline.py` sets `ctx.channel.niche_config = MagicMock()` without
configuring `format_pool`, so `list(MagicMock())` will raise `TypeError`. Update
`_make_ctx()`:

```python
def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.id = 'run-outline-1'
    ctx.run.prompt_snapshot = {}
    ctx.channel.id = 'chan-outline-1'
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.format_pool.filter.return_value = []
    ctx.channel.niche_config.format = MagicMock()
    ctx.channel.niche_config.format.beats = [
        {'key': 'intro', 'pct': 0.1, 'purpose': 'hook'},
        {'key': 'main', 'pct': 0.8, 'purpose': 'story'},
        {'key': 'outro', 'pct': 0.1, 'purpose': 'cta'},
    ]
    ctx.channel.niche_config.format.key = 'legacy_format'
    ctx.channel.wpm = 158
    ctx.upstream = {
        'research': {
            'brief': {
                'topic': 'The fall of Rome',
                'key_facts': ['Rome fell in 476 AD'],
                'narrative_angles': ['economic decline'],
                'hooks': ['What really ended Rome?'],
                'sources': [],
            },
            'sources': [],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx
```

This keeps `format_pool` empty (falls back to the legacy `.format` FK path — 0 pool
entries), matching the pre-Task-1 behavior for every existing test.

Also update `test_outline_run_with_no_niche_config`'s `ctx = MagicMock()` block the same
way is not needed there since it sets `ctx.channel.niche_config = None` directly, which
the new code already handles (`if niche:` guard).

- [ ] **Step 8: Add tests proving the pool path is used when populated**

Add to `test_outline.py`:

```python
def test_outline_run_uses_format_pool_when_multiple_present() -> None:
    """When niche.format_pool has 2+ entries, run() picks one and reports format_key."""
    from server.apps.pipelines.schemas import Chapter, OutlineOutput

    ctx = _make_ctx()
    fmt_a = MagicMock(key='fmt_a', beats=[{'name': 'a'}])
    fmt_b = MagicMock(key='fmt_b', beats=[{'name': 'b'}])
    ctx.channel.niche_config.format_pool.filter.return_value = [fmt_a, fmt_b]

    fake_output = OutlineOutput(
        chapters=[
            Chapter(idx=0, title='T', thesis='X', target_seconds=60, device='open_loop'),
        ],
        total_target_seconds=60,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.outline._recent_format_keys',
                new=AsyncMock(return_value=set()),
            ),
        ):
            return await OutlineStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['format_key'] in {'fmt_a', 'fmt_b'}


def test_outline_run_single_pool_entry_used_directly() -> None:
    """When niche.format_pool has exactly 1 entry, it's used without a DB lookup."""
    from server.apps.pipelines.schemas import Chapter, OutlineOutput

    ctx = _make_ctx()
    fmt_only = MagicMock(key='only_fmt', beats=[{'name': 'solo'}])
    ctx.channel.niche_config.format_pool.filter.return_value = [fmt_only]

    fake_output = OutlineOutput(
        chapters=[
            Chapter(idx=0, title='T', thesis='X', target_seconds=60, device='open_loop'),
        ],
        total_target_seconds=60,
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await OutlineStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['format_key'] == 'only_fmt'
```

- [ ] **Step 9: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_outline.py tests/test_apps/test_prompts/ -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add server/apps/prompts/models.py server/apps/prompts/migrations/0003_storyformat_niches.py server/apps/pipelines/schemas.py server/apps/pipelines/stages/outline.py tests/test_apps/test_pipelines/test_stages/test_outline.py tests/test_apps/test_prompts/test_models.py
git commit -m "feat(pipelines): rotate StoryFormat pool per run to avoid templated structure"
```

---

### Task 2: Mandated commentary/POV in scripts

**Files:**
- Modify: `server/apps/pipelines/schemas.py:54-68` (`ScriptChapter`, `ScriptOutput`)
- Modify: `server/apps/pipelines/stages/script.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_script.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `ScriptChapter.commentary: str` (required) — consumed by Task 5 (no direct
  dependency) and by the Milestone-3 `narrative_qc` stage in a later plan.

- [ ] **Step 1: Write the failing schema test**

Add to `tests/test_apps/test_pipelines/test_stages/test_script.py`:

```python
def test_script_chapter_requires_commentary() -> None:
    """ScriptChapter without commentary fails validation."""
    import pytest
    from pydantic import ValidationError

    from server.apps.pipelines.schemas import ScriptChapter

    with pytest.raises(ValidationError):
        ScriptChapter(
            idx=0,
            title='Intro',
            text='Rome was great.',
            word_count=3,
            closing_line='But it fell.',
            commentary='',
        )
```

Add `import pytest` at the top of the test file (not currently imported there).

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_script.py -v --no-cov`
Expected: FAIL — `ScriptChapter.__init__()` got an unexpected keyword argument
`'commentary'`.

- [ ] **Step 2: Add `commentary` to the schema**

In `server/apps/pipelines/schemas.py`, change:
```python
class ScriptChapter(BaseModel):
    """Narration script for one chapter."""

    idx: int
    title: str
    text: str
    word_count: int = Field(ge=1)
    closing_line: str
```
to:
```python
class ScriptChapter(BaseModel):
    """Narration script for one chapter."""

    idx: int
    title: str
    text: str
    word_count: int = Field(ge=1)
    closing_line: str
    commentary: str = Field(min_length=1)
```

And add a distinctness validator to `ScriptOutput`:
```python
class ScriptOutput(BaseModel):
    """Full output of the script stage."""

    chapters: list[ScriptChapter]
    total_word_count: int = Field(ge=1)

    @model_validator(mode='after')
    def enforce_commentary_distinct(self) -> ScriptOutput:
        """At least half the chapters must have commentary distinct from text."""
        if not self.chapters:
            return self
        distinct_count = sum(
            1
            for ch in self.chapters
            if _word_overlap_ratio(ch.text, ch.commentary) < 0.8  # noqa: PLC0415
        )
        if distinct_count < len(self.chapters) / 2:
            msg = (
                'commentary must read as genuine analysis distinct from '
                'narration in at least half the chapters'
            )
            raise ValueError(msg)
        return self
```

`ScriptOutput` needs `from __future__ import annotations` for the `-> ScriptOutput`
return type to resolve — check the top of `schemas.py`: it already has
`from __future__ import annotations` at line 7 (confirmed — this file is Pydantic
schemas, not punq-registered, so this is safe here). No change needed there.

Add the helper function above `ScriptChapter` (near the top of the file, after imports):
```python
def _word_overlap_ratio(text_a: str, text_b: str) -> float:
    """Fraction of text_b's words that also appear in text_a (case-insensitive)."""
    words_a = set(text_a.lower().split())
    words_b = text_b.lower().split()
    if not words_b:
        return 1.0
    overlap = sum(1 for w in words_b if w in words_a)
    return overlap / len(words_b)
```

- [ ] **Step 3: Run schema test, fix if needed**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_script.py -v --no-cov`
Expected: `test_script_chapter_requires_commentary` PASSes;
`test_script_run_returns_chapters_and_word_count` now FAILs (its `ScriptChapter(...)`
call in the fixture is missing `commentary` — fix in the next step).

- [ ] **Step 4: Add an output validator with self-correction to the agent**

In `server/apps/pipelines/stages/script.py`, add `ModelRetry` to the import and register
an output validator on the cached agent, mirroring
`server/apps/pipelines/stages/scene_breakdown.py:44-64`:

```python
from pydantic_ai import Agent, ModelRetry, RunContext
```

Then inside `_agent()`, after the existing `@a.system_prompt` block, add:
```python
    @a.output_validator
    def _validate(  # pragma: no cover
        ctx: RunContext[StageContext],
        output: ScriptOutput,
    ) -> ScriptOutput:
        """Reject scripts whose commentary is filler, not genuine analysis."""
        try:
            output.model_validate(output.model_dump())
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return output
```

(`ScriptOutput`'s own `model_validator` already runs on construction from the LLM's raw
output — the `output_validator` re-runs the same check and turns a would-be
`ValidationError` from a manual retry path into a `ModelRetry` so PydanticAI
self-corrects, exactly like `scene_breakdown`'s pattern. In practice `output` here is
already a validated `ScriptOutput` instance so `model_validate(output.model_dump())`
either re-passes or re-raises the same `ValueError` the constructor would have raised —
this exists to give the agent a retry loop rather than a hard crash.)

- [ ] **Step 5: Update the prompt template default text**

In `ScriptStage.run`, the fallback `user_prompt` (used when no `PromptVersion` is
active) currently ends with:
```python
        user_prompt = usr or (
            f'Write the full script for "{ctx.run.topic}".\n'
            f'Chapters: {chapters}\n'
            f'Research: {research.get("brief", {})}\n'
            f'Target WPM: {wpm}. '
            f'Include a closing_line per chapter for continuity.'
        )
```
Change to:
```python
        user_prompt = usr or (
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

- [ ] **Step 6: Fix the existing fixture and add a rejection test**

In `_make_ctx()`'s consumers, update the existing test's `ScriptChapter(...)` call in
`test_script_run_returns_chapters_and_word_count`:
```python
            ScriptChapter(
                idx=0,
                title='Intro',
                text='Rome was great.',
                word_count=3,
                closing_line='But it fell.',
                commentary='I think Rome\'s fall was avoidable, not inevitable.',
            ),
```

Add a new test proving the constructor-level rejection end-to-end:
```python
def test_script_output_rejects_filler_commentary() -> None:
    """ScriptOutput construction fails when commentary just echoes narration."""
    import pytest
    from pydantic import ValidationError

    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    with pytest.raises(ValidationError):
        ScriptOutput(
            chapters=[
                ScriptChapter(
                    idx=0,
                    title='Intro',
                    text='Rome was great and powerful for centuries.',
                    word_count=7,
                    closing_line='It fell.',
                    commentary='Rome was great and powerful for centuries.',
                ),
            ],
            total_word_count=7,
        )
```

- [ ] **Step 7: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_script.py tests/test_apps/test_pipelines/test_stages/test_scene_breakdown.py -v --no-cov`
Expected: all PASS (scene_breakdown tests are unaffected but re-run to confirm the
`ModelRetry` import pattern didn't break anything shared).

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add server/apps/pipelines/schemas.py server/apps/pipelines/stages/script.py tests/test_apps/test_pipelines/test_stages/test_script.py
git commit -m "feat(pipelines): require genuine per-chapter commentary distinct from narration"
```

---

### Task 3: Upload cadence governor (`PUBLISH_HOLD`)

**Files:**
- Modify: `server/apps/channels/models.py:49-109` (`Channel`)
- Create migration: `just run makemigrations channels` (expect `0005_channel_max_publishes_per_day.py`)
- Modify: `server/apps/pipelines/models.py:16-26` (`RunStatus`)
- Create migration: `just run makemigrations pipelines` (expect `0007_pipelinerun_publish_hold_status.py`)
- Modify: `server/apps/pipelines/services/orchestrator.py`
- Test: `tests/test_apps/test_channels/test_models.py`
- Test: `tests/test_apps/test_pipelines/test_orchestrator.py`

**Interfaces:**
- Produces: `Channel.max_publishes_per_day: int | None`, `RunStatus.PUBLISH_HOLD`.
- Produces: `server.apps.pipelines.services.orchestrator._publish_rate_limited(channel) -> bool`
  (sync helper; called only from `_process_node_sync`, not exposed elsewhere).

- [ ] **Step 1: Add `Channel.max_publishes_per_day`**

In `server/apps/channels/models.py`, in `Channel`, add after `default_budget_usd`:
```python
    default_budget_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    max_publishes_per_day = models.PositiveSmallIntegerField(default=1)
```

Run:
```bash
docker compose exec web python manage.py makemigrations channels
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration `0005_channel_max_publishes_per_day.py`; both lint commands
exit 0 (a non-nullable field with a static `default=1` is a backward-compatible add).

- [ ] **Step 2: Add `RunStatus.PUBLISH_HOLD`**

In `server/apps/pipelines/models.py`:
```python
class RunStatus(models.TextChoices):
    """Lifecycle status of a PipelineRun."""

    PENDING = 'PENDING', 'Pending'
    RUNNING = 'RUNNING', 'Running'
    AWAITING_REVIEW = 'AWAITING_REVIEW', 'Awaiting review'
    BUDGET_HOLD = 'BUDGET_HOLD', 'Budget hold'
    PUBLISH_HOLD = 'PUBLISH_HOLD', 'Publish hold'
    PUBLISHING = 'PUBLISHING', 'Publishing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'
```

Run:
```bash
docker compose exec web python manage.py makemigrations pipelines
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration altering the `pipelines_pipelinerun_status_valid` check
constraint to include `PUBLISH_HOLD`; both lint commands exit 0.

- [ ] **Step 3: Write the failing orchestrator test**

Add to `tests/test_apps/test_pipelines/test_orchestrator.py` (reuse the existing
`dummy_blueprint`/`orch_channel`/`orch_run` fixtures — but this test needs a blueprint
whose single stage key is `'publish'` so the rate-limit check applies; add a dedicated
fixture rather than reusing `dummy_blueprint`):

```python
@pytest.fixture
def publish_blueprint() -> PipelineBlueprint:
    """A 1-stage blueprint whose only node is the real 'publish' stage key."""
    return PipelineBlueprint.objects.create(
        name='publish_hold_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'publish', 'depends_on': [], 'queue': 'api'}]},
    )


@pytest.mark.django_db(transaction=True)
def test_advance_parks_run_at_publish_hold_when_daily_cap_reached(
    publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    """publish stage does not enqueue once today's PublishJob count hits the cap."""
    from server.apps.pipelines.models import PipelineRun, RunStatus
    from server.apps.pipelines.services.orchestrator import advance_pipeline_impl
    from server.apps.publishing.models import PublishJob, PublishStatus

    orch_channel.max_publishes_per_day = 1
    orch_channel.save(update_fields=['max_publishes_per_day'])

    prior_run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='already published today',
    )
    PublishJob.objects.create(
        run=prior_run,
        channel=orch_channel,
        status=PublishStatus.COMPLETED,
    )

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='second video today',
    )

    _run(advance_pipeline_impl(str(run.id)))

    run.refresh_from_db()
    assert run.status == RunStatus.PUBLISH_HOLD
    assert not run.stages.filter(stage_key='publish').exists()


@pytest.mark.django_db(transaction=True)
def test_advance_enqueues_publish_when_under_cap(
    publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    """publish stage enqueues normally when today's PublishJob count is under the cap."""
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.models import PipelineRun, StageStatus
    from server.apps.pipelines.services.orchestrator import advance_pipeline_impl

    orch_channel.max_publishes_per_day = 1
    orch_channel.save(update_fields=['max_publishes_per_day'])

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='first video today',
    )

    with patch(
        'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
        new=AsyncMock(),
    ):
        _run(advance_pipeline_impl(str(run.id)))

    assert run.stages.filter(
        stage_key='publish',
        status=StageStatus.QUEUED,
    ).exists()
```

`test_orchestrator.py` already has `PipelineBlueprint`, `PipelineKind`, `PipelineRun`,
and `RunStatus` imported at module scope (two `from server.apps.pipelines.models import
(...)` blocks in the file), which is why the `publish_blueprint` fixture above doesn't
need its own import. `StageStatus`, `StageExecution`, `PublishJob`, `PublishStatus`, and
`unittest.mock` names are not imported at module scope anywhere in the file — every
existing test that needs them imports inline inside the test function (see
`test_cost_recorder_accumulates_total`), which is why the two new tests above do the
same for `StageStatus`/`PublishJob`/`PublishStatus`/`AsyncMock`/`patch`. The redundant
inline `PipelineRun` re-import in both new tests is harmless and matches the file's
existing defensive style of not relying on where in the file a module-level import
happens to sit.

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_orchestrator.py -v --no-cov -k publish_hold`
Expected: FAIL — run status stays `PENDING`/`RUNNING`, not `PUBLISH_HOLD` (no gating
logic exists yet); second test may pass already (no regression), that's fine.

- [ ] **Step 4: Implement the rate-limit check in the orchestrator**

In `server/apps/pipelines/services/orchestrator.py`, add a new sync helper near
`_node_should_skip`:

```python
def _publish_rate_limited(run: 'PipelineRun') -> bool:
    """True when the channel already hit its max_publishes_per_day today."""
    from server.apps.publishing.models import (  # noqa: PLC0415
        PublishJob,
        PublishStatus,
    )

    channel = run.channel
    cap = getattr(channel, 'max_publishes_per_day', None)
    if not cap:
        return False
    today_start = tz.now().replace(hour=0, minute=0, second=0, microsecond=0)
    published_today = PublishJob.objects.filter(
        channel=channel,
        status=PublishStatus.COMPLETED,
        created_at__gte=today_start,
    ).count()
    return published_today >= cap
```

Then update `_process_node_sync` to check this specifically for the `publish` stage key,
before the existing enqueue path:

```python
def _process_node_sync(
    node: dict[str, Any],
    run: 'PipelineRun',
    states: dict[str, str | None],
    armed_gates: list[str],
    to_enqueue: list[str],
) -> None:
    """Evaluate one blueprint node; enqueue, skip, or ignore (sync)."""
    from server.apps.pipelines.models import RunStatus, StageStatus  # noqa: PLC0415

    key = node['key']
    current = states.get(key)
    if current not in {None, StageStatus.PENDING}:
        return

    if _node_should_skip(node, run, armed_gates):
        _mark_skipped_sync(run, key)
        states[key] = StageStatus.SKIPPED
        return

    if key == 'publish' and _publish_rate_limited(run):
        run.status = RunStatus.PUBLISH_HOLD
        run.save(update_fields=['status'])
        return

    if _try_park_gate_sync(node, run, states, key):
        return

    _try_enqueue_stage_sync(node, run, states, to_enqueue, key)
```

- [ ] **Step 5: Allow resuming from `PUBLISH_HOLD`**

In `_resume_run_sync` (same file), the allowed-status set currently is:
```python
        if run.status in {
            RunStatus.PENDING,
            RunStatus.AWAITING_REVIEW,
            RunStatus.BUDGET_HOLD,
        }:
            run.status = RunStatus.RUNNING
```
Change to:
```python
        if run.status in {
            RunStatus.PENDING,
            RunStatus.AWAITING_REVIEW,
            RunStatus.BUDGET_HOLD,
            RunStatus.PUBLISH_HOLD,
        }:
            run.status = RunStatus.RUNNING
```

- [ ] **Step 6: Add the daily resume task**

Create a small scheduled task alongside the existing pattern in
`server/apps/pipelines/tasks.py` (open that file first and match its existing
`@broker.task(...)` decorator style exactly — it currently has two tasks at lines 6 and
16). Add a third:

```python
@broker.task(retry_on_error=False, queue='api')
async def resume_publish_held_runs() -> None:
    """Re-advance every PUBLISH_HOLD run — called once daily by an external scheduler."""
    from server.apps.pipelines.models import PipelineRun, RunStatus  # noqa: PLC0415
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    run_ids = [
        str(run_id)
        async for run_id in PipelineRun.objects.filter(
            status=RunStatus.PUBLISH_HOLD,
        ).values_list('id', flat=True)
    ]
    for run_id in run_ids:
        await advance_pipeline_impl(run_id)
```

This follows the same "plain `@broker.task`, triggered by an external scheduler" shape
as `analytics/tasks.py::refresh_analytics_views` — wiring the actual daily trigger
(system cron / hosting platform scheduler calling this task) is an ops step outside this
codebase, matching how that existing task is triggered.

- [ ] **Step 7: Test the resume task and re-run everything**

Add to `tests/test_apps/test_pipelines/test_orchestrator.py` or a new
`tests/test_apps/test_pipelines/test_tasks.py` (check whether that file already exists;
if so, add there and follow its style):

```python
@pytest.mark.django_db(transaction=True)
def test_resume_publish_held_runs_advances_each_held_run(
    publish_blueprint: PipelineBlueprint,
    orch_channel,
) -> None:
    from server.apps.pipelines.models import PipelineRun, RunStatus
    from server.apps.pipelines.tasks import resume_publish_held_runs

    run = PipelineRun.objects.create(
        channel=orch_channel,
        blueprint=publish_blueprint,
        blueprint_snapshot=publish_blueprint.graph,
        topic='held run',
        status=RunStatus.PUBLISH_HOLD,
    )

    with patch(
        'server.apps.pipelines.services.orchestrator.execute_stage_kiq',
        new=AsyncMock(),
    ):
        _run(resume_publish_held_runs())

    run.refresh_from_db()
    assert run.status != RunStatus.PUBLISH_HOLD
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_orchestrator.py tests/test_apps/test_pipelines/test_tasks.py tests/test_apps/test_channels/test_models.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add server/apps/channels/models.py server/apps/channels/migrations/0005_channel_max_publishes_per_day.py server/apps/pipelines/models.py server/apps/pipelines/migrations/0007_*.py server/apps/pipelines/services/orchestrator.py server/apps/pipelines/tasks.py tests/test_apps/test_pipelines/test_orchestrator.py tests/test_apps/test_pipelines/test_tasks.py
git commit -m "feat(pipelines): add per-channel daily publish cap (PUBLISH_HOLD)"
```

---

### Task 4: AI content disclosure on publish

**Files:**
- Modify: `server/apps/generation/clients/youtube.py:107-157` (`upload_video`)
- Modify: `server/apps/pipelines/stages/publish.py`
- Test: `tests/test_apps/test_generation/test_youtube_client.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_publish.py`

**Interfaces:**
- Produces: `yt_client.upload_video(..., contains_synthetic_media: bool = True)`.

- [ ] **Step 1: Spike — confirm the current YouTube Data API v3 field**

Before writing code, confirm against the live YouTube Data API v3 `videos.insert`
reference (`https://developers.google.com/youtube/v3/docs/videos/insert` and the
`videos#resource` `status` object docs) exactly which field name currently carries the
creator's synthetic-media self-declaration. Treat this as a 10-minute research step, not
an assumption — the field name is written below as `containsSyntheticMedia` based on the
plan's research, but verify it against the live docs before shipping; if the API has
changed shape, use whatever the current docs specify in its place throughout this task.

- [ ] **Step 2: Write the failing client test**

Add to `tests/test_apps/test_generation/test_youtube_client.py`:

```python
def test_upload_video_includes_synthetic_media_disclosure_by_default() -> None:
    """upload_video's request body declares synthetic media unless overridden."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.generation.clients.youtube import upload_video

    captured: dict = {}

    async def _fake_post(self, url, **kwargs):  # noqa: ANN001, ARG001
        captured['body'] = kwargs['json']
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {'Location': 'https://upload.example.com/resumable'}
        return resp

    async def _fake_put(self, url, **kwargs):  # noqa: ANN001, ARG001
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'id': 'yt_new_video'}
        return resp

    async def _inner() -> str:
        with (
            patch('httpx.AsyncClient.post', new=_fake_post),
            patch('httpx.AsyncClient.put', new=_fake_put),
        ):
            return await upload_video(
                access_token='tok',
                video_bytes=b'video',
                title='Title',
                description='Desc',
                tags=['a'],
            )

    video_id = asyncio.run(_inner())
    assert video_id == 'yt_new_video'
    assert captured['body']['status']['containsSyntheticMedia'] is True
```

(Use the field name confirmed in Step 1 — replace `containsSyntheticMedia` throughout
this task if the live docs specify something different.)

Run: `docker compose exec web pytest tests/test_apps/test_generation/ -v --no-cov -k synthetic_media`
Expected: FAIL — `KeyError: 'containsSyntheticMedia'`.

- [ ] **Step 3: Implement the parameter**

In `server/apps/generation/clients/youtube.py`, change the `upload_video` signature and
body construction:

```python
async def upload_video(
    access_token: str,
    video_bytes: bytes,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = '27',
    schedule_at: _Schedulable | None = None,
    made_for_kids: bool = False,  # noqa: FBT001, FBT002
    contains_synthetic_media: bool = True,  # noqa: FBT001, FBT002
) -> str:
    """Resumable upload to YouTube. Returns the youtube_video_id."""
    status: dict[str, object] = {
        'privacyStatus': 'private' if schedule_at else 'public',
        'selfDeclaredMadeForKids': made_for_kids,
        'containsSyntheticMedia': contains_synthetic_media,
    }
```

Everything else in the function is unchanged.

- [ ] **Step 4: Wire it from `PublishStage`**

`server/apps/pipelines/stages/publish.py`'s call to `yt_client.upload_video(...)` doesn't
need an explicit change since the new parameter defaults to `True` and every ReelForge
video is synthetic by construction — but add an explicit keyword for clarity and to
guard against the default ever changing silently:

```python
        youtube_video_id = await yt_client.upload_video(
            access_token=access_token,
            video_bytes=video_bytes,
            title=meta['title'],
            description=meta['description'],
            tags=meta.get('tags', []),
            schedule_at=schedule_at,
            contains_synthetic_media=True,
        )
```

- [ ] **Step 5: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_generation/ tests/test_apps/test_pipelines/test_stages/test_publish.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add server/apps/generation/clients/youtube.py server/apps/pipelines/stages/publish.py tests/test_apps/test_generation/ tests/test_apps/test_pipelines/test_stages/test_publish.py
git commit -m "feat(publish): declare AI-generated/synthetic media on every YouTube upload"
```

---

### Task 5: Cross-run similarity guard

**Files:**
- Create: `server/apps/generation/clients/embeddings.py`
- Create: `server/apps/pipelines/logic/similarity.py`
- Modify: `server/apps/pipelines/models.py` (`PipelineRun`)
- Create migration: `just run makemigrations pipelines` (expect `0008_pipelinerun_script_embedding.py`)
- Modify: `server/apps/pipelines/stages/script.py`
- Test: `tests/test_apps/test_generation/test_embeddings.py` (new)
- Test: `tests/test_apps/test_pipelines/test_logic/test_similarity.py` (new — check
  whether `tests/test_apps/test_pipelines/test_logic/` exists as a directory already; if
  not, create it with an `__init__.py`)
- Test: `tests/test_apps/test_pipelines/test_stages/test_script.py`

**Interfaces:**
- Consumes: `ScriptChapter.commentary`/`.text` from Task 2 (no signature change needed —
  just reads existing fields).
- Produces: `similarity.cosine_similarity(a, b) -> float`, `similarity.is_too_similar(new, recent) -> bool`
  (pure, importable by the Milestone-3 `narrative_qc` stage later).
- Produces: `PipelineRun.script_embedding: list[float] | None`.
- Produces: script stage output key `similarity_flag: bool`.

- [ ] **Step 1: Write and implement pure similarity math (TDD, no mocking needed)**

Write the failing test first at `tests/test_apps/test_pipelines/test_logic/test_similarity.py`:

```python
"""Tests for cross-run script similarity math."""

from server.apps.pipelines.logic.similarity import (
    cosine_similarity,
    is_too_similar,
    max_similarity,
)


def test_cosine_similarity_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_mismatched_length_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0


def test_cosine_similarity_zero_vector_is_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_max_similarity_empty_recent_is_zero() -> None:
    assert max_similarity([1.0, 0.0], []) == 0.0


def test_max_similarity_returns_highest() -> None:
    result = max_similarity([1.0, 0.0], [[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]])
    assert result == 1.0


def test_is_too_similar_true_above_threshold() -> None:
    assert is_too_similar([1.0, 0.0], [[1.0, 0.0001]]) is True


def test_is_too_similar_false_below_threshold() -> None:
    assert is_too_similar([1.0, 0.0], [[0.0, 1.0]]) is False
```

If `tests/test_apps/test_pipelines/test_logic/` doesn't exist yet, create it with an
empty `__init__.py` first.

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_similarity.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: server.apps.pipelines.logic.similarity`.

Implement `server/apps/pipelines/logic/similarity.py`:

```python
"""Pure cosine-similarity math for cross-run script duplication detection."""

import math

_SIMILARITY_THRESHOLD = 0.92


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 for empty/mismatched/zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def max_similarity(new_vec: list[float], recent_vecs: list[list[float]]) -> float:
    """Highest cosine similarity between new_vec and any entry in recent_vecs."""
    if not recent_vecs:
        return 0.0
    return max(cosine_similarity(new_vec, v) for v in recent_vecs)


def is_too_similar(new_vec: list[float], recent_vecs: list[list[float]]) -> bool:
    """True when new_vec is a near-duplicate of any recent script embedding."""
    return max_similarity(new_vec, recent_vecs) >= _SIMILARITY_THRESHOLD
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_similarity.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 2: Write and implement the embeddings client**

Write the failing test at `tests/test_apps/test_generation/test_embeddings.py`:

```python
"""Tests for the text embeddings client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.generation.clients.embeddings import embed_text


def test_embed_text_returns_vector_from_openai_response() -> None:
    fake_response = MagicMock()
    fake_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    async def _inner() -> list[float]:
        with patch(
            'server.apps.generation.clients.embeddings.AsyncOpenAI',
        ) as mock_cls:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=fake_response)
            mock_cls.return_value = mock_client
            return await embed_text('some script text')

    result = asyncio.run(_inner())
    assert result == [0.1, 0.2, 0.3]


def test_embed_text_truncates_long_input() -> None:
    fake_response = MagicMock()
    fake_response.data = [MagicMock(embedding=[0.5])]
    captured: dict = {}

    async def _fake_create(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return fake_response

    async def _inner() -> list[float]:
        with patch(
            'server.apps.generation.clients.embeddings.AsyncOpenAI',
        ) as mock_cls:
            mock_client = MagicMock()
            mock_client.embeddings.create = _fake_create
            mock_cls.return_value = mock_client
            return await embed_text('x' * 20000)

    asyncio.run(_inner())
    assert len(captured['input']) == 8000
```

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_embeddings.py -v --no-cov`
Expected: FAIL — module doesn't exist.

Implement `server/apps/generation/clients/embeddings.py`:

```python
"""Text embeddings client — used for cross-run script similarity detection."""

from openai import AsyncOpenAI

_EMBEDDING_MODEL = 'text-embedding-3-small'
_MAX_CHARS = 8000


async def embed_text(text: str) -> list[float]:
    """Return a text-embedding-3-small vector for the given text."""
    client = AsyncOpenAI()
    response = await client.embeddings.create(
        model=_EMBEDDING_MODEL,
        input=text[:_MAX_CHARS],
    )
    return list(response.data[0].embedding)
```

Run: `docker compose exec web pytest tests/test_apps/test_generation/test_embeddings.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 3: Add `PipelineRun.script_embedding`**

In `server/apps/pipelines/models.py`, add to `PipelineRun` after `total_cost_usd`:
```python
    total_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
    )
    script_embedding = models.JSONField(null=True, blank=True)
```

Run:
```bash
docker compose exec web python manage.py makemigrations pipelines
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration `0008_pipelinerun_script_embedding.py`; both lint commands
exit 0 (nullable field, backward compatible).

- [ ] **Step 4: Write the failing integration test for the script stage**

Add to `tests/test_apps/test_pipelines/test_stages/test_script.py`:

```python
def test_script_run_flags_similarity_and_saves_embedding() -> None:
    """run() computes an embedding, compares to recent runs, and flags similarity."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    ctx = _make_ctx()
    ctx.channel.publish_mode = 'review'
    ctx.run.asave = AsyncMock()

    fake_output = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Intro',
                text='Rome was great.',
                word_count=3,
                closing_line='But it fell.',
                commentary='I think this collapse was avoidable.',
            ),
        ],
        total_word_count=3,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.script.embed_text',
                new=AsyncMock(return_value=[1.0, 0.0]),
            ),
            patch(
                'server.apps.pipelines.stages.script._recent_script_embeddings',
                new=AsyncMock(return_value=[[1.0, 0.0001]]),
            ),
        ):
            return await ScriptStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['similarity_flag'] is True
    ctx.run.asave.assert_awaited_once_with(update_fields=['script_embedding'])
    assert ctx.run.script_embedding == [1.0, 0.0]


def test_script_run_auto_channel_retries_once_on_similarity() -> None:
    """publish_mode=auto triggers exactly one regeneration when too similar."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    ctx = _make_ctx()
    ctx.channel.publish_mode = 'auto'
    ctx.run.asave = AsyncMock()

    first = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0, title='Intro', text='Rome was great.', word_count=3,
                closing_line='But it fell.', commentary='I think this was avoidable.',
            ),
        ],
        total_word_count=3,
    )
    second = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0, title='Intro', text='A different take entirely.', word_count=4,
                closing_line='Or was it?', commentary='Actually I disagree with the usual take.',
            ),
        ],
        total_word_count=4,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(side_effect=[first, second]),
            ) as mock_run_agent,
            patch(
                'server.apps.pipelines.stages.script.embed_text',
                new=AsyncMock(side_effect=[[1.0, 0.0], [0.0, 1.0]]),
            ),
            patch(
                'server.apps.pipelines.stages.script._recent_script_embeddings',
                new=AsyncMock(return_value=[[1.0, 0.0001]]),
            ),
        ):
            result = await ScriptStage().run(ctx)
            assert mock_run_agent.await_count == 2
            return result

    result = asyncio.run(_inner())
    assert result['similarity_flag'] is False
    assert result['chapters'][0]['text'] == 'A different take entirely.'
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_script.py -v --no-cov -k similarity`
Expected: FAIL — `embed_text`/`_recent_script_embeddings` not imported into
`script.py`, `similarity_flag` not in output.

- [ ] **Step 5: Implement in `script.py`**

Restructure `server/apps/pipelines/stages/script.py`. Add imports:
```python
from server.apps.generation.clients.embeddings import embed_text
from server.apps.pipelines.logic.similarity import is_too_similar
```

Extract the prompt-building + agent call into a helper (so it can be called twice with
an extra hint), and add the recent-embeddings fetch helper:

```python
async def _generate_script(
    ctx: StageContext,
    extra_hint: str = '',
) -> ScriptOutput:
    """Build the script prompt and run the agent once."""
    outline = ctx.upstream.get('outline', {})
    research = ctx.upstream.get('research', {})
    chapters = outline.get('chapters', [])
    wpm = getattr(ctx.channel, 'wpm', 158)

    _, usr = await ctx.prompts.render(
        'script',
        {
            'topic': ctx.run.topic,
            'chapters': chapters,
            'research': research,
            'wpm': wpm,
        },
    )
    user_prompt = usr or (
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
    if extra_hint:
        user_prompt = f'{user_prompt}\n\n{extra_hint}'
    return await llm_client.run_agent(
        _agent(),
        user_prompt,
        ctx,
        stage_key=ScriptStage.key,
    )


async def _recent_script_embeddings(
    channel_id: str,
    exclude_run_id: str,
    limit: int = 5,
) -> list[list[float]]:
    """script_embedding values from the channel's last `limit` COMPLETED runs."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
    )

    embeddings: list[list[float]] = []
    async for run in (
        PipelineRun.objects.filter(
            channel_id=channel_id,
            status=RunStatus.COMPLETED,
            script_embedding__isnull=False,
        )
        .exclude(id=exclude_run_id)
        .order_by('-finished_at')[:limit]
    ):
        embeddings.append(run.script_embedding)
    return embeddings


_SIMILARITY_RETRY_HINT = (
    'Your previous draft was too similar to a recent video on this '
    'channel. Use a different structure, different examples, and '
    'different phrasing throughout.'
)
```

Replace `ScriptStage.run` body with:
```python
    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Write a full script for all chapters from outline + research."""
        output = await _generate_script(ctx)
        combined_text = ' '.join(ch.text for ch in output.chapters)
        new_vec = await embed_text(combined_text)
        recent_vecs = await _recent_script_embeddings(
            str(ctx.channel.id),
            str(ctx.run.id),
        )
        too_similar = is_too_similar(new_vec, recent_vecs)

        if too_similar and getattr(ctx.channel, 'publish_mode', '') == 'auto':
            output = await _generate_script(ctx, extra_hint=_SIMILARITY_RETRY_HINT)
            combined_text = ' '.join(ch.text for ch in output.chapters)
            new_vec = await embed_text(combined_text)
            too_similar = is_too_similar(new_vec, recent_vecs)

        ctx.run.script_embedding = new_vec
        await ctx.run.asave(update_fields=['script_embedding'])

        result = output.model_dump()
        result['similarity_flag'] = too_similar
        return result
```

Remove the now-unused inline prompt-building code that previously lived directly in
`run()` (it has moved into `_generate_script`).

- [ ] **Step 6: Update the pre-existing script test for the new return shape**

`test_script_run_returns_chapters_and_word_count` calls `ScriptStage().run(ctx)` while
only patching `llm.run_agent` — it now also needs `embed_text` and
`_recent_script_embeddings` patched (or it will hit real network/DB calls). Update it:

```python
def test_script_run_returns_chapters_and_word_count() -> None:
    """run() returns dict with 'chapters' and 'total_word_count'."""
    from server.apps.pipelines.schemas import ScriptChapter, ScriptOutput

    ctx = _make_ctx()
    ctx.run.asave = AsyncMock()
    fake_output = ScriptOutput(
        chapters=[
            ScriptChapter(
                idx=0,
                title='Intro',
                text='Rome was great.',
                word_count=3,
                closing_line='But it fell.',
                commentary='I think Rome\'s fall was avoidable, not inevitable.',
            ),
        ],
        total_word_count=3,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.script.embed_text',
                new=AsyncMock(return_value=[1.0, 0.0]),
            ),
            patch(
                'server.apps.pipelines.stages.script._recent_script_embeddings',
                new=AsyncMock(return_value=[]),
            ),
        ):
            return await ScriptStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'chapters' in result
    assert result['total_word_count'] == 3
    assert result['similarity_flag'] is False
```

Also add `ctx.channel.id = 'chan-script-1'` and `ctx.run.id = 'run-script-1'` to
`_make_ctx()` in this test file if not already present (needed since `run()` now calls
`str(ctx.channel.id)` / `str(ctx.run.id)` — on a bare `MagicMock` this already works
because `MagicMock()` attributes stringify fine, so this is optional but keep IDs
explicit for readability).

- [ ] **Step 7: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_script.py tests/test_apps/test_pipelines/test_logic/ tests/test_apps/test_generation/test_embeddings.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add server/apps/generation/clients/embeddings.py server/apps/pipelines/logic/similarity.py server/apps/pipelines/models.py server/apps/pipelines/migrations/0008_*.py server/apps/pipelines/stages/script.py tests/test_apps/test_generation/test_embeddings.py tests/test_apps/test_pipelines/test_logic/ tests/test_apps/test_pipelines/test_stages/test_script.py
git commit -m "feat(pipelines): detect near-duplicate scripts via embedding similarity"
```

---

### Task 6: Review → Auto graduation criteria

**Files:**
- Modify: `server/apps/pipelines/models.py` (`PipelineRun`)
- Create migration: `just run makemigrations pipelines` (expect `0009_pipelinerun_had_manual_edits.py`)
- Modify: `server/apps/pipelines/services/run_review.py`
- Modify: `server/apps/channels/services.py`
- Modify: `server/apps/channels/logic/value_objects.py`
- Modify: `server/apps/channels/api/views.py`
- Modify: `server/apps/channels/api/urls.py`
- Test: `tests/test_apps/test_pipelines/test_run_review.py` (check exact existing
  filename for `run_review.py` tests first)
- Test: `tests/test_apps/test_channels/test_api.py`

**Interfaces:**
- Produces: `PipelineRun.had_manual_edits: bool`.
- Produces: `ChannelService.graduation_status(channel_id: str) -> GraduationStatusPayload`.
- Produces: `GraduationStatusPayload(clean_run_count: int, required_count: int, eligible: bool)`
  in `channels/logic/value_objects.py`.

- [ ] **Step 1: Add `PipelineRun.had_manual_edits`**

In `server/apps/pipelines/models.py`, add to `PipelineRun` after `is_paused`:
```python
    is_paused = models.BooleanField(default=False)
    had_manual_edits = models.BooleanField(default=False)
```

Run:
```bash
docker compose exec web python manage.py makemigrations pipelines
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration `0009_pipelinerun_had_manual_edits.py`; both exit 0.

- [ ] **Step 2: Write failing tests for the manual-edit flag**

`RunReviewService` is exercised through DMR API tests, not direct service-unit tests —
add to `tests/test_apps/test_pipelines/test_review_api.py`, which already has `channel`,
`blueprint`, `run`, `scene_breakdown_stage`, and `visual_prompts_stage` fixtures (see the
existing `test_patch_scene` at line 199 and `test_publish_metadata_get_and_patch` at
line 613 for the exact request shapes to mirror):

```python
@pytest.mark.django_db(transaction=True)
def test_patch_scene_sets_had_manual_edits(
    dmr_client: DMRClient,
    run: PipelineRun,
    scene_breakdown_stage: StageExecution,
    visual_prompts_stage: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """PATCH scene marks the run as having had a manual edit."""
    assert run.had_manual_edits is False

    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-scene-detail',
            kwargs={'run_id': run.id, 'scene_idx': 0},
        ),
        data={'narration_text': 'Updated narration text here now'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    run.refresh_from_db()
    assert run.had_manual_edits is True


@pytest.mark.django_db
def test_publish_metadata_patch_sets_had_manual_edits(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """PATCH publish-metadata marks the run as having had a manual edit."""
    StageExecution.objects.create(
        run=run,
        stage_key='metadata',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'title': 'Original title',
            'description': 'Original description',
            'tags': ['history'],
            'category': 'Education',
        },
    )
    assert run.had_manual_edits is False

    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-publish-metadata',
            kwargs={'run_id': run.id},
        ),
        data={'title': 'Updated title'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    run.refresh_from_db()
    assert run.had_manual_edits is True
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_review_api.py -v --no-cov -k had_manual_edits`
Expected: FAIL — `had_manual_edits` stays `False`.

- [ ] **Step 4: Implement in `run_review.py`**

In `server/apps/pipelines/services/run_review.py`, add a small helper:

```python
def _mark_manual_edit_sync(run_id: str) -> None:
    from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

    PipelineRun.objects.filter(id=uuid.UUID(run_id)).update(had_manual_edits=True)
```

Call it at the end of `patch_scene` (right before `board = get_storyboard(...)`) and at
the end of `patch_publish_metadata` (right before `return self.get_publish_metadata(...)`):

```python
    def patch_publish_metadata(
        self,
        run_id: str,
        payload: PublishMetadataPatchPayload,
    ) -> PublishMetadataPayload:
        """Merge edits into metadata stage output."""
        meta_exec = _latest_parent_execution(run_id, 'metadata')
        if meta_exec is None:
            msg = 'metadata stage output is not available'
            raise ValidationError(msg)
        meta = dict(meta_exec.output)
        if payload.title is not None:
            meta['title'] = payload.title
        if payload.description is not None:
            meta['description'] = payload.description
        if payload.tags is not None:
            meta['tags'] = payload.tags
        if payload.category is not None:
            meta['category'] = payload.category
        if payload.thumbnail_asset_id is not None:
            meta['thumbnail_asset_id'] = payload.thumbnail_asset_id
        meta_exec.output = meta
        meta_exec.save(update_fields=['output'])
        _mark_manual_edit_sync(run_id)
        return self.get_publish_metadata(run_id)
```

And in `patch_scene`, add `_mark_manual_edit_sync(run_id)` right after the
`with transaction.atomic():` block closes, before `board = get_storyboard(...)`.

- [ ] **Step 5: Run the run_review tests, fix, confirm pass**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_review_api.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 6: Write the failing test for `ChannelService.graduation_status`**

`ChannelService` has no dedicated direct-unit-test file today (its existing coverage
comes entirely through `tests/test_apps/test_channels/test_api.py`'s DMR-level tests).
Create `tests/test_apps/test_channels/test_services.py` for this first direct
service-level test:

```python
@pytest.mark.django_db
def test_graduation_status_counts_consecutive_clean_completed_runs() -> None:
    """graduation_status counts trailing COMPLETED runs with no manual edits."""
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
    )

    channel = Channel.objects.create(name='Grad Ch', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='grad_test_v1', kind=PipelineKind.LONGFORM, graph={'stages': []},
    )
    for _ in range(3):
        PipelineRun.objects.create(
            channel=channel, blueprint=bp, blueprint_snapshot={}, topic='clean',
            status=RunStatus.COMPLETED, had_manual_edits=False,
        )
    PipelineRun.objects.create(
        channel=channel, blueprint=bp, blueprint_snapshot={}, topic='dirty',
        status=RunStatus.COMPLETED, had_manual_edits=True,
    )

    status = ChannelService().graduation_status(str(channel.id))
    assert status.clean_run_count == 3
    assert status.required_count == 10
    assert status.eligible is False


@pytest.mark.django_db
def test_graduation_status_eligible_at_threshold() -> None:
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
    )

    channel = Channel.objects.create(name='Grad Ch 2', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='grad_test_v2', kind=PipelineKind.LONGFORM, graph={'stages': []},
    )
    for _ in range(10):
        PipelineRun.objects.create(
            channel=channel, blueprint=bp, blueprint_snapshot={}, topic='clean',
            status=RunStatus.COMPLETED, had_manual_edits=False,
        )

    status = ChannelService().graduation_status(str(channel.id))
    assert status.eligible is True
```

Run: `docker compose exec web pytest tests/test_apps/test_channels/ -v --no-cov -k graduation`
Expected: FAIL — `graduation_status` doesn't exist.

- [ ] **Step 7: Implement `graduation_status`**

In `server/apps/channels/logic/value_objects.py`, add:
```python
class GraduationStatusPayload(msgspec.Struct, frozen=True):
    """Review-to-auto graduation progress for a channel."""

    clean_run_count: int
    required_count: int
    eligible: bool
```

In `server/apps/channels/services.py`, add a module constant near the top and a new
method on `ChannelService`:
```python
_GRADUATION_REQUIRED_RUNS = 10
```
```python
    def graduation_status(self, channel_id: str) -> GraduationStatusPayload:
        """Count consecutive trailing clean COMPLETED runs for a channel."""
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineRun,
            RunStatus,
        )

        clean_count = 0
        runs = PipelineRun.objects.filter(
            channel_id=uuid.UUID(channel_id),
            status=RunStatus.COMPLETED,
        ).order_by('-finished_at').values_list('had_manual_edits', flat=True)
        for had_edits in runs:
            if had_edits:
                break
            clean_count += 1
        return GraduationStatusPayload(
            clean_run_count=clean_count,
            required_count=_GRADUATION_REQUIRED_RUNS,
            eligible=clean_count >= _GRADUATION_REQUIRED_RUNS,
        )
```

Add `GraduationStatusPayload` to the existing import block from
`server.apps.channels.logic.value_objects` at the top of `services.py`.

- [ ] **Step 8: Expose via API**

In `server/apps/channels/api/views.py`, add a new controller near
`ChannelDetailController`:
```python
@final
class ChannelGraduationStatusController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return review-to-auto graduation progress for a channel."""

    auth = (jwt_sync_auth,)

    def get(self) -> GraduationStatusPayload:
        """Return graduation status; does not change publish_mode."""
        return self.resolve(ChannelService).graduation_status(
            str(self.kwargs['channel_id']),
        )
```
Add `GraduationStatusPayload` to the existing `from server.apps.channels.logic.value_objects import (...)` block in this file.

In `server/apps/channels/api/urls.py`, add to the `channel_urlpatterns` list (matching
the existing `channel-branding` entry's exact style), right after the
`channel-branding` entry:
```python
    path(
        'channels/<uuid:channel_id>/graduation-status/',
        views.ChannelGraduationStatusController.as_view(),
        name='channel-graduation-status',
    ),
```

- [ ] **Step 9: Write the API test**

Add to `tests/test_apps/test_channels/test_api.py`, following the file's existing
`channel` fixture and `dmr_client`/`auth_headers` pattern (seen in the file's existing
`test_list_channels`):

```python
@pytest.mark.django_db
def test_graduation_status_endpoint(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.get(
        reverse(
            'api:channels_api:channel-graduation-status',
            kwargs={'channel_id': str(channel.id)},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['clean_run_count'] == 0
    assert body['required_count'] == 10
    assert body['eligible'] is False
```

- [ ] **Step 10: Run everything, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_channels/ tests/test_apps/test_pipelines/ --no-cov -v`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100` (full suite with coverage,
project-wide gate per `CLAUDE.md`)
Expected: passes at 100% coverage, or identifies any line this task left uncovered —
add a covering test for anything flagged.

Run: `docker compose exec web ruff check . && docker compose exec web ruff format --check . && docker compose exec web mypy server && docker compose exec web lint-imports`
Expected: all clean.

- [ ] **Step 11: Commit**

```bash
git add server/apps/pipelines/models.py server/apps/pipelines/migrations/0009_*.py server/apps/pipelines/services/run_review.py server/apps/channels/services.py server/apps/channels/logic/value_objects.py server/apps/channels/api/views.py server/apps/channels/api/urls.py tests/
git commit -m "feat(channels): add review-to-auto graduation status tracking"
```

---

### Task 7: Cross-channel differentiation floor

**Files:**
- Modify: `server/apps/channels/logic/value_objects.py` (`ChannelBrandingPayload`)
- Modify: `server/apps/channels/selectors.py:164-185` (`get_channel_branding`)
- Test: `tests/test_apps/test_channels/test_api.py`

**Interfaces:**
- Produces: `ChannelBrandingPayload.warnings: list[str]` (new field).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_apps/test_channels/test_api.py`, using the file's existing fixtures:

```python
@pytest.mark.django_db
def test_branding_warns_when_identical_to_another_channel(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    from server.apps.channels.models import ChannelBranding

    channel_a = Channel.objects.create(name='Warn A', kind=ChannelKind.LONGFORM)
    channel_b = Channel.objects.create(name='Warn B', kind=ChannelKind.LONGFORM)
    ChannelBranding.objects.create(
        channel=channel_a,
        watermark_position='top_left',
    )
    ChannelBranding.objects.create(
        channel=channel_b,
        watermark_position='top_left',
    )

    response = dmr_client.get(
        reverse(
            'api:channels_api:channel-branding',
            kwargs={'channel_id': str(channel_b.id)},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['warnings']
    assert 'Warn A' in body['warnings'][0]


@pytest.mark.django_db
def test_branding_no_warning_for_default_empty_branding(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Two channels with no branding set (all-default) should not warn each other."""
    other = Channel.objects.create(name='Other Default', kind=ChannelKind.LONGFORM)
    from server.apps.channels.models import ChannelBranding

    ChannelBranding.objects.create(channel=other)

    response = dmr_client.get(
        reverse(
            'api:channels_api:channel-branding',
            kwargs={'channel_id': str(channel.id)},
        ),
        headers=auth_headers,
    )
    assert response.json()['warnings'] == []
```

(`'api:channels_api:channel-branding'` matches the existing `name='channel-branding'`
registration in `channels/api/urls.py`.)

Run: `docker compose exec web pytest tests/test_apps/test_channels/test_api.py -v --no-cov -k branding_warn`
Expected: FAIL — `KeyError: 'warnings'`.

- [ ] **Step 2: Add the field and computation**

In `server/apps/channels/logic/value_objects.py`, add `warnings` to
`ChannelBrandingPayload`:
```python
class ChannelBrandingPayload(msgspec.Struct, frozen=True):
    """Branding assets attached to a channel."""

    channel_id: str
    intro_asset_id: str | None
    outro_asset_id: str | None
    watermark_asset_id: str | None
    watermark_position: str
    watermark_opacity: float
    caption_style_asset_id: str | None
    font_asset_ids: list[str]
    music_pool_tags: list[str]
    thumbnail_palette: dict[str, str]
    warnings: list[str]
```

In `server/apps/channels/selectors.py`, add two helpers above `get_channel_branding`:
```python
def _branding_fingerprint(branding: ChannelBranding) -> tuple[object, ...]:
    return (
        branding.intro_id,
        branding.outro_id,
        branding.watermark_id,
        branding.watermark_position,
        tuple(sorted(str(f.id) for f in branding.fonts.all())),
    )


def _branding_warnings(
    channel: Channel,
    branding: ChannelBranding,
) -> list[str]:
    """Warn when another channel's branding is fingerprint-identical."""
    fingerprint = _branding_fingerprint(branding)
    is_all_default = fingerprint == (
        None, None, None, branding.watermark_position, (),
    )
    if is_all_default:
        return []
    others = (
        ChannelBranding.objects
        .exclude(channel_id=channel.id)
        .select_related('channel')
        .prefetch_related('fonts')
    )
    return [
        (
            f'Branding matches channel "{other.channel.name}" exactly — '
            'consider varying watermark, fonts, or intro/outro to reduce '
            'operator-linkage risk between channels.'
        )
        for other in others
        if _branding_fingerprint(other) == fingerprint
    ]
```

Update `get_channel_branding`'s return statement to include:
```python
        warnings=_branding_warnings(channel, branding),
```
as the last field.

- [ ] **Step 3: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_channels/ -v --no-cov`
Expected: all PASS — including the two new tests and every pre-existing branding test
(which now needs the response body to include a `warnings` key; if any existing test
asserts an exact response dict rather than checking individual keys, it will need
`'warnings': []` added — search the file for existing branding-response assertions and
update accordingly).

Run: `docker compose exec web pytest --cov-fail-under=100`
Expected: 100% coverage maintained.

Run: `docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add server/apps/channels/logic/value_objects.py server/apps/channels/selectors.py tests/test_apps/test_channels/test_api.py
git commit -m "feat(channels): warn when branding is identical across channels"
```

---

## Final Verification (after Task 7)

- [ ] Run the full suite with coverage: `docker compose exec web pytest` (must pass at
  100% coverage per `CLAUDE.md`).
- [ ] Run `docker compose exec web ruff check .`, `docker compose exec web ruff format --check .`, `docker compose exec web mypy server`, `docker compose exec web lint-imports`.
- [ ] Run `docker compose exec web python manage.py lintmigrations` and
  `docker compose exec web python manage.py check_migrations --exclude-apps=axes` across
  all migrations added by this plan (prompts `0003`, channels `0005`, pipelines
  `0007`–`0009`).
- [ ] Manually drive one `longform_v1` run end-to-end (via `just run shell` or the API)
  against a channel with a 2-entry `StoryFormat` pool and `max_publishes_per_day=1`, and
  confirm: the outline stage records a `format_key`, the script stage returns
  non-empty `commentary` per chapter and a `similarity_flag`, and a second run on the
  same day parks at `PUBLISH_HOLD` instead of publishing.
- [ ] Hand off to `superpowers:requesting-code-review` for the final whole-branch review
  once all 7 tasks are committed, then `superpowers:finishing-a-development-branch`.
