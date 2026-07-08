# Differentiation & Creative Moat (Milestone 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each channel a recognizable-but-never-identical creative identity, catch
weak scripts before expensive render spend, raise the factual rigor of research, and
close the loop from real per-second audience retention data back into how future videos
are paced — the parts of the system that are genuinely hard for a generic AI-slideshow
tool to copy.

**Architecture:** A new LLM-judge stage (`narrative_qc`, same `Stage`/`pydantic_ai.Agent`
shape as `research`/`outline`/`script`/`scene_breakdown`), a new per-channel
`AssemblyStyleConfig` model (same shape as the existing `ChannelBranding`) wired into the
already-fanned-out `motion` stage and the `assembly`/`ffmpeg` rendering path, a
multi-source corroboration validator on the `research` stage (same `ModelRetry` pattern
used throughout `pipelines/stages/`), and a retention-curve aggregation service that
reads `PublishJobMetric.retention_curve` (from Milestone 2) and feeds a "known soft
spots" summary into the `outline` stage's prompt.

**Tech Stack:** Django 6.0, `pydantic-ai`, FFmpeg (via the existing
`server/apps/rendering/ffmpeg.py` async-subprocess wrapper), `pytest`.

**Prerequisites:** This plan assumes both
`docs/superpowers/plans/2026-07-07-policy-risk-mitigations.md` (Milestone 1 — for
`ScriptChapter.commentary`, used by Task 1's scoring) and
`docs/superpowers/plans/2026-07-07-money-loop-foundations.md` (Milestone 2 — for
`PublishJobMetric.retention_curve`, used by Task 5) are already merged. Migration numbers
below are illustrative; `just makemigrations` assigns the real next number.

**Full design context:** `/Users/chuckz/.claude/plans/the-clipping-feature-is-misty-rossum.md`
(sections 3.1–3.4) — read this for the "why."

## Global Constraints

- Same repo-wide gate as Milestones 1 and 2: Python 3.13.x, Django 6.0.x, `ruff`, `mypy`
  strict, 100% coverage, migrations via `just run makemigrations <app>` +
  `lintmigrations` + `check_migrations --exclude-apps=axes`, `@final` +
  `@attrs.define(slots=True, frozen=True)` for services, `msgspec.Struct(frozen=True)`
  DTOs, never `from __future__ import annotations` in punq-registered files.
- **Failure-handling consistency:** `narrative_qc` (Task 1) follows the exact same
  failure convention as the existing `qc` stage (`pipelines/stages/qc.py`) — on a failed
  check it raises `FatalProviderError`, which the orchestrator turns into `NEEDS_INPUT`,
  requiring a human to inspect and manually rerun the upstream stage. This plan does
  **not** add new auto-rerun orchestration logic; that would be a larger, separate change
  and isn't needed for the gate to be valuable (it already saves render spend by sitting
  before `image_gen`/`motion`/`tts`, regardless of who triggers the rerun).
- Tasks 2 and 3 both extend `AssemblyStyleConfig` and are sequenced back-to-back; Task 5
  depends on Milestone 2's `PublishJobMetric` model already existing. Implement in order
  1 → 5.
- Run `docker compose exec web pytest <touched paths> --no-cov` after each task's
  implementation, `docker compose exec web pytest --cov-fail-under=100` before that
  task's final commit, and `ruff check .` / `ruff format --check .` / `mypy server` /
  `lint-imports` before every commit.

---

### Task 1: Narrative QC gate

**Files:**
- Create: `server/apps/pipelines/stages/narrative_qc.py`
- Modify: `server/apps/pipelines/schemas.py` — add `NarrativeQCOutput`
- Modify: `server/apps/pipelines/management/commands/seed_blueprints.py` — insert the
  stage into `_LONGFORM_V1_GRAPH`
- Test: `tests/test_apps/test_pipelines/test_stages/test_narrative_qc.py`
- Test: `tests/test_apps/test_pipelines/test_management/test_seed_blueprints.py` (check
  exact filename first)

**Interfaces:**
- Produces: `NarrativeQCOutput(passed: bool, score: float, issues: list[str])`,
  registered stage key `narrative_qc`, `depends_on: ['scene_breakdown']`; `visual_prompts`
  and `tts` both move their `depends_on` from `scene_breakdown` to `narrative_qc`.

- [ ] **Step 1: Add the output schema**

In `server/apps/pipelines/schemas.py`, add after `SceneBreakdownOutput`:
```python
class NarrativeQCOutput(BaseModel):
    """LLM-judge score for a script + scene breakdown, before expensive render spend."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = pydantic.Field(default_factory=list)
```
(Check the top of `schemas.py` for how `Field`/`pydantic` are already imported — the
file currently does `from pydantic import BaseModel, Field, model_validator`, so use
`Field(default_factory=list)` directly, matching `VisualPrompt.negative_prompt`-style
defaults already in the file, not `pydantic.Field`.)

- [ ] **Step 2: Write the failing stage test**

Create `tests/test_apps/test_pipelines/test_stages/test_narrative_qc.py`:
```python
"""Tests for the narrative_qc stage (pre-render creative quality gate)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.narrative_qc import NarrativeQCStage
from server.common.exceptions import FatalProviderError


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.upstream = {
        'script': {
            'chapters': [
                {
                    'idx': 0, 'title': 'Intro', 'text': 'Rome was great.',
                    'word_count': 3, 'closing_line': 'But it fell.',
                    'commentary': 'I think this collapse was avoidable.',
                },
            ],
            'total_word_count': 3,
        },
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': 0, 'chapter_idx': 0, 'beat': 'intro',
                    'narration_text': 'Rome was great once, long ago.',
                    'visual_concept': 'aerial Rome', 'shot_type': 'aerial',
                    'est_seconds': 8.0, 'is_hero': True,
                    'foreground_cast': [], 'word_count': 20,
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_narrative_qc_stage_key() -> None:
    assert NarrativeQCStage.key == 'narrative_qc'
    assert NarrativeQCStage.queue == 'api'


def test_narrative_qc_fan_out_none() -> None:
    assert NarrativeQCStage().fan_out(MagicMock()) is None


def test_narrative_qc_passes_through_on_high_score() -> None:
    from server.apps.pipelines.schemas import NarrativeQCOutput

    ctx = _make_ctx()
    fake_output = NarrativeQCOutput(passed=True, score=0.85, issues=[])

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await NarrativeQCStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['passed'] is True
    assert result['score'] == 0.85


def test_narrative_qc_raises_fatal_error_on_failed_score() -> None:
    from server.apps.pipelines.schemas import NarrativeQCOutput

    ctx = _make_ctx()
    fake_output = NarrativeQCOutput(
        passed=False, score=0.2, issues=['weak hook', 'no retention loops'],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await NarrativeQCStage().run(ctx)

    with pytest.raises(FatalProviderError, match='narrative_qc'):
        asyncio.run(_inner())
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_narrative_qc.py -v --no-cov`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the stage**

