"""Blueprint profiles — map a blueprint to its visual stage roles.

A blueprint graph may declare ``profile`` to select which registered stages
play each visual role. Absent, it resolves to ``ai_visual`` so existing
blueprints behave exactly as they did before profiles existed.

>>> resolve_role({'stages': []}, SEGMENT_STAGE)
'motion'
>>> snapshot = {'stages': [], 'profile': 'documentary_footage'}
>>> resolve_role(snapshot, SEGMENT_STAGE)
'footage_prep'
"""

from collections.abc import Mapping
from typing import Any, Final, final

import attrs

PROMPT_STAGE: Final = 'prompt_stage'
SOURCE_STAGE: Final = 'source_stage'
SEGMENT_STAGE: Final = 'segment_stage'

_ROLE_NAMES: Final = frozenset({PROMPT_STAGE, SOURCE_STAGE, SEGMENT_STAGE})

DEFAULT_PROFILE_KEY: Final = 'ai_visual'


@final
@attrs.define(slots=True, frozen=True)
class BlueprintProfile:
    """Maps visual role names to the stage keys that implement them."""

    key: str
    roles: Mapping[str, str]


AI_VISUAL: Final = BlueprintProfile(
    key='ai_visual',
    roles={
        PROMPT_STAGE: 'visual_prompts',
        SOURCE_STAGE: 'image_gen',
        SEGMENT_STAGE: 'motion',
    },
)

DOCUMENTARY_FOOTAGE: Final = BlueprintProfile(
    key='documentary_footage',
    roles={
        PROMPT_STAGE: 'footage_queries',
        SOURCE_STAGE: 'footage_search',
        SEGMENT_STAGE: 'footage_prep',
    },
)

PROFILE_REGISTRY: Final[dict[str, BlueprintProfile]] = {
    AI_VISUAL.key: AI_VISUAL,
    DOCUMENTARY_FOOTAGE.key: DOCUMENTARY_FOOTAGE,
}


def resolve_profile_key(blueprint_snapshot: dict[str, Any]) -> str:
    """Return the profile key for a graph, defaulting to ``ai_visual``."""
    key = blueprint_snapshot.get('profile') or DEFAULT_PROFILE_KEY
    return str(key) if str(key) in PROFILE_REGISTRY else DEFAULT_PROFILE_KEY


def resolve_role(blueprint_snapshot: dict[str, Any], role: str) -> str:
    """Return the stage key playing ``role`` for this blueprint.

    Raises:
        KeyError: If ``role`` is not a known visual role name.
    """
    if role not in _ROLE_NAMES:
        msg = f'Unknown blueprint role: {role}'
        raise KeyError(msg)
    overrides = blueprint_snapshot.get('roles') or {}
    override = overrides.get(role) if isinstance(overrides, dict) else None
    if override:
        return str(override)
    profile = PROFILE_REGISTRY[resolve_profile_key(blueprint_snapshot)]
    return profile.roles[role]
