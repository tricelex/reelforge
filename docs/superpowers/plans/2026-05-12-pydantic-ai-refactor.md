# PydanticAI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `ClaudeProvider`/`OpenAIProvider`/OpenAI Agents SDK/`dependency-injector` with PydanticAI across the entire LLM layer, consolidating all AI code into a single `reelforge/ai/` Django app.

**Architecture:** Foundation-first — PR 1 creates the `ai/` skeleton, moves schemas/prompts/providers, and removes the old packages. PRs 2–4 rewrite the three agents. PR 5 handles the two non-agent LLM usages (clipping analysis, caption translation). PR 6 deletes all dead code.

**Tech Stack:** `pydantic-ai[anthropic,openai]`, Django 5.2, Celery, `uv`

---

## Discovered scope addition (not in spec)

Two `get_llm_provider()` call sites outside the agent layer were found:

1. `reelforge/clipping/services.py:28` — `ClipAnalysisService` calls `llm.complete()` to identify clip candidates
2. `reelforge/services/media/render_stages/captions.py:199` — calls `llm.complete()` to translate Whisper transcripts

Both are covered in **Task 5**.

The `registry.py` non-LLM getters (`get_tts_provider`, `get_image_provider`, `get_video_clip_provider`) currently call `_container()` which comes from `AgentContainer`. Removing the container requires replacing those with lazy module-level singletons. Covered in **Task 1**.

---

## File Map

### Task 1 — Foundation

**Create:**
- `reelforge/ai/__init__.py`
- `reelforge/ai/apps.py`
- `reelforge/ai/deps.py`
- `reelforge/ai/agents/__init__.py`
- `reelforge/ai/schemas/__init__.py`
- `reelforge/ai/schemas/research.py`
- `reelforge/ai/schemas/script.py`
- `reelforge/ai/schemas/visual.py`
- `reelforge/ai/prompts/__init__.py`
- `reelforge/ai/prompts/script.py`
- `reelforge/ai/prompts/visual_planner.py`
- `reelforge/ai/providers/__init__.py`
- `reelforge/ai/providers/protocols.py`
- `reelforge/ai/providers/community.py`
- `reelforge/ai/providers/trends.py`
- `reelforge/ai/providers/web_search.py`
- `reelforge/ai/providers/youtube.py`
- `reelforge/ai/providers/serpapi.py`
- `reelforge/ai/providers/tavily.py`

**Modify:**
- `pyproject.toml` — swap AI packages
- `config/settings/base.py` — add per-agent model settings, update INSTALLED_APPS
- `reelforge/services/providers/registry.py` — remove `get_llm_provider()`, replace container usage with lazy singletons
- `reelforge/services/base.py` — remove `BaseLLMProvider`

### Task 2 — ResearchAgent

**Create:** `reelforge/ai/agents/research.py`

**Modify:**
- `reelforge/pipeline/tasks.py` — `run_research_job`, `_save_research_results`

### Task 3 — ScriptAgent

**Create:** `reelforge/ai/agents/script.py`

**Modify:**
- `reelforge/pipeline/tasks.py` — `run_script_job`, `run_script_revision_job`, `_save_script_results`

### Task 4 — VisualPlannerAgent

**Create:** `reelforge/ai/agents/visual_planner.py`

**Modify:**
- `reelforge/pipeline/tasks.py` — `run_scene_breakdown_job`

### Task 5 — Non-agent LLM usages

**Create:**
- `reelforge/ai/agents/clip_analysis.py`
- `reelforge/ai/agents/translation.py`

**Modify:**
- `reelforge/clipping/services.py`
- `reelforge/services/media/render_stages/captions.py`
- `config/settings/base.py` — add CLIP_ANALYSIS_MODEL, CAPTION_TRANSLATION_MODEL

### Task 6 — Cleanup

**Delete:**
- `reelforge/agents/` (entire directory)
- `reelforge/services/providers/llm/` (entire directory)

**Modify:**
- `reelforge/pipeline/tasks.py` — remove `@inject`, `Provide[...]`, container imports
- `reelforge/services/base.py` — confirm `BaseLLMProvider` removed (done in Task 1)
- `reelforge/services/dataclass.py` — remove `LLMResponse`

---

## Task 1: Foundation

**Files:**
- Create: `reelforge/ai/` (all files listed in File Map above)
- Modify: `pyproject.toml`, `config/settings/base.py`, `reelforge/services/providers/registry.py`, `reelforge/services/base.py`

- [ ] **Step 1: Install pydantic-ai and remove old AI packages**

Run:
```bash
cd /Users/chuckz/Code/29SignalsDev/reelforge
uv add "pydantic-ai[anthropic,openai]"
uv remove anthropic openai-agents dependency-injector
```

Open `pyproject.toml` and confirm the `dependencies` list contains `"pydantic-ai[anthropic,openai]"` and no longer contains `"anthropic>=0.80.0"`, `"openai-agents>=0.9.1"`, `"dependency-injector>=4.45.0"`.

- [ ] **Step 2: Create the `reelforge/ai/` directory structure**

```bash
mkdir -p reelforge/reelforge/ai/agents reelforge/reelforge/ai/schemas reelforge/reelforge/ai/prompts reelforge/reelforge/ai/providers
touch reelforge/reelforge/ai/__init__.py reelforge/reelforge/ai/agents/__init__.py reelforge/reelforge/ai/schemas/__init__.py reelforge/reelforge/ai/prompts/__init__.py reelforge/reelforge/ai/providers/__init__.py
```

- [ ] **Step 3: Create `reelforge/ai/apps.py`**

```python
from __future__ import annotations

from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reelforge.ai"
    verbose_name = "AI"
```

- [ ] **Step 4: Move schemas — create `reelforge/ai/schemas/research.py`**

Copy the research-related models from `reelforge/agents/schemas.py`. The new file contains exactly these symbols (imports unchanged, just the file moves):

```python
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from pydantic import BaseModel


@dataclass
class VideoResult:
    title: str
    url: str
    channel: str
    channel_id: str
    channel_handle: str
    views: int | None
    likes: int | None
    published_at: str | None
    duration_seconds: int | None


@dataclass
class TrendPoint:
    date: str
    value: int


@dataclass
class TrendData:
    keyword: str
    interest_score: int
    trend_direction: str
    interest_over_time: list[TrendPoint] = field(default_factory=list)
    related_queries: list[str] = field(default_factory=list)


@dataclass
class CommunityPost:
    title: str
    score: int
    num_comments: int
    url: str
    source: str


@dataclass
class RisingTopic:
    keyword: str
    growth_rate: str
    category: str
    description: str


class ResearchTopicIdea(BaseModel):
    title_idea: str
    hook_angle: str
    target_keyword: str
    estimated_search_vol: int
    competition_level: Literal["LOW", "MEDIUM", "HIGH"]
    opportunity_score: float
    trend_direction: Literal["RISING", "STABLE", "DECLINING"]
    thumbnail_concept: str
    why_it_works: str
    content_format: str
    source_signals: list[str] = []


class DiscoveredCompetitor(BaseModel):
    youtube_channel_id: str
    channel_name: str
    channel_url: str
    subscriber_count: int = 0
    notes: str = ""


class ResearchAgentOutput(BaseModel):
    topics: list[ResearchTopicIdea]
    research_summary: str = ""
    discovered_competitors: list[DiscoveredCompetitor] = []
    data_gaps: list[str] = []
```

- [ ] **Step 5: Create `reelforge/ai/schemas/script.py`**

```python
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class ScriptSectionTag(StrEnum):
    HOOK = "HOOK"
    INTRO_BRIDGE = "INTRO_BRIDGE"
    SECTION_1 = "SECTION_1"
    SECTION_2 = "SECTION_2"
    SECTION_3 = "SECTION_3"
    TAKEAWAY = "TAKEAWAY"
    OUTRO_CTA = "OUTRO_CTA"


class NarratorPacing(StrEnum):
    SLOW = "SLOW"
    NORMAL = "NORMAL"
    FAST = "FAST"
    WHISPER = "WHISPER"


class AgentBRollSuggestion(BaseModel):
    scene_index: int = 0
    section: str = "SECTION_1"
    description: str = ""
    subject: str = ""
    setting: str = ""
    lighting: str = ""
    camera_angle: str = "eye-level"
    colour_palette: list[str] = []
    style_preset: str = "cinematic_realism"
    stock_search_keywords: list[str] = []
    duration_seconds: int = 8
    visual_type: str = ""
    mood: str = ""
    fallback_description: str = ""


class ScriptSection(BaseModel):
    tag: str
    content: str = ""
    word_count: int = 0
    estimated_duration_seconds: int = 0
    narrator_pacing: NarratorPacing = NarratorPacing.NORMAL
    narrator_notes: str = ""
    broll_indices: list[int] = []


class ScriptChapter(BaseModel):
    time: str = "0:00"
    label: str = ""


class ScriptSEOMetadata(BaseModel):
    final_title: str = ""
    description: str = ""
    tags: list[str] = []
    chapters: list[ScriptChapter] = []
    pinned_comment: str = ""
    thumbnail_text: str = ""
    thumbnail_emotion: str = ""
    search_hashtags: list[str] = []


class ResearchSource(BaseModel):
    url: str = ""
    title: str = ""
    key_claim: str = ""


class ScriptQualityFlags(BaseModel):
    hook_score: float = 0.0
    hook_type: str = ""
    avg_sentence_length: float = 0.0
    passive_voice_instances: int = 0
    jargon_flags: list[str] = []
    faceless_compliance: bool = False
    research_confidence: str = "LOW"
    open_loops_resolved: bool = False


class ScriptAgentOutput(BaseModel):
    script_text: str = ""
    sections: list[ScriptSection] = []
    hook_used: str = ""
    hook_score: float = 0.0
    word_count: int = 0
    estimated_duration_mins: float = 0.0
    broll_suggestions: list[AgentBRollSuggestion] = []
    research_sources: list[ResearchSource] = []
    seo_metadata: ScriptSEOMetadata = ScriptSEOMetadata()
    quality_flags: ScriptQualityFlags = ScriptQualityFlags()
    ready_for_production: bool = False
    revision_notes: str = ""
    narrative_mode: str = Field(default="")
    open_loops_planted: int = Field(default=0)
    aha_moments_count: int = Field(default=0)
```

