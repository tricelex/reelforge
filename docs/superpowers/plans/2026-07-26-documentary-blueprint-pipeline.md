# Documentary Blueprint — Pipeline, Review & Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three documentary stages, seed the blueprint and its
footage-aware prompts, add the profile-dispatched review layer with its API
endpoints, and enforce licence attribution through to the published
description.

**Architecture:** `footage_queries` turns scenes into provider search terms;
`footage_search` fans out per scene running the broaden→AI→park cascade and
persists provenance; `footage_prep` normalizes mixed media into segments whose
output shape matches `motion` exactly. A profile-dispatched `review/` package
serves a documentary storyboard payload without touching the existing AI-visual
selectors.

**Tech Stack:** Python 3.13, Django 6.0, pydantic-ai, pytest, httpx, ffmpeg,
django-modern-rest (DMR), msgspec.

**Prerequisite:** `2026-07-26-documentary-blueprint-foundations.md` must be
complete. This plan consumes `resolve_role`, `FootageCandidate`,
`search_candidates`, `build_providers`, `AssetKind.FOOTAGE`, `FootageCredit`,
and `FootageSourcingConfig` from it.

**Covers:** §12 steps 6–10 of
`docs/superpowers/specs/2026-07-26-longform-documentary-blueprint-design.md`.

## Global Constraints

- Python 3.13.x, Django 6.0.x.
- `ruff`: single quotes, 80-char line length.
- `mypy` strict — all public functions annotated.
- 100% test coverage — `--cov-fail-under=100`.
- `--doctest-modules` is active.
- **Never** add `from __future__ import annotations` to punq-registered files.
- `@final` on concrete classes; `msgspec.Struct` for API value objects;
  `pydantic.BaseModel` for stage output schemas in
  `server/apps/pipelines/schemas.py`.
- Stage classes subclass `Stage`, use `@register_stage`, and must be imported in
  `server/apps/pipelines/stages/__init__.py` or the registry will not see them.
- Every new `stages.* -> generation.clients.*` / `-> assets.models` import
  **must** be added to `.importlinter`'s `ignore_imports`.
- API tests use `dmr.test.DMRClient`, not Django's `Client`.
- Migrations backward-compatible; verified with `lintmigrations`.

## mypy baseline — IMPORTANT

`mypy server` reports **78 pre-existing errors across 31 files** on this branch
(measured 2026-07-26). That is the baseline, not a regression you caused.

- Never expect `mypy server` to print zero errors.
- The bar is **no NEW errors in files you touched**. Check with
  `docker compose exec web mypy server 2>&1 | grep '<your-file>'` — that must
  be empty — and confirm the trailing total has not risen above 78.

## lint-imports baseline — IMPORTANT

`lint-imports` **already fails on this branch**: 3 of 6 contracts broken,
~50 violating imports (measured 2026-07-26), all pre-existing and unrelated
to this work (clips->assets, pipelines.logic->models, common->apps, and more).

- Never expect `lint-imports` to pass outright.
- The bar is: **your new stage->client imports are declared in `.importlinter`
  and no NEW violation names a file you touched.** Check with
  `docker compose exec web lint-imports 2>&1 | grep '<your-module>'`.
- Do NOT add exemptions for pre-existing violations you did not introduce.
  That is a separate cleanup and an architectural decision for the repo owner.

## Verification Commands

```bash
docker compose exec web pytest --no-cov
docker compose exec web pytest
docker compose exec web ruff check .
docker compose exec web mypy server
docker compose exec web lint-imports
docker compose exec web python manage.py lintmigrations
```

---

## Steps specified as contracts rather than literal code

Most steps below contain the exact code to write. Four do not, because they
depend on file-local conventions an implementer must read first (existing DMR
controller structure, the channels API payload builders, and the fixture style
in `test_review_api.py`). These steps state the **required behaviour, names,
and assertions** precisely; write the code to match the surrounding file:

- Task 9, Step 5 — `test_documentary.py` cases
- Task 10, Step 1 — `test_footage_api.py` cases
- Task 10, Step 4 — the three DMR controllers
- Task 12, Step 3 — channels API `footage_sourcing` exposure

Every other step is copy-paste complete.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `server/apps/pipelines/stages/footage_queries.py` | LLM stage: scenes → provider search terms. |
| `server/apps/pipelines/stages/footage_search.py` | Fan-out stage: cascade, re-rank, download, provenance. |
| `server/apps/pipelines/stages/footage_prep.py` | Fan-out stage: normalize clips/stills to segments. |
| `server/apps/pipelines/logic/footage_rerank.py` | Pure ranking helpers (metadata scoring, ordering). |
| `server/apps/pipelines/review/__init__.py` | Package marker. |
| `server/apps/pipelines/review/dispatch.py` | Profile → review adapter. |
| `server/apps/pipelines/review/ai_visual.py` | Delegates to existing selectors, unchanged. |
| `server/apps/pipelines/review/documentary.py` | Documentary storyboard payload + scene-edit sync. |
| `server/apps/pipelines/footage_selectors.py` | Read-only credits selector. |
| `server/apps/prompts/management/commands/seed_story_formats.py` | Idempotent format + prompt template seeding. |

**Modified:**

| Path | Change |
|---|---|
| `server/apps/pipelines/schemas.py` | `FootageQuery`, `FootageQueriesOutput`, `CandidateRanking`. |
| `server/apps/pipelines/stages/__init__.py` | Import the 3 new stages. |
| `server/apps/pipelines/management/commands/seed_blueprints.py` | Seed `longform_documentary_v1`. |
| `server/apps/pipelines/services/pipeline_run.py` | Resolve `prompt_overrides` into `prompt_snapshot`. |
| `server/apps/pipelines/services/prompt_renderer.py` | Read nested `prompt_snapshot['prompts']`. |
| `server/apps/pipelines/services/prompt_variables.py` | Add the `footage` namespace. |
| `server/apps/pipelines/stages/metadata.py` | Append the attribution block. |
| `server/apps/pipelines/api/review_views.py`, `urls.py` | 3 new endpoints; dispatch storyboard. |
| `server/apps/pipelines/stage_output_selectors.py` | Add 3 keys to `_KNOWN_STAGE_KEYS`. |
| `server/apps/pipelines/run_asset_selectors.py` | Add keys to `_SCENE_LABEL_STAGES`. |
| `server/apps/generation/clients/llm.py` | Widen `run_agent` `user_prompt` type for vision. |
| `server/apps/channels/api/` | Expose `footage_sourcing` on channel GET/PATCH. |
| `.importlinter` | New stage→client exemptions. |

---

## Task 1: Stage output schemas

**Files:**
- Modify: `server/apps/pipelines/schemas.py`
- Test: `tests/test_apps/test_pipelines/test_schemas.py`

**Interfaces:**
- Produces:
  - `FootageQuery(BaseModel)` — `scene_idx: int`, `primary_query: str`,
    `fallback_queries: list[str]`, `media_preference: str`,
    `orientation: str`, `era_hint: str`, `negative_terms: list[str]`,
    `ai_fallback_prompt: str`.
  - `FootageQueriesOutput(BaseModel)` — `queries: list[FootageQuery]`.
  - `CandidateRanking(BaseModel)` — `external_id: str`, `score: float`
    (0.0–1.0), `reason: str`.
  - `CandidateRankingOutput(BaseModel)` — `rankings: list[CandidateRanking]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_apps/test_pipelines/test_schemas.py`:

```python
def test_footage_query_defaults() -> None:
    """Optional query fields default to empty, not None."""
    from server.apps.pipelines.schemas import FootageQuery

    query = FootageQuery(scene_idx=0, primary_query='ocean waves')
    assert query.fallback_queries == []
    assert query.negative_terms == []
    assert query.media_preference == 'any'
    assert query.orientation == 'landscape'
    assert query.era_hint == ''
    assert query.ai_fallback_prompt == ''


def test_candidate_ranking_score_is_bounded() -> None:
    """Rankings outside 0..1 are rejected by validation."""
    import pydantic
    import pytest

    from server.apps.pipelines.schemas import CandidateRanking

    assert CandidateRanking(external_id='a', score=1.0, reason='r').score == 1.0
    with pytest.raises(pydantic.ValidationError):
        CandidateRanking(external_id='a', score=1.5, reason='r')
    with pytest.raises(pydantic.ValidationError):
        CandidateRanking(external_id='a', score=-0.1, reason='r')


def test_footage_queries_output_holds_queries() -> None:
    """The stage output wraps a list of per-scene queries."""
    from server.apps.pipelines.schemas import (
        FootageQueriesOutput,
        FootageQuery,
    )

    output = FootageQueriesOutput(
        queries=[FootageQuery(scene_idx=0, primary_query='q')],
    )
    assert len(output.queries) == 1
    assert output.queries[0].scene_idx == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_schemas.py -k footage -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'FootageQuery'`

- [ ] **Step 3: Write the implementation**

Append to `server/apps/pipelines/schemas.py`:

```python
class FootageQuery(BaseModel):
    """Provider search terms for one scene."""

    scene_idx: int
    primary_query: str
    fallback_queries: list[str] = Field(default_factory=list)
    media_preference: str = 'any'
    orientation: str = 'landscape'
    era_hint: str = ''
    negative_terms: list[str] = Field(default_factory=list)
    ai_fallback_prompt: str = ''


class FootageQueriesOutput(BaseModel):
    """Full output of the footage_queries stage."""

    queries: list[FootageQuery]


class CandidateRanking(BaseModel):
    """A vision model's score for one footage candidate."""

    external_id: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ''


class CandidateRankingOutput(BaseModel):
    """Full output of a candidate re-ranking call."""

    rankings: list[CandidateRanking]
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_schemas.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/apps/pipelines/schemas.py \
        tests/test_apps/test_pipelines/test_schemas.py
git commit -m "feat(pipelines): add footage query and ranking schemas"
```

---

## Task 2: `footage_queries` stage

**Files:**
- Create: `server/apps/pipelines/stages/footage_queries.py`
- Modify: `server/apps/pipelines/stages/__init__.py`
- Modify: `.importlinter`
- Test: `tests/test_apps/test_pipelines/test_stages/test_footage_queries.py`

**Interfaces:**
- Consumes: `FootageQueriesOutput` (Task 1).
- Produces: `FootageQueriesStage` with `key = 'footage_queries'`,
  `queue = 'api'`. Output dict: `{'queries': [FootageQuery.model_dump(), ...]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_pipelines/test_stages/test_footage_queries.py`:

```python
"""Tests for the footage_queries stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.schemas import FootageQueriesOutput, FootageQuery
from server.apps.pipelines.stages.footage_queries import FootageQueriesStage
from server.common.exceptions import FatalProviderError


def _make_ctx(n_scenes: int = 3) -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'Battle of Midway'
    ctx.run.id = 'run-uuid'
    ctx.run.prompt_snapshot = {}
    ctx.channel.niche_config = None
    ctx.upstream = {
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': i,
                    'chapter_idx': 0,
                    'visual_concept': f'concept {i}',
                    'narration_text': f'narration {i}',
                    'est_seconds': 8.0,
                }
                for i in range(n_scenes)
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def _output(scene_idxs: list[int]) -> FootageQueriesOutput:
    return FootageQueriesOutput(
        queries=[
            FootageQuery(
                scene_idx=i,
                primary_query=f'query {i}',
                fallback_queries=[f'broad {i}'],
                ai_fallback_prompt=f'ai {i}',
            )
            for i in scene_idxs
        ],
    )


def test_stage_key_and_queue() -> None:
    """The stage registers under the expected key and queue."""
    assert FootageQueriesStage.key == 'footage_queries'
    assert FootageQueriesStage.queue == 'api'


def test_run_returns_one_query_per_scene() -> None:
    """Full scene coverage produces a query per scene."""
    ctx = _make_ctx(n_scenes=3)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([0, 1, 2])),
    ):
        result = asyncio.run(FootageQueriesStage().run(ctx))
    assert len(result['queries']) == 3
    assert result['queries'][0]['primary_query'] == 'query 0'
    assert result['queries'][0]['ai_fallback_prompt'] == 'ai 0'


def test_run_raises_when_scene_breakdown_is_empty() -> None:
    """No scenes upstream is a fatal configuration error."""
    ctx = _make_ctx(n_scenes=0)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([])),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageQueriesStage().run(ctx))
    assert exc_info.value.error_code == 'missing_scenes'


def test_run_raises_on_coverage_mismatch() -> None:
    """A missing scene query is fatal, not silently tolerated."""
    ctx = _make_ctx(n_scenes=3)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([0, 1])),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageQueriesStage().run(ctx))
    assert exc_info.value.error_code == 'query_coverage'
    assert '2' in str(exc_info.value)


def test_run_raises_on_extra_queries() -> None:
    """A query for a nonexistent scene is also a coverage failure."""
    ctx = _make_ctx(n_scenes=2)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([0, 1, 7])),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageQueriesStage().run(ctx))
    assert exc_info.value.error_code == 'query_coverage'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_footage_queries.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: ...stages.footage_queries`

- [ ] **Step 3: Write the implementation**

Create `server/apps/pipelines/stages/footage_queries.py`:

```python
"""Footage queries stage — turns scenes into provider search terms."""

from functools import lru_cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.schemas import FootageQueriesOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_FALLBACK_SYSTEM = (
    'You write search queries for stock and public-domain footage '
    'libraries. For each scene, produce a primary_query of 2-5 concrete '
    'visual nouns describing an archetypal, findable shot — subject, '
    'action, setting. Never name individuals, specific dated events, or '
    'anything unique enough that no library would hold it. Add 2-3 '
    'progressively broader fallback_queries. Set media_preference to '
    '"video" for motion-led scenes and "image" for archival or static '
    'ones. Use era_hint for period material. Always write an '
    'ai_fallback_prompt describing the shot for an image generator, used '
    'only when no footage is found.'
)


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, FootageQueriesOutput]:
    """Create and cache the footage queries agent on first call."""
    a: Agent[StageContext, FootageQueriesOutput] = Agent(
        model,
        output_type=FootageQueriesOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = await build_prompt_variables(
            ctx.deps,
            include_character=False,
        )
        sys, _ = await ctx.deps.prompts.render('footage_queries', variables)
        return sys or _FALLBACK_SYSTEM

    return a


@register_stage
class FootageQueriesStage(Stage):
    """Documentary stage: search terms for every scene."""

    key = 'footage_queries'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Write provider search queries for each scene."""
        scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        if not scenes:
            raise FatalProviderError(
                'scene_breakdown has no scenes for footage queries',
                provider='footage_queries',
                error_code='missing_scenes',
            )

        variables = await build_prompt_variables(
            ctx,
            include_character=False,
        )
        _, usr = await ctx.prompts.render('footage_queries', variables)
        user_prompt = usr or (
            f'Write footage search queries for "{ctx.run.topic}".\n'
            f'Scenes: {scenes}\n'
            f'Return one FootageQuery per scene, same scene_idx values.'
        )
        model_slug = await resolve_stage_model(ctx, self.key)
        output: FootageQueriesOutput = await llm_client.run_agent(
            _agent(to_pydantic_ai_model(model_slug)),
            user_prompt,
            ctx,
            stage_key=self.key,
            model_slug=model_slug,
        )

        scene_idxs = {int(s['idx']) for s in scenes}
        query_idxs = {int(q.scene_idx) for q in output.queries}
        if query_idxs != scene_idxs:
            missing = sorted(scene_idxs - query_idxs)
            extra = sorted(query_idxs - scene_idxs)
            raise FatalProviderError(
                f'footage_queries coverage mismatch — '
                f'missing={missing} extra={extra}',
                provider='footage_queries',
                error_code='query_coverage',
            )
        return output.model_dump()
```

- [ ] **Step 4: Register the stage**

In `server/apps/pipelines/stages/__init__.py`, add `footage_queries,  # noqa: F401`
to the import list in alphabetical order (after `final_gate`).

- [ ] **Step 5: Add the import-linter exemption**

In `.importlinter`, under `ignore_imports`:

```
  server.apps.pipelines.stages.footage_queries -> server.apps.generation.clients.llm
```

- [ ] **Step 6: Run tests and the import contract**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_footage_queries.py -v --no-cov
docker compose exec web lint-imports
```
Expected: PASS, 5 passed

- [ ] **Step 7: Commit**

```bash
git add server/apps/pipelines/stages/footage_queries.py \
        server/apps/pipelines/stages/__init__.py .importlinter \
        tests/test_apps/test_pipelines/test_stages/test_footage_queries.py
git commit -m "feat(pipelines): add footage_queries stage"
```

---

## Task 3: Candidate re-ranking helpers

Pure ranking logic, separated from the stage so the cascade in Task 4 stays
readable and the scoring is testable without mocking a stage context.

**Files:**
- Create: `server/apps/pipelines/logic/footage_rerank.py`
- Modify: `server/apps/generation/clients/llm.py` (widen one annotation)
- Test: `tests/test_apps/test_pipelines/test_logic/test_footage_rerank.py`

**Interfaces:**
- Consumes: `FootageCandidate` (foundations Task 6), `CandidateRankingOutput`
  (Task 1).
- Produces:
  - `metadata_score(candidate, *, visual_concept, negative_terms) -> float`.
  - `rank_by_metadata(candidates, *, visual_concept, negative_terms)
    -> list[FootageCandidate]`.
  - `apply_vision_rankings(candidates, rankings) -> list[FootageCandidate]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_pipelines/test_logic/test_footage_rerank.py`:

```python
"""Tests for footage candidate ranking helpers."""

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.pipelines.logic.footage_rerank import (
    apply_vision_rankings,
    metadata_score,
    rank_by_metadata,
)
from server.apps.pipelines.schemas import CandidateRanking


def _candidate(
    external_id: str,
    title: str = '',
    tags: tuple[str, ...] = (),
    width: int = 1920,
) -> FootageCandidate:
    return FootageCandidate(
        provider='pexels', external_id=external_id, media_type='video',
        download_url='https://e.test/v.mp4', thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p', width=width, height=1080,
        duration_s=10.0, license='pexels', license_url='',
        author='A', attribution_required=False, title=title, tags=tags,
    )


def test_matching_title_scores_higher_than_unrelated() -> None:
    """Term overlap with the visual concept raises the score."""
    match = _candidate('1', title='stormy ocean waves at sea')
    miss = _candidate('2', title='a plate of pasta')
    concept = 'stormy ocean waves'
    assert metadata_score(
        match, visual_concept=concept, negative_terms=[],
    ) > metadata_score(miss, visual_concept=concept, negative_terms=[])


def test_negative_terms_penalise_a_candidate() -> None:
    """A negative term present in metadata reduces the score."""
    candidate = _candidate('1', title='modern cruise ship at sea')
    clean = metadata_score(
        candidate, visual_concept='ship at sea', negative_terms=[],
    )
    penalised = metadata_score(
        candidate, visual_concept='ship at sea', negative_terms=['modern'],
    )
    assert penalised < clean


def test_tags_contribute_to_the_score() -> None:
    """Tags are searched as well as the title."""
    tagged = _candidate('1', title='', tags=('ocean', 'waves'))
    untagged = _candidate('2', title='', tags=())
    concept = 'ocean waves'
    assert metadata_score(
        tagged, visual_concept=concept, negative_terms=[],
    ) > metadata_score(untagged, visual_concept=concept, negative_terms=[])


def test_rank_by_metadata_orders_best_first() -> None:
    """Ranking returns candidates sorted by descending score."""
    candidates = [
        _candidate('miss', title='a plate of pasta'),
        _candidate('hit', title='stormy ocean waves'),
    ]
    ranked = rank_by_metadata(
        candidates, visual_concept='stormy ocean waves', negative_terms=[],
    )
    assert [c.external_id for c in ranked] == ['hit', 'miss']


def test_rank_by_metadata_is_stable_for_equal_scores() -> None:
    """Equal scores preserve the provider's original ordering."""
    candidates = [_candidate('a'), _candidate('b'), _candidate('c')]
    ranked = rank_by_metadata(
        candidates, visual_concept='unrelated', negative_terms=[],
    )
    assert [c.external_id for c in ranked] == ['a', 'b', 'c']


def test_apply_vision_rankings_orders_by_score() -> None:
    """Vision scores reorder candidates, best first."""
    candidates = [_candidate('a'), _candidate('b'), _candidate('c')]
    rankings = [
        CandidateRanking(external_id='c', score=0.9, reason='best'),
        CandidateRanking(external_id='a', score=0.5, reason='ok'),
        CandidateRanking(external_id='b', score=0.1, reason='poor'),
    ]
    ranked = apply_vision_rankings(candidates, rankings)
    assert [c.external_id for c in ranked] == ['c', 'a', 'b']


def test_apply_vision_rankings_keeps_unscored_candidates_last() -> None:
    """A candidate the model ignored is retained, ranked last."""
    candidates = [_candidate('a'), _candidate('b')]
    rankings = [CandidateRanking(external_id='b', score=0.8, reason='r')]
    ranked = apply_vision_rankings(candidates, rankings)
    assert [c.external_id for c in ranked] == ['b', 'a']


def test_apply_vision_rankings_ignores_unknown_ids() -> None:
    """A hallucinated external_id does not inject a phantom candidate."""
    candidates = [_candidate('a')]
    rankings = [
        CandidateRanking(external_id='ghost', score=1.0, reason='r'),
        CandidateRanking(external_id='a', score=0.2, reason='r'),
    ]
    ranked = apply_vision_rankings(candidates, rankings)
    assert [c.external_id for c in ranked] == ['a']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_footage_rerank.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: ...logic.footage_rerank`

- [ ] **Step 3: Write the implementation**

Create `server/apps/pipelines/logic/footage_rerank.py`:

```python
"""Pure ranking helpers for footage candidates.

Metadata scoring is a cheap term-overlap heuristic used when vision
re-ranking is disabled or has failed. It is deliberately simple — the vision
model is the quality path; this only has to beat provider default ordering.

>>> round(metadata_score_terms({'ocean', 'waves'}, {'ocean'}, set()), 2)
0.5
"""

from collections.abc import Sequence

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.pipelines.schemas import CandidateRanking

_NEGATIVE_PENALTY = 0.5


def _terms(text: str) -> set[str]:
    """Split text into a lowercase term set."""
    return {t for t in text.casefold().replace(',', ' ').split() if t}


def metadata_score_terms(
    concept_terms: set[str],
    candidate_terms: set[str],
    negative_terms: set[str],
) -> float:
    """Return an overlap score in 0..1, penalised for negative terms."""
    if not concept_terms:
        return 0.0
    overlap = len(concept_terms & candidate_terms) / len(concept_terms)
    if negative_terms & candidate_terms:
        overlap -= _NEGATIVE_PENALTY
    return max(0.0, min(1.0, overlap))


def metadata_score(
    candidate: FootageCandidate,
    *,
    visual_concept: str,
    negative_terms: Sequence[str],
) -> float:
    """Score one candidate on title/tag overlap with the scene concept."""
    candidate_terms = _terms(candidate.title) | {
        t.casefold() for t in candidate.tags
    }
    return metadata_score_terms(
        _terms(visual_concept),
        candidate_terms,
        {t.casefold() for t in negative_terms},
    )


def rank_by_metadata(
    candidates: Sequence[FootageCandidate],
    *,
    visual_concept: str,
    negative_terms: Sequence[str],
) -> list[FootageCandidate]:
    """Return candidates ordered by descending metadata score (stable)."""
    return sorted(
        candidates,
        key=lambda c: -metadata_score(
            c,
            visual_concept=visual_concept,
            negative_terms=negative_terms,
        ),
    )


def apply_vision_rankings(
    candidates: Sequence[FootageCandidate],
    rankings: Sequence[CandidateRanking],
) -> list[FootageCandidate]:
    """Reorder candidates by vision score; unscored ones sort last.

    Rankings naming an unknown ``external_id`` are ignored, so a model
    hallucination cannot introduce a candidate that was never fetched.
    """
    scores = {r.external_id: r.score for r in rankings}
    return sorted(
        candidates,
        key=lambda c: -scores.get(c.external_id, -1.0),
    )
```

- [ ] **Step 4: Widen `run_agent` to accept vision content**

In `server/apps/generation/clients/llm.py`, change the `run_agent` signature's
second parameter from:

```python
    user_prompt: str,
```

to:

```python
    user_prompt: 'str | Sequence[Any]',
```

and add `from collections.abc import Sequence` to the imports. This is an
annotation-only widening — `pydantic-ai`'s `agent.run()` already accepts a
content sequence, so runtime behavior is unchanged.

- [ ] **Step 5: Run tests, doctests, and types**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_pipelines/test_logic/test_footage_rerank.py -v --no-cov
docker compose exec web pytest --doctest-modules server/apps/pipelines/logic/footage_rerank.py --no-cov
docker compose exec web mypy server
```
Expected: PASS, 8 passed

- [ ] **Step 6: Commit**

```bash
git add server/apps/pipelines/logic/footage_rerank.py \
        server/apps/generation/clients/llm.py \
        tests/test_apps/test_pipelines/test_logic/test_footage_rerank.py
git commit -m "feat(pipelines): add footage candidate ranking helpers"
```

---

## Task 4: `footage_search` stage — the cascade

The core of the feature. Fan-out per scene running
broaden → AI → park, with provenance persisted.

**Files:**
- Create: `server/apps/pipelines/stages/footage_search.py`
- Modify: `server/apps/pipelines/stages/__init__.py`, `.importlinter`
- Test: `tests/test_apps/test_pipelines/test_stages/test_footage_search.py`

**Interfaces:**
- Consumes: `search_candidates`, `build_providers` (foundations Task 10);
  `rank_by_metadata`, `apply_vision_rankings` (Task 3); `AssetKind.FOOTAGE`,
  `FootageCredit` (foundations Task 4); `footage_sourcing_or_default`
  (foundations Task 5).
- Produces: `FootageSearchStage`, `key = 'footage_search'`, `queue = 'api'`,
  fan-out over scenes. Shard output:

```python
{'scene_idx': int, 'asset_id': str, 'media_type': str, 'source': str,
 'license': str, 'license_url': str, 'attribution': str,
 'attribution_required': bool, 'source_url': str,
 'rerank_score': float | None, 'candidates': list[dict]}
```

`attribution` carries the author name; `attribution_required` is the boolean.
Both are consumed by the review payload in Task 9 — keep the names aligned.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_pipelines/test_stages/test_footage_search.py`:

```python
"""Tests for the footage_search fan-out stage and its fallback cascade."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.pipelines.stages.footage_search import FootageSearchStage
from server.common.exceptions import FatalProviderError


def _candidate(external_id: str = '1') -> FootageCandidate:
    return FootageCandidate(
        provider='pexels', external_id=external_id, media_type='video',
        download_url='https://e.test/v.mp4', thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p', width=1920, height=1080,
        duration_s=10.0, license='pexels', license_url='',
        author='A', attribution_required=False, title='ocean', tags=(),
    )


def _make_ctx(*, ai_fallback: bool = True, rerank: str = 'none') -> MagicMock:
    ctx = MagicMock()
    ctx.run.id = 'run-uuid'
    ctx.run.topic = 'Oceans'
    config = MagicMock()
    config.enabled_providers = ['pexels']
    config.ai_fallback_enabled = ai_fallback
    config.rerank_mode = rerank
    config.candidates_per_scene = 8
    config.min_clip_width = 1280
    config.min_clip_duration_s = 3.0
    config.allowed_licenses = []
    ctx.channel.footage_sourcing_or_default.return_value = config
    ctx.upstream = {
        'footage_queries': {
            'queries': [{
                'scene_idx': 0,
                'primary_query': 'ocean waves',
                'fallback_queries': ['ocean'],
                'media_preference': 'video',
                'orientation': 'landscape',
                'era_hint': '',
                'negative_terms': [],
                'ai_fallback_prompt': 'a stormy ocean',
            }],
        },
        'scene_breakdown': {
            'scenes': [{'idx': 0, 'visual_concept': 'ocean waves'}],
        },
    }
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'primary_query': 'ocean waves',
        'fallback_queries': ['ocean'],
        'media_preference': 'video',
        'orientation': 'landscape',
        'negative_terms': [],
        'ai_fallback_prompt': 'a stormy ocean',
        'visual_concept': 'ocean waves',
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='asset-uuid'))
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def test_stage_key_and_queue() -> None:
    """The stage registers under the expected key and queue."""
    assert FootageSearchStage.key == 'footage_search'
    assert FootageSearchStage.queue == 'api'


def test_fan_out_returns_one_shard_per_query() -> None:
    """Fan-out shards carry the query plus the scene's visual concept."""
    ctx = _make_ctx()
    shards = FootageSearchStage().fan_out(ctx)
    assert shards is not None
    assert len(shards) == 1
    assert shards[0]['scene_idx'] == 0
    assert shards[0]['primary_query'] == 'ocean waves'
    assert shards[0]['visual_concept'] == 'ocean waves'