Create `server/apps/pipelines/stages/narrative_qc.py`:
```python
"""Narrative QC stage — LLM-judge creative quality gate before expensive render spend.

Sits between scene_breakdown and visual_prompts/tts. Follows the same failure
convention as the technical `qc` stage: on failure it raises
FatalProviderError (-> NEEDS_INPUT), requiring a human to inspect and rerun
upstream stages. It does not auto-retry script generation itself.
"""

from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL
from server.apps.pipelines.schemas import NarrativeQCOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_PASS_THRESHOLD = 0.5


@cache
def _agent() -> Agent[StageContext, NarrativeQCOutput]:
    """Create and cache the narrative QC agent on first call."""
    a: Agent[StageContext, NarrativeQCOutput] = Agent(
        PYDANTIC_AI_MODEL,
        output_type=NarrativeQCOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render('narrative_qc', {})
        return sys or (
            'You are a documentary editorial quality judge. Score this '
            "script + scene breakdown 0.0-1.0 on: (1) does the first 30s "
            'hook restate a real payoff, (2) is there a genuine retention '
            'device (beat, reveal, or question) roughly every 15-30s, '
            '(3) does each chapter\'s commentary read as real analysis, '
            'not filler that just restates the narration. passed=true only '
            'if score >= 0.5. List specific issues for anything weak.'
        )

    return a


@register_stage
class NarrativeQCStage(Stage):
    """Pre-render creative quality gate."""

    key = 'narrative_qc'
    queue = 'api'
    max_retries = 3
    timeout_s = 180

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Score the script + scene breakdown; raise on failure."""
        script = ctx.upstream.get('script', {})
        scenes = ctx.upstream.get('scene_breakdown', {})

        _, usr = await ctx.prompts.render(
            'narrative_qc',
            {'topic': ctx.run.topic, 'script': script, 'scene_breakdown': scenes},
        )
        user_prompt = usr or (
            f'Topic: "{ctx.run.topic}"\n'
            f'Script chapters (with commentary): {script.get("chapters", [])}\n'
            f'Scene breakdown: {scenes.get("scenes", [])}\n'
            'Score this and list issues.'
        )
        output: NarrativeQCOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
        )

        if not output.passed or output.score < _PASS_THRESHOLD:
            raise FatalProviderError(
                f'narrative_qc failed: score={output.score:.2f} '
                f'issues={output.issues}',
                provider='narrative_qc',
                error_code='NARRATIVE_QC_FAILED',
            )
        return output.model_dump()
```

- [ ] **Step 4: Run the stage tests, fix**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_narrative_qc.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Insert the stage into `longform_v1`'s blueprint graph**

In `server/apps/pipelines/management/commands/seed_blueprints.py`, in
`_LONGFORM_V1_GRAPH`, change:
```python
        {'key': 'scene_breakdown', 'depends_on': ['script'], 'queue': 'api'},
        {
            'key': 'visual_prompts',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
```
to:
```python
        {'key': 'scene_breakdown', 'depends_on': ['script'], 'queue': 'api'},
        {
            'key': 'narrative_qc',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'visual_prompts',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
        },
```
and change the `tts` node's `depends_on`:
```python
        {
            'key': 'tts',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
```
to:
```python
        {
            'key': 'tts',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
```
(`music_plan` also currently depends on `scene_breakdown` directly — leave it as-is,
since music selection doesn't need to wait on the QC judgment, and `assembly`'s own
`depends_on` list is unaffected since it already depends on `motion`/`tts`/`alignment`/
`music_plan`, which now transitively depend on `narrative_qc` having succeeded via `tts`
and `visual_prompts` → `image_gen` → `motion`.)

Find the exact filename for `seed_blueprints`'s existing tests
(`find tests -iname '*seed_blueprint*'`) and add a test asserting the new dependency
edges, following that file's existing style for asserting on `_LONGFORM_V1_GRAPH` (or on
the `PipelineBlueprint` row after running the command):
```python
def test_longform_v1_graph_includes_narrative_qc_between_breakdown_and_visuals() -> None:
    from server.apps.pipelines.management.commands.seed_blueprints import (
        _LONGFORM_V1_GRAPH,
    )

    by_key = {node['key']: node for node in _LONGFORM_V1_GRAPH['stages']}
    assert by_key['narrative_qc']['depends_on'] == ['scene_breakdown']
    assert by_key['visual_prompts']['depends_on'] == ['narrative_qc']
    assert by_key['tts']['depends_on'] == ['narrative_qc']
```

- [ ] **Step 6: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/ -v --no-cov -k "narrative_qc or seed_blueprint"`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add server/apps/pipelines/stages/narrative_qc.py server/apps/pipelines/schemas.py server/apps/pipelines/management/commands/seed_blueprints.py tests/
git commit -m "feat(pipelines): add pre-render narrative QC gate (script quality before spend)"
```

**Rollout note (not a code step):** after this merges, run
`docker compose exec web python manage.py seed_blueprints` in each environment to push
the updated `longform_v1` graph — existing in-flight `PipelineRun`s are unaffected (they
keep their `blueprint_snapshot` from creation time, per the architecture's snapshot
design); only runs created after the reseed pick up `narrative_qc`.

---

### Task 2: `AssemblyStyleConfig` — per-channel camera-movement pool

**Files:**
- Create: `server/apps/channels/models.py` — add `AssemblyStyleConfig` (append to file)
- Create migration: `just run makemigrations channels`
- Modify: `server/apps/channels/logic/value_objects.py`
- Modify: `server/apps/channels/services.py`
- Modify: `server/apps/pipelines/stages/motion.py`
- Test: `tests/test_apps/test_channels/test_models.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_motion.py`

**Interfaces:**
- Produces: `AssemblyStyleConfig` model (`camera_movements: list[str]`,
  `transition_styles: list[str]`, `sfx_pool_tags: list[str]`, `target_cuts_per_minute:
  tuple`), `motion.py::_pick_camera_movement(pool, scene_idx) -> str`.

- [ ] **Step 1: Add the model**

In `server/apps/channels/models.py`, append after `ChannelBranding`:
```python
_DEFAULT_CAMERA_MOVEMENTS = ['push_in', 'pan_left', 'pan_right', 'static_hold']
_DEFAULT_TRANSITION_STYLES = ['hard_cut', 'cross_dissolve']


class AssemblyStyleConfig(UUIDModel):
    """Per-channel cinematic fingerprint: camera movement, transitions, SFX, pacing."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name='assembly_style',
    )
    camera_movements = ArrayField(
        models.CharField(max_length=30),
        default=list,
        blank=True,
    )
    transition_styles = ArrayField(
        models.CharField(max_length=30),
        default=list,
        blank=True,
    )
    sfx_pool_tags = ArrayField(
        models.CharField(max_length=40),
        default=list,
        blank=True,
    )
    min_cuts_per_minute = models.PositiveSmallIntegerField(default=4)
    max_cuts_per_minute = models.PositiveSmallIntegerField(default=8)

    @override
    def __str__(self) -> str:
        return f'AssemblyStyleConfig for {self.channel}'
```
(`ArrayField` and `models` are already imported at the top of this file; `Channel` is
already defined above in the same module.)

Run:
```bash
docker compose exec web python manage.py makemigrations channels
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: new migration; both exit 0.

- [ ] **Step 2: Add DTOs and a selector-level default**

In `server/apps/channels/logic/value_objects.py`, add:
```python
class AssemblyStyleConfigPayload(msgspec.Struct, frozen=True):
    """Per-channel cinematic style pool."""

    channel_id: str
    camera_movements: list[str]
    transition_styles: list[str]
    sfx_pool_tags: list[str]
    min_cuts_per_minute: int
    max_cuts_per_minute: int


class AssemblyStyleConfigPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a channel's assembly style config."""

    camera_movements: list[str] | None = None
    transition_styles: list[str] | None = None
    sfx_pool_tags: list[str] | None = None
    min_cuts_per_minute: int | None = None
    max_cuts_per_minute: int | None = None