- [ ] **Step 6: Create `reelforge/ai/schemas/visual.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

_DURATION_GAP_TOLERANCE = 0.1
_COVERAGE_TOLERANCE = 0.5


class VisualSegment(BaseModel):
    scene_id: int = Field(..., description="Sequential 1-based integer")
    section_tag: str = Field(..., description="The script [SECTION_TAG] this segment belongs to")
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    duration: float = Field(..., gt=0, le=10)
    narration_excerpt: str
    image_prompt: str = Field(..., description="Minimum 40 words")
    style_preset: Literal["cinematic_realism", "flat_illustration", "dark_tech", "corporate_clean"]
    colour_palette: list[str] = Field(default_factory=list)
    animation_type: Literal[
        "hook", "intro", "body_concept", "body_stat", "body_story",
        "transition", "takeaway", "outro"
    ]
    video_prompt: str
    mood: Literal["calm", "tense", "inspiring", "curious", "urgent", "warm"]
    visual_keywords: list[str] = Field(default_factory=list)
    is_transition: bool = False

    @model_validator(mode="after")
    def check_duration_matches(self) -> VisualSegment:
        computed = round(self.end_seconds - self.start_seconds, 3)
        if abs(computed - self.duration) > _DURATION_GAP_TOLERANCE:
            msg = f"duration {self.duration} does not match end_seconds - start_seconds = {computed}"
            raise ValueError(msg)
        return self


class VisualPlannerOutput(BaseModel):
    segments: list[VisualSegment] = Field(..., min_length=10)
    total_duration_seconds: float
    segment_count: int
    coverage_confirmed: bool
    revision_notes: str = ""

    @model_validator(mode="after")
    def check_coverage(self) -> VisualPlannerOutput:
        if self.segment_count != len(self.segments):
            msg = f"segment_count={self.segment_count} does not match len(segments)={len(self.segments)}"
            raise ValueError(msg)
        segs = sorted(self.segments, key=lambda s: s.start_seconds)
        for i in range(1, len(segs)):
            gap = segs[i].start_seconds - segs[i - 1].end_seconds
            if abs(gap) > _DURATION_GAP_TOLERANCE:
                msg = f"Gap of {gap:.2f}s between segment {i} and {i+1}"
                raise ValueError(msg)
        if abs(segs[-1].end_seconds - self.total_duration_seconds) > _COVERAGE_TOLERANCE:
            msg = (
                f"Timeline ends at {segs[-1].end_seconds:.2f}s "
                f"but total_duration is {self.total_duration_seconds:.2f}s"
            )
            raise ValueError(msg)
        return self
```

- [ ] **Step 7: Move script prompt — create `reelforge/ai/prompts/script.py`**

Copy `SCRIPT_AGENT_INSTRUCTIONS` verbatim from `reelforge/agents/script_agent_prompt.py` into a new file `reelforge/ai/prompts/script.py`. The file should contain only:

```python
from __future__ import annotations

SCRIPT_AGENT_INSTRUCTIONS: str = """..."""  # paste verbatim from agents/script_agent_prompt.py
```

Do not change a single character of the prompt string itself.

- [ ] **Step 8: Move visual planner prompt — create `reelforge/ai/prompts/visual_planner.py`**

Copy `VISUAL_PLANNER_INSTRUCTIONS` verbatim from `reelforge/agents/visual_planner_prompt.py` into a new file `reelforge/ai/prompts/visual_planner.py`:

```python
from __future__ import annotations

VISUAL_PLANNER_INSTRUCTIONS: str = """..."""  # paste verbatim from agents/visual_planner_prompt.py
```

- [ ] **Step 9: Move provider implementations — create `reelforge/ai/providers/community.py`**

Copy `reelforge/agents/providers/community.py` to `reelforge/ai/providers/community.py`. Update the single import that references old paths:

```python
# Change this line:
from reelforge.agents.schemas import CommunityPost
# To:
from reelforge.ai.schemas.research import CommunityPost
```

- [ ] **Step 10: Create `reelforge/ai/providers/trends.py`**

Copy `reelforge/agents/providers/trends.py` to `reelforge/ai/providers/trends.py`. Update imports:

```python
# Change:
from reelforge.agents.schemas import RisingTopic
from reelforge.agents.schemas import TrendData
from reelforge.agents.schemas import TrendPoint
# To:
from reelforge.ai.schemas.research import RisingTopic
from reelforge.ai.schemas.research import TrendData
from reelforge.ai.schemas.research import TrendPoint
```

- [ ] **Step 11: Create `reelforge/ai/providers/web_search.py`**

Copy `reelforge/agents/providers/web_search.py` to `reelforge/ai/providers/web_search.py`. Update imports:

```python
# Change (TYPE_CHECKING block):
from reelforge.services.tavily.client import TavilyResearchClient
# No change needed — this import path is still valid
```

Verify the file has no `reelforge.agents` imports; update any that do.

- [ ] **Step 12: Create `reelforge/ai/providers/youtube.py`**

Copy `reelforge/agents/providers/youtube.py` to `reelforge/ai/providers/youtube.py`. Update imports:

```python
# Change:
from reelforge.agents.schemas import VideoResult
# To:
from reelforge.ai.schemas.research import VideoResult
```

- [ ] **Step 13: Create `reelforge/ai/providers/protocols.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import runtime_checkable

if TYPE_CHECKING:
    from reelforge.ai.schemas.research import CommunityPost
    from reelforge.ai.schemas.research import RisingTopic
    from reelforge.ai.schemas.research import TrendData
    from reelforge.ai.schemas.research import VideoResult
    from reelforge.services.dataclass import ImageResponse
    from reelforge.services.dataclass import TTSResponse


@runtime_checkable
class VideoSearchProvider(Protocol):
    def search_trending(self, niche: str, days_back: int, limit: int) -> list[VideoResult]: ...
    def search_videos(self, query: str, max_results: int) -> list[VideoResult]: ...
    def get_channel_videos(self, channel_id: str, max_results: int) -> list[VideoResult]: ...
    def analyze_competitors(self, channel_ids: list[str]) -> dict[str, Any]: ...


@runtime_checkable
class TrendsProvider(Protocol):
    def get_interest(self, keyword: str, timeframe: str) -> TrendData: ...
    def get_interest_batch(self, keywords: list[str], timeframe: str) -> list[TrendData]: ...
    def get_trending_searches(self, region: str) -> list[str]: ...
    def get_rising_topics(self, category: str) -> list[RisingTopic]: ...


@runtime_checkable
class CommunitySearchProvider(Protocol):
    def search_discussions(self, niche: str, query: str | None, limit: int) -> list[CommunityPost]: ...


@runtime_checkable
class WebSearchProvider(Protocol):
    def research(self, topic: str, depth: str) -> dict[str, Any]: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    def synthesize(self, text: str, voice_id: str, **settings: Any) -> TTSResponse: ...


@runtime_checkable
class ImageProvider(Protocol):
    name: str
    def generate(self, prompt: str, width: int, height: int, **kwargs: Any) -> list[ImageResponse]: ...
```

Note: `LLMProvider` protocol is intentionally removed — replaced by PydanticAI.

- [ ] **Step 14: Create `reelforge/ai/providers/serpapi.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reelforge.ai.providers.community import SerpApiCommunityProvider
    from reelforge.ai.providers.trends import SerpApiTrendsProvider
    from reelforge.ai.providers.youtube import SerpApiYouTubeProvider
    from reelforge.services.serpapi.client import SerpApiClient

_client: SerpApiClient | None = None
_youtube: SerpApiYouTubeProvider | None = None
_trends: SerpApiTrendsProvider | None = None
_community: SerpApiCommunityProvider | None = None


def _get_client() -> SerpApiClient:
    global _client
    if _client is None:
        from django.conf import settings
        from reelforge.services.serpapi.client import SerpApiClient
        _client = SerpApiClient(api_key=settings.SERPAPI_API_KEY)
    return _client


def get_youtube_search() -> SerpApiYouTubeProvider:
    global _youtube
    if _youtube is None:
        from reelforge.ai.providers.youtube import SerpApiYouTubeProvider
        _youtube = SerpApiYouTubeProvider(client=_get_client())
    return _youtube


def get_trends() -> SerpApiTrendsProvider:
    global _trends
    if _trends is None:
        from reelforge.ai.providers.trends import SerpApiTrendsProvider
        _trends = SerpApiTrendsProvider(client=_get_client())
    return _trends


def get_community() -> SerpApiCommunityProvider:
    global _community
    if _community is None:
        from reelforge.ai.providers.community import SerpApiCommunityProvider
        _community = SerpApiCommunityProvider(client=_get_client())
    return _community
```

