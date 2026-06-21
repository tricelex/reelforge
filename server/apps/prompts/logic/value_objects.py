"""API DTOs for prompts and story formats."""

import msgspec

from server.apps.generation.logic.constants import DEFAULT_LLM_MODEL

JsonScalar = str | int | float | bool | None
JsonObject = dict[str, JsonScalar | list[str]]


class PromptTemplateSummaryPayload(msgspec.Struct, frozen=True):
    """Lightweight prompt template row."""

    id: str
    name: str
    key: str
    scope: str
    description: str
    active_version: int | None


class PromptTemplateDetailPayload(msgspec.Struct, frozen=True):
    """Full prompt template with active version metadata."""

    id: str
    name: str
    key: str
    scope: str
    description: str
    active_version: int | None


class PromptTemplateCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a prompt template."""

    name: str
    key: str
    scope: str
    description: str = ''


class PromptTemplatePatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a prompt template."""

    name: str | None = None
    scope: str | None = None
    description: str | None = None


class PromptTemplateListPayload(msgspec.Struct, frozen=True):
    """List of prompt templates."""

    items: list[PromptTemplateSummaryPayload]
    next_cursor: str | None
    total: int


class PromptVersionPayload(msgspec.Struct, frozen=True):
    """One prompt version."""

    id: str
    template_id: str
    version: int
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float
    max_tokens: int
    is_active: bool


class PromptVersionCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a new prompt version."""

    system_prompt: str
    user_prompt: str
    model: str = DEFAULT_LLM_MODEL
    temperature: float = 1.0
    max_tokens: int = 8192


class PromptVersionListPayload(msgspec.Struct, frozen=True):
    """Versions for one template."""

    items: list[PromptVersionPayload]
    total: int


class StoryFormatPayload(msgspec.Struct, frozen=True):
    """Story format configuration."""

    id: str
    key: str
    name: str
    fiction: bool
    narration_pov: str
    beats: list[JsonObject]
    pacing: JsonObject
    prompt_overrides: JsonObject
    music_mood_map: JsonObject
    is_active: bool


class StoryFormatCreatePayload(msgspec.Struct, frozen=True):
    """Input for creating a story format."""

    key: str
    name: str
    fiction: bool = False
    narration_pov: str = 'narrator'
    beats: list[JsonObject] | None = None
    pacing: JsonObject | None = None
    prompt_overrides: JsonObject | None = None
    music_mood_map: JsonObject | None = None


class StoryFormatPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a story format."""

    name: str | None = None
    fiction: bool | None = None
    narration_pov: str | None = None
    beats: list[JsonObject] | None = None
    pacing: JsonObject | None = None
    prompt_overrides: JsonObject | None = None
    music_mood_map: JsonObject | None = None
    is_active: bool | None = None


class StoryFormatListPayload(msgspec.Struct, frozen=True):
    """List of story formats."""

    items: list[StoryFormatPayload]
    next_cursor: str | None
    total: int