```

In `server/apps/channels/services.py`, add a `get_or_create`-then-patch method (mirroring
`patch_branding`'s exact shape) and its matching selector-style getter. Add these methods
to `ChannelService`:
```python
    def get_assembly_style(self, channel_id: str) -> AssemblyStyleConfigPayload:
        """Return the channel's assembly style config, creating defaults if missing."""
        channel = Channel.objects.get(id=uuid.UUID(channel_id))
        style, created = AssemblyStyleConfig.objects.get_or_create(
            channel=channel,
            defaults={
                'camera_movements': list(_DEFAULT_CAMERA_MOVEMENTS),
                'transition_styles': list(_DEFAULT_TRANSITION_STYLES),
            },
        )
        return AssemblyStyleConfigPayload(
            channel_id=str(channel.id),
            camera_movements=list(style.camera_movements),
            transition_styles=list(style.transition_styles),
            sfx_pool_tags=list(style.sfx_pool_tags),
            min_cuts_per_minute=style.min_cuts_per_minute,
            max_cuts_per_minute=style.max_cuts_per_minute,
        )

    def patch_assembly_style(
        self,
        channel_id: str,
        payload: AssemblyStyleConfigPatchPayload,
    ) -> AssemblyStyleConfigPayload:
        """Update a channel's assembly style pool."""
        channel = Channel.objects.get(id=uuid.UUID(channel_id))
        style, _ = AssemblyStyleConfig.objects.get_or_create(channel=channel)
        update_fields = _apply_patch_fields(
            style,
            payload,
            (
                'camera_movements', 'transition_styles', 'sfx_pool_tags',
                'min_cuts_per_minute', 'max_cuts_per_minute',
            ),
        )
        if update_fields:
            style.save(update_fields=update_fields)
        return self.get_assembly_style(channel_id)
```
Add `AssemblyStyleConfig`, `_DEFAULT_CAMERA_MOVEMENTS`, `_DEFAULT_TRANSITION_STYLES` to
the existing `from server.apps.channels.models import (...)` import block, and
`AssemblyStyleConfigPayload`, `AssemblyStyleConfigPatchPayload` to the
`value_objects` import block, at the top of `services.py`. `_apply_patch_fields` is
already a generic helper defined in this file (used by `patch`/`patch_branding`) — no
change needed to it.

- [ ] **Step 3: Write the failing model/service tests**

Add to `tests/test_apps/test_channels/test_models.py`:
```python
@pytest.mark.django_db
def test_assembly_style_config_defaults_and_str() -> None:
    from server.apps.channels.models import AssemblyStyleConfig, Channel, ChannelKind

    channel = Channel.objects.create(name='Style Ch', kind=ChannelKind.LONGFORM)
    style = AssemblyStyleConfig.objects.create(channel=channel)
    assert style.min_cuts_per_minute == 4
    assert style.max_cuts_per_minute == 8
    assert 'Style Ch' in str(style)
```

Add to `tests/test_apps/test_channels/test_services.py` (created by Milestone 1's
Task 6 — if this plan is implemented before Milestone 1, create it following the same
`@final @attrs.define` `ChannelService()` direct-instantiation pattern used in that
task):
```python
@pytest.mark.django_db
def test_get_assembly_style_creates_defaults() -> None:
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService

    channel = Channel.objects.create(name='Get Style Ch', kind=ChannelKind.LONGFORM)
    payload = ChannelService().get_assembly_style(str(channel.id))
    assert payload.camera_movements == ['push_in', 'pan_left', 'pan_right', 'static_hold']
    assert payload.transition_styles == ['hard_cut', 'cross_dissolve']


@pytest.mark.django_db
def test_patch_assembly_style_updates_pool() -> None:
    from server.apps.channels.logic.value_objects import (
        AssemblyStyleConfigPatchPayload,
    )
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.channels.services import ChannelService

    channel = Channel.objects.create(name='Patch Style Ch', kind=ChannelKind.LONGFORM)
    result = ChannelService().patch_assembly_style(
        str(channel.id),
        AssemblyStyleConfigPatchPayload(camera_movements=['push_in']),
    )
    assert result.camera_movements == ['push_in']
```

Run: `docker compose exec web pytest tests/test_apps/test_channels/ -v --no-cov -k assembly_style`
Expected: FAIL until Steps 1-2 land, then PASS.

- [ ] **Step 4: Write the failing motion-stage test**

Add to `tests/test_apps/test_pipelines/test_stages/test_motion.py` (reusing the file's
existing `_make_ctx()`):
```python
def test_pick_camera_movement_cycles_through_pool_by_scene_idx() -> None:
    from server.apps.pipelines.stages.motion import _pick_camera_movement

    pool = ['push_in', 'pan_left', 'static_hold']
    assert _pick_camera_movement(pool, scene_idx=0) == 'push_in'
    assert _pick_camera_movement(pool, scene_idx=1) == 'pan_left'
    assert _pick_camera_movement(pool, scene_idx=3) == 'push_in'


def test_pick_camera_movement_empty_pool_returns_default() -> None:
    from server.apps.pipelines.stages.motion import _pick_camera_movement

    assert _pick_camera_movement([], scene_idx=0) == 'push_in'
```

Also update `_make_ctx()` (or add a new test) to confirm the Kling prompt for a hero
scene incorporates the channel's camera-movement pool:
```python
def test_motion_run_hero_scene_uses_channel_camera_movement() -> None:
    ctx = _make_ctx()
    ctx.channel.assembly_style_camera_movements = ['pan_right']
    ctx.execution.input_snapshot = {
        'scene_idx': 0, 'is_hero': True, 'est_seconds': 5.0,
        'image_url': 'https://img.example.com/0.jpg', 'visual_concept': 'aerial shot',
    }
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='asset-vid'))

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.motion.fal_client'
                '.generate_video_kling',
                new=AsyncMock(return_value={'video_url': 'https://v.example.com/0.mp4'}),
            ) as mock_kling,
            patch('httpx.AsyncClient.get') as mock_get,
        ):
            mock_get.return_value.__aenter__.return_value.content = b'video'
            mock_get.return_value.__aenter__.return_value.raise_for_status = (
                MagicMock()
            )
            result = await MotionStage().run(ctx)
            prompt = mock_kling.call_args.kwargs['prompt']
            assert 'pan_right' in prompt
            return result

    asyncio.run(_inner())
```
(Check `test_motion.py`'s existing hero-scene test for the exact httpx mocking pattern
already used there — mirror it exactly rather than reintroducing a slightly different
mock shape; the sketch above shows the intent, adjust the `httpx.AsyncClient.get` mock
wiring to match whatever pattern the file's existing
`test_motion_run_hero_scene_calls_kling`-equivalent test already uses.)

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_motion.py -v --no-cov -k camera_movement`
Expected: FAIL — `_pick_camera_movement` doesn't exist; channel prompt doesn't include a
movement descriptor.

- [ ] **Step 5: Implement in `motion.py`**

In `server/apps/pipelines/stages/motion.py`, add near `_KEN_BURNS_PRESETS`:
```python
_DEFAULT_CAMERA_MOVEMENT = 'push_in'
_MOVEMENT_PROMPT_PHRASES = {
    'push_in': 'Slow cinematic push-in',
    'pan_left': 'Smooth pan left',
    'pan_right': 'Smooth pan right',
    'static_hold': 'Static hold with subtle parallax',
}


def _pick_camera_movement(pool: list[str], scene_idx: int) -> str:
    """Cycle through the channel's camera-movement pool by scene index."""
    if not pool:
        return _DEFAULT_CAMERA_MOVEMENT
    return pool[scene_idx % len(pool)]
```