def _patched_download() -> object:
    return patch(
        'server.apps.pipelines.stages.footage_search._download_and_validate',
        new=AsyncMock(return_value=(b'bytes', 'video/mp4')),
    )


def test_primary_query_hit_selects_a_candidate() -> None:
    """A direct hit downloads and records the selected candidate."""
    ctx = _make_ctx()
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[_candidate('1')]),
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['scene_idx'] == 0
    assert result['source'] == 'pexels'
    assert result['asset_id'] == 'asset-uuid'
    assert result['media_type'] == 'video'
    assert len(result['candidates']) == 1


def test_broadens_to_fallback_query_when_primary_is_empty() -> None:
    """An empty primary result retries with the broadened query."""
    ctx = _make_ctx()
    search = AsyncMock(side_effect=[[], [_candidate('2')]])
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=search,
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert search.await_count == 2
    assert result['source'] == 'pexels'


def test_falls_back_to_ai_generation_when_nothing_found() -> None:
    """Exhausted queries fall through to AI image generation."""
    ctx = _make_ctx(ai_fallback=True)
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[]),
        ),
        patch(
            'server.apps.generation.clients.fal.generate_image',
            new=AsyncMock(return_value={'url': 'https://fal/x.png'}),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._fetch_bytes',
            new=AsyncMock(return_value=b'img'),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['source'] == 'ai_flux'
    assert result['media_type'] == 'image'
    assert result['candidates'] == []


def test_parks_when_nothing_found_and_ai_disabled() -> None:
    """With AI disabled, an exhausted cascade parks the scene."""
    ctx = _make_ctx(ai_fallback=False)
    with patch(
        'server.apps.pipelines.stages.footage_search.search_candidates',
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageSearchStage().run(ctx))
    assert exc_info.value.error_code == 'no_footage_found'


def test_corrupt_download_falls_through_to_next_candidate() -> None:
    """A candidate that fails ffprobe validation is skipped."""
    ctx = _make_ctx()
    download = AsyncMock(side_effect=[None, (b'bytes', 'video/mp4')])
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[_candidate('1'), _candidate('2')]),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._download_and_validate',
            new=download,
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert download.await_count == 2
    assert result['asset_id'] == 'asset-uuid'


def test_vision_failure_degrades_to_metadata_ranking() -> None:
    """A failed vision call must not fail the scene."""
    ctx = _make_ctx(rerank='vision')
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[_candidate('1')]),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._vision_rank',
            new=AsyncMock(side_effect=RuntimeError('vision down')),
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['asset_id'] == 'asset-uuid'
    assert result['rerank_score'] is None


