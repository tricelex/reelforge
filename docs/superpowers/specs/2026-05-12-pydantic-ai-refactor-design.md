# PydanticAI Refactor Design

**Date:** 2026-05-12  
**Status:** Approved  
**Scope:** Replace `ClaudeProvider`/`OpenAIProvider` + OpenAI Agents SDK with PydanticAI across the entire LLM layer

---

## Goal

Consolidate all LLM work into a single `reelforge/ai/` Django app backed by PydanticAI. Remove the custom provider abstraction, the OpenAI Agents SDK, and the `dependency-injector` container. The result is a uniform, type-safe, extensible AI layer with no LLM code scattered across multiple apps.

---

## What Changes

### Deleted

| File / Package | Replaced by |
|---|---|
| `reelforge/agents/` (entire app) | `reelforge/ai/` |
| `reelforge/services/providers/llm/claude.py` | PydanticAI `anthropic:*` model string |
| `reelforge/services/providers/llm/openai.py` | PydanticAI `openai:*` model string |
| `reelforge/services/base.py` (LLM parts) | PydanticAI handles all LLM I/O |
| `reelforge/services/providers/registry.py` | Per-agent model settings |
| `reelforge/agents/containers.py` | PydanticAI `RunContext` + lazy singletons |
| `dependency-injector` package | — |
| `openai-agents` package | `pydantic-ai[anthropic,openai]` |
| `anthropic` (direct import) | transitive via pydantic-ai |

### Untouched

- `reelforge/services/providers/` — TTS, image, video, distribution providers
- All Pydantic output schemas (`ResearchAgentOutput`, `ScriptAgentOutput`, `VisualPlannerOutput`) — moved, not changed
- All system prompts — moved, not changed
- `pipeline/tasks.py` structure (FSM transitions, Celery task signatures, error handling) — only agent call sites change

---

## New Module Structure

```
reelforge/ai/
├── apps.py                   # AiConfig — minimal, no container wiring
├── deps.py                   # ResearchDeps, ScriptDeps, VisualPlannerDeps dataclasses
├── agents/
│   ├── __init__.py
│   ├── research.py           # research_agent singleton + @research_agent.tool functions
│   ├── script.py             # script_agent singleton + tools + _seo_agent sub-agent
│   └── visual_planner.py     # visual_planner_agent singleton
├── schemas/
│   ├── __init__.py
│   ├── research.py           # ResearchAgentOutput et al. (moved from agents/schemas.py)
│   ├── script.py             # ScriptAgentOutput et al.
│   └── visual.py             # VisualPlannerOutput et al.
├── prompts/
│   ├── __init__.py
│   ├── research.py           # RESEARCH_SYSTEM_PROMPT (moved from agents/)
│   ├── script.py             # SCRIPT_SYSTEM_PROMPT
│   └── visual_planner.py     # VISUAL_PLANNER_SYSTEM_PROMPT
└── providers/
    ├── __init__.py
    ├── protocols.py           # VideoSearchProvider, TrendsProvider, WebSearchProvider protocols (moved from agents/providers/protocols.py)
    ├── serpapi.py             # Module-level lazy singletons: get_youtube_search(), get_trends(), get_community()
    └── tavily.py              # Module-level lazy singleton: get_web_search()
```

---

## Model Configuration

Per-agent model strings in Django settings. PydanticAI resolves `"openai:gpt-4o"` and `"anthropic:claude-sonnet-4-5"` natively — switching providers requires only an env var change.

```python
# config/settings/base.py
RESEARCH_AGENT_MODEL  = env("RESEARCH_AGENT_MODEL",  default="openai:gpt-4o")
SCRIPT_AGENT_MODEL    = env("SCRIPT_AGENT_MODEL",    default="openai:gpt-4o")
VISUAL_PLANNER_MODEL  = env("VISUAL_PLANNER_MODEL",  default="openai:gpt-4o")
```

`DEFAULT_LLM_PROVIDER` is removed. No model is set at agent definition time — the model string is passed at `.run_sync()` call time, keeping agent modules importable before Django fully boots.

---

## Agent Architecture

### Pattern

Each agent is a module-level singleton with tools registered via `@agent.tool`. All external service dependencies flow through a typed `RunContext[Deps]` — no closures, no injected constructor arguments.

```python
# ai/agents/research.py
research_agent: Agent[ResearchDeps, ResearchAgentOutput] = Agent(
    deps_type=ResearchDeps,
    output_type=ResearchAgentOutput,
    system_prompt=RESEARCH_SYSTEM_PROMPT,
)

@research_agent.tool
async def search_youtube_trends(
    ctx: RunContext[ResearchDeps],
    niche: str,
    days_back: int,
    limit: int,
) -> str:
    results = await ctx.deps.video_search.search(niche, days_back=days_back, limit=limit)
    return json.dumps([asdict(r) for r in results])
```