- [ ] **Step 15: Create `reelforge/ai/providers/tavily.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reelforge.ai.providers.web_search import TavilyProvider

_web_search: TavilyProvider | None = None


def get_web_search() -> TavilyProvider:
    global _web_search
    if _web_search is None:
        from django.conf import settings
        from reelforge.ai.providers.web_search import TavilyProvider
        from reelforge.services.tavily.client import TavilyResearchClient
        _web_search = TavilyProvider(client=TavilyResearchClient(api_key=settings.TAVILY_API_KEY))
    return _web_search
```

- [ ] **Step 16: Create `reelforge/ai/deps.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reelforge.ai.providers.community import SerpApiCommunityProvider
    from reelforge.ai.providers.trends import SerpApiTrendsProvider
    from reelforge.ai.providers.web_search import TavilyProvider
    from reelforge.ai.providers.youtube import SerpApiYouTubeProvider
    from reelforge.channels.models import Channel
    from reelforge.research.models import TopicIdea


@dataclass
class ResearchDeps:
    video_search: SerpApiYouTubeProvider
    web_search: TavilyProvider
    trends: SerpApiTrendsProvider
    community: SerpApiCommunityProvider
    channel: Channel


@dataclass
class ScriptDeps:
    web_search: TavilyProvider
    channel: Channel
    topic: TopicIdea


@dataclass
class VisualPlannerDeps:
    sections: list[dict]
    broll_suggestions: list[dict]
    total_duration_seconds: float
    channel_tone: str
    narrative_mode: str
```

- [ ] **Step 17: Update `config/settings/base.py` — AI settings block**

Find the `# AI PROVIDER CONFIGURATION` section (around line 751) and replace it:

```python
# AI PROVIDER CONFIGURATION
# ------------------------------------------------------------------------------
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")

# Per-agent model strings — PydanticAI resolves "openai:*" and "anthropic:*" natively
RESEARCH_AGENT_MODEL      = env("RESEARCH_AGENT_MODEL",      default="openai:gpt-4o")
SCRIPT_AGENT_MODEL        = env("SCRIPT_AGENT_MODEL",        default="openai:gpt-4o")
VISUAL_PLANNER_MODEL      = env("VISUAL_PLANNER_MODEL",      default="openai:gpt-4o")
CLIP_ANALYSIS_MODEL       = env("CLIP_ANALYSIS_MODEL",       default="anthropic:claude-sonnet-4-5")
CAPTION_TRANSLATION_MODEL = env("CAPTION_TRANSLATION_MODEL", default="anthropic:claude-sonnet-4-5")

# Provider Defaults (TTS, image, video — unchanged)
DEFAULT_TTS_PROVIDER        = env("DEFAULT_TTS_PROVIDER",   default="elevenlabs")
DEFAULT_IMAGE_PROVIDER      = env("DEFAULT_IMAGE_PROVIDER", default="fal_ai")
DEFAULT_VIDEO_CLIP_PROVIDER = env("DEFAULT_VIDEO_CLIP_PROVIDER", default="fal_ai_kling")
```

Remove the `DEFAULT_LLM_PROVIDER` line entirely.

- [ ] **Step 18: Update `config/settings/base.py` — INSTALLED_APPS**

In `LOCAL_APPS`, replace `"reelforge.agents"` with `"reelforge.ai"`:

```python
LOCAL_APPS = [
    "reelforge.users",
    "reelforge.core",
    "reelforge.channels",
    "reelforge.pipeline",
    "reelforge.research",
    "reelforge.scripts",
    "reelforge.assets",
    "reelforge.production",
    "reelforge.distribution",
    "reelforge.ai",          # replaces reelforge.agents
    "reelforge.clipping",
    "reelforge.ui",
]
```

- [ ] **Step 19: Update `reelforge/services/providers/registry.py`**

Replace the entire file:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from reelforge.channels.models import Channel
    from reelforge.channels.models import SocialAccount
    from reelforge.services.base import BaseImageProvider
    from reelforge.services.base import BaseTTSProvider
    from reelforge.services.base import BaseVideoClipProvider
    from reelforge.services.providers.distribution.base import BaseClipDistributionProvider

logger = logging.getLogger("reelforge.providers")

# ── Lazy singletons — TTS ─────────────────────────────────────────────────────

_tts_elevenlabs: ElevenLabsProvider | None = None  # type: ignore[name-defined]
_tts_mock: MockTTSProvider | None = None  # type: ignore[name-defined]


def get_tts_provider(channel: Channel | None = None) -> BaseTTSProvider:
    global _tts_elevenlabs, _tts_mock
    from reelforge.services.providers.tts.elevenlabs import ElevenLabsProvider
    from reelforge.services.providers.tts.mock import MockTTSProvider

    name = channel.tts_provider if channel and channel.tts_provider else settings.DEFAULT_TTS_PROVIDER
    if name == "mock":
        if _tts_mock is None:
            _tts_mock = MockTTSProvider(name="mock")
        return _tts_mock
    if _tts_elevenlabs is None:
        _tts_elevenlabs = ElevenLabsProvider(api_key=settings.ELEVENLABS_API_KEY)
    return _tts_elevenlabs


# ── Lazy singletons — Image ───────────────────────────────────────────────────

_image_fal: FalAiImageProvider | None = None  # type: ignore[name-defined]
_image_mock: MockImageProvider | None = None  # type: ignore[name-defined]


def get_image_provider(channel: Channel | None = None) -> BaseImageProvider:
    global _image_fal, _image_mock
    from reelforge.services.fal.client import FalAiClient
    from reelforge.services.providers.image.fal_ai import FalAiImageProvider
    from reelforge.services.providers.image.mock import MockImageProvider

    name = channel.image_provider if channel and channel.image_provider else settings.DEFAULT_IMAGE_PROVIDER
    if name == "mock":
        if _image_mock is None:
            _image_mock = MockImageProvider(name="mock")
        return _image_mock
    if _image_fal is None:
        _image_fal = FalAiImageProvider(client=FalAiClient(api_key=settings.FAL_API_KEY))
    return _image_fal


# ── Lazy singletons — Video clip ──────────────────────────────────────────────

_video_clip_fal: FalAiVideoClipProvider | None = None  # type: ignore[name-defined]
_video_clip_mock: MockVideoClipProvider | None = None  # type: ignore[name-defined]


def get_video_clip_provider(channel: Channel | None = None) -> BaseVideoClipProvider:
    global _video_clip_fal, _video_clip_mock
    from reelforge.services.fal.client import FalAiClient
    from reelforge.services.providers.video_clip.fal_ai import FalAiVideoClipProvider
    from reelforge.services.providers.video_clip.mock import MockVideoClipProvider

    name = (getattr(channel, "video_clip_provider", None) if channel else None) or settings.DEFAULT_VIDEO_CLIP_PROVIDER
    if name == "mock":
        if _video_clip_mock is None:
            _video_clip_mock = MockVideoClipProvider(name="mock")
        return _video_clip_mock
    if _video_clip_fal is None:
        _video_clip_fal = FalAiVideoClipProvider(client=FalAiClient(api_key=settings.FAL_API_KEY))
    return _video_clip_fal


# ── Distribution provider — unchanged ────────────────────────────────────────

def get_distribution_provider(
    social_account: SocialAccount,
) -> BaseClipDistributionProvider:
    from reelforge.channels.models import SocialAccount as _SocialAccount
    from reelforge.services.providers.distribution.instagram import InstagramClipProvider
    from reelforge.services.providers.distribution.tiktok import TikTokClipProvider
    from reelforge.services.providers.distribution.youtube import YouTubeClipProvider

    platform = social_account.platform
    if platform == _SocialAccount.Platform.YOUTUBE:
        return YouTubeClipProvider(social_account)
    if platform == _SocialAccount.Platform.TIKTOK:
        return TikTokClipProvider(social_account)
    if platform == _SocialAccount.Platform.INSTAGRAM:
        return InstagramClipProvider(social_account)
    msg = f"Distribution provider not implemented for platform: {platform}"
    raise NotImplementedError(msg)
```

- [ ] **Step 20: Remove `BaseLLMProvider` from `reelforge/services/base.py`**

Delete the `BaseLLMProvider` class and its import of `LLMResponse`. The file should become:

```python
from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import Any

from reelforge.services.dataclass import ImageResponse
from reelforge.services.dataclass import TTSResponse
from reelforge.services.dataclass import VideoClipResponse


class BaseTTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, **settings: Any) -> TTSResponse: ...


class BaseImageProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str, width: int, height: int, **kwargs: Any) -> list[ImageResponse]: ...

    async def generate_batch_async(
        self, scene_prompts: list[dict[str, Any]]
    ) -> list[ImageResponse | BaseException]:
        results: list[ImageResponse | BaseException] = []
        for sp in scene_prompts:
            try:
                responses = self.generate(
                    prompt=sp["prompt"],
                    width=sp.get("width", 1920),
                    height=sp.get("height", 1080),
                )
                results.append(responses[0])
            except Exception as exc:
                results.append(exc)
        return results


class BaseVideoClipProvider(ABC):
    name: str

    @abstractmethod
    def generate_clip(
        self,
        image_path: str,
        prompt: str,
        duration_sec: float = 5.0,
        **kwargs: Any,
    ) -> VideoClipResponse: ...

    async def generate_clips_async(
        self, clip_requests: list[dict[str, Any]]
    ) -> list[VideoClipResponse | BaseException]:
        results: list[VideoClipResponse | BaseException] = []
        for req in clip_requests:
            try:
                results.append(
                    self.generate_clip(
                        image_path=req["image_path"],
                        prompt=req["prompt"],
                        duration_sec=req.get("duration_sec", 5.0),
                    )
                )
            except Exception as exc:
                results.append(exc)
        return results
```

- [ ] **Step 21: Run lint to verify Task 1 changes compile**

```bash
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run ruff check . --unsafe-fixes
```

Fix any errors. The agents app still exists (we haven't deleted it), so import errors in `pipeline/tasks.py` are expected — they will be fixed in Tasks 2–4.

- [ ] **Step 22: Commit Task 1**

```bash
git add reelforge/ai/ pyproject.toml config/settings/base.py \
  reelforge/services/providers/registry.py reelforge/services/base.py
git commit -m "feat(ai): add reelforge/ai app skeleton — schemas, providers, deps, settings"
```

---

## Task 2: ResearchAgent

**Files:**
- Create: `reelforge/ai/agents/research.py`
- Modify: `reelforge/pipeline/tasks.py` (lines 36–88, 1628–1822)

- [ ] **Step 1: Create `reelforge/ai/agents/research.py`**

```python
from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai import RunContext

from reelforge.ai.deps import ResearchDeps
from reelforge.ai.schemas.research import ResearchAgentOutput

if TYPE_CHECKING:
    pass

research_agent: Agent[ResearchDeps, ResearchAgentOutput] = Agent(
    deps_type=ResearchDeps,
    output_type=ResearchAgentOutput,
)


@research_agent.system_prompt
def build_research_system_prompt(ctx: RunContext[ResearchDeps]) -> str:
    channel = ctx.deps.channel
    competitor_context = (
        "\n".join(f"{c.youtube_channel_id} ({c.channel_name})" for c in channel.competitors.all())
        or "None configured yet"
    )
    channel_keywords_str = ", ".join(channel.channel_keywords) or "none yet"
    target_locations_str = ", ".join(channel.target_location) or "global"
    target_niches_str = ", ".join(channel.target_niches)

    return f"""
You are an expert YouTube content research strategist operating the research phase of the
Reelforge automation pipeline.

═══════════════════════════════════════════════════════════════
CHANNEL CONTEXT
═══════════════════════════════════════════════════════════════
Channel name      : {channel.name}
Target niches     : {target_niches_str}
Audience          : {channel.target_audience_description}
Age range         : {channel.target_age_range or "not specified"}
Target locations  : {target_locations_str}
Tone              : {channel.content_tone}
Video length      : {channel.video_length_min}–{channel.video_length_max} minutes
Upload frequency  : {channel.upload_frequency}
Existing keywords : {channel_keywords_str}

Known competitor channels (ALWAYS include in Step 4):
{competitor_context}

═══════════════════════════════════════════════════════════════
FORMAT DEFINITIONS
═══════════════════════════════════════════════════════════════
Pick the format that best fits each topic:

  • listicle    — "Top X / Best X / X Things to Know"
                  Tool roundups, tips, mistakes — 8–10 min
  • tutorial    — Step-by-step process, screen capture or visuals
                  Walkthroughs, how-to guides — 10–14 min
  • comparison  — "A vs B", "X or Y", two clear options
                  Side-by-side analysis — 8–12 min
  • explainer   — "How X works / Why X happens"
                  Educational, data-driven — 10–14 min
  • case-study  — Real example with outcomes, narrative arc
                  Success stories, breakdowns — 8–12 min
  • myth-debunk — "The Truth About X", contrarian angle
                  Widely-believed misconceptions — 8–10 min
  • deep-dive   — Comprehensive single-topic coverage
                  Exhaustive reference — 12–14 min

RULE: The final topic list MUST include at least 3 different formats.

═══════════════════════════════════════════════════════════════
RESEARCH PROCESS — 6 STEPS (follow in order)
═══════════════════════════════════════════════════════════════

STEP 1 — YouTube Trend Discovery
  Call: search_youtube_trends for each niche in target_niches (days_back=7, limit=20)
  Read from results:
    • duration_seconds  → understand what video length the algorithm rewards right now
    • title patterns    → note recurring structures
    • views             → proxy for audience size for this specific angle
    • channel_handle    → collect every channel_handle for use in Step 4
  Flag: any niche returning < 5 results → retry with a broader term before moving on.

STEP 2 — Keyword Demand Validation
  After Step 1, collect ALL top candidate keywords (max 10).
  Call: check_google_trends_batch ONCE with the full list (timeframe="today 3-m").
  Do NOT call any trends tool one keyword at a time — always batch into a single call.
  Read from each TrendData result:
    • interest_score    → < 15 = low demand; > 80 with HIGH competition = likely oversaturated
    • trend_direction   → prefer RISING; STABLE acceptable; DECLINING = skip unless unique angle
    • related_queries   → mine for sub-keywords and long-tail title angles

STEP 3 — Community Intelligence
  Call: search_community_discussions for each niche (limit=25)
  Then call: research_audience_questions for each niche

STEP 4 — Competitor Content Gap Analysis
  Call: analyze_competitor_channels with ALL known channel handles (from CHANNEL CONTEXT above)
        PLUS every channel_handle collected from Step 1 trending results.

STEP 5 — Rising / Pre-Peak Trend Detection
  Call: check_exploding_topics for each niche category

STEP 6 — Score and Rank All Candidates
  Apply this scoring table:
    Search volume score: > 50,000 → +30 | > 20,000 → +20 | > 5,000 → +10 | ≤ 5,000 → +0
    Competition score: LOW → +35 | MEDIUM → +20 | HIGH → +5
    Trend score: RISING → +25 | STABLE → +10 | DECLINING → +0
  Bonus: +10 for any topic in BOTH Step 3 community pain points AND Step 4 competitor gap.
  Minimum threshold: total score >= 60. Select top 8–12 topics.

═══════════════════════════════════════════════════════════════
TOPIC SELECTION RULES
═══════════════════════════════════════════════════════════════
  ✓ opportunity_score >= 60
  ✓ estimated_search_vol > 10,000/month
  ✓ competition_level is LOW or MEDIUM only
  ✓ Suitable for faceless AI video — no talking head required
  ✓ Video fits the {channel.video_length_min}–{channel.video_length_max} minute format
  ✗ Do NOT use any keyword already present in: {channel_keywords_str}
  ✗ Do NOT use DECLINING trend_direction unless the angle is uniquely differentiated

═══════════════════════════════════════════════════════════════
HOOK PSYCHOLOGY STANDARDS
═══════════════════════════════════════════════════════════════
Each hook_angle MUST name a specific psychological trigger:
  CURIOSITY GAP | FOMO | SOCIAL PROOF | AUTHORITY | CONTROVERSY | PATTERN INTERRUPT
And describe the first 15 seconds specifically.
Format: "[TRIGGER TYPE] — [first 15 seconds described in one or two sentences]"

═══════════════════════════════════════════════════════════════
TITLE QUALITY RULES
═══════════════════════════════════════════════════════════════
  • Length: 50–65 characters (optimal YouTube CTR range)
  • Must include a specific number, question mark, or power phrase
  • Must create a curiosity gap OR promise a specific measurable outcome

═══════════════════════════════════════════════════════════════
THUMBNAIL CONCEPT STANDARDS
═══════════════════════════════════════════════════════════════
Each thumbnail_concept must specify: primary subject, dominant emotion, text overlay, color scheme.

NEVER fabricate numbers, channel names, or video titles. Use null for unknown fields.
Document every insufficient tool response in the data_gaps array.

═══════════════════════════════════════════════════════════════
PRE-OUTPUT QUALITY GATE
═══════════════════════════════════════════════════════════════
Before finalizing, run this checklist on EVERY topic:
  □ opportunity_score was computed using the Step 6 scoring table and is >= 60?
  □ why_it_works cites a specific number from a tool result?
  □ hook_angle names a psychological trigger AND describes the first 15 seconds?
  □ thumbnail_concept specifies subject, emotion, text overlay, and color scheme?
  □ title_idea is 50–65 characters?
  □ content_format is one of the 7 defined formats?
  □ topic does NOT duplicate a keyword already in channel_keywords?
Reject any topic that fails 2 or more checks.

Any YouTube channel you analyzed must be included in discovered_competitors.
Only include channels you actually saw data for — never invent entries.
"""