In `MotionStage.run`, change the hero branch's prompt construction:
```python
        if is_hero:
            model = ctx.config.get(
                'i2v_model',
                'fal-ai/kling-video/v2.1/standard/image-to-video',
            )
            movement_pool = getattr(
                ctx.channel, 'assembly_style_camera_movements', [],
            )
            movement = _pick_camera_movement(movement_pool, scene_idx)
            phrase = _MOVEMENT_PROMPT_PHRASES.get(
                movement, _MOVEMENT_PROMPT_PHRASES[_DEFAULT_CAMERA_MOVEMENT],
            )
            result = await fal_client.generate_video_kling(
                image_url=image_url,
                prompt=f'{phrase}. Cinematic motion. {visual_concept}',
                duration=5,
                model=model,
            )
```
(everything else in the hero branch is unchanged.)

Since `ctx.channel` is the real `Channel` ORM instance in production (not the
`AssemblyStyleConfig` row directly), add a small property-style accessor rather than
querying inside the stage on every call. Add to `server/apps/channels/models.py`'s
`Channel` class:
```python
    @property
    def assembly_style_camera_movements(self) -> list[str]:
        """Camera-movement pool from this channel's AssemblyStyleConfig, or []."""
        style = getattr(self, 'assembly_style', None)
        return list(style.camera_movements) if style else []
```
(`assembly_style` is the `related_name` from Step 1's `OneToOneField` — accessing it
raises `AssemblyStyleConfig.DoesNotExist` if no row exists yet, which `getattr(...,
None)` on a reverse one-to-one descriptor actually raises rather than returning `None`
by default in Django; catch that explicitly instead:)
```python
    @property
    def assembly_style_camera_movements(self) -> list[str]:
        """Camera-movement pool from this channel's AssemblyStyleConfig, or []."""
        from server.apps.channels.models import AssemblyStyleConfig  # noqa: PLC0415

        try:
            style = self.assembly_style
        except AssemblyStyleConfig.DoesNotExist:
            return []
        return list(style.camera_movements)
```
(Use this second version — the first is wrong about `getattr` swallowing
`RelatedObjectDoesNotExist` for reverse one-to-one accessors, which it does not.)