### Deps Dataclasses (`ai/deps.py`)

```python
@dataclass
class ResearchDeps:
    video_search: SerpApiYouTubeProvider
    web_search: TavilyProvider
    trends: SerpApiTrendsProvider
    community: SerpApiCommunityProvider

@dataclass
class ScriptDeps:
    web_search: TavilyProvider

@dataclass
class VisualPlannerDeps:
    pass  # pure LLM, no external services
```

### Sub-agent for Structured Single-Turn Calls

The script agent's `generate_seo_metadata` tool previously called `llm.complete_json()` on an injected provider. It becomes a private micro-agent with `output_type=ScriptSEOMetadata`:

```python
_seo_agent: Agent[None, ScriptSEOMetadata] = Agent(output_type=ScriptSEOMetadata)

@script_agent.tool
async def generate_seo_metadata(
    ctx: RunContext[ScriptDeps],
    title_idea: str,
    script_excerpt: str,
    keyword: str,
) -> str:
    result = await _seo_agent.run(
        f"Generate YouTube SEO metadata for: {title_idea}...",
        model=settings.SCRIPT_AGENT_MODEL,
    )
    return result.output.model_dump_json()
```

### Dynamic System Prompts

If any agent needs runtime context (channel name, niche, etc.) in its system prompt, use `@agent.system_prompt` instead of a static string:

```python
@research_agent.system_prompt
def build_system_prompt(ctx: RunContext[ResearchDeps]) -> str:
    return RESEARCH_SYSTEM_PROMPT  # can interpolate ctx.deps values
```

---

## External Service Providers

SerpAPI and Tavily clients move to `reelforge/ai/providers/` as module-level lazy singletons. No DI container needed.

```python
# ai/providers/serpapi.py
_youtube: SerpApiYouTubeProvider | None = None

def get_youtube_search() -> SerpApiYouTubeProvider:
    global _youtube
    if _youtube is None:
        _youtube = SerpApiYouTubeProvider(api_key=settings.SERPAPI_API_KEY)
    return _youtube
```

---

## Celery Task Call Sites

Tasks become plain functions (no `@inject`, no container). They construct `Deps` from provider getters and call `agent.run_sync()`.

```python
# pipeline/tasks.py
@shared_task(bind=True, max_retries=3, soft_time_limit=1800, time_limit=2400)
def run_research_job(self, job_id: str) -> None:
    # ... FSM transition, job fetch, prompt construction unchanged ...
    result = research_agent.run_sync(
        prompt,
        model=settings.RESEARCH_AGENT_MODEL,
        deps=ResearchDeps(
            video_search=get_youtube_search(),
            web_search=get_web_search(),
            trends=get_trends(),
            community=get_community(),
        ),
    )
    output: ResearchAgentOutput = result.output  # typed, already validated
    _save_research_results(job, output)
```

`result.output` is a typed, already-validated Pydantic instance — no `isinstance` check or `model_validate_json()` fallback required.

---

## Dependency Changes (`pyproject.toml`)

```toml
# Remove
"anthropic>=0.80.0"
"openai-agents>=0.9.1"
"dependency-injector>=4.45.0"

# Add
"pydantic-ai[anthropic,openai]>=0.x"
```

---

## Migration Order (Foundation-First)

1. **PR 1 — Foundation**: Create `reelforge/ai/` app skeleton, move schemas + prompts unchanged, add `pydantic-ai` to deps, remove deleted packages, add per-agent model settings, implement lazy provider singletons. Update `INSTALLED_APPS`.
2. **PR 2 — ResearchAgent**: Rewrite `ai/agents/research.py`, update `run_research_job` task.
3. **PR 3 — ScriptAgent**: Rewrite `ai/agents/script.py` (includes `_seo_agent`), update `run_script_job` and `run_script_revision_job` tasks.
4. **PR 4 — VisualPlannerAgent**: Rewrite `ai/agents/visual_planner.py`, update `run_scene_breakdown_job` task.
5. **PR 5 — Cleanup**: Delete `reelforge/agents/`, delete LLM provider files, remove `dependency-injector` wiring from any remaining imports. Final lint + mypy pass.

Each PR after PR 1 is self-contained and independently deployable.

---

## Invariants

- Agents are never instantiated more than once (module-level singletons)
- No LLM SDK is imported directly in pipeline/task/model code — all LLM work goes through PydanticAI agents
- All agent outputs are validated Pydantic instances by the time they reach `_save_*` helpers
- Provider singletons are initialized lazily — safe to import agent modules in management commands and tests without triggering API connections
- FSM transitions, Celery task structure, and `_save_*` helpers are unchanged