@research_agent.tool
def search_youtube_trends(ctx: RunContext[ResearchDeps], niche: str, days_back: int = 7, limit: int = 20) -> str:
    """Search YouTube for trending videos in a niche. Returns titles, views, dates, durations."""
    results = ctx.deps.video_search.search_trending(niche=niche, days_back=days_back, limit=limit)
    return json.dumps([asdict(r) for r in results], default=str)


@research_agent.tool
def check_google_trends_batch(ctx: RunContext[ResearchDeps], keywords: list[str], timeframe: str = "today 3-m") -> str:
    """Get search volume trend data for multiple keywords in a single call. Always batch — never call one keyword at a time."""
    results = ctx.deps.trends.get_interest_batch(keywords=keywords[:10], timeframe=timeframe)
    return json.dumps([asdict(r) for r in results], default=str)


@research_agent.tool
def search_community_discussions(
    ctx: RunContext[ResearchDeps],
    niche: str,
    query: str | None = None,
    limit: int = 20,
) -> str:
    """Search web community discussions (Reddit, forums, HN) about a niche."""
    posts = ctx.deps.community.search_discussions(niche=niche, query=query, limit=limit)
    return json.dumps([asdict(p) for p in posts], default=str)


@research_agent.tool
def research_audience_questions(ctx: RunContext[ResearchDeps], niche: str) -> str:
    """Use web-grounded AI search to find common audience questions and pain points for a niche."""
    prompt = (
        f"What are the most common questions, pain points, and confusions beginners have "
        f"about {niche}? List 10-15 specific questions."
    )
    result = ctx.deps.web_search.research(topic=prompt, depth="deep")
    return json.dumps(result, default=str)


@research_agent.tool
def analyze_competitor_channels(ctx: RunContext[ResearchDeps], channel_ids: list[str]) -> str:
    """Analyze competitor YouTube channels for content patterns and gaps."""
    result = ctx.deps.video_search.analyze_competitors(channel_ids=channel_ids)
    return json.dumps(result, default=str)


@research_agent.tool
def check_exploding_topics(ctx: RunContext[ResearchDeps], category: str) -> str:
    """Find rising keyword trends before they peak using Google Trends rising topics data via SerpAPI."""
    rising = ctx.deps.trends.get_rising_topics(category=category)
    return json.dumps([asdict(t) for t in rising], default=str)
```

- [ ] **Step 2: Update `run_research_job` in `reelforge/pipeline/tasks.py`**

Replace lines 36–88 (the `run_research_job` function). Keep the decorator and change the body:

```python
@shared_task(
    bind=True,
    queue="research",
    soft_time_limit=1800,
    time_limit=2400,
)
def run_research_job(
    self: Any,
    channel_id: str,
    research_job_id: str,
) -> None:
    from reelforge.ai.agents.research import research_agent
    from reelforge.ai.deps import ResearchDeps
    from reelforge.ai.providers.serpapi import get_community
    from reelforge.ai.providers.serpapi import get_trends
    from reelforge.ai.providers.serpapi import get_youtube_search
    from reelforge.ai.providers.tavily import get_web_search
    from reelforge.channels.models import Channel
    from reelforge.research.models import ResearchJob

    try:
        job = ResearchJob.objects.get(id=research_job_id)
    except ResearchJob.DoesNotExist:
        logger.exception(
            "ResearchJob %s not found — aborting task (will not retry)",
            research_job_id,
            extra={"research_job_id": research_job_id},
        )
        return

    job.mark_running(task_id=self.request.id)

    try:
        channel = Channel.objects.prefetch_related("competitors").get(id=channel_id)

        result = research_agent.run_sync(
            f"Research topics for channel {channel.name}. Niches: {channel.target_niches}",
            model=settings.RESEARCH_AGENT_MODEL,
            deps=ResearchDeps(
                video_search=get_youtube_search(),
                web_search=get_web_search(),
                trends=get_trends(),
                community=get_community(),
                channel=channel,
            ),
        )
        _save_research_results(job, result, channel)
        job.mark_completed()

    except Exception as exc:
        job.mark_failed(str(exc))
        raise
```

Add `from django.conf import settings` to the top-level imports of `tasks.py` if not already present.

- [ ] **Step 3: Update `_save_research_results` in `reelforge/pipeline/tasks.py`**

Replace the function signature and the first section (output parsing + usage tracking):

```python
def _save_research_results(job: Any, result: Any, channel: Any) -> None:
    from reelforge.ai.schemas.research import ResearchAgentOutput
    from reelforge.research.choices import CompetitionLevel
    from reelforge.research.choices import TrendDirection
    from reelforge.research.models import TopicIdea

    output: ResearchAgentOutput = result.output

    # ── Token usage and cost ─────────────────────────────────────────────────
    usage = result.usage()
    total_input = usage.request_tokens or 0
    total_output = usage.response_tokens or 0
    total_tokens = usage.total_tokens or 0

    cost_usd = (
        Decimal(str(total_input)) * _GPT4O_INPUT_COST_PER_M / Decimal(1000000)
        + Decimal(str(total_output)) * _GPT4O_OUTPUT_COST_PER_M / Decimal(1000000)
    ).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)

    agent_run_id = ""

    # ... rest of the function (trend_data_raw, competitor_data_raw, etc.) is UNCHANGED
```

Remove the `isinstance` / `model_validate_json` fallback block — `result.output` is always typed.

- [ ] **Step 4: Remove old imports from `pipeline/tasks.py` top section**

Remove these lines from the top of `tasks.py`:
```python
from dependency_injector.wiring import Provide
from dependency_injector.wiring import inject
from reelforge.agents.containers import AgentContainer
```

And from the `TYPE_CHECKING` block, remove:
```python
from reelforge.agents.providers.protocols import CommunitySearchProvider
from reelforge.agents.providers.protocols import LLMProvider
from reelforge.agents.providers.protocols import TrendsProvider
from reelforge.agents.providers.protocols import VideoSearchProvider
from reelforge.agents.providers.protocols import WebSearchProvider
```

Add at the top of the file:
```python
from django.conf import settings
```

- [ ] **Step 5: Run lint + type check**

```bash
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run ruff check . --unsafe-fixes && uv run mypy reelforge/ai/agents/research.py reelforge/pipeline/tasks.py
```

Fix any errors before committing.

- [ ] **Step 6: Commit Task 2**

```bash
git add reelforge/ai/agents/research.py reelforge/pipeline/tasks.py
git commit -m "feat(ai): add PydanticAI ResearchAgent, update run_research_job"
```

---

## Task 3: ScriptAgent

**Files:**
- Create: `reelforge/ai/agents/script.py`
- Modify: `reelforge/pipeline/tasks.py` (lines 114–244, 1825–2019)

- [ ] **Step 1: Create `reelforge/ai/agents/script.py`**

```python
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai import RunContext

from reelforge.ai.deps import ScriptDeps
from reelforge.ai.prompts.script import SCRIPT_AGENT_INSTRUCTIONS
from reelforge.ai.schemas.script import ScriptAgentOutput
from reelforge.ai.schemas.script import ScriptSEOMetadata

if TYPE_CHECKING:
    pass

_seo_agent: Agent[None, ScriptSEOMetadata] = Agent(output_type=ScriptSEOMetadata)

script_agent: Agent[ScriptDeps, ScriptAgentOutput] = Agent(
    deps_type=ScriptDeps,
    output_type=ScriptAgentOutput,
)


@script_agent.system_prompt
def build_script_system_prompt(ctx: RunContext[ScriptDeps]) -> str:
    channel = ctx.deps.channel
    topic = ctx.deps.topic

    channel_niches_str = ", ".join(channel.target_niches) if channel.target_niches else "general"
    keywords_str = ", ".join(topic.keywords) if topic.keywords else "N/A"
    content_format = getattr(topic, "content_format", "explainer") or "explainer"
    topic_hook_angle = getattr(topic, "angle", "") or ""
    target_length_min = channel.video_length_min
    target_length_max = channel.video_length_max
    target_wc_min = target_length_min * 130
    target_wc_max = target_length_max * 130
    description_str = topic.description or "N/A"
    why_it_works_str = topic.why_it_works or ""
    thumbnail_concept_str = topic.thumbnail_concept or ""
    community_questions_str = (
        "\n".join(f"  - {q}" for q in topic.community_questions)
        if topic.community_questions
        else "  None captured"
    )
    suggested_sources_str = (
        "\n".join(f"  - {s}" for s in topic.suggested_sources)
        if topic.suggested_sources
        else "  None captured"
    )

    return SCRIPT_AGENT_INSTRUCTIONS.format(
        channel=channel,
        topic=topic,
        channel_niches_str=channel_niches_str,
        content_format=content_format,
        target_length_min=target_length_min,
        target_length_max=target_length_max,
        target_wc_min=target_wc_min,
        target_wc_max=target_wc_max,
        topic_hook_angle=topic_hook_angle,
        keywords_str=keywords_str,
        description_str=description_str,
        why_it_works_str=why_it_works_str,
        thumbnail_concept_str=thumbnail_concept_str,
        community_questions_str=community_questions_str,
        suggested_sources_str=suggested_sources_str,
    )


