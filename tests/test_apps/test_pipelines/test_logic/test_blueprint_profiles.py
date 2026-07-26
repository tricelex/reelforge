"""Tests for blueprint profile role resolution."""

import pytest

from server.apps.pipelines.logic.blueprint_profiles import (
    PROFILE_REGISTRY,
    PROMPT_STAGE,
    SEGMENT_STAGE,
    SOURCE_STAGE,
    resolve_profile_key,
    resolve_role,
)


def test_absent_profile_defaults_to_ai_visual() -> None:
    """A graph with no profile key behaves exactly as it does today."""
    snapshot: dict[str, object] = {'stages': []}
    assert resolve_profile_key(snapshot) == 'ai_visual'
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'motion'
    assert resolve_role(snapshot, SOURCE_STAGE) == 'image_gen'
    assert resolve_role(snapshot, PROMPT_STAGE) == 'visual_prompts'


def test_documentary_profile_resolves_footage_stages() -> None:
    """The documentary profile maps roles to the footage stages."""
    snapshot = {'stages': [], 'profile': 'documentary_footage'}
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'footage_prep'
    assert resolve_role(snapshot, SOURCE_STAGE) == 'footage_search'
    assert resolve_role(snapshot, PROMPT_STAGE) == 'footage_queries'


def test_unknown_profile_falls_back_to_ai_visual() -> None:
    """An unregistered profile name must not crash a running pipeline."""
    snapshot = {'stages': [], 'profile': 'not_a_real_profile'}
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'motion'


def test_explicit_roles_override_the_profile() -> None:
    """A graph may override one role without defining a new profile."""
    snapshot = {
        'stages': [],
        'profile': 'documentary_footage',
        'roles': {'segment_stage': 'custom_segment'},
    }
    assert resolve_role(snapshot, SEGMENT_STAGE) == 'custom_segment'
    assert resolve_role(snapshot, SOURCE_STAGE) == 'footage_search'


def test_unknown_role_raises() -> None:
    """An unknown role name is a programming error, not a runtime fallback."""
    with pytest.raises(KeyError):
        resolve_role({'stages': []}, 'nonexistent_role')


def test_registry_contains_both_profiles() -> None:
    """Both shipped profiles are registered under their key."""
    assert set(PROFILE_REGISTRY) == {'ai_visual', 'documentary_footage'}
    for key, profile in PROFILE_REGISTRY.items():
        assert profile.key == key