def test_vision_success_populates_the_rerank_score() -> None:
    """A successful vision pass reports the selected item's confidence."""
    ctx = _make_ctx(rerank='vision')
    ranked = [_candidate('1')]
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=ranked),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._vision_rank',
            new=AsyncMock(return_value=(ranked, {'1': 0.87})),
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['rerank_score'] == pytest.approx(0.87)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_footage_search.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: ...stages.footage_search`

- [ ] **Step 3: Write the implementation**

Create `server/apps/pipelines/stages/footage_search.py`:

```python
"""Footage search stage — fan-out per scene with a fallback cascade.

Per scene: search providers in priority order, re-rank, download and
validate the winner. When nothing usable is found the query broadens, then
falls back to AI generation, and only then parks the run for an operator.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, override

import httpx
import structlog
from asgiref.sync import sync_to_async

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import fal as fal_client
from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.generation.clients.stock.registry import (
    build_providers,
    search_candidates,
)
from server.apps.pipelines.logic.footage_rerank import (
    apply_vision_rankings,
    rank_by_metadata,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

logger = structlog.get_logger(__name__)

_AI_IMAGE_COST_USD = 0.035
_DOWNLOAD_TIMEOUT_S = 120.0


async def _fetch_bytes(url: str) -> bytes:
    """Download a URL and return its bytes."""
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


async def _probe_ok(content: bytes, suffix: str) -> bool:
    """Return True when ffprobe can read the downloaded media."""
    from server.apps.rendering.ffmpeg import async_ffprobe  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        path = handle.name
    try:
        await asyncio.to_thread(Path(path).write_bytes, content)
        probe = await async_ffprobe(path)
        return bool(probe.get('streams') or probe.get('format'))
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning('footage_probe_failed', error=str(exc))
        return False
    finally:
        await asyncio.to_thread(Path(path).unlink, missing_ok=True)


async def _download_and_validate(
    candidate: FootageCandidate,
) -> tuple[bytes, str] | None:
    """Download a candidate and verify it is playable; None when unusable."""
    try:
        content = await _fetch_bytes(candidate.download_url)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning(
            'footage_download_failed',
            provider=candidate.provider,
            external_id=candidate.external_id,
            error=str(exc),
        )
        return None
    if not content:
        return None
    suffix = '.mp4' if candidate.media_type == 'video' else '.jpg'
    if not await _probe_ok(content, suffix):
        return None
    mime = 'video/mp4' if candidate.media_type == 'video' else 'image/jpeg'
    return content, mime


def _record_credit_sync(
    run_id: str,
    asset_id: str,
    scene_idx: int,
    candidate: FootageCandidate,
) -> None:
    """Persist a FootageCredit row for a selected candidate."""
    from server.apps.assets.models import FootageCredit  # noqa: PLC0415

    FootageCredit.objects.create(
        asset_id=asset_id,
        run_id=run_id,
        scene_idx=scene_idx,
        provider=candidate.provider,
        license=candidate.license,
        license_url=candidate.license_url,
        author=candidate.author,
        source_url=candidate.source_page_url,
        title=candidate.title,
        attribution_required=candidate.attribution_required,
    )


_record_credit = sync_to_async(_record_credit_sync)


async def _vision_rank(
    ctx: StageContext,
    candidates: list[FootageCandidate],
    visual_concept: str,
) -> tuple[list[FootageCandidate], dict[str, float]]:
    """Score candidate thumbnails against the scene concept with a VLM.

    Returns the reordered candidates plus their scores keyed by
    ``external_id`` so the selected item's confidence reaches the review UI.
    """
    from pydantic_ai import Agent, ImageUrl  # noqa: PLC0415

    from server.apps.generation.clients import llm as llm_client  # noqa: PLC0415
    from server.apps.generation.logic.model_resolver import (  # noqa: PLC0415
        to_pydantic_ai_model,
    )
    from server.apps.generation.logic.stage_model import (  # noqa: PLC0415
        resolve_stage_model,
    )
    from server.apps.pipelines.schemas import (  # noqa: PLC0415
        CandidateRankingOutput,
    )

    model_slug = await resolve_stage_model(ctx, 'footage_search')
    agent: Agent[StageContext, CandidateRankingOutput] = Agent(
        to_pydantic_ai_model(model_slug),
        output_type=CandidateRankingOutput,
        deps_type=StageContext,
    )
    content: list[Any] = [
        f'Scene visual concept: "{visual_concept}". Score each numbered '
        f'image 0.0-1.0 on how well it depicts this concept. Return one '
        f'ranking per image using the external_id given.',
    ]
    for candidate in candidates:
        content.append(f'external_id={candidate.external_id}')
        content.append(ImageUrl(url=candidate.thumb_url))

    output: CandidateRankingOutput = await llm_client.run_agent(
        agent,
        content,
        ctx,
        stage_key='footage_search',
        model_slug=model_slug,
    )
    scores = {r.external_id: r.score for r in output.rankings}
    return apply_vision_rankings(candidates, output.rankings), scores


@register_stage
class FootageSearchStage(Stage):
    """Documentary stage: find and download one visual per scene."""

    key = 'footage_search'
    queue = 'api'
    max_retries = 3
    timeout_s = 600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Shard by query — one child per scene."""
        queries = ctx.upstream.get('footage_queries', {}).get('queries', [])
        scenes = {
            int(s['idx']): s
            for s in ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        }
        return [
            {
                'scene_idx': q['scene_idx'],
                'primary_query': q['primary_query'],
                'fallback_queries': q.get('fallback_queries', []),
                'media_preference': q.get('media_preference', 'any'),
                'orientation': q.get('orientation', 'landscape'),
                'negative_terms': q.get('negative_terms', []),
                'ai_fallback_prompt': q.get('ai_fallback_prompt', ''),
                'visual_concept': scenes.get(int(q['scene_idx']), {}).get(
                    'visual_concept',
                    '',
                ),
            }
            for q in queries
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Run the cascade for this shard's scene."""
        snap = ctx.execution.input_snapshot
        scene_idx = int(snap['scene_idx'])
        config = ctx.channel.footage_sourcing_or_default()
        providers = build_providers(list(config.enabled_providers))
        media_type = (
            'image' if snap.get('media_preference') == 'image' else 'video'
        )

        queries = [snap['primary_query'], *snap.get('fallback_queries', [])]
        for query in queries:
            candidates = await search_candidates(
                providers=providers,
                query=query,
                media_type=media_type,
                orientation=snap.get('orientation', 'landscape'),
                min_width=config.min_clip_width,
                min_duration_s=config.min_clip_duration_s,
                allowed_licenses=list(config.allowed_licenses),
                limit=config.candidates_per_scene,
            )
            if not candidates:
                continue
            ranked, scores = await self._rank(ctx, candidates, snap, config)
            selected = await self._download_first_usable(
                ctx,
                ranked,
                scene_idx,
                scores,
            )
            if selected is not None:
                return selected

        return await self._ai_fallback(ctx, snap, scene_idx, config)

    async def _rank(
        self,
        ctx: StageContext,
        candidates: list[FootageCandidate],
        snap: dict[str, Any],
        config: Any,
    ) -> tuple[list[FootageCandidate], dict[str, float]]:
        """Order candidates by the channel's configured rerank mode.

        Returns (ranked, scores). ``scores`` is empty for every mode except a
        successful vision pass, so ``rerank_score`` is None whenever no model
        actually scored the pick.
        """
        concept = snap.get('visual_concept', '')
        negatives = snap.get('negative_terms', [])
        if config.rerank_mode == 'none':
            return list(candidates), {}
        if config.rerank_mode == 'vision':
            try:
                return await _vision_rank(ctx, candidates, concept)
            except Exception as exc:  # noqa: BLE001 — degrade, never fail
                logger.warning(
                    'footage_vision_rerank_failed',
                    run_id=str(ctx.run.id),
                    error=str(exc),
                )
        return rank_by_metadata(
            candidates,
            visual_concept=concept,
            negative_terms=negatives,
        ), {}

    async def _download_first_usable(
        self,
        ctx: StageContext,
        ranked: list[FootageCandidate],
        scene_idx: int,
        scores: dict[str, float],
    ) -> dict[str, Any] | None:
        """Download ranked candidates until one validates; None if all fail."""
        for candidate in ranked:
            downloaded = await _download_and_validate(candidate)
            if downloaded is None:
                continue
            content, mime = downloaded
            suffix = 'mp4' if candidate.media_type == 'video' else 'jpg'
            asset = await ctx.assets.save(
                kind=AssetKind.FOOTAGE,
                content=content,
                filename=f'scene_{scene_idx:04d}.{suffix}',
                mime=mime,
            )
            await _record_credit(
                str(ctx.run.id),
                str(asset.id),
                scene_idx,
                candidate,
            )
            return {
                'scene_idx': scene_idx,
                'asset_id': str(asset.id),
                'media_type': candidate.media_type,
                'source': candidate.provider,
                'license': candidate.license,
                'license_url': candidate.license_url,
                'attribution': candidate.author,
                'attribution_required': candidate.attribution_required,
                'source_url': candidate.source_page_url,
                'rerank_score': scores.get(candidate.external_id),
                'candidates': [
                    _candidate_dict(c) for c in ranked
                ],
            }
        return None

    async def _ai_fallback(
        self,
        ctx: StageContext,
        snap: dict[str, Any],
        scene_idx: int,
        config: Any,
    ) -> dict[str, Any]:
        """Generate the scene with AI, or park when that is disabled."""
        prompt = snap.get('ai_fallback_prompt', '')
        if not config.ai_fallback_enabled or not prompt:
            raise FatalProviderError(
                f'Scene {scene_idx}: no usable footage found and AI '
                f'fallback is unavailable',
                provider='footage_search',
                error_code='no_footage_found',
            )
        result = await fal_client.generate_image(
            prompt=prompt,
            model=ctx.config.get('ai_model', 'fal-ai/flux/dev'),
            width=1920,
            height=1080,
        )
        content = await _fetch_bytes(result['url'])
        asset = await ctx.assets.save(
            kind=AssetKind.FOOTAGE,
            content=content,
            filename=f'scene_{scene_idx:04d}.jpg',
            mime='image/jpeg',
        )
        await ctx.costs.record(
            provider='fal_flux',
            operation='footage_ai_fallback',
            units=1,
            unit_cost_usd=_AI_IMAGE_COST_USD,
        )
        logger.info(
            'footage_ai_fallback_used',
            run_id=str(ctx.run.id),
            scene_idx=scene_idx,
        )
        return {
            'scene_idx': scene_idx,
            'asset_id': str(asset.id),
            'media_type': 'image',
            'source': 'ai_flux',
            'license': 'generated',
            'license_url': '',
            'attribution': '',
            'attribution_required': False,
            'source_url': '',
            'rerank_score': None,
            'candidates': [],
        }


def _candidate_dict(candidate: FootageCandidate) -> dict[str, Any]:
    """Serialise a candidate for the review UI."""
    return {
        'external_id': candidate.external_id,
        'provider': candidate.provider,
        'thumb_url': candidate.thumb_url,
        'preview_url': candidate.download_url,
        'width': candidate.width,
        'height': candidate.height,
        'duration_s': candidate.duration_s,
        'license': candidate.license,
        'author': candidate.author,
        'source_url': candidate.source_page_url,
    }
```

- [ ] **Step 4: Register the stage and add import exemptions**

Add `footage_search,  # noqa: F401` to `stages/__init__.py`.

In `.importlinter`, add:

```
  server.apps.pipelines.stages.footage_search -> server.apps.generation.clients.fal
  server.apps.pipelines.stages.footage_search -> server.apps.generation.clients.stock.base
  server.apps.pipelines.stages.footage_search -> server.apps.generation.clients.stock.registry
  server.apps.pipelines.stages.footage_search -> server.apps.assets.models
  server.apps.pipelines.stages.footage_search -> server.apps.rendering.ffmpeg
```

- [ ] **Step 5: Run tests and the import contract**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_footage_search.py -v --no-cov
docker compose exec web lint-imports
docker compose exec web mypy server
```
Expected: PASS, 9 passed

- [ ] **Step 6: Commit**

```bash
git add server/apps/pipelines/stages/footage_search.py \
        server/apps/pipelines/stages/__init__.py .importlinter \
        tests/test_apps/test_pipelines/test_stages/test_footage_search.py
git commit -m "feat(pipelines): add footage_search stage with fallback cascade"
```

---

## Task 5: `footage_prep` stage

**Files:**
- Create: `server/apps/pipelines/stages/footage_prep.py`
- Modify: `server/apps/rendering/ffmpeg.py` (add `normalize_clip`)
- Modify: `server/apps/pipelines/stages/__init__.py`, `.importlinter`
- Test: `tests/test_apps/test_pipelines/test_stages/test_footage_prep.py`
- Test: `tests/test_apps/test_rendering/test_ffmpeg_normalize_clip.py`

**Interfaces:**
- Consumes: `ken_burns` (foundations Task 3), `AssetKind` .
- Produces:
  - `async def normalize_clip(video_bytes: bytes, duration_s: float, *,
    width: int = 1920, height: int = 1080, fps: int = 30) -> tuple[bytes, str]`
    returning `(mp4_bytes, method)` where method is `'clip_trim'` or
    `'clip_loop'`.
  - `FootagePrepStage`, `key = 'footage_prep'`, `queue = 'render'`. Shard
    output **matches `motion` exactly**: `{'scene_idx', 'asset_id',
    'duration_s', 'method'}`.

- [ ] **Step 1: Write the failing ffmpeg test**

Create `tests/test_apps/test_rendering/test_ffmpeg_normalize_clip.py`:

```python
"""Tests for normalizing sourced clips to a scene duration."""

import asyncio
from pathlib import Path

from server.apps.rendering.ffmpeg import async_ffprobe, normalize_clip


def _synthetic_clip(tmp_path: Path, seconds: float) -> bytes:
    """Render a short test clip at a non-target resolution."""
    out = tmp_path / f'src_{seconds}.mp4'
    proc = asyncio.run(
        asyncio.create_subprocess_exec(
            'ffmpeg', '-y', '-f', 'lavfi',
            '-i', f'testsrc=size=640x480:rate=25:duration={seconds}',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        ),
    )
    asyncio.run(proc.wait())
    return out.read_bytes()


def test_longer_clip_is_trimmed_from_the_start(tmp_path: Path) -> None:
    """A clip longer than the scene is trimmed, not looped."""
    source = _synthetic_clip(tmp_path, seconds=10.0)
    result, method = asyncio.run(normalize_clip(source, duration_s=4.0))
    assert method == 'clip_trim'
    out = tmp_path / 'trim.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    assert 3.5 <= float(probe['format']['duration']) <= 4.5


def test_shorter_clip_is_looped_to_fill(tmp_path: Path) -> None:
    """A clip shorter than the scene loops to reach the target length."""
    source = _synthetic_clip(tmp_path, seconds=2.0)
    result, method = asyncio.run(normalize_clip(source, duration_s=6.0))
    assert method == 'clip_loop'
    out = tmp_path / 'loop.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    assert 5.5 <= float(probe['format']['duration']) <= 6.5


def test_output_is_scaled_to_target_resolution(tmp_path: Path) -> None:
    """Whatever the source size, output is 1920x1080."""
    source = _synthetic_clip(tmp_path, seconds=5.0)
    result, _ = asyncio.run(normalize_clip(source, duration_s=3.0))
    out = tmp_path / 'scaled.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert int(stream['width']) == 1920
    assert int(stream['height']) == 1080


def test_output_has_no_audio_stream(tmp_path: Path) -> None:
    """Source audio is stripped — narration owns the audio track."""
    source = _synthetic_clip(tmp_path, seconds=5.0)
    result, _ = asyncio.run(normalize_clip(source, duration_s=3.0))
    out = tmp_path / 'noaudio.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    assert not [s for s in probe['streams'] if s['codec_type'] == 'audio']
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_rendering/test_ffmpeg_normalize_clip.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'normalize_clip'`

- [ ] **Step 3: Implement `normalize_clip`**

Add to `server/apps/rendering/ffmpeg.py`:

```python
async def normalize_clip(
    video_bytes: bytes,
    duration_s: float,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> tuple[bytes, str]:
    """Fit a sourced clip to a scene: trim or loop, scale, strip audio.

    Trimming always takes the window from the start of the clip so a shard
    rerun produces an identical segment. Returns (mp4_bytes, method) where
    method is 'clip_trim' or 'clip_loop'.
    """
    assert video_bytes, 'video_bytes must be non-empty'
    assert duration_s > 0, f'duration_s must be > 0, got {duration_s}'

    with (
        tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as src_f,
        tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as out_f,
    ):
        src_path = src_f.name
        out_path = out_f.name
    try:
        await asyncio.to_thread(Path(src_path).write_bytes, video_bytes)
        probe = await async_ffprobe(src_path)
        source_duration = float(
            probe.get('format', {}).get('duration', 0.0) or 0.0,
        )
        needs_loop = source_duration < duration_s
        method = 'clip_loop' if needs_loop else 'clip_trim'

        vf = (
            f'scale={width}:{height}:force_original_aspect_ratio=increase,'
            f'crop={width}:{height},fps={fps}'
        )
        cmd = ['ffmpeg', '-y']
        if needs_loop:
            cmd += ['-stream_loop', '-1']
        cmd += [
            '-i', src_path,
            '-t', str(duration_s),
            '-vf', vf,
            '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-an', out_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f'FFmpeg normalize_clip failed: {stderr.decode()[:300]}',
            )

        out_bytes = await asyncio.to_thread(Path(out_path).read_bytes)
        assert out_bytes, 'normalize_clip produced empty video'
        return out_bytes, method
    finally:
        await asyncio.to_thread(Path(src_path).unlink, missing_ok=True)
        await asyncio.to_thread(Path(out_path).unlink, missing_ok=True)
```

- [ ] **Step 4: Write the failing stage test**

Create `tests/test_apps/test_pipelines/test_stages/test_footage_prep.py`:

```python
"""Tests for the footage_prep fan-out stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.footage_prep import FootagePrepStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.id = 'run-uuid'
    ctx.upstream = {
        'footage_search': {
            'shards': [
                {'scene_idx': 0, 'asset_id': 'a0', 'media_type': 'video'},
                {'scene_idx': 1, 'asset_id': 'a1', 'media_type': 'image'},
            ],
        },
        'scene_breakdown': {
            'scenes': [
                {'idx': 0, 'est_seconds': 8.0},
                {'idx': 1, 'est_seconds': 6.0},
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='seg-uuid'))
    return ctx


def test_stage_key_and_queue() -> None:
    """The stage runs on the render queue."""
    assert FootagePrepStage.key == 'footage_prep'
    assert FootagePrepStage.queue == 'render'


def test_fan_out_carries_media_type_and_duration() -> None:
    """Each shard knows its media type and target duration."""
    shards = FootagePrepStage().fan_out(_make_ctx())
    assert shards is not None
    assert shards[0] == {
        'scene_idx': 0, 'asset_id': 'a0',
        'media_type': 'video', 'est_seconds': 8.0,
    }
    assert shards[1]['media_type'] == 'image'


def test_video_shard_normalizes_the_clip() -> None:
    """A video shard runs normalize_clip and reports its method."""
    ctx = _make_ctx()
    ctx.execution.input_snapshot = {
        'scene_idx': 0, 'asset_id': 'a0',
        'media_type': 'video', 'est_seconds': 8.0,
    }
    with (
        patch(
            'server.apps.pipelines.stages.footage_prep._load_asset_bytes',
            new=AsyncMock(return_value=b'src'),
        ),
        patch(
            'server.apps.rendering.ffmpeg.normalize_clip',
            new=AsyncMock(return_value=(b'out', 'clip_trim')),
        ),
    ):
        result = asyncio.run(FootagePrepStage().run(ctx))
    assert result == {
        'scene_idx': 0, 'asset_id': 'seg-uuid',
        'duration_s': 8.0, 'method': 'clip_trim',
    }


def test_image_shard_applies_ken_burns() -> None:
    """An image shard reuses the shared Ken Burns helper."""
    ctx = _make_ctx()
    ctx.execution.input_snapshot = {
        'scene_idx': 1, 'asset_id': 'a1',
        'media_type': 'image', 'est_seconds': 6.0,
    }
    with (
        patch(
            'server.apps.pipelines.stages.footage_prep._load_asset_bytes',
            new=AsyncMock(return_value=b'img'),
        ),
        patch(
            'server.apps.rendering.ffmpeg.ken_burns',
            new=AsyncMock(return_value=b'out'),
        ),
    ):
        result = asyncio.run(FootagePrepStage().run(ctx))
    assert result['method'] == 'ken_burns'
    assert result['duration_s'] == 6.0


def test_output_shape_matches_motion_stage() -> None:
    """Assembly reads these keys; they must match motion exactly."""
    ctx = _make_ctx()
    ctx.execution.input_snapshot = {
        'scene_idx': 0, 'asset_id': 'a0',
        'media_type': 'video', 'est_seconds': 8.0,
    }
    with (
        patch(
            'server.apps.pipelines.stages.footage_prep._load_asset_bytes',
            new=AsyncMock(return_value=b'src'),
        ),
        patch(
            'server.apps.rendering.ffmpeg.normalize_clip',
            new=AsyncMock(return_value=(b'out', 'clip_trim')),
        ),
    ):
        result = asyncio.run(FootagePrepStage().run(ctx))
    assert set(result) == {'scene_idx', 'asset_id', 'duration_s', 'method'}
```

- [ ] **Step 5: Implement the stage**

Create `server/apps/pipelines/stages/footage_prep.py`:

```python
"""Footage prep stage — normalize sourced media into scene segments.

Output shape is identical to the motion stage so assembly consumes either
without branching.
"""

import asyncio
from typing import Any, override

from server.apps.assets.models import AssetKind
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.apps.rendering import ffmpeg


async def _load_asset_bytes(asset_id: str) -> bytes:
    """Read a stored Asset's bytes."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return await asyncio.to_thread(asset.file.read)


@register_stage
class FootagePrepStage(Stage):
    """Documentary stage: fit each sourced visual to its scene."""

    key = 'footage_prep'
    queue = 'render'
    max_retries = 2
    timeout_s = 600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Shard by scene — one child per footage_search result."""
        shards = ctx.upstream.get('footage_search', {}).get('shards', [])
        scenes = {
            int(s['idx']): s
            for s in ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        }
        return [
            {
                'scene_idx': sh['scene_idx'],
                'asset_id': sh['asset_id'],
                'media_type': sh.get('media_type', 'image'),
                'est_seconds': float(
                    scenes.get(int(sh['scene_idx']), {}).get(
                        'est_seconds',
                        8.0,
                    ),
                ),
            }
            for sh in shards
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Normalize this shard's media into a video segment."""
        snap = ctx.execution.input_snapshot
        scene_idx = int(snap['scene_idx'])
        est_seconds = float(snap.get('est_seconds', 8.0))
        content = await _load_asset_bytes(str(snap['asset_id']))

        if snap.get('media_type') == 'video':
            video_bytes, method = await ffmpeg.normalize_clip(
                content,
                duration_s=est_seconds,
                width=ctx.config.get('target_width', 1920),
                height=ctx.config.get('target_height', 1080),
                fps=ctx.config.get('fps', 30),
            )
        else:
            video_bytes = await ffmpeg.ken_burns(
                image_bytes=content,
                duration_s=est_seconds,
                preset_idx=scene_idx,
            )
            method = 'ken_burns'

        asset = await ctx.assets.save(
            kind=AssetKind.VIDEO_SEGMENT,
            content=video_bytes,
            filename=f'scene_{scene_idx:04d}_{method}.mp4',
            mime='video/mp4',
        )
        return {
            'scene_idx': scene_idx,
            'asset_id': str(asset.id),
            'duration_s': est_seconds,
            'method': method,
        }
```

- [ ] **Step 6: Register and exempt imports**

Add `footage_prep,  # noqa: F401` to `stages/__init__.py`.

In `.importlinter`:

```
  server.apps.pipelines.stages.footage_prep -> server.apps.assets.models
  server.apps.pipelines.stages.footage_prep -> server.apps.rendering.ffmpeg
```

- [ ] **Step 7: Run tests**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_rendering/test_ffmpeg_normalize_clip.py tests/test_apps/test_pipelines/test_stages/test_footage_prep.py -v --no-cov
docker compose exec web lint-imports
```
Expected: PASS, 9 passed

- [ ] **Step 8: Commit**

```bash
git add server/apps/pipelines/stages/footage_prep.py \
        server/apps/rendering/ffmpeg.py \
        server/apps/pipelines/stages/__init__.py .importlinter \
        tests/test_apps/test_rendering/test_ffmpeg_normalize_clip.py \
        tests/test_apps/test_pipelines/test_stages/test_footage_prep.py
git commit -m "feat(pipelines): add footage_prep stage and clip normalizer"
```

---

## Task 6: Format-driven prompt snapshots

**Files:**
- Modify: `server/apps/pipelines/services/prompt_renderer.py`
- Modify: `server/apps/pipelines/services/pipeline_run.py`
- Modify: `server/apps/pipelines/services/prompt_variables.py`
- Test: `tests/test_apps/test_pipelines/test_prompt_snapshot.py`

**Interfaces:**
- Produces:
  - `build_prompt_overrides_snapshot(channel) -> dict[str, str]` in
    `pipeline_run.py` — maps stage key → `PromptVersion` id string.
  - `PromptRenderer` reads `snapshot['prompts'][stage_key]`, falling back to
    `snapshot[stage_key]`.
  - `build_prompt_variables` gains a `footage` key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_pipelines/test_prompt_snapshot.py`:

```python
"""Tests for format-driven prompt selection and the footage namespace."""

import pytest

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    NicheConfig,
)
from server.apps.pipelines.services.pipeline_run import (
    build_prompt_overrides_snapshot,
)
from server.apps.pipelines.services.prompt_renderer import PromptRenderer
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


@pytest.fixture
def channel(db: None) -> Channel:
    return Channel.objects.create(name='Doc', kind=ChannelKind.LONGFORM)


@pytest.mark.django_db
def test_channel_without_format_gets_empty_snapshot(
    channel: Channel,
) -> None:
    """Existing longform channels are completely unaffected."""
    assert build_prompt_overrides_snapshot(channel) == {}


@pytest.mark.django_db
def test_format_with_no_overrides_gets_empty_snapshot(
    channel: Channel,
) -> None:
    """A format with the default empty overrides changes nothing."""
    fmt = StoryFormat.objects.create(
        key='plain', name='Plain', beats=[], prompt_overrides={},
    )
    NicheConfig.objects.create(channel=channel, format=fmt)
    channel.refresh_from_db()
    assert build_prompt_overrides_snapshot(channel) == {}


@pytest.mark.django_db
def test_overrides_resolve_to_active_prompt_version(
    channel: Channel,
) -> None:
    """A template key maps to the currently-active version id."""
    template = PromptTemplate.objects.create(
        name='Doc script', key='script_documentary', scope=PromptScope.GLOBAL,
    )
    active = PromptVersion.objects.create(
        template=template, version=2, system_prompt='s',
        user_prompt='u', is_active=True,
    )
    PromptVersion.objects.create(
        template=template, version=1, system_prompt='old',
        user_prompt='old', is_active=False,
    )
    fmt = StoryFormat.objects.create(
        key='doc', name='Doc', beats=[],
        prompt_overrides={'script': 'script_documentary'},
    )
    NicheConfig.objects.create(channel=channel, format=fmt)
    channel.refresh_from_db()

    snapshot = build_prompt_overrides_snapshot(channel)
    assert snapshot == {'script': str(active.id)}


@pytest.mark.django_db
def test_override_naming_a_missing_template_is_skipped(
    channel: Channel,
) -> None:
    """A typo'd template key degrades to the global default, not a crash."""
    fmt = StoryFormat.objects.create(
        key='doc', name='Doc', beats=[],
        prompt_overrides={'script': 'no_such_template'},
    )
    NicheConfig.objects.create(channel=channel, format=fmt)
    channel.refresh_from_db()
    assert build_prompt_overrides_snapshot(channel) == {}


@pytest.mark.django_db
async def test_renderer_reads_nested_prompts_key() -> None:
    """Resolved prompts live under snapshot['prompts']."""
    template = await PromptTemplate.objects.acreate(
        name='T', key='script', scope=PromptScope.GLOBAL,
    )
    version = await PromptVersion.objects.acreate(
        template=template, version=1,
        system_prompt='sys {{ topic }}', user_prompt='usr',
        is_active=True,
    )
    renderer = PromptRenderer({'prompts': {'script': str(version.id)}})
    sys, _ = await renderer.render('script', {'topic': 'Rome'})
    assert sys == 'sys Rome'


@pytest.mark.django_db
async def test_renderer_still_reads_flat_keys() -> None:
    """The pre-nesting flat layout keeps working."""
    template = await PromptTemplate.objects.acreate(
        name='T', key='outline', scope=PromptScope.GLOBAL,
    )
    version = await PromptVersion.objects.acreate(
        template=template, version=1,
        system_prompt='flat', user_prompt='u', is_active=True,
    )
    renderer = PromptRenderer({'outline': str(version.id)})
    sys, _ = await renderer.render('outline', {})
    assert sys == 'flat'


@pytest.mark.django_db
def test_clip_metadata_keys_do_not_leak_into_prompt_lookup() -> None:
    """Clipping metadata in the snapshot is not mistaken for a version id."""
    renderer = PromptRenderer({
        'source_title': 'A video',
        'clip_options': {'auto_approve': True},
    })
    assert renderer._snapshot.get('prompts') is None
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_prompt_snapshot.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name
'build_prompt_overrides_snapshot'`

- [ ] **Step 3: Update `PromptRenderer` to read the nested key**

In `server/apps/pipelines/services/prompt_renderer.py`, replace the body of
`_get_prompt_version`'s lookup. Change:

```python
        version_id = self._snapshot.get(stage_key)
```

to:

```python
        nested = self._snapshot.get('prompts')
        version_id = (
            nested.get(stage_key) if isinstance(nested, dict) else None
        ) or self._snapshot.get(stage_key)
```

Apply the same change in `get_version_id`:

```python
    async def get_version_id(self, stage_key: str) -> str | None:
        """Return the PromptVersion UUID pinned for this stage, or None."""
        nested = self._snapshot.get('prompts')
        if isinstance(nested, dict) and stage_key in nested:
            return str(nested[stage_key])
        value = self._snapshot.get(stage_key)
        return str(value) if value else None
```

- [ ] **Step 4: Add snapshot resolution in `pipeline_run.py`**

Add the helper at module level:

```python
def build_prompt_overrides_snapshot(channel: 'Channel') -> dict[str, str]:
    """Resolve a channel's StoryFormat prompt overrides to version ids.

    ``StoryFormat.prompt_overrides`` maps a stage key to a *template* key.
    Each is resolved to the currently-active PromptVersion id so the run is
    pinned to an immutable version. Overrides naming an unknown template are
    skipped, falling back to the global default for that stage.
    """
    from server.apps.prompts.models import PromptVersion  # noqa: PLC0415

    niche = getattr(channel, 'niche_config', None)
    fmt = getattr(niche, 'format', None) if niche else None
    overrides = getattr(fmt, 'prompt_overrides', None) or {}
    if not isinstance(overrides, dict):
        return {}

    resolved: dict[str, str] = {}
    for stage_key, template_key in overrides.items():
        version_id = (
            PromptVersion.objects
            .filter(template__key=str(template_key), is_active=True)
            .values_list('id', flat=True)
            .first()
        )
        if version_id is not None:
            resolved[str(stage_key)] = str(version_id)
    return resolved
```

Then populate it on the non-clipping run creation path. Change:

```python
        topic = payload.topic
        prompt_snapshot: dict[str, object] = {}
```

to:

```python
        topic = payload.topic
        prompt_snapshot: dict[str, object] = {}
        resolved_prompts = build_prompt_overrides_snapshot(channel)
        if resolved_prompts:
            prompt_snapshot['prompts'] = resolved_prompts
```

The clipping branch overwrites `prompt_snapshot` wholesale; add
`'prompts': resolved_prompts` to that dict literal too so clipping runs keep
any format overrides:

```python
                prompt_snapshot = {
                    'source_title': clip_source.title,
                    'source_id': str(clip_source.id),
                    'clip_options': clip_options,
                    'prompts': resolved_prompts,
                }
```

- [ ] **Step 5: Add the `footage` prompt namespace**

In `server/apps/pipelines/services/prompt_variables.py`, add the helper:

```python
def _footage_dict(channel: Any) -> dict[str, Any]:
    """Expose footage sourcing settings to prompt templates."""
    config = getattr(channel, 'footage_sourcing', None)
    if config is None:
        return {
            'providers': [],
            'sourcing_mode': 'stock_first',
            'ai_fallback_enabled': True,
            'min_width': 1280,
            'attribution_required': True,
        }
    return {
        'providers': list(getattr(config, 'enabled_providers', []) or []),
        'sourcing_mode': getattr(config, 'sourcing_mode', 'stock_first'),
        'ai_fallback_enabled': bool(
            getattr(config, 'ai_fallback_enabled', True),
        ),
        'min_width': int(getattr(config, 'min_clip_width', 1280)),
        'attribution_required': bool(
            getattr(config, 'require_attribution', True),
        ),
    }
```

and add to the `variables` dict in `build_prompt_variables`:

```python
        'footage': _footage_dict(ctx.channel),
```

- [ ] **Step 6: Run tests**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_pipelines/test_prompt_snapshot.py -v --no-cov
docker compose exec web pytest tests/test_apps/test_pipelines/ -v --no-cov
```
Expected: PASS. **Every pre-existing pipelines test must still pass** — that is
the proof `longform_v1` prompt resolution is unchanged.

- [ ] **Step 7: Commit**

```bash
git add server/apps/pipelines/services/ \
        tests/test_apps/test_pipelines/test_prompt_snapshot.py
git commit -m "feat(pipelines): resolve StoryFormat prompt overrides per run"
```

---

## Task 7: Seed documentary formats and prompt templates

**Files:**
- Create: `server/apps/prompts/management/commands/seed_story_formats.py`
- Create: `server/apps/prompts/management/__init__.py`,
  `server/apps/prompts/management/commands/__init__.py` (if absent)
- Test: `tests/test_apps/test_prompts/test_seed_story_formats.py`

**Interfaces:**
- Produces: management command `seed_story_formats`, idempotent, creating
  `StoryFormat` rows `documentary_stock` and `documentary_archival` plus
  `PromptTemplate` + active `PromptVersion` rows for `script_documentary`,
  `scene_breakdown_documentary`, and `footage_queries`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_prompts/test_seed_story_formats.py`:

```python
"""Tests for the documentary format and prompt seeding command."""

import pytest
from django.core.management import call_command

from server.apps.prompts.models import (
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


@pytest.mark.django_db
def test_seeds_both_documentary_formats() -> None:
    """Both formats exist with documentary beats and no fiction flag."""
    call_command('seed_story_formats')
    keys = set(StoryFormat.objects.values_list('key', flat=True))
    assert {'documentary_stock', 'documentary_archival'} <= keys
    fmt = StoryFormat.objects.get(key='documentary_stock')
    assert fmt.fiction is False
    assert fmt.narration_pov == 'narrator'
    assert len(fmt.beats) >= 5


@pytest.mark.django_db
def test_formats_point_at_documentary_prompt_templates() -> None:
    """prompt_overrides map stage keys to documentary template keys."""
    call_command('seed_story_formats')
    fmt = StoryFormat.objects.get(key='documentary_stock')
    assert fmt.prompt_overrides['script'] == 'script_documentary'
    assert (
        fmt.prompt_overrides['scene_breakdown']
        == 'scene_breakdown_documentary'
    )


@pytest.mark.django_db
def test_seeds_active_prompt_versions() -> None:
    """Each new template has exactly one active version."""
    call_command('seed_story_formats')
    for key in (
        'script_documentary',
        'scene_breakdown_documentary',
        'footage_queries',
    ):
        template = PromptTemplate.objects.get(key=key)
        active = PromptVersion.objects.filter(
            template=template, is_active=True,
        )
        assert active.count() == 1
        assert active.first().system_prompt


@pytest.mark.django_db
def test_command_is_idempotent() -> None:
    """Running twice creates no duplicates."""
    call_command('seed_story_formats')
    call_command('seed_story_formats')
    assert StoryFormat.objects.filter(key='documentary_stock').count() == 1
    assert (
        PromptTemplate.objects.filter(key='script_documentary').count() == 1
    )
    assert (
        PromptVersion.objects.filter(
            template__key='script_documentary',
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_archival_format_prefers_stills() -> None:
    """The archival format's overrides differ from the stock format's."""
    call_command('seed_story_formats')
    archival = StoryFormat.objects.get(key='documentary_archival')
    assert archival.prompt_overrides['script'] == 'script_documentary'
    assert archival.pacing
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_prompts/test_seed_story_formats.py -v --no-cov`
Expected: FAIL — `CommandError: Unknown command: 'seed_story_formats'`

- [ ] **Step 3: Write the command**

Create `server/apps/prompts/management/commands/seed_story_formats.py`:

```python
"""Seed documentary story formats and their prompt templates (idempotent)."""

from typing import override

from django.core.management.base import BaseCommand

_DOC_BEATS = [
    'cold_open_hook',
    'thesis',
    'context',
    'escalating_evidence',
    'turn',
    'resolution',
    'reflection',
]

_SCRIPT_SYSTEM = (
    'You write narration for documentary videos built from stock and '
    'archival footage. Narration may name specific people, places, and '
    'dates. The VISUALS may not: every scene must be describable as an '
    'archetypal, findable shot. Write "a destroyer\'s deck in heavy seas", '
    'never "HMS Hood at 05:52". Favour visual motifs that recur across the '
    'video — maps, documents, machinery, landscapes, crowds, hands at work '
    '— so a limited footage inventory carries the full runtime without '
    'visible repetition. Never describe a shot that could only exist if '
    'someone had filmed one specific unrepeatable moment.'
)

_SCRIPT_USER = (
    'Write the documentary script for "{{ topic }}".\n'
    'Audience: {{ niche.audience }}\n'
    'Angle: {{ niche.angle }}\n'
    'Research: {{ upstream.research }}\n'
    'Outline: {{ upstream.outline }}\n'
    'Every visual you imply must be sourceable from a footage library.'
)

_BREAKDOWN_SYSTEM = (
    'You break documentary scripts into scenes for footage sourcing. Each '
    'scene needs 6-12 seconds of narration and a visual_concept naming a '
    'concrete, generic, findable shot. Set era_hint for period material and '
    'avoid anachronism — do not pair 1940s narration with a visual concept '
    'that implies modern equipment. This format has no cast: return an '
    'empty cast list. Each scene narration_text must be 10-35 words.'
)

_BREAKDOWN_USER = (
    'Break "{{ topic }}" into documentary scenes.\n'
    'Chapters: {{ upstream.script.chapters }}\n'
    'Return scenes with idx, chapter_idx, beat, narration_text, '
    'visual_concept, shot_type, est_seconds (6-12), is_hero, word_count. '
    'Return an empty cast list.'
)

_QUERIES_SYSTEM = (
    'You write search queries for stock and public-domain footage '
    'libraries. For each scene, produce a primary_query of 2-5 concrete '
    'visual nouns describing an archetypal, findable shot. Never name '
    'individuals or specific dated events. Add 2-3 progressively broader '
    'fallback_queries. Set media_preference to "video" for motion-led '
    'scenes and "image" for archival or static ones. Always write an '
    'ai_fallback_prompt used only when no footage is found.'
)

_QUERIES_USER = (
    'Write footage search queries for "{{ topic }}".\n'
    'Available providers: {{ footage.providers }}\n'
    'Sourcing mode: {{ footage.sourcing_mode }}\n'
    'Scenes: {{ upstream.scene_breakdown.scenes }}\n'
    'Return one FootageQuery per scene, matching scene_idx values.'
)

_TEMPLATES = [
    ('script_documentary', 'Documentary script', _SCRIPT_SYSTEM, _SCRIPT_USER),
    (
        'scene_breakdown_documentary',
        'Documentary scene breakdown',
        _BREAKDOWN_SYSTEM,
        _BREAKDOWN_USER,
    ),
    ('footage_queries', 'Footage queries', _QUERIES_SYSTEM, _QUERIES_USER),
]

_OVERRIDES = {
    'script': 'script_documentary',
    'scene_breakdown': 'scene_breakdown_documentary',
    'footage_queries': 'footage_queries',
}


class Command(BaseCommand):
    """Seed documentary story formats and prompts (idempotent upsert)."""

    help = 'Seed documentary StoryFormats and their prompt templates'

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Create or update documentary formats and prompt versions."""
        from server.apps.prompts.models import (  # noqa: PLC0415
            PromptScope,
            PromptTemplate,
            PromptVersion,
            StoryFormat,
        )

        for key, name, system, user in _TEMPLATES:
            template, _ = PromptTemplate.objects.update_or_create(
                key=key,
                defaults={'name': name, 'scope': PromptScope.GLOBAL},
            )
            PromptVersion.objects.update_or_create(
                template=template,
                version=1,
                defaults={
                    'system_prompt': system,
                    'user_prompt': user,
                    'is_active': True,
                },
            )
            self.stdout.write(self.style.SUCCESS(f'Seeded prompt: {key}'))

        formats = [
            (
                'documentary_stock',
                'Documentary (stock footage)',
                {'scene_seconds': [6, 12], 'hero_ratio': 0.15},
            ),
            (
                'documentary_archival',
                'Documentary (archival)',
                {'scene_seconds': [8, 14], 'hero_ratio': 0.10},
            ),
        ]
        for key, name, pacing in formats:
            fmt, _ = StoryFormat.objects.update_or_create(
                key=key,
                defaults={
                    'name': name,
                    'fiction': False,
                    'narration_pov': 'narrator',
                    'beats': _DOC_BEATS,
                    'pacing': pacing,
                    'prompt_overrides': dict(_OVERRIDES),
                    'music_mood_map': {
                        'cold_open_hook': 'tense',
                        'escalating_evidence': 'driving',
                        'resolution': 'reflective',
                    },
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(f'Seeded format: {fmt.key}'),
            )
```

Create empty `__init__.py` files for
`server/apps/prompts/management/` and `.../commands/` if they do not exist.

- [ ] **Step 4: Run the command and the tests**

Run:
```bash
just run seed_story_formats
docker compose exec web pytest tests/test_apps/test_prompts/test_seed_story_formats.py -v --no-cov
```
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add server/apps/prompts/management/ \
        tests/test_apps/test_prompts/test_seed_story_formats.py
git commit -m "feat(prompts): seed documentary formats and footage prompts"
```

---

## Task 8: Seed the blueprint and validate every graph

**Files:**
- Modify: `server/apps/pipelines/management/commands/seed_blueprints.py`
- Modify: `server/apps/pipelines/stage_output_selectors.py`
- Modify: `server/apps/pipelines/run_asset_selectors.py`
- Test: `tests/test_apps/test_pipelines/test_management_commands.py`
- Test: `tests/test_apps/test_pipelines/test_blueprint_graphs.py`

**Interfaces:**
- Produces: blueprint `longform_documentary_v1`, kind `LONGFORM`, with
  `profile: 'documentary_footage'`.

- [ ] **Step 1: Write the failing graph-structure test**

Create `tests/test_apps/test_pipelines/test_blueprint_graphs.py`:

```python
"""Structural validation for every seeded blueprint graph."""

import pytest
from django.core.management import call_command

from server.apps.pipelines.models import PipelineBlueprint
from server.apps.pipelines.stages.base import STAGE_REGISTRY


def _graphs() -> list[tuple[str, list[dict[str, object]]]]:
    return [
        (bp.name, bp.graph.get('stages', []))
        for bp in PipelineBlueprint.objects.all()
    ]


@pytest.mark.django_db
def test_every_stage_key_is_registered() -> None:
    """A blueprint naming an unregistered stage would deadlock a run."""
    call_command('seed_blueprints')
    for name, stages in _graphs():
        for node in stages:
            assert node['key'] in STAGE_REGISTRY, (
                f'{name}: unregistered stage {node["key"]}'
            )


@pytest.mark.django_db
def test_every_dependency_resolves() -> None:
    """depends_on must reference a node present in the same graph."""
    call_command('seed_blueprints')
    for name, stages in _graphs():
        keys = {node['key'] for node in stages}
        for node in stages:
            for dep in node.get('depends_on', []):
                assert dep in keys, f'{name}: {node["key"]} needs missing {dep}'


@pytest.mark.django_db
def test_no_graph_has_a_cycle() -> None:
    """A dependency cycle would never become runnable."""
    call_command('seed_blueprints')
    for name, stages in _graphs():
        deps = {n['key']: set(n.get('depends_on', [])) for n in stages}
        resolved: set[str] = set()
        progressed = True
        while progressed:
            progressed = False
            for key, required in deps.items():
                if key not in resolved and required <= resolved:
                    resolved.add(key)
                    progressed = True
        assert resolved == set(deps), f'{name}: cycle among {set(deps) - resolved}'


@pytest.mark.django_db
def test_documentary_blueprint_is_seeded() -> None:
    """The documentary blueprint exists with the right profile."""
    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_documentary_v1')
    assert bp.graph['profile'] == 'documentary_footage'
    assert bp.is_active is True


@pytest.mark.django_db
def test_documentary_graph_has_no_character_stages() -> None:
    """There is no AI cast in a documentary pipeline."""
    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_documentary_v1')
    keys = {n['key'] for n in bp.graph['stages']}
    assert 'cast_proposal' not in keys
    assert 'character_gate' not in keys
    assert {'footage_queries', 'footage_search', 'footage_prep'} <= keys


@pytest.mark.django_db
def test_longform_v1_graph_declares_no_profile() -> None:
    """The AI blueprint is untouched and relies on the default profile."""
    call_command('seed_blueprints')
    bp = PipelineBlueprint.objects.get(name='longform_v1')
    assert 'profile' not in bp.graph
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_blueprint_graphs.py -v --no-cov`
Expected: FAIL — `PipelineBlueprint.DoesNotExist: ... longform_documentary_v1`

- [ ] **Step 3: Add the graph to the seeder**

In `server/apps/pipelines/management/commands/seed_blueprints.py`, add after
`_LONGFORM_V1_GRAPH`:

```python
_LONGFORM_DOC_V1_GRAPH: dict[str, object] = {
    'profile': 'documentary_footage',
    'stages': [
        {'key': 'research', 'depends_on': [], 'queue': 'api'},
        {'key': 'outline', 'depends_on': ['research'], 'queue': 'api'},
        {'key': 'script', 'depends_on': ['outline'], 'queue': 'api'},
        {'key': 'scene_breakdown', 'depends_on': ['script'], 'queue': 'api'},
        {
            'key': 'script_gate',
            'depends_on': ['scene_breakdown'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'narrative_qc',
            'depends_on': ['script_gate'],
            'queue': 'api',
        },
        {
            'key': 'footage_queries',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
        },
        {
            'key': 'footage_search',
            'depends_on': ['footage_queries'],
            'queue': 'api',
            'fan_out': 'scenes',
            'config': {'ai_model': 'fal-ai/flux/dev'},
        },
        {
            'key': 'storyboard_gate',
            'depends_on': ['footage_search'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'tts',
            'depends_on': ['storyboard_gate'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
        {
            'key': 'footage_prep',
            'depends_on': ['storyboard_gate'],
            'queue': 'render',
            'fan_out': 'scenes',
            'config': {
                'target_width': 1920,
                'target_height': 1080,
                'fps': 30,
            },
        },
        {
            'key': 'alignment',
            'depends_on': ['tts', 'scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'music_plan',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
        },
        {
            'key': 'metadata',
            'depends_on': ['script', 'alignment', 'footage_search'],
            'queue': 'api',
        },
        {
            'key': 'thumbnail',
            'depends_on': ['metadata'],
            'queue': 'api',
            'config': {'candidates': 3},
        },
        {
            'key': 'assembly',
            'depends_on': [
                'footage_prep',
                'tts',
                'alignment',
                'music_plan',
            ],
            'queue': 'render',
        },
        {'key': 'qc', 'depends_on': ['assembly'], 'queue': 'render'},
        {
            'key': 'final_gate',
            'depends_on': ['qc', 'thumbnail', 'metadata'],
            'gate': True,
            'queue': 'api',
        },
        {'key': 'publish', 'depends_on': ['final_gate'], 'queue': 'api'},
    ],
}
```

Add to the `specs` list in `handle`:

```python
            (
                'longform_documentary_v1',
                PipelineKind.LONGFORM,
                _LONGFORM_DOC_V1_GRAPH,
            ),
```

Update the command's `help` text to mention the documentary blueprint.

- [ ] **Step 4: Register the new keys in the selectors**

In `server/apps/pipelines/stage_output_selectors.py`, add to
`_KNOWN_STAGE_KEYS`:

```python
    'footage_queries',
    'footage_search',
    'footage_prep',
```

In `server/apps/pipelines/run_asset_selectors.py`, change:

```python
_SCENE_LABEL_STAGES = frozenset({'image_gen', 'motion'})
```

to:

```python
_SCENE_LABEL_STAGES = frozenset({
    'image_gen',
    'motion',
    'footage_search',
    'footage_prep',
})
```

- [ ] **Step 5: Run the tests**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_pipelines/test_blueprint_graphs.py tests/test_apps/test_pipelines/test_management_commands.py -v --no-cov
```
Expected: PASS, all graph checks green

- [ ] **Step 6: Commit**

```bash
git add server/apps/pipelines/management/commands/seed_blueprints.py \
        server/apps/pipelines/stage_output_selectors.py \
        server/apps/pipelines/run_asset_selectors.py \
        tests/test_apps/test_pipelines/test_blueprint_graphs.py
git commit -m "feat(pipelines): seed longform_documentary_v1 blueprint"
```

---

## Task 9: Profile-dispatched review layer

**Files:**
- Create: `server/apps/pipelines/review/__init__.py`
- Create: `server/apps/pipelines/review/dispatch.py`
- Create: `server/apps/pipelines/review/ai_visual.py`
- Create: `server/apps/pipelines/review/documentary.py`
- Modify: `server/apps/pipelines/logic/value_objects.py`
- Test: `tests/test_apps/test_pipelines/test_review/test_dispatch.py`
- Test: `tests/test_apps/test_pipelines/test_review/test_documentary.py`

**Do not modify** `storyboard_selectors.py` or `run_review.py`.

**Interfaces:**
- Consumes: `resolve_profile_key` (foundations Task 1).
- Produces:
  - `dispatch.get_storyboard(run_id, presign) -> StoryboardPayload |
    FootageStoryboardPayload`.
  - `dispatch.apply_scene_edit(run_id, scene_idx, payload) -> str` returning
    the `stale_from` stage key.
  - `FootageStoryboardPayload`, `FootageSceneRow`, `FootageCandidatePayload`
    msgspec structs in `logic/value_objects.py`.

- [ ] **Step 1: Write the failing dispatch test**

Create `tests/test_apps/test_pipelines/test_review/test_dispatch.py`:

```python
"""Tests for profile-based review dispatch."""

from unittest.mock import MagicMock, patch

import pytest

from server.apps.pipelines.review import dispatch


@pytest.mark.django_db
def test_ai_visual_run_uses_the_existing_selector() -> None:
    """Runs with no profile keep today's storyboard payload builder."""
    run = MagicMock()
    run.blueprint_snapshot = {'stages': []}
    presign = MagicMock()

    with (
        patch(
            'server.apps.pipelines.review.dispatch._load_run',
            return_value=run,
        ),
        patch(
            'server.apps.pipelines.review.ai_visual.get_storyboard',
            return_value='ai-payload',
        ) as ai_visual,
    ):
        result = dispatch.get_storyboard('run-id', presign)

    assert result == 'ai-payload'
    ai_visual.assert_called_once_with('run-id', presign)


@pytest.mark.django_db
def test_documentary_run_uses_the_footage_selector() -> None:
    """Documentary runs get the footage payload builder."""
    run = MagicMock()
    run.blueprint_snapshot = {
        'stages': [], 'profile': 'documentary_footage',
    }
    presign = MagicMock()

    with (
        patch(
            'server.apps.pipelines.review.dispatch._load_run',
            return_value=run,
        ),
        patch(
            'server.apps.pipelines.review.documentary.get_storyboard',
            return_value='doc-payload',
        ) as doc,
    ):
        result = dispatch.get_storyboard('run-id', presign)

    assert result == 'doc-payload'
    doc.assert_called_once_with('run-id', presign)


@pytest.mark.django_db
def test_scene_edit_stale_key_is_profile_specific() -> None:
    """A documentary scene edit stales footage_queries, not visual_prompts."""
    run = MagicMock()
    run.blueprint_snapshot = {
        'stages': [], 'profile': 'documentary_footage',
    }
    with (
        patch(
            'server.apps.pipelines.review.dispatch._load_run',
            return_value=run,
        ),
        patch(
            'server.apps.pipelines.review.documentary.apply_scene_edit',
            return_value='footage_queries',
        ),
    ):
        assert dispatch.apply_scene_edit('run-id', 0, {}) == 'footage_queries'
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_review/test_dispatch.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: server.apps.pipelines.review`

- [ ] **Step 3: Add the payload value objects**

Append to `server/apps/pipelines/logic/value_objects.py`:

```python
class FootageCandidatePayload(msgspec.Struct):
    """One alternate footage option offered at the review gate."""

    external_id: str
    provider: str
    thumb_url: str
    preview_url: str
    width: int
    height: int
    duration_s: float | None
    license: str
    author: str
    source_url: str


class FootageSceneRow(msgspec.Struct):
    """One scene row in the documentary storyboard."""

    idx: int
    narration_text: str
    visual_concept: str
    status: str
    est_seconds: float
    asset_url: str | None
    media_type: str
    source: str
    license: str
    license_url: str
    attribution_required: bool
    author: str
    source_url: str
    rerank_score: float | None
    candidates: list[FootageCandidatePayload]


class FootageStoryboardPayload(msgspec.Struct):
    """Documentary storyboard review payload."""

    profile: str
    run: StoryboardRunSummaryPayload
    scenes: list[FootageSceneRow]
    ai_fallback_count: int
```

- [ ] **Step 4: Write the review modules**

Create `server/apps/pipelines/review/__init__.py`:

```python
"""Profile-dispatched run review payloads."""
```

Create `server/apps/pipelines/review/ai_visual.py`:

```python
"""AI-visual review adapter — delegates to the original selectors.

This module exists so `dispatch` has a uniform interface for both profiles
without modifying `storyboard_selectors` or `run_review`.
"""

from typing import Any

from server.apps.pipelines.logic.value_objects import StoryboardPayload
from server.common.storage import PresignUrlHelper


def get_storyboard(
    run_id: str,
    presign: PresignUrlHelper,
) -> StoryboardPayload:
    """Return the AI-visual storyboard payload."""
    from server.apps.pipelines.storyboard_selectors import (  # noqa: PLC0415
        get_storyboard as _get,
    )

    return _get(run_id, presign)


def apply_scene_edit(
    run_id: str,
    scene_idx: int,
    payload: dict[str, Any],
) -> str:
    """Apply a scene text edit and return the stage to stale from."""
    from server.apps.pipelines.services.run_review import (  # noqa: PLC0415
        apply_scene_edit as _apply,
    )

    return _apply(run_id, scene_idx, payload)
```

**Confirm the exact exported name and signature of the scene-edit entry point
in `server/apps/pipelines/services/run_review.py` before writing this file** —
the call around line 248 uses `_sync_visual_prompts` internally, and the public
wrapper's name must match what the API view currently calls.

Create `server/apps/pipelines/review/dispatch.py`:

```python
"""Route review requests to the adapter matching the run's profile."""

import uuid
from typing import Any

from server.apps.pipelines.logic.blueprint_profiles import (
    resolve_profile_key,
)
from server.apps.pipelines.review import ai_visual, documentary
from server.common.storage import PresignUrlHelper

_ADAPTERS = {
    'ai_visual': ai_visual,
    'documentary_footage': documentary,
}


def _load_run(run_id: str) -> Any:
    """Load the run with the fields needed to pick an adapter."""
    from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

    return PipelineRun.objects.get(id=uuid.UUID(run_id))


def _adapter(run_id: str) -> Any:
    """Return the review adapter for this run's blueprint profile."""
    run = _load_run(run_id)
    key = resolve_profile_key(run.blueprint_snapshot or {})
    return _ADAPTERS[key]


def get_storyboard(run_id: str, presign: PresignUrlHelper) -> Any:
    """Return the storyboard payload for this run's profile."""
    return _adapter(run_id).get_storyboard(run_id, presign)


def apply_scene_edit(
    run_id: str,
    scene_idx: int,
    payload: dict[str, Any],
) -> str:
    """Apply a scene edit and return the stage key to stale from."""
    return _adapter(run_id).apply_scene_edit(run_id, scene_idx, payload)
```

Create `server/apps/pipelines/review/documentary.py`:

```python
"""Documentary review adapter — footage storyboard and scene edits."""

import uuid
from typing import Any

from server.apps.pipelines.logic.value_objects import (
    FootageCandidatePayload,
    FootageSceneRow,
    FootageStoryboardPayload,
    StoryboardRunSummaryPayload,
)
from server.apps.pipelines.models import (
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.common.storage import PresignUrlHelper

_AI_SOURCE = 'ai_flux'


def _latest_parent_output(run_id: str, stage_key: str) -> dict[str, Any]:
    """Return the latest successful parent execution output for a stage."""
    row = (
        StageExecution.objects
        .filter(
            run_id=uuid.UUID(run_id),
            stage_key=stage_key,
            parent=None,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-attempt', '-created_at')
        .first()
    )
    return dict(row.output) if row and isinstance(row.output, dict) else {}


def _footage_state(run_id: str) -> dict[int, StageExecution]:
    """Map scene_idx → latest footage_search child execution."""
    state: dict[int, StageExecution] = {}
    rows = (
        StageExecution.objects
        .filter(
            run_id=uuid.UUID(run_id),
            stage_key='footage_search',
            parent__isnull=False,
        )
        .order_by('shard_index', '-attempt')
    )
    for row in rows:
        idx = row.output.get('scene_idx')
        if idx is None or int(idx) in state:
            continue
        state[int(idx)] = row
    return state


def _presign_asset(
    asset_id: str,
    presign: PresignUrlHelper,
) -> str | None:
    """Return a presigned URL for a pipeline asset, or None."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = Asset.objects.filter(id=asset_id).first()
    if asset is None or not asset.file:
        return None
    return presign(asset.file.name)


def _candidate_payloads(
    output: dict[str, Any],
) -> list[FootageCandidatePayload]:
    """Map stored candidate dicts to API payloads."""
    return [
        FootageCandidatePayload(
            external_id=str(c.get('external_id', '')),
            provider=str(c.get('provider', '')),
            thumb_url=str(c.get('thumb_url', '')),
            preview_url=str(c.get('preview_url', '')),
            width=int(c.get('width') or 0),
            height=int(c.get('height') or 0),
            duration_s=(
                float(c['duration_s'])
                if c.get('duration_s') is not None
                else None
            ),
            license=str(c.get('license', '')),
            author=str(c.get('author', '')),
            source_url=str(c.get('source_url', '')),
        )
        for c in output.get('candidates', [])
    ]


def _scene_row(
    scene: dict[str, Any],
    execution: StageExecution | None,
    presign: PresignUrlHelper,
) -> FootageSceneRow:
    """Build one documentary storyboard row."""
    output = dict(execution.output) if execution else {}
    asset_id = output.get('asset_id')
    return FootageSceneRow(
        idx=int(scene['idx']),
        narration_text=str(scene.get('narration_text', '')),
        visual_concept=str(scene.get('visual_concept', '')),
        status=execution.status if execution else StageStatus.PENDING,
        est_seconds=float(scene.get('est_seconds', 0.0)),
        asset_url=(
            _presign_asset(str(asset_id), presign) if asset_id else None
        ),
        media_type=str(output.get('media_type', '')),
        source=str(output.get('source', '')),
        license=str(output.get('license', '')),
        license_url=str(output.get('license_url', '')),
        attribution_required=bool(output.get('attribution_required')),
        author=str(output.get('attribution', '')),
        source_url=str(output.get('source_url', '')),
        rerank_score=(
            float(output['rerank_score'])
            if output.get('rerank_score') is not None
            else None
        ),
        candidates=_candidate_payloads(output),
    )


def get_storyboard(
    run_id: str,
    presign: PresignUrlHelper,
) -> FootageStoryboardPayload:
    """Build the documentary storyboard from footage_search outputs."""
    run = PipelineRun.objects.select_related('channel').get(
        id=uuid.UUID(run_id),
    )
    breakdown = _latest_parent_output(run_id, 'scene_breakdown')
    raw_scenes = breakdown.get('scenes') or []
    scenes_raw = [s for s in raw_scenes if isinstance(s, dict)]
    state = _footage_state(run_id)

    rows = [
        _scene_row(scene, state.get(int(scene['idx'])), presign)
        for scene in scenes_raw
    ]
    ai_fallback_count = sum(1 for row in rows if row.source == _AI_SOURCE)
    budget = run.channel.default_budget_usd

    return FootageStoryboardPayload(
        profile='documentary_footage',
        run=StoryboardRunSummaryPayload(
            id=str(run.id),
            status=run.status,
            gate=_active_gate_key(run),
            spent_usd=str(run.total_cost_usd),
            projected_next_usd='0',
            budget_usd=str(budget) if budget is not None else None,
        ),
        scenes=rows,
        ai_fallback_count=ai_fallback_count,
    )


def _active_gate_key(run: PipelineRun) -> str | None:
    """Return the key of the gate this run is parked on, if any."""
    from server.apps.pipelines.logic.constants import (  # noqa: PLC0415
        GATE_PARKED_STATUSES,
    )

    row = (
        StageExecution.objects
        .filter(run=run, parent=None, status__in=GATE_PARKED_STATUSES)
        .order_by('-created_at')
        .first()
    )
    return row.stage_key if row else None


def apply_scene_edit(
    run_id: str,
    scene_idx: int,
    payload: dict[str, Any],
) -> str:
    """Write an edited scene back to scene_breakdown; stale footage_queries.

    Returns the stage key downstream consumers must be staled from — for
    documentary runs the queries, not the AI visual prompts.
    """
    row = (
        StageExecution.objects
        .filter(
            run_id=uuid.UUID(run_id),
            stage_key='scene_breakdown',
            parent=None,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-attempt', '-created_at')
        .first()
    )
    if row is None:
        return 'footage_queries'

    output = dict(row.output)
    scenes = list(output.get('scenes') or [])
    for scene in scenes:
        if not isinstance(scene, dict) or int(scene.get('idx', -1)) != scene_idx:
            continue
        for field in ('narration_text', 'visual_concept'):
            if payload.get(field) is not None:
                scene[field] = payload[field]
    output['scenes'] = scenes
    row.output = output
    row.save(update_fields=['output'])
    return 'footage_queries'
```

**Before writing this, confirm `_active_gate_key` is not already importable
from `storyboard_selectors`** — if it is, import it rather than duplicating it.
`GATE_PARKED_STATUSES` already exists in
`server/apps/pipelines/logic/constants.py`.

- [ ] **Step 5: Write the documentary payload test**

Create `tests/test_apps/test_pipelines/test_review/test_documentary.py`
covering: a scene sourced from a provider exposes licence and candidates; a
scene sourced from `ai_flux` reports `source='ai_flux'` with empty candidates
and increments `ai_fallback_count`; a scene with no `footage_search` shard
yields `asset_url=None` and a pending status; and `apply_scene_edit` returns
`'footage_queries'`. Build fixtures with real `PipelineRun`, `StageExecution`,
and `Asset` rows under `@pytest.mark.django_db`, following the fixture style in
`tests/test_apps/test_pipelines/test_review_api.py`.

- [ ] **Step 6: Run the review tests**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_review/ -v --no-cov`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add server/apps/pipelines/review/ \
        server/apps/pipelines/logic/value_objects.py \
        tests/test_apps/test_pipelines/test_review/
git commit -m "feat(pipelines): add profile-dispatched review layer"
```

---

## Task 10: Review API endpoints

**Files:**
- Modify: `server/apps/pipelines/api/review_views.py`
- Modify: `server/apps/pipelines/api/urls.py`
- Create: `server/apps/pipelines/footage_selectors.py`
- Test: `tests/test_apps/test_pipelines/test_footage_api.py`

**Interfaces:**
- Produces:
  - `RunStoryboardController` routes through `review.dispatch`.
  - `POST runs/<uuid:run_id>/scenes/<int:scene_idx>/select-candidate/`
    → `{'external_id': str}`.
  - `POST runs/<uuid:run_id>/scenes/<int:scene_idx>/research-footage/`
    → `{'query': str}`.
  - `GET runs/<uuid:run_id>/credits/` → `RunCreditsPayload`.
  - `get_run_credits(run_id) -> RunCreditsPayload` in `footage_selectors.py`.

- [ ] **Step 1: Write the failing API test**

Create `tests/test_apps/test_pipelines/test_footage_api.py` using
`dmr.test.DMRClient`, covering:

```python
"""API tests for documentary review endpoints."""

import pytest
from dmr.test import DMRClient
```

Write these cases:

1. `test_storyboard_returns_profile_for_ai_visual_run` — a `longform_v1` run's
   storyboard response reports `profile == 'ai_visual'` and the existing scene
   fields are unchanged.
2. `test_storyboard_returns_footage_fields_for_documentary_run` — scene rows
   include `media_type`, `source`, `license`, `attribution_required`, and
   `candidates`.
3. `test_select_candidate_requeues_only_that_shard` — patch
   `rerun_stage_impl` and assert it is called with
   `stage_key='footage_prep'` and `shard_indices=[scene_idx]`.
4. `test_select_candidate_rejects_unknown_external_id` — returns HTTP 400 and
   does not enqueue anything.
5. `test_research_footage_requeues_the_search_shard` — patch
   `rerun_stage_impl`, assert `stage_key='footage_search'` and
   `shard_indices=[scene_idx]`.
6. `test_research_footage_rejects_an_empty_query` — HTTP 400.
7. `test_credits_endpoint_lists_required_attributions_first` — two credits, one
   `attribution_required=True`, and the required one sorts first.
8. `test_credits_endpoint_flags_truncation` — with enough entries to exceed the
   5000-character budget, `truncated is True` and no
   `attribution_required=True` entry is dropped.

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_footage_api.py -v --no-cov`
Expected: FAIL — routes not registered (HTTP 404)

- [ ] **Step 3: Write the credits selector**

Create `server/apps/pipelines/footage_selectors.py`:

```python
"""Read-only selectors for footage credits."""

import uuid

from server.apps.pipelines.logic.value_objects import (
    FootageCreditPayload,
    RunCreditsPayload,
)

_DESCRIPTION_BUDGET_CHARS = 5000


def _entry_text(credit: 'FootageCreditPayload') -> str:
    """Render one credit line as it appears in the description."""
    author = f' by {credit.author}' if credit.author else ''
    return f'{credit.title}{author} ({credit.license}) — {credit.source_url}'


def get_run_credits(run_id: str) -> RunCreditsPayload:
    """Build the attribution block, required credits first.

    Entries are truncated to the YouTube description budget. Credits with
    ``attribution_required`` are never dropped — only optional ones are.
    """
    from server.apps.assets.models import FootageCredit  # noqa: PLC0415

    rows = list(
        FootageCredit.objects
        .filter(run_id=uuid.UUID(run_id))
        .order_by('-attribution_required', 'provider', 'scene_idx'),
    )

    seen: dict[tuple[str, str], FootageCreditPayload] = {}
    for row in rows:
        key = (row.provider, row.source_url)
        if key in seen:
            seen[key].scene_idxs.append(row.scene_idx)
            continue
        seen[key] = FootageCreditPayload(
            provider=row.provider,
            license=row.license,
            license_url=row.license_url,
            author=row.author,
            source_url=row.source_url,
            title=row.title,
            attribution_required=row.attribution_required,
            scene_idxs=[row.scene_idx],
        )

    entries: list[FootageCreditPayload] = []
    budget = _DESCRIPTION_BUDGET_CHARS
    truncated = False
    for entry in seen.values():
        cost = len(_entry_text(entry)) + 1
        if cost > budget and not entry.attribution_required:
            truncated = True
            continue
        budget -= cost
        entries.append(entry)
    return RunCreditsPayload(entries=entries, truncated=truncated)
```

Add `FootageCreditPayload` and `RunCreditsPayload` msgspec structs to
`logic/value_objects.py`:

```python
class FootageCreditPayload(msgspec.Struct):
    """One attribution entry for the published description."""

    provider: str
    license: str
    license_url: str
    author: str
    source_url: str
    title: str
    attribution_required: bool
    scene_idxs: list[int]


class RunCreditsPayload(msgspec.Struct):
    """Attribution block preview for a run."""

    entries: list[FootageCreditPayload]
    truncated: bool
```

- [ ] **Step 4: Add the controllers**

In `server/apps/pipelines/api/review_views.py`, change
`RunStoryboardController` to call
`server.apps.pipelines.review.dispatch.get_storyboard` instead of
`storyboard_selectors.get_storyboard`, and the scene-edit controller to call
`dispatch.apply_scene_edit`. Then add three controllers following the existing
DMR patterns in that file:

- `RunSceneSelectCandidateController` — POST; validates `external_id` against
  the latest `footage_search` shard output for that scene; on match, writes the
  chosen candidate into the shard output and calls
  `rerun_stage_impl(run_id, 'footage_prep', shard_indices=[scene_idx])`;
  raises `ValidationError` (HTTP 400) on an unknown id.
- `RunSceneResearchFootageController` — POST; rejects an empty/whitespace
  `query` with HTTP 400; writes the operator query into the shard's
  `input_snapshot` as `primary_query` and calls
  `rerun_stage_impl(run_id, 'footage_search', shard_indices=[scene_idx])`.
- `RunCreditsController` — GET; returns `get_run_credits(run_id)`.

- [ ] **Step 5: Register the routes**

In `server/apps/pipelines/api/urls.py`, add to `review_urlpatterns`:

```python
    path(
        'runs/<uuid:run_id>/scenes/<int:scene_idx>/select-candidate/',
        review_views.RunSceneSelectCandidateController.as_view(),
        name='run-scene-select-candidate',
    ),
    path(
        'runs/<uuid:run_id>/scenes/<int:scene_idx>/research-footage/',
        review_views.RunSceneResearchFootageController.as_view(),
        name='run-scene-research-footage',
    ),
    path(
        'runs/<uuid:run_id>/credits/',
        review_views.RunCreditsController.as_view(),
        name='run-credits',
    ),
```

- [ ] **Step 6: Run the API tests and regenerate the schema**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_pipelines/test_footage_api.py tests/test_apps/test_pipelines/test_review_api.py -v --no-cov
just run dump_openapi_schema
```
Expected: PASS; the OpenAPI export gains the three endpoints for the frontend's
`orval` generation.

- [ ] **Step 7: Commit**

```bash
git add server/apps/pipelines/api/ \
        server/apps/pipelines/footage_selectors.py \
        server/apps/pipelines/logic/value_objects.py \
        tests/test_apps/test_pipelines/test_footage_api.py
git commit -m "feat(api): add documentary review and credits endpoints"
```

---

## Task 11: Attribution in the published description

**Files:**
- Modify: `server/apps/pipelines/stages/metadata.py`
- Test: `tests/test_apps/test_pipelines/test_stages/test_metadata.py`

**Interfaces:**
- Consumes: `get_run_credits` (Task 10).
- Produces: `metadata` output `description` gains a trailing credits block for
  documentary runs; AI-visual runs are unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_apps/test_pipelines/test_stages/test_metadata.py`:

```python
def test_description_gains_credits_for_documentary_runs() -> None:
    """Required attributions are appended to the YouTube description."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.pipelines.logic.value_objects import (
        FootageCreditPayload,
        RunCreditsPayload,
    )
    from server.apps.pipelines.stages.metadata import MetadataStage

    ctx = _make_ctx()  # existing helper in this module
    ctx.run.blueprint_snapshot = {'profile': 'documentary_footage'}
    credits = RunCreditsPayload(
        entries=[
            FootageCreditPayload(
                provider='wikimedia', license='CC-BY-4.0',
                license_url='https://creativecommons.org/licenses/by/4.0/',
                author='A Photographer', source_url='https://commons/x',
                title='A Photograph', attribution_required=True,
                scene_idxs=[0],
            ),
        ],
        truncated=False,
    )
    with patch(
        'server.apps.pipelines.stages.metadata._load_credits',
        new=AsyncMock(return_value=credits),
    ):
        result = asyncio.run(MetadataStage().run(ctx))
    assert 'A Photographer' in result['description']
    assert 'CC-BY-4.0' in result['description']


def test_description_is_unchanged_for_ai_visual_runs() -> None:
    """A longform_v1 run gets no credits block."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from server.apps.pipelines.stages.metadata import MetadataStage

    ctx = _make_ctx()
    ctx.run.blueprint_snapshot = {'stages': []}
    with patch(
        'server.apps.pipelines.stages.metadata._load_credits',
        new=AsyncMock(),
    ) as loader:
        result = asyncio.run(MetadataStage().run(ctx))
    loader.assert_not_awaited()
    assert 'Footage credits' not in result['description']
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_metadata.py -k credits -v --no-cov`
Expected: FAIL — `AttributeError: ... has no attribute '_load_credits'`

- [ ] **Step 3: Implement the credits block**

In `server/apps/pipelines/stages/metadata.py`, add:

```python
_load_credits = sync_to_async(
    lambda run_id: get_run_credits(run_id),  # noqa: PLR0917
)


def _credits_block(credits: 'RunCreditsPayload') -> str:
    """Render the attribution block appended to the description."""
    if not credits.entries:
        return ''
    lines = ['', 'Footage credits:']
    for entry in credits.entries:
        author = f' by {entry.author}' if entry.author else ''
        lines.append(
            f'- {entry.title}{author} ({entry.license}) — {entry.source_url}',
        )
    return '\n'.join(lines)
```

At the end of `MetadataStage.run`, before returning, append the block only for
documentary profiles:

```python
        from server.apps.pipelines.logic.blueprint_profiles import (  # noqa: PLC0415
            resolve_profile_key,
        )

        result = output.model_dump()
        profile = resolve_profile_key(ctx.run.blueprint_snapshot or {})
        if profile == 'documentary_footage':
            credits = await _load_credits(str(ctx.run.id))
            result['description'] = (
                f'{result["description"]}{_credits_block(credits)}'
            )
        return result
```

Add the needed imports (`sync_to_async`, `get_run_credits`,
`RunCreditsPayload`) at the top of the module.

- [ ] **Step 4: Run tests**

Run: `docker compose exec web pytest tests/test_apps/test_pipelines/test_stages/test_metadata.py -v --no-cov`
Expected: PASS — including all pre-existing metadata tests

- [ ] **Step 5: Commit**

```bash
git add server/apps/pipelines/stages/metadata.py \
        tests/test_apps/test_pipelines/test_stages/test_metadata.py
git commit -m "feat(pipelines): append footage attribution to descriptions"
```

---

## Task 12: Expose `footage_sourcing` on the channels API

**Files:**
- Modify: `server/apps/channels/api/` (views + value objects)
- Test: `tests/test_apps/test_channels/test_footage_sourcing_api.py`

**Interfaces:**
- Produces: channel GET returns a `footage_sourcing` sub-object; PATCH accepts
  it, preserving `enabled_providers` ordering.

- [ ] **Step 1: Write the failing test**

Create `tests/test_apps/test_channels/test_footage_sourcing_api.py` with
`DMRClient` covering:

1. `test_channel_detail_includes_footage_sourcing_defaults` — a channel with no
   config row returns the default values, not `null`.
2. `test_patch_creates_the_config_row` — PATCH with a `footage_sourcing` body
   creates the row and returns the saved values.
3. `test_patch_preserves_provider_order` — send
   `['wikimedia', 'openverse', 'pexels']`, read it back in the same order.
4. `test_patch_rejects_an_unknown_rerank_mode` — HTTP 400.

- [ ] **Step 2: Run it and confirm the failure**

Run: `docker compose exec web pytest tests/test_apps/test_channels/test_footage_sourcing_api.py -v --no-cov`
Expected: FAIL — `footage_sourcing` absent from the response

- [ ] **Step 3: Implement**

Add a `FootageSourcingPayload` msgspec struct to the channels app's value
objects with the fields from foundations Task 5, include it on the channel
detail payload built from `channel.footage_sourcing_or_default()`, and handle
it in the channel update path with `update_or_create` on the config row.
Validate `sourcing_mode` and `rerank_mode` against their `TextChoices` before
saving, raising `ValidationError` for unknown values.

- [ ] **Step 4: Run tests and regenerate the schema**

Run:
```bash
docker compose exec web pytest tests/test_apps/test_channels/ -v --no-cov
just run dump_openapi_schema
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/apps/channels/ \
        tests/test_apps/test_channels/test_footage_sourcing_api.py
git commit -m "feat(api): expose footage sourcing config on channels"
```

---

## Task 13: Full-suite verification gate

- [ ] **Step 1: Seed everything into a clean database**

Run:
```bash
just run migrate
just run seed_story_formats
just run seed_blueprints
```
Expected: idempotent success; `longform_documentary_v1` created.

- [ ] **Step 2: Run the full suite with the coverage gate**

Run: `docker compose exec web pytest`
Expected: PASS at 100% coverage.

- [ ] **Step 3: Run every static check**

Run:
```bash
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web mypy server
docker compose exec web lint-imports
docker compose exec web python manage.py lintmigrations
docker compose exec web python manage.py check_migrations --exclude-apps=axes
```
Expected: all clean

- [ ] **Step 4: Prove the AI path is untouched**

Confirm `test_assembly.py`, `test_motion.py`, `test_image_gen.py`,
`test_visual_prompts.py`, and `test_storyboard*` required **no edits** across
this plan. If any did, document why in the commit message — it means the
isolation goal slipped.

- [ ] **Step 5: Export the OpenAPI schema for the frontend**

Run: `just run dump_openapi_schema`
Expected: the export contains `select-candidate`, `research-footage`,
`credits`, and `footage_sourcing`. Hand this to `reelforge-frontend` for
`orval` generation, alongside
`docs/superpowers/specs/2026-07-26-longform-documentary-frontend-brief.md`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: verification pass for documentary pipeline"
```

---

## Done criteria

- `longform_documentary_v1` seeds, and every seeded graph passes the
  structural validator.
- The cascade is covered per branch: hit, broaden, AI fallback, park,
  corrupt-media skip, vision degradation.
- `footage_prep` output keys match `motion` exactly.
- A documentary channel's `script` / `scene_breakdown` resolve to the
  documentary prompt versions; a channel without overrides resolves to `{}`.
- `storyboard_selectors.py` and `run_review.py` are unmodified.
- Credits appear in documentary descriptions; required attributions are never
  truncated.
- Full suite green at 100% coverage; all static checks clean.
- OpenAPI export updated for the frontend.