@script_agent.tool
def fetch_research_facts(ctx: RunContext[ScriptDeps], topic: str, depth: str = "deep") -> str:
    """Fetch credible facts, statistics, and sources for a topic via web-grounded search.

    Returns JSON with keys: query, answer, key_facts, statistics, expert_quotes,
    common_misconceptions, sources (list of {url, title}), confidence.
    Call this at least 3 times with different angle queries before writing the script.
    """
    result = ctx.deps.web_search.research(topic=topic, depth=depth)
    return json.dumps(result, default=str)


@script_agent.tool
async def generate_seo_metadata(
    ctx: RunContext[ScriptDeps],
    title_idea: str,
    script_excerpt: str,
    keyword: str,
    channel_tags: list[str],
) -> str:
    """Generate YouTube SEO title, description, tags, chapter markers, and thumbnail metadata.

    Returns JSON with final_title, description, tags, chapters, pinned_comment,
    thumbnail_text, thumbnail_emotion, and search_hashtags.
    """
    from django.conf import settings

    prompt = f"""Generate YouTube SEO metadata:
Title idea: {title_idea}, Keyword: {keyword}
Script start: {script_excerpt[:400]}
Channel tags: {channel_tags}
Return JSON matching the ScriptSEOMetadata schema:
{{
    "final_title": "str (max 70 chars, keyword in first 40 chars, creates curiosity)",
    "description": "str (800 chars, first 150 chars = complete compelling sentence with keyword)",
    "tags": ["str (25 tags — mix of broad, specific, and long-tail)"],
    "chapters": [{{"time": "0:00", "label": "str (concise chapter label)"}}],
    "pinned_comment": "str (open-ended question that triggers genuine viewer responses)",
    "thumbnail_text": "str (2-5 words that create curiosity without spoiling the hook)",
    "thumbnail_emotion": "str (one word only: shock|curiosity|urgency|disbelief|aspiration)",
    "search_hashtags": ["str (3-5 most-searched hashtags for video description footer)"]
}}"""
    seo_result = await _seo_agent.run(prompt, model=settings.SCRIPT_AGENT_MODEL)
    return seo_result.output.model_dump_json()
```

- [ ] **Step 2: Update `run_script_job` in `reelforge/pipeline/tasks.py`**

Replace lines 114–165 (`run_script_job` function body):

```python
@shared_task(
    bind=True,
    queue="default",
    soft_time_limit=1200,
    time_limit=1800,
)
def run_script_job(
    self: Any,
    topic_id: str,
    pipeline_run_id: str,
) -> None:
    from reelforge.ai.agents.script import script_agent
    from reelforge.ai.deps import ScriptDeps
    from reelforge.ai.providers.tavily import get_web_search
    from reelforge.pipeline.models import PipelineRun
    from reelforge.research.models import TopicIdea
    from reelforge.scripts.models import ScriptJob

    topic = TopicIdea.objects.select_related("channel").get(id=topic_id)
    channel = topic.channel

    job, _ = ScriptJob.objects.get_or_create(
        topic=topic,
        defaults={"channel": channel},
    )
    job.mark_running(task_id=self.request.id)

    try:
        result = script_agent.run_sync(
            f"Write a full script for: {topic.title_idea}",
            model=settings.SCRIPT_AGENT_MODEL,
            deps=ScriptDeps(
                web_search=get_web_search(),
                channel=channel,
                topic=topic,
            ),
        )
        _save_script_results(job, result)
        job.mark_completed()

        PipelineRun.objects.filter(id=pipeline_run_id).update(script_job=job)

    except Exception as exc:
        job.mark_failed(str(exc))
        raise
```

- [ ] **Step 3: Update `run_script_revision_job` in `reelforge/pipeline/tasks.py`**

Replace lines 170–244 (`run_script_revision_job` function body):

```python
@shared_task(
    bind=True,
    queue="default",
    soft_time_limit=1200,
    time_limit=1800,
)
def run_script_revision_job(
    self: Any,
    script_job_id: str,
) -> None:
    from django_fsm import can_proceed

    from reelforge.ai.agents.script import script_agent
    from reelforge.ai.deps import ScriptDeps
    from reelforge.ai.providers.tavily import get_web_search
    from reelforge.scripts.models import ScriptJob

    script_job = ScriptJob.objects.select_related("topic__channel").get(id=script_job_id)
    channel = script_job.topic.channel
    topic = script_job.topic
    change_request = script_job.change_request

    if can_proceed(script_job.begin_revision):
        script_job.begin_revision(task_id=self.request.id)
        script_job.save(update_fields=["status", "started_at", "celery_task_id"])
    else:
        script_job.celery_task_id = self.request.id
        script_job.save(update_fields=["celery_task_id"])

    try:
        last_revision = script_job.revisions.order_by("-version_number").first()
        next_version = (last_revision.version_number + 1) if last_revision else 2

        hook_text = script_job.selected_hook.text if script_job.selected_hook else ""
        revision_input = (
            f"Revise the existing script for: {topic.title_idea}\n\n"
            f"CHANGE REQUEST FROM OPERATOR:\n{change_request}\n\n"
            f"EXISTING SCRIPT:\n{script_job.script_text}\n\n"
            f"HOOK USED (score {script_job.hook_score:.1f}):\n"
            f"{hook_text}\n\n"
            f"AGENT SELF-REVIEW NOTES FROM PREVIOUS RUN:\n{script_job.revision_notes or '(none)'}\n\n"
            "Incorporate the change request. Keep what works well. "
            "Return the complete refined script via the standard output format."
        )

        result = script_agent.run_sync(
            revision_input,
            model=settings.SCRIPT_AGENT_MODEL,
            deps=ScriptDeps(
                web_search=get_web_search(),
                channel=channel,
                topic=topic,
            ),
        )

        _save_script_results(
            script_job,
            result,
            version_number=next_version,
            change_summary=f"Revision: {change_request[:200]}",
        )
        script_job.mark_completed()

        script_job.change_request = ""
        script_job.save(update_fields=["change_request", "updated_at"])

    except Exception as exc:
        script_job.mark_failed(str(exc))
        raise
```

- [ ] **Step 4: Update `_save_script_results` in `reelforge/pipeline/tasks.py`**

Replace the first section (output parsing only — everything after stays the same):

```python
def _save_script_results(
    job: Any,
    result: Any,
    version_number: int = 1,
    change_summary: str = "Agent v1 — auto-saved from pipeline",
) -> None:
    from reelforge.ai.schemas.script import ScriptAgentOutput

    output: ScriptAgentOutput = result.output

    seo = output.seo_metadata
    # ... rest of function unchanged (broll, sections, hooks, etc.)
```

Remove the `isinstance` / `model_validate_json` fallback block.

- [ ] **Step 5: Run lint + type check**

```bash
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run ruff check . --unsafe-fixes && uv run mypy reelforge/ai/agents/script.py reelforge/pipeline/tasks.py
```

- [ ] **Step 6: Commit Task 3**

```bash
git add reelforge/ai/agents/script.py reelforge/pipeline/tasks.py
git commit -m "feat(ai): add PydanticAI ScriptAgent and _seo_agent, update script tasks"
```

---

## Task 4: VisualPlannerAgent

**Files:**
- Create: `reelforge/ai/agents/visual_planner.py`
- Modify: `reelforge/pipeline/tasks.py` (lines 304–473)

- [ ] **Step 1: Create `reelforge/ai/agents/visual_planner.py`**

```python
from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai import RunContext

from reelforge.ai.deps import VisualPlannerDeps
from reelforge.ai.prompts.visual_planner import VISUAL_PLANNER_INSTRUCTIONS
from reelforge.ai.schemas.visual import VisualPlannerOutput

_TARGET_SEG_DURATION = 6.0
_SECTION_CONTENT_PREVIEW_CHARS = 300

visual_planner_agent: Agent[VisualPlannerDeps, VisualPlannerOutput] = Agent(
    deps_type=VisualPlannerDeps,
    output_type=VisualPlannerOutput,
)