- [ ] **Step 6: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_channels/ tests/test_apps/test_pipelines/test_stages/test_motion.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add server/apps/channels/models.py server/apps/channels/migrations/*.py server/apps/channels/logic/value_objects.py server/apps/channels/services.py server/apps/pipelines/stages/motion.py tests/
git commit -m "feat(channels): per-channel camera-movement pool for hero-scene motion"
```

---

### Task 3: Sound-design layer + chapter transitions

**Files:**
- Modify: `server/apps/rendering/ffmpeg.py` — add SFX mixing + optional cross-dissolve
  chapter concat
- Modify: `server/apps/pipelines/stages/assembly.py`
- Test: `tests/test_apps/test_rendering/test_ffmpeg.py` (check exact filename first)
- Test: `tests/test_apps/test_pipelines/test_stages/test_assembly.py`

**Interfaces:**
- Produces: `ffmpeg.concat_chapter_with_transition(segment_paths, transition, duration_s, out_path)`
  (falls back to the existing `concat_chapter` for `transition == 'hard_cut'`),
  `ffmpeg.final_pass(..., sfx_paths=[], sfx_gains_db=[])` (new optional params, default
  `[]` — fully backward compatible with every existing caller).

- [ ] **Step 1: Write the failing pure-selection test**

Add to `tests/test_apps/test_pipelines/test_stages/test_assembly.py` (reusing the file's
existing fixtures/mocking style):
```python
def test_pick_transition_style_cycles_by_chapter_index() -> None:
    from server.apps.pipelines.stages.assembly import _pick_transition_style

    pool = ['hard_cut', 'cross_dissolve']
    assert _pick_transition_style(pool, chapter_idx=0) == 'hard_cut'
    assert _pick_transition_style(pool, chapter_idx=1) == 'cross_dissolve'
    assert _pick_transition_style(pool, chapter_idx=2) == 'hard_cut'


def test_pick_transition_style_empty_pool_returns_hard_cut() -> None:
    from server.apps.pipelines.stages.assembly import _pick_transition_style

    assert _pick_transition_style([], chapter_idx=0) == 'hard_cut'
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_assembly.py -v --no-cov -k transition_style`
Expected: FAIL — function doesn't exist.

- [ ] **Step 2: Implement `_pick_transition_style` in `assembly.py`**

In `server/apps/pipelines/stages/assembly.py`, add:
```python
_DEFAULT_TRANSITION = 'hard_cut'


def _pick_transition_style(pool: list[str], chapter_idx: int) -> str:
    """Cycle through the channel's transition-style pool by chapter index."""
    if not pool:
        return _DEFAULT_TRANSITION
    return pool[chapter_idx % len(pool)]
```

- [ ] **Step 3: Write the failing ffmpeg cross-dissolve test**

Find the exact test file for `rendering/ffmpeg.py`
(`find tests -path '*test_rendering*' -iname '*ffmpeg*'`) and add — following that
file's existing style for asserting on the constructed ffmpeg `cmd` list (it very likely
already patches `asyncio.create_subprocess_exec` and inspects `call_args` the same way
`motion`/`qc` tests do):
```python
def test_concat_chapter_with_transition_hard_cut_delegates_to_concat_chapter() -> None:
    """hard_cut transition uses the existing stream-copy concat_chapter path."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from server.apps.rendering.ffmpeg import concat_chapter_with_transition

    async def _inner() -> None:
        with patch(
            'server.apps.rendering.ffmpeg.concat_chapter',
            new=AsyncMock(),
        ) as mock_concat:
            await concat_chapter_with_transition(
                ['a.mp4', 'b.mp4'], transition='hard_cut',
                transition_duration_s=0.5, out_path='out.mp4',
            )
            mock_concat.assert_awaited_once_with(['a.mp4', 'b.mp4'], 'out.mp4')

    asyncio.run(_inner())


def test_concat_chapter_with_transition_cross_dissolve_builds_xfade_filter() -> None:
    """cross_dissolve builds a cascading xfade/acrossfade filter_complex."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.rendering.ffmpeg import concat_chapter_with_transition

    fake_probe = {'format': {'duration': '10.0'}}

    async def _inner() -> None:
        with (
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=fake_probe),
            ),
            patch(
                'asyncio.create_subprocess_exec',
                new=AsyncMock(),
            ) as mock_exec,
        ):
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b'', b''))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await concat_chapter_with_transition(
                ['a.mp4', 'b.mp4', 'c.mp4'], transition='cross_dissolve',
                transition_duration_s=0.5, out_path='out.mp4',
            )
            cmd = mock_exec.call_args.args
            assert '-filter_complex' in cmd
            fc = cmd[cmd.index('-filter_complex') + 1]
            assert 'xfade' in fc
            assert 'acrossfade' in fc

    asyncio.run(_inner())
```

Run: `docker compose exec web pytest tests/test_apps/test_rendering/ -v --no-cov -k transition`
Expected: FAIL — function doesn't exist.

- [ ] **Step 4: Implement `concat_chapter_with_transition` in `ffmpeg.py`**

In `server/apps/rendering/ffmpeg.py`, add after `concat_chapter`:
```python
async def _probe_duration(path: str) -> float:
    probe = await async_ffprobe(path)
    return float(probe.get('format', {}).get('duration', 0.0))


def _build_xfade_filter(
    durations: list[float],
    transition_duration_s: float,
) -> tuple[str, str, str]:
    """Cascading xfade/acrossfade filter_complex chain across N inputs.

    Returns (filter_complex, video_out_label, audio_out_label).
    """
    parts: list[str] = []
    cum = durations[0]
    v_prev = '[0:v]'
    a_prev = '[0:a]'
    for i in range(1, len(durations)):
        offset = max(cum - transition_duration_s, 0.0)
        v_out = f'[v{i}]'
        a_out = f'[a{i}]'
        parts.append(
            f'{v_prev}[{i}:v]xfade=transition=fade:'
            f'duration={transition_duration_s}:offset={offset:.3f}{v_out}',
        )
        parts.append(
            f'{a_prev}[{i}:a]acrossfade=d={transition_duration_s}{a_out}',
        )
        v_prev, a_prev = v_out, a_out
        cum += durations[i] - transition_duration_s
    return ';'.join(parts), v_prev, a_prev


async def concat_chapter_with_transition(
    segment_paths: list[str],
    transition: str,
    transition_duration_s: float,
    out_path: str,
) -> None:
    """Concatenate chapter files with a named transition between each pair.

    transition='hard_cut' delegates to the existing stream-copy concat_chapter
    (fast path, no re-encode). Any other transition name re-encodes using a
    cascading xfade/acrossfade filter_complex chain.

    Raises:
        RuntimeError: If FFmpeg exits with non-zero return code.
    """
    if transition == 'hard_cut' or len(segment_paths) < 2:  # noqa: PLR2004
        await concat_chapter(segment_paths, out_path)
        return

    durations = [await _probe_duration(p) for p in segment_paths]
    filter_complex, v_out, a_out = _build_xfade_filter(
        durations, transition_duration_s,
    )
    inputs: list[str] = []
    for p in segment_paths:
        inputs += ['-i', p]

    cmd = [
        'ffmpeg', '-y', *inputs,
        '-filter_complex', filter_complex,
        '-map', v_out, '-map', a_out,
        *_final_encode_args(out_path),
    ]
    await _run_ffmpeg_cmd(cmd)
```

- [ ] **Step 5: Add SFX mixing to `final_pass`**

In `server/apps/rendering/ffmpeg.py`, extend `_build_complex_filter` and `final_pass` to
accept an optional SFX track list, mixed the same way music already is. Change
`_build_complex_filter`'s signature and body:
```python
def _build_complex_filter(
    *,
    music_paths: list[str],
    music_gains_db: list[float],
    sfx_paths: list[str],
    sfx_gains_db: list[float],
    ass_path: str | None,
    watermark_path: str | None,
    wm_idx: int,
    loudnorm_af: str,
) -> tuple[str, str, str]:
    """Return (filter_complex, video_map, audio_map) for final_pass."""
    filter_parts: list[str] = []
    if watermark_path:
        filter_parts.append(
            f'[0:v][{wm_idx}:v]overlay=W-w-20:H-h-20:format=auto[vwm]',
        )
        v_out = '[vwm]'
    else:
        v_out = '[0:v]'

    if ass_path:
        filter_parts.append(f"{v_out}subtitles='{ass_path}'[vout]")
        v_out = '[vout]'

    extra_paths = music_paths + sfx_paths
    extra_gains = music_gains_db + sfx_gains_db
    if extra_paths:
        for i, gain_db in enumerate(extra_gains, start=1):
            gain_linear = 10 ** (gain_db / 20.0)
            filter_parts.append(f'[{i}:a]volume={gain_linear:.4f}[m{i}]')
        music_refs = ''.join(f'[m{i}]' for i in range(1, len(extra_paths) + 1))
        n = 1 + len(extra_paths)
        filter_parts.append(
            f'[0:a]{music_refs}amix=inputs={n}:duration=first,'
            f'{loudnorm_af}[aout]',
        )
        a_out = '[aout]'
    else:
        filter_parts.append(f'[0:a]{loudnorm_af}[aout]')
        a_out = '[aout]'

    vmap = v_out if v_out != '[0:v]' else '0:v'
    return ';'.join(filter_parts), vmap, a_out
```
Update `_build_final_pass_cmd` to pass `sfx_paths`/`sfx_gains_db` through, and its
`use_complex`/`wm_idx` calculation to count SFX inputs too:
```python
def _build_final_pass_cmd(
    *,
    inputs: list[str],
    music_paths: list[str],
    music_gains_db: list[float],
    sfx_paths: list[str],
    sfx_gains_db: list[float],
    ass_path: str | None,
    watermark_path: str | None,
    loudnorm_af: str,
    out_path: str,
) -> list[str]:
    """Assemble the ffmpeg argv for the final encode pass."""
    use_complex = bool(music_paths or sfx_paths or watermark_path)
    wm_idx = 1 + len(music_paths) + len(sfx_paths)

    if use_complex:
        fc, vmap, a_out = _build_complex_filter(
            music_paths=music_paths,
            music_gains_db=music_gains_db,
            sfx_paths=sfx_paths,
            sfx_gains_db=sfx_gains_db,
            ass_path=ass_path,
            watermark_path=watermark_path,
            wm_idx=wm_idx,
            loudnorm_af=loudnorm_af,
        )
        return [
            'ffmpeg', '-y', *inputs, '-filter_complex', fc,
            '-map', vmap, '-map', a_out, *_final_encode_args(out_path),
        ]

    vf_parts = []
    if ass_path:
        vf_parts.append(f"subtitles='{ass_path}'")
    vf = ','.join(vf_parts) if vf_parts else 'null'
    return [
        'ffmpeg', '-y', *inputs, '-vf', vf, '-af', loudnorm_af,
        *_final_encode_args(out_path),
    ]
```
Update `final_pass`'s signature and body:
```python
async def final_pass(
    chapter_paths: list[str],
    music_paths: list[str],
    music_gains_db: list[float],
    ass_path: str | None,
    watermark_path: str | None,
    out_path: str,
    watermark_opacity: float = 0.6,
    sfx_paths: list[str] | None = None,
    sfx_gains_db: list[float] | None = None,
) -> None:
    """Produce final video with loudnorm, watermark, subtitles, music, and SFX.
    ...
    """
    sfx_paths = sfx_paths or []
    sfx_gains_db = sfx_gains_db or []
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        concat_tmp = f.name

    try:
        await concat_chapter(chapter_paths, concat_tmp)
        stats = await loudnorm_pass1(concat_tmp)

        inputs = ['-i', concat_tmp]
        for mp in music_paths:
            inputs += ['-i', mp]
        for sp in sfx_paths:
            inputs += ['-i', sp]
        if watermark_path:
            inputs += ['-i', watermark_path]

        cmd = _build_final_pass_cmd(
            inputs=inputs,
            music_paths=music_paths,
            music_gains_db=music_gains_db,
            sfx_paths=sfx_paths,
            sfx_gains_db=sfx_gains_db,
            ass_path=ass_path,
            watermark_path=watermark_path,
            loudnorm_af=_loudnorm_audio_filter(stats),
            out_path=out_path,
        )
        await _run_ffmpeg_cmd(cmd)
    finally:
        await asyncio.to_thread(Path(concat_tmp).unlink, missing_ok=True)
```
(`watermark_opacity` was already an unused-in-body parameter before this change per the
original file — leave its handling exactly as-is; this task does not touch it.)

- [ ] **Step 6: Wire transition + SFX selection into the `assembly` stage**

In `server/apps/pipelines/stages/assembly.py`, add SFX fetching (mirroring
`_build_music_paths`) and pass the channel's transition pool through to `final_pass`.
Add after `_build_music_paths`:
```python
async def _build_sfx_paths(
    tmp: Path,
    ctx: StageContext,
) -> tuple[list[str], list[float]]:
    """Download up to 3 SFX tracks matching the channel's sfx_pool_tags."""
    from server.apps.assets.models import LibraryAsset, LibraryAssetKind  # noqa: PLC0415

    tags = getattr(ctx.channel, 'assembly_style_sfx_pool_tags', [])
    if not tags:
        return [], []
    assets_qs = LibraryAsset.objects.filter(
        kind=LibraryAssetKind.SFX,
        is_active=True,
        tags__overlap=tags,
    ).order_by('name')[:3]

    sfx_paths: list[str] = []
    sfx_gains: list[float] = []
    async for asset in assets_qs:
        sfx_bytes = await _fetch_library_bytes(str(asset.id))
        sfx_file = tmp / f'sfx_{asset.id}.mp3'
        await asyncio.to_thread(sfx_file.write_bytes, sfx_bytes)
        sfx_paths.append(str(sfx_file))
        sfx_gains.append(-12.0)
    return sfx_paths, sfx_gains
```
In `AssemblyStage.run`, after the existing `music_paths, music_gains =
await _build_music_paths(...)` call, add:
```python
            sfx_paths, sfx_gains = await _build_sfx_paths(tmp, ctx)
```
And update the `ffmpeg.final_pass` call to pass them through:
```python
            await ffmpeg.final_pass(
                chapter_paths=chapter_files,
                music_paths=music_paths,
                music_gains_db=music_gains,
                ass_path=ass_path,
                watermark_path=watermark_path,
                out_path=str(final_file),
                watermark_opacity=watermark_opacity,
                sfx_paths=sfx_paths,
                sfx_gains_db=sfx_gains,
            )
```
Change `_build_chapter_files` to use `ffmpeg.concat_chapter_with_transition` instead of
`ffmpeg.concat_chapter` for the per-chapter concat, picking a transition per chapter:
```python
async def _build_chapter_files(
    tmp: Path,
    scene_groups: dict[int, list[dict[str, Any]]],
    scene_asset_map: dict[int, str],
    chapter_audio_files: dict[int, str],
    transition_pool: list[str],
) -> list[str]:
    """Mux scenes per chapter and concat; return ordered chapter file paths."""
    from server.apps.rendering import ffmpeg  # noqa: PLC0415

    chapter_files: list[str] = []
    for ch_idx, ch_scenes in scene_groups.items():
        scene_mezz_files: list[str] = []
        audio_path = chapter_audio_files.get(ch_idx, '')
        for scene in sorted(ch_scenes, key=operator.itemgetter('segment_idx')):
            scene_idx = scene.get(
                'scene_idx',
                ch_idx * 1000 + scene['segment_idx'],
            )
            vid_asset_id = scene_asset_map.get(int(scene_idx))
            if not vid_asset_id:
                continue
            vid_bytes = await _fetch_asset_bytes(vid_asset_id)
            vid_file = tmp / f'vid_{int(scene_idx):04d}.mp4'
            await asyncio.to_thread(vid_file.write_bytes, vid_bytes)
            mezz_file = tmp / f'mezz_{int(scene_idx):04d}.mp4'
            await ffmpeg.mux_scene(
                video_path=str(vid_file),
                audio_path=audio_path,
                start_s=scene['start_s'],
                end_s=scene['end_s'],
                out_path=str(mezz_file),
            )
            scene_mezz_files.append(str(mezz_file))
        transition = _pick_transition_style(transition_pool, ch_idx)
        chapter_file = tmp / f'ch_{ch_idx:03d}_concat.mp4'
        await ffmpeg.concat_chapter_with_transition(
            scene_mezz_files, transition, 0.5, str(chapter_file),
        )
        chapter_files.append(str(chapter_file))
    return chapter_files
```
Update its one call site inside `AssemblyStage.run`:
```python
            transition_pool = getattr(
                ctx.channel, 'assembly_style_transition_styles', [],
            )
            chapter_files = await _build_chapter_files(
                tmp,
                scene_groups,
                scene_asset_map,
                chapter_audio_files,
                transition_pool,
            )
```

Finally, add the two remaining `Channel` property accessors (alongside
`assembly_style_camera_movements` from Task 2) in `server/apps/channels/models.py`:
```python
    @property
    def assembly_style_transition_styles(self) -> list[str]:
        """Transition-style pool from this channel's AssemblyStyleConfig, or []."""
        from server.apps.channels.models import AssemblyStyleConfig  # noqa: PLC0415

        try:
            style = self.assembly_style
        except AssemblyStyleConfig.DoesNotExist:
            return []
        return list(style.transition_styles)

    @property
    def assembly_style_sfx_pool_tags(self) -> list[str]:
        """SFX tag pool from this channel's AssemblyStyleConfig, or []."""
        from server.apps.channels.models import AssemblyStyleConfig  # noqa: PLC0415

        try:
            style = self.assembly_style
        except AssemblyStyleConfig.DoesNotExist:
            return []
        return list(style.sfx_pool_tags)
```

- [ ] **Step 7: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/ tests/test_apps/test_pipelines/test_stages/test_assembly.py -v --no-cov`
Expected: all PASS. The existing `final_pass`/`_build_complex_filter`/
`_build_final_pass_cmd` tests should still pass unchanged since `sfx_paths`/`sfx_gains_db`
default to `[]` everywhere — if any existing test asserts on the exact positional-args
shape of `_build_complex_filter`/`_build_final_pass_cmd` rather than kwargs, update the
call to include the new required kwargs (they were added as required, not defaulted, on
the two internal `_build_*` helpers — only the public `final_pass` has `None`-defaulted
optionals).

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add server/apps/rendering/ffmpeg.py server/apps/pipelines/stages/assembly.py server/apps/channels/models.py tests/
git commit -m "feat(rendering): per-channel transition styles and SFX layer in final assembly"
```

---

### Task 4: Research rigor — multi-source verification

**Files:**
- Modify: `server/apps/pipelines/schemas.py` (`ResearchBrief`)
- Modify: `server/apps/pipelines/stages/research.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_research.py`

**Interfaces:** none new — tightens an existing validator boundary on
`ResearchBrief.key_facts`.

- [ ] **Step 1: Write the failing schema test**

Add to `tests/test_apps/test_pipelines/test_stages/test_research.py`:
```python
def test_research_brief_rejects_majority_uncorroborated_facts() -> None:
    """A brief where most key_facts have < 2 corroborating sources is rejected."""
    import pytest
    from pydantic import ValidationError

    from server.apps.pipelines.schemas import ResearchBrief, ResearchSource

    with pytest.raises(ValidationError, match='corroborat'):
        ResearchBrief(
            topic='Rome',
            key_facts=['Rome fell in 476 AD', 'Odoacer deposed Romulus Augustulus'],
            sources=[
                ResearchSource(
                    url='https://a.example.com', title='A',
                    key_facts=['Rome fell in 476 AD'],
                ),
            ],
            narrative_angles=[],
            hooks=[],
        )


def test_research_brief_accepts_well_corroborated_facts() -> None:
    from server.apps.pipelines.schemas import ResearchBrief, ResearchSource

    brief = ResearchBrief(
        topic='Rome',
        key_facts=['Rome fell in 476 AD'],
        sources=[
            ResearchSource(
                url='https://a.example.com', title='A',
                key_facts=['Rome fell in 476 AD'],
            ),
            ResearchSource(
                url='https://b.example.com', title='B',
                key_facts=['The city of Rome fell in the year 476 AD'],
            ),
        ],
        narrative_angles=[],
        hooks=[],
    )
    assert brief.key_facts == ['Rome fell in 476 AD']
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_research.py -v --no-cov -k corroborat`
Expected: FAIL — no such validation exists yet.

- [ ] **Step 2: Implement the validator**

In `server/apps/pipelines/schemas.py`, add a module-level helper above `ResearchBrief`
and a `model_validator` on the class:
```python
_MIN_CORROBORATING_SOURCES = 2
_OVERLAP_THRESHOLD = 0.4


def _corroboration_count(fact: str, sources: list[ResearchSource]) -> int:
    """Count distinct sources whose own key_facts overlap this brief-level fact."""
    fact_words = set(fact.lower().split())
    count = 0
    for source in sources:
        for source_fact in source.key_facts:
            source_words = set(source_fact.lower().split())
            if not fact_words or not source_words:
                continue
            overlap = len(fact_words & source_words) / len(fact_words)
            if overlap >= _OVERLAP_THRESHOLD:
                count += 1
                break
    return count
```
```python
class ResearchBrief(BaseModel):
    """Synthesised research brief for the topic."""

    topic: str
    key_facts: list[str]
    sources: list[ResearchSource]
    narrative_angles: list[str]
    hooks: list[str]

    @model_validator(mode='after')
    def enforce_corroboration(self) -> ResearchBrief:
        """At least half of key_facts must have >=2 corroborating sources."""
        if not self.key_facts:
            return self
        corroborated = sum(
            1
            for fact in self.key_facts
            if _corroboration_count(fact, self.sources) >= _MIN_CORROBORATING_SOURCES
        )
        if corroborated < len(self.key_facts) / 2:
            msg = (
                'at least half of key_facts must have 2+ corroborating '
                'sources (matching entries in sources[].key_facts)'
            )
            raise ValueError(msg)
        return self
```
`model_validator` is already imported at the top of `schemas.py`. `ResearchSource` is
defined above `ResearchBrief` in the same file already — no new import needed.

- [ ] **Step 3: Add an output validator + prompt update to the research stage**

In `server/apps/pipelines/stages/research.py`, add `ModelRetry` to the import and an
`@a.output_validator`, mirroring `scene_breakdown.py`:
```python
from pydantic_ai import Agent, ModelRetry, RunContext
```
```python
    @a.output_validator
    def _validate(  # pragma: no cover
        ctx: RunContext[StageContext],
        output: ResearchOutput,
    ) -> ResearchOutput:
        """Reject briefs with mostly single-sourced key facts."""
        try:
            output.brief.model_validate(output.brief.model_dump())
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return output
```
(Insert this inside `_agent()` after the existing `@a.tool async def web_search(...)`
block, before `return a`.)

Update the fallback `user_prompt` in `ResearchStage.run` to state the requirement
explicitly:
```python
        user_prompt = usr or (
            f'Research "{ctx.run.topic}". '
            f'Target audience: {audience or "general"}. '
            f'Angle: {angle or "factual overview"}. '
            f'Find 6-10 key facts with sources, identify 3-5 narrative angles, '
            f'and surface 2-3 surprising hooks. '
            f'For each key fact in the brief, at least 2 of your sources must '
            f'independently state it (put the matching wording in that '
            f'source\'s own key_facts list) — prefer primary/archival/academic '
            f'sources when available.'
        )
```

- [ ] **Step 4: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_research.py -v --no-cov`
Expected: all PASS. The pre-existing `test_research_run_returns_brief_and_sources` test
constructs a `ResearchBrief` with `key_facts=['Rome fell in 476 AD']` and `sources=[]` —
since `key_facts` is non-empty and `sources` is empty, `_corroboration_count` returns 0
for every fact, `corroborated < len(key_facts)/2` (`0 < 0.5`) is `True`, so this existing
fixture will now fail construction. Fix it by adding a matching `ResearchSource` to that
test's `sources=[]` list (two entries, to keep it correct going forward):
```python
    fake_output = ResearchOutput(
        brief=ResearchBrief(
            topic='The fall of Rome',
            key_facts=['Rome fell in 476 AD'],
            sources=[
                ResearchSource(
                    url='https://a.example.com', title='A',
                    key_facts=['Rome fell in 476 AD'],
                ),
                ResearchSource(
                    url='https://b.example.com', title='B',
                    key_facts=['Rome fell in the year 476 AD'],
                ),
            ],
            narrative_angles=['economic decline'],
            hooks=['What really ended Rome?'],
        ),
        sources=[],
    )
```
(Add `ResearchSource` to that test's imports.)

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add server/apps/pipelines/schemas.py server/apps/pipelines/stages/research.py tests/test_apps/test_pipelines/test_stages/test_research.py
git commit -m "feat(research): require multi-source corroboration for key facts"
```

---

### Task 5: Retention-curve-informed pacing

**Files:**
- Create: `server/apps/analytics/retention_rollup.py`
- Modify: `server/apps/pipelines/stages/outline.py`
- Test: `tests/test_apps/test_analytics/test_retention_rollup.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_outline.py`

**Interfaces:**
- Produces: `retention_rollup.compute_soft_spots(channel_id) -> str` (a human-readable
  summary, empty string if insufficient data — consumed directly by `outline.py`, no
  intermediate DTO needed since it's prompt text, matching how `research_brief`/`beats`
  are already just passed as dicts/strings into prompt context).

- [ ] **Step 1: Write the failing pure-aggregation test**

Create `tests/test_apps/test_analytics/test_retention_rollup.py`:
```python
"""Tests for retention-curve aggregation by chapter retention device."""

from server.apps.analytics.retention_rollup import _bucket_curve_by_device


def test_bucket_curve_by_device_maps_elapsed_ratio_to_chapter_device() -> None:
    """A curve point's elapsed_ratio*duration falls within a chapter's time span."""
    retention_curve = [
        {'elapsed_ratio': 0.1, 'watch_ratio': 0.9, 'relative_performance': 0.6},
        {'elapsed_ratio': 0.6, 'watch_ratio': 0.4, 'relative_performance': 0.3},
    ]
    # Two chapters spanning a 100s video: chapter 0 = [0, 30), chapter 1 = [30, 100)
    chapter_boundaries = [
        {'device': 'open_loop', 'start_s': 0.0, 'end_s': 30.0},
        {'device': 'tension_build', 'start_s': 30.0, 'end_s': 100.0},
    ]

    buckets = _bucket_curve_by_device(retention_curve, chapter_boundaries, total_duration_s=100.0)

    assert buckets['open_loop'] == [0.6]
    assert buckets['tension_build'] == [0.3]


def test_bucket_curve_by_device_skips_points_outside_any_chapter() -> None:
    from server.apps.analytics.retention_rollup import _bucket_curve_by_device

    retention_curve = [{'elapsed_ratio': 0.99, 'watch_ratio': 0.1, 'relative_performance': 0.2}]
    chapter_boundaries = [{'device': 'open_loop', 'start_s': 0.0, 'end_s': 10.0}]

    buckets = _bucket_curve_by_device(retention_curve, chapter_boundaries, total_duration_s=100.0)
    assert buckets == {}
```

Run: `docker compose exec web pytest tests/test_apps/test_analytics/test_retention_rollup.py -v --no-cov`
Expected: FAIL — module doesn't exist.

- [ ] **Step 2: Implement the pure bucketing function**

Create `server/apps/analytics/retention_rollup.py`:
```python
"""Aggregate YouTube retention-curve data by chapter retention device, to
surface a channel's "known soft spots" back into future outline prompts.
"""

from typing import Any

_SOFT_SPOT_THRESHOLD = 0.5
_MIN_SAMPLES = 3


def _bucket_curve_by_device(
    retention_curve: list[dict[str, float]],
    chapter_boundaries: list[dict[str, Any]],
    total_duration_s: float,
) -> dict[str, list[float]]:
    """Map each curve point's relative_performance to its chapter's device."""
    buckets: dict[str, list[float]] = {}
    if total_duration_s <= 0:
        return buckets
    for point in retention_curve:
        elapsed_s = point['elapsed_ratio'] * total_duration_s
        for chapter in chapter_boundaries:
            if chapter['start_s'] <= elapsed_s < chapter['end_s']:
                buckets.setdefault(chapter['device'], []).append(
                    point['relative_performance'],
                )
                break
    return buckets


def _chapter_boundaries_from_outline(
    chapters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build cumulative [start_s, end_s) spans from outline chapters' target_seconds."""
    boundaries: list[dict[str, Any]] = []
    cursor = 0.0
    for ch in chapters:
        duration = float(ch.get('target_seconds', 0))
        boundaries.append({
            'device': ch.get('device', ''),
            'start_s': cursor,
            'end_s': cursor + duration,
        })
        cursor += duration
    return boundaries


def compute_soft_spots(channel_id: str) -> str:
    """Summarize which retention devices underperform for this channel's history.

    Returns '' when there isn't enough data (fewer than _MIN_SAMPLES points
    for every device) to say anything meaningful yet.
    """
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415
    from server.apps.pipelines.models import StageExecution, StageStatus  # noqa: PLC0415

    all_buckets: dict[str, list[float]] = {}
    metrics = (
        PublishJobMetric.objects
        .filter(publish_job__channel_id=channel_id, retention_curve__len__gt=0)
        .select_related('publish_job__run')
        .order_by('-pulled_at')[:30]
    )
    for metric in metrics:
        run_id = metric.publish_job.run_id
        outline_exec = StageExecution.objects.filter(
            run_id=run_id, stage_key='outline', status=StageStatus.SUCCEEDED,
        ).first()
        assembly_exec = StageExecution.objects.filter(
            run_id=run_id, stage_key='assembly', status=StageStatus.SUCCEEDED,
        ).first()
        if outline_exec is None or assembly_exec is None:
            continue
        chapters = outline_exec.output.get('chapters', [])
        total_duration_s = float(assembly_exec.output.get('duration_s', 0))
        boundaries = _chapter_boundaries_from_outline(chapters)
        buckets = _bucket_curve_by_device(
            metric.retention_curve, boundaries, total_duration_s,
        )
        for device, values in buckets.items():
            all_buckets.setdefault(device, []).extend(values)

    soft_spots = [
        (device, sum(values) / len(values))
        for device, values in all_buckets.items()
        if len(values) >= _MIN_SAMPLES
        and (sum(values) / len(values)) < _SOFT_SPOT_THRESHOLD
    ]
    if not soft_spots:
        return ''

    lines = [
        f'chapters using the "{device}" retention device underperform '
        f'similar-length videos platform-wide (avg relative performance '
        f'{avg:.2f})'
        for device, avg in soft_spots
    ]
    return 'Known pacing soft spots on this channel: ' + '; '.join(lines) + '.'
```
(`retention_curve__len__gt=0` requires Postgres JSONField length lookup support — if
`django-jsonfield-backport`/native Postgres `jsonb` array-length filtering isn't already
used elsewhere in this codebase, replace with a plain Python filter after fetching
instead: fetch `PublishJobMetric.objects.filter(publish_job__channel_id=channel_id)
.order_by('-pulled_at')[:30]` without the `retention_curve__len__gt=0` clause, and skip
rows where `not metric.retention_curve` inside the loop. Check whether `__len` JSONField
lookups are used anywhere else in `server/apps/` first — if not, use the Python-side
filter to stay consistent with this codebase's existing patterns.)

- [ ] **Step 3: Write the failing outline-stage integration test**

Add to `tests/test_apps/test_pipelines/test_stages/test_outline.py`:
```python
def test_outline_run_includes_soft_spots_in_prompt_context() -> None:
    """run() passes compute_soft_spots' output into the prompt render call."""
    from server.apps.pipelines.schemas import Chapter, OutlineOutput

    ctx = _make_ctx()
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
                'server.apps.pipelines.stages.outline.compute_soft_spots',
                return_value='Known pacing soft spots on this channel: ...',
            ),
        ):
            return await OutlineStage().run(ctx)

    asyncio.run(_inner())
    render_kwargs = ctx.prompts.render.call_args.args[1]
    assert 'soft spots' in render_kwargs['soft_spots']
```

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_outline.py -v --no-cov -k soft_spot`
Expected: FAIL — `compute_soft_spots` not imported/used in `outline.py`.

- [ ] **Step 4: Wire it into the outline stage**

In `server/apps/pipelines/stages/outline.py`, add the import:
```python
from server.apps.analytics.retention_rollup import compute_soft_spots
```
In `OutlineStage.run`, add right before the `_, usr = await ctx.prompts.render(...)`
call:
```python
        soft_spots = compute_soft_spots(str(ctx.channel.id))
```
and add `'soft_spots': soft_spots` to the render context dict:
```python
        _, usr = await ctx.prompts.render(
            'outline',
            {
                'topic': ctx.run.topic,
                'research_brief': brief,
                'beats': beats,
                'total_target_seconds': total_s,
                'soft_spots': soft_spots,
            },
        )
        user_prompt = usr or (
            f'Topic: {ctx.run.topic}\n'
            f'Research brief: {brief}\n'
            f'Format beats: {beats}\n'
            f'Target total duration: {total_s}s (~{total_s // 60} min).\n'
            + (f'{soft_spots}\n' if soft_spots else '')
            + 'Write a chapter outline with 6-10 chapters.'
        )
```

- [ ] **Step 5: Run tests, fix, run full suite**

Run: `docker compose exec web pytest tests/test_apps/test_analytics/test_retention_rollup.py tests/test_apps/test_pipelines/test_stages/test_outline.py -v --no-cov`
Expected: all PASS.

Run: `docker compose exec web pytest --cov-fail-under=100 && docker compose exec web ruff check . && docker compose exec web mypy server && docker compose exec web lint-imports`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add server/apps/analytics/retention_rollup.py server/apps/pipelines/stages/outline.py tests/
git commit -m "feat(analytics): feed retention-curve soft-spot analysis back into outline prompts"
```

---

## Final Verification (after Task 5)

- [ ] Run the full suite with coverage: `docker compose exec web pytest` (100% required).
- [ ] Run `ruff check .`, `ruff format --check .`, `mypy server`, `lint-imports`.
- [ ] Run `lintmigrations` and `check_migrations --exclude-apps=axes` across all
  migrations added by this plan (`channels` for `AssemblyStyleConfig`).
- [ ] Run `docker compose exec web python manage.py seed_blueprints` and confirm
  `narrative_qc` appears in the active `longform_v1` blueprint's graph.
- [ ] Manually drive one `longform_v1` run end-to-end against a channel with a
  populated `AssemblyStyleConfig` and confirm: a deliberately weak topic gets stopped at
  `narrative_qc` (`NEEDS_INPUT`), a normal run's hero-scene Kling prompts vary by the
  channel's camera-movement pool, and the assembled video's chapter transitions vary per
  the channel's transition pool.
- [ ] Hand off to `superpowers:requesting-code-review` for the final whole-branch review
  once all 5 tasks are committed, then `superpowers:finishing-a-development-branch`.