def _build_section_context(
    sections: list[dict],
    broll_suggestions: list[dict],
    total_duration_seconds: float,
) -> tuple[str, int]:
    """Return (section_context_string, total_segments_needed)."""
    raw_durations = [float(s.get("estimated_duration_seconds", 8)) for s in sections]
    raw_total = sum(raw_durations)
    section_timing: list[dict] = []
    cursor = 0.0
    for i, section in enumerate(sections):
        weight = raw_durations[i] / raw_total if raw_total > 0 else 1 / len(sections)
        duration = round(weight * total_duration_seconds, 2)
        section_timing.append({
            "index": i,
            "tag": section.get("tag", f"SECTION_{i + 1}"),
            "content": section.get("content", ""),
            "start_seconds": round(cursor, 2),
            "end_seconds": round(cursor + duration, 2),
            "duration_seconds": round(duration, 2),
        })
        cursor += duration
    if section_timing:
        section_timing[-1]["end_seconds"] = total_duration_seconds
        section_timing[-1]["duration_seconds"] = round(
            total_duration_seconds - section_timing[-1]["start_seconds"], 2
        )

    broll_by_section: dict[str, dict] = {}
    for broll in broll_suggestions:
        section_key = broll.get("section", "")
        if section_key and section_key not in broll_by_section:
            broll_by_section[section_key] = broll
    for i, broll in enumerate(broll_suggestions):
        if i < len(section_timing):
            tag = section_timing[i]["tag"]
            if tag not in broll_by_section:
                broll_by_section[tag] = broll

    segment_targets: list[dict] = []
    for st in section_timing:
        n_segments = max(1, round(st["duration_seconds"] / _TARGET_SEG_DURATION))
        actual_seg_duration = round(st["duration_seconds"] / n_segments, 2)
        style = broll_by_section.get(st["tag"], {})
        segment_targets.append({
            **st,
            "n_segments": n_segments,
            "target_seg_duration": actual_seg_duration,
            "style_preset": style.get("style_preset", "cinematic_realism"),
            "colour_palette": style.get("colour_palette", ["#0A0A0A", "#FFFFFF"]),
            "mood": style.get("mood", "curious"),
            "style_description": style.get("description", ""),
            "style_subject": style.get("subject", ""),
            "style_lighting": style.get("lighting", "natural light"),
        })

    total_segments_needed = sum(t["n_segments"] for t in segment_targets)
    section_context_lines = []
    for t in segment_targets:
        content_preview = t["content"][:_SECTION_CONTENT_PREVIEW_CHARS]
        if len(t["content"]) > _SECTION_CONTENT_PREVIEW_CHARS:
            content_preview += "..."
        section_context_lines.append(
            f"SECTION: [{t['tag']}]\n"
            f"  Time window    : {t['start_seconds']}s → {t['end_seconds']}s ({t['duration_seconds']}s)\n"
            f"  Segments needed: {t['n_segments']} segments × ~{t['target_seg_duration']}s each\n"
            f"  Narration text : {content_preview}\n"
            f"  Style preset   : {t['style_preset']}\n"
            f"  Colour palette : {', '.join(t['colour_palette'])}\n"
            f"  Mood           : {t['mood']}\n"
            f"  Style anchor   : {t['style_description']}\n"
            f"  Subject anchor : {t['style_subject']}\n"
            f"  Lighting anchor: {t['style_lighting']}"
        )
    section_context = "\n\n".join(section_context_lines)
    section_context = section_context.replace("{", "{{").replace("}", "}}")
    return section_context, total_segments_needed


@visual_planner_agent.system_prompt
def build_visual_planner_system_prompt(ctx: RunContext[VisualPlannerDeps]) -> str:
    deps = ctx.deps
    if not deps.sections:
        msg = "sections must be non-empty — cannot build a visual timeline without script sections"
        raise ValueError(msg)

    section_context, total_segments_needed = _build_section_context(
        deps.sections, deps.broll_suggestions, deps.total_duration_seconds
    )

    return VISUAL_PLANNER_INSTRUCTIONS.format(
        narrative_mode=deps.narrative_mode,
        channel_tone=deps.channel_tone,
        total_duration_seconds=deps.total_duration_seconds,
        total_sections=len(deps.sections),
        total_segments_needed=total_segments_needed,
        section_context=section_context,
    )
```

- [ ] **Step 2: Update `run_scene_breakdown_job` in `reelforge/pipeline/tasks.py`**

Replace the inner block from `from agents import Runner` through `planner_output = result.final_output` (lines 336–380):

```python
    try:
        from reelforge.ai.agents.visual_planner import visual_planner_agent
        from reelforge.ai.deps import VisualPlannerDeps
        from reelforge.ai.schemas.visual import VisualPlannerOutput  # noqa: TC001

        sections = job.script_job.sections or []
        broll_suggestions = job.script_job.broll_suggestions or []

        total_duration_seconds: float = float(job.script_job.estimated_duration_mins or 0) * 60.0
        if not total_duration_seconds:
            word_count = job.script_job.word_count or len(
                (job.script_job.script_text or "").split()
            )
            total_duration_seconds = (word_count / 130.0) * 60.0
        _MIN_DURATION_SECONDS = 30  # noqa: N806
        if total_duration_seconds < _MIN_DURATION_SECONDS:
            msg = (
                f"total_duration_seconds={total_duration_seconds:.1f} is suspiciously short. "
                "Check estimated_duration_mins or script word count."
            )
            raise ValueError(msg)  # noqa: TRY301

        channel = job.script_job.topic.channel
        narrative_mode: str = getattr(job.script_job, "narrative_mode", "") or "REVEAL"

        logger.info(
            "VisualPlannerAgent: planning timeline",
            extra={
                "scene_breakdown_job_id": scene_breakdown_job_id,
                "total_duration_seconds": total_duration_seconds,
                "sections": len(sections),
                "broll_suggestions": len(broll_suggestions),
            },
        )

        result = visual_planner_agent.run_sync(
            "Generate the complete visual timeline.",
            model=settings.VISUAL_PLANNER_MODEL,
            deps=VisualPlannerDeps(
                sections=sections,
                broll_suggestions=broll_suggestions,
                total_duration_seconds=total_duration_seconds,
                channel_tone=channel.content_tone or "informative",
                narrative_mode=narrative_mode,
            ),
        )
        planner_output: VisualPlannerOutput = result.output
```

Also update `job.breakdown_provider = "gpt-5.2"` (line 409) to:
```python
job.breakdown_provider = settings.VISUAL_PLANNER_MODEL
```

- [ ] **Step 3: Run lint + type check**

```bash
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run ruff check . --unsafe-fixes && uv run mypy reelforge/ai/agents/visual_planner.py reelforge/pipeline/tasks.py
```

- [ ] **Step 4: Commit Task 4**

```bash
git add reelforge/ai/agents/visual_planner.py reelforge/pipeline/tasks.py
git commit -m "feat(ai): add PydanticAI VisualPlannerAgent, update run_scene_breakdown_job"
```

---

## Task 5: Non-agent LLM usages (Clipping + Captions)

**Files:**
- Create: `reelforge/ai/agents/clip_analysis.py`, `reelforge/ai/agents/translation.py`
- Modify: `reelforge/clipping/services.py`, `reelforge/services/media/render_stages/captions.py`

- [ ] **Step 1: Create `reelforge/ai/agents/clip_analysis.py`**

```python
from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import Agent


class ClipSuggestion(BaseModel):
    start_sec: float
    end_sec: float
    title: str = ""
    hook_text: str = ""
    caption_template: str = ""
    relevance_score: float = 0.0
    reason: str = ""


class ClipAnalysisOutput(BaseModel):
    clips: list[ClipSuggestion]


clip_analysis_agent: Agent[None, ClipAnalysisOutput] = Agent(
    output_type=ClipAnalysisOutput,
)
```

- [ ] **Step 2: Update `reelforge/clipping/services.py`**

Replace the entire file:

```python
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import Any

from django.conf import settings

from reelforge.ai.agents.clip_analysis import ClipAnalysisOutput
from reelforge.ai.agents.clip_analysis import clip_analysis_agent
from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob

logger = logging.getLogger("reelforge.clipping")
_SIX_PLACES = Decimal("0.000001")

_GPT4O_INPUT_COST_PER_M = Decimal("2.50")
_GPT4O_OUTPUT_COST_PER_M = Decimal("10.00")


class ClipAnalysisService:
    def __init__(self, clipping_job: ClippingJob) -> None:
        self.job = clipping_job

    def analyze(
        self,
        enriched_transcript: list[dict] | None = None,
        diarization: dict | None = None,
    ) -> list[ClipCandidate]:
        transcript = self.job.transcript_text
        user_prompt = self._build_prompt(transcript, enriched_transcript=enriched_transcript, diarization=diarization)
        system = self._system_prompt()

        result = clip_analysis_agent.run_sync(
            user_prompt,
            model=settings.CLIP_ANALYSIS_MODEL,
            model_settings={"system": system},
        )
        output: ClipAnalysisOutput = result.output

        usage = result.usage()
        total_input = usage.request_tokens or 0
        total_output = usage.response_tokens or 0
        cost_usd = (
            Decimal(str(total_input)) * _GPT4O_INPUT_COST_PER_M / Decimal(1000000)
            + Decimal(str(total_output)) * _GPT4O_OUTPUT_COST_PER_M / Decimal(1000000)
        ).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)

        candidates: list[ClipCandidate] = []
        for clip_data in output.clips[: self.job.clips_requested]:
            excerpt = self._extract_transcript_excerpt(
                start_sec=clip_data.start_sec,
                end_sec=clip_data.end_sec,
            )
            candidate = ClipCandidate(
                clipping_job=self.job,
                start_sec=clip_data.start_sec,
                end_sec=clip_data.end_sec,
                title=clip_data.title,
                hook_text=clip_data.hook_text,
                caption_template=clip_data.caption_template,
                relevance_score=clip_data.relevance_score,
                reason=clip_data.reason,
                transcript_excerpt=excerpt,
            )
            try:
                candidate.save()
                candidates.append(candidate)
            except Exception as exc:
                logger.warning(
                    "Skipping invalid clip candidate",
                    extra={
                        "clipping_job_id": str(self.job.id),
                        "start_sec": clip_data.start_sec,
                        "end_sec": clip_data.end_sec,
                        "error": str(exc),
                    },
                )

        self.job.analysis_cost_usd = cost_usd
        self.job.analysis_provider = settings.CLIP_ANALYSIS_MODEL
        self.job.save(update_fields=["analysis_cost_usd", "analysis_provider", "updated_at"])

        logger.info(
            "Clip analysis completed",
            extra={
                "clipping_job_id": str(self.job.id),
                "candidates_created": len(candidates),
                "clips_requested": self.job.clips_requested,
            },
        )
        return candidates

    def _extract_transcript_excerpt(self, start_sec: float, end_sec: float) -> str:
        segments = self.job.transcript_json.get("segments", [])
        words: list[str] = []
        for segment in segments:
            for word_data in segment.get("words", []):
                word_start = float(word_data.get("start", 0))
                word_end = float(word_data.get("end", 0))
                if word_start >= start_sec and word_end <= end_sec:
                    words.append(word_data.get("word", "").strip())
        return " ".join(words)

    def _build_prompt(
        self,
        transcript: str,
        enriched_transcript: list[dict] | None = None,
        diarization: dict | None = None,
    ) -> str:
        lines = [
            f"Source video transcript:\n{transcript}\n",
            f"Number of clips to identify: {self.job.clips_requested}",
        ]
        if diarization and diarization.get("segments"):
            speaker_count = len({s["speaker_id"] for s in diarization["segments"]})
            lines.append(f"\nThis video has {speaker_count} speaker(s).")
        lines.append(
            "\nIdentify the most engaging segments and return them as the clips array."
        )
        return "\n".join(lines)

    def _system_prompt(self) -> str:
        platform = self.job.social_account.platform
        account_name = self.job.social_account.handle or self.job.social_account.display_name
        return (
            f"You are an expert video editor specialising in short-form content for {platform}. "
            f"You are working on clips for the account @{account_name}. "
            "Identify the most engaging segments that will perform well on this platform."
        )
```

Note: PydanticAI's structured output removes the need for manual JSON parsing and markdown fence stripping.

- [ ] **Step 3: Create `reelforge/ai/agents/translation.py`**

```python
from __future__ import annotations

from pydantic_ai import Agent

caption_translation_agent: Agent[None, str] = Agent()
```

The agent returns a raw string — the caller parses it as JSON. No structured output type here since the shape of the translated Whisper JSON is complex and variable.

- [ ] **Step 4: Update `reelforge/services/media/render_stages/captions.py`**

Replace the section at lines 197–215 (the translation block inside the `_translate_transcript` method):

```python
        from django.conf import settings

        from reelforge.ai.agents.translation import caption_translation_agent

        llm_response = caption_translation_agent.run_sync(
            (
                f"Translate the following Whisper transcript JSON to {target_lang}. "
                "Preserve the exact JSON structure, keys, and timestamps. "
                "Only translate the 'text' and 'word' string values. "
                "Return only valid JSON with no commentary.\n\n"
                f"{self.transcript_json}"
            ),
            model=settings.CAPTION_TRANSLATION_MODEL,
            model_settings={"system": "You are a professional translator."},
        )

        try:
            translated = json.loads(llm_response.output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON for translation: {exc}") from exc
```

Remove the old `from reelforge.services.providers.registry import get_llm_provider` import (line 197) and `llm = get_llm_provider(self.channel)` (line 199).

- [ ] **Step 5: Run lint + type check**

```bash
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run ruff check . --unsafe-fixes && uv run mypy reelforge/ai/agents/clip_analysis.py reelforge/ai/agents/translation.py reelforge/clipping/services.py reelforge/services/media/render_stages/captions.py
```

- [ ] **Step 6: Commit Task 5**

```bash
git add reelforge/ai/agents/clip_analysis.py reelforge/ai/agents/translation.py \
  reelforge/clipping/services.py reelforge/services/media/render_stages/captions.py
git commit -m "feat(ai): migrate clip analysis and caption translation to PydanticAI"
```

---

## Task 6: Cleanup

**Files:**
- Delete: `reelforge/agents/`, `reelforge/services/providers/llm/`
- Modify: `reelforge/services/dataclass.py`, and verify no dead imports remain

- [ ] **Step 1: Verify no remaining imports of deleted modules**

```bash
grep -r "from reelforge.agents" reelforge/ --include="*.py" -l | grep -v __pycache__
grep -r "from agents import\|import agents" reelforge/ --include="*.py" | grep -v __pycache__
grep -r "dependency_injector\|Provide\[" reelforge/ --include="*.py" | grep -v __pycache__
grep -r "from reelforge.services.providers.llm" reelforge/ --include="*.py" | grep -v __pycache__
grep -r "get_llm_provider\|BaseLLMProvider\|ClaudeProvider\|OpenAIProvider" reelforge/ --include="*.py" | grep -v __pycache__
```

Expected output: empty for all commands. If any files still reference these, update them before deleting.

- [ ] **Step 2: Delete `reelforge/agents/` directory**

```bash
rm -rf reelforge/agents/
```

- [ ] **Step 3: Delete `reelforge/services/providers/llm/` directory**

```bash
rm -rf reelforge/services/providers/llm/
```

- [ ] **Step 4: Remove `LLMResponse` from `reelforge/services/dataclass.py`**

Open `reelforge/services/dataclass.py` and delete the `LLMResponse` dataclass. Verify nothing imports it:

```bash
grep -r "LLMResponse" reelforge/ --include="*.py" | grep -v __pycache__
```

Expected: empty. Then remove:

```python
@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    raw: Any = None
```

- [ ] **Step 5: Run full lint + type check**

```bash
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run ruff check . --unsafe-fixes && uv run ruff format . && uv run mypy reelforge
```

Expected: zero errors. Fix all errors before committing.

- [ ] **Step 6: Run tests**

```bash
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run pytest -x -q
```

Expected: all existing tests pass (agent tests are out of scope for this refactor).

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "chore(ai): delete legacy agents/ and services/providers/llm/ — PydanticAI migration complete"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task covering it |
|---|---|
| `reelforge/ai/` app skeleton | Task 1 |
| Remove `ClaudeProvider`/`OpenAIProvider` | Tasks 1 + 6 |
| Remove `BaseLLMProvider` | Task 1 Step 20 |
| Remove `get_llm_provider()` | Task 1 Step 19 |
| Remove `dependency-injector` container | Tasks 1 + 6 |
| Remove `openai-agents`/`anthropic` packages | Task 1 Step 1 |
| Add `pydantic-ai` | Task 1 Step 1 |
| Per-agent model settings (RESEARCH_AGENT_MODEL etc.) | Task 1 Step 17 |
| Model passed at `.run_sync()` call time | Tasks 2–5 |
| `ResearchDeps` / `ScriptDeps` / `VisualPlannerDeps` dataclasses | Task 1 Step 16 |
| Schemas moved to `ai/schemas/` | Task 1 Steps 4–6 |
| Prompts moved to `ai/prompts/` | Task 1 Steps 7–8 |
| Provider implementations moved to `ai/providers/` | Task 1 Steps 9–12 |
| Lazy singleton getters for SerpAPI/Tavily | Task 1 Steps 14–15 |
| ResearchAgent with 6 tools via `@research_agent.tool` | Task 2 Step 1 |
| `run_research_job` updated | Task 2 Step 2 |
| `_save_research_results` uses `result.output` + `result.usage()` | Task 2 Step 3 |
| ScriptAgent with `_seo_agent` sub-agent | Task 3 Step 1 |
| `run_script_job` + `run_script_revision_job` updated | Task 3 Steps 2–3 |
| VisualPlannerAgent — preprocessing in `@agent.system_prompt` | Task 4 Step 1 |
| `run_scene_breakdown_job` updated | Task 4 Step 2 |
| `ClipAnalysisService` migrated | Task 5 Steps 1–2 |
| Caption translation migrated | Task 5 Steps 3–4 |
| `CLIP_ANALYSIS_MODEL` + `CAPTION_TRANSLATION_MODEL` settings | Task 1 Step 17 |
| Registry non-LLM providers use lazy singletons | Task 1 Step 19 |
| `reelforge/agents/` deleted | Task 6 Step 2 |
| `services/providers/llm/` deleted | Task 6 Step 3 |
| `LLMResponse` dataclass removed | Task 6 Step 4 |

**No gaps found.**

**Type consistency check:**
- `ResearchDeps.channel` referenced in `research_agent.py` and `run_research_job` — consistent
- `ScriptDeps.channel` + `.topic` referenced in `script_agent.py` and `run_script_job` — consistent
- `VisualPlannerDeps` fields built in `run_scene_breakdown_job`, consumed in `visual_planner_agent.py` — consistent
- `result.output` used in all tasks (not `result.final_output`) — consistent
- `result.usage()` returning `.request_tokens` / `.response_tokens` — consistent across tasks 2, 3, 5

**No placeholder patterns found.**
