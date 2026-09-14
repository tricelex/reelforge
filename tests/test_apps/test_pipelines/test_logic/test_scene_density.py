"""Tests for scene density helpers (coverage, stitch, hero clamp, settings)."""

from server.apps.pipelines.logic.scene_density import (
    COVERAGE_RATIO_MAX,
    COVERAGE_RATIO_MIN,
    MAX_SETTING_ANCHORS,
    chapter_word_count,
    clamp_hero_flags,
    coverage_limits,
    coverage_ok,
    density_bounds,
    is_stage_direction,
    normalize_setting,
    select_anchor_settings,
    stitch_global_idx,
)


def test_density_bounds_invalid_values_fall_back() -> None:
    """Non-numeric config values use documentary defaults."""
    min_w, max_w, min_s, max_s = density_bounds({
        'min_words': 'nope',
        'max_words': None,
        'min_seconds': 'x',
        'max_seconds': object(),
    })
    assert (min_w, max_w, min_s, max_s) == (10, 35, 6.0, 12.0)


def test_max_hero_scenes_none_when_unset() -> None:
    """Documentary graphs omit the cap and must not clamp."""
    from server.apps.pipelines.logic.scene_density import max_hero_scenes

    assert max_hero_scenes({}) is None
    assert max_hero_scenes({'max_hero_scenes': 0}) == 0
    assert max_hero_scenes({'max_hero_scenes': 6}) == 6


def test_density_bounds_default_to_documentary_range() -> None:
    """Unset config keeps the original 10-35 word / 6-12s envelope."""
    min_w, max_w, min_s, max_s = density_bounds({})
    assert min_w == 10
    assert max_w == 35
    assert min_s == 6.0
    assert max_s == 12.0


def test_density_bounds_read_ai_longform_config() -> None:
    """Blueprint config tightens words and seconds for denser stills."""
    min_w, max_w, min_s, max_s = density_bounds({
        'min_words': 8,
        'max_words': 16,
        'min_seconds': 3,
        'max_seconds': 5,
    })
    assert (min_w, max_w, min_s, max_s) == (8, 16, 3.0, 5.0)


def test_coverage_ok_accepts_ratio_inside_band() -> None:
    """Scene word sum within 95-110% of the chapter is covered."""
    assert coverage_ok(95, 100) is True
    assert coverage_ok(110, 100) is True
    assert coverage_ok(94, 100) is False
    assert coverage_ok(111, 100) is False


def test_coverage_ok_empty_chapter_requires_empty_scenes() -> None:
    """A zero-word chapter is covered only by zero scene words."""
    assert coverage_ok(0, 0) is True
    assert coverage_ok(10, 0) is False


def test_chapter_word_count_splits_on_whitespace() -> None:
    """Word budget matches alignment's split() counting."""
    assert chapter_word_count('Rome was great once.') == 4


def test_is_stage_direction_true_for_whole_bracket_span() -> None:
    """A single bracket pair wrapping the entire text is a stage direction."""
    assert is_stage_direction('[Ambient pause. No narration.]') is True


def test_is_stage_direction_false_for_real_narration() -> None:
    """Plain narration with no brackets is not a stage direction."""
    assert is_stage_direction('Rome was great once.') is False


def test_is_stage_direction_false_for_embedded_tag() -> None:
    """A short tag inside otherwise-normal narration is not a stage direction."""
    assert is_stage_direction('[sighs] Rome was great once.') is False


def test_chapter_word_count_whole_chapter_stage_direction_is_zero() -> None:
    """A chapter that is entirely one bracketed stage direction has no narration to cover."""
    text = (
        '[Ambient pause. No narration. Soft water sounds continue, '
        'then thin into spacious room tone.]'
    )
    assert chapter_word_count(text) == 0


def test_chapter_word_count_embedded_tag_counts_normally() -> None:
    """A tag embedded in real narration still counts as narration words."""
    assert chapter_word_count('[sighs] Rome was great once.') == 5


def test_chapter_word_count_tags_at_both_ends_count_normally() -> None:
    """Multiple bracket spans around real narration are not a stage direction."""
    text = '[whispers] Real content here [exhales]'
    assert chapter_word_count(text) == len(text.split())


def test_stitch_global_idx_renumbers_across_chapters() -> None:
    """Per-chapter scene lists become one globally indexed list."""
    chapters = [
        [{'idx': 0, 'chapter_idx': 0, 'beat': 'a'}],
        [
            {'idx': 0, 'chapter_idx': 1, 'beat': 'b'},
            {'idx': 1, 'chapter_idx': 1, 'beat': 'c'},
        ],
    ]
    stitched = stitch_global_idx(chapters)
    assert [s['idx'] for s in stitched] == [0, 1, 2]
    assert [s['chapter_idx'] for s in stitched] == [0, 1, 1]
    assert [s['beat'] for s in stitched] == ['a', 'b', 'c']


def test_clamp_hero_flags_keeps_first_n_heroes() -> None:
    """Later hero flags drop once the cap is reached."""
    scenes = [
        {'idx': 0, 'is_hero': True},
        {'idx': 1, 'is_hero': True},
        {'idx': 2, 'is_hero': False},
        {'idx': 3, 'is_hero': True},
    ]
    clamped = clamp_hero_flags(scenes, max_hero_scenes=2)
    assert [s['is_hero'] for s in clamped] == [True, True, False, False]


def test_clamp_hero_flags_zero_clears_all() -> None:
    """max_hero_scenes=0 means Ken Burns only."""
    scenes = [{'idx': 0, 'is_hero': True}]
    clamped = clamp_hero_flags(scenes, max_hero_scenes=0)
    assert clamped[0]['is_hero'] is False


def test_normalize_setting_collapses_case_and_space() -> None:
    """Setting keys match even when the LLM varies casing."""
    assert normalize_setting('  Ancient Rome  ') == 'ancient rome'


def test_select_anchor_settings_caps_first_seen() -> None:
    """Only the first N unique settings become establishing-shot keys."""
    scenes = [
        {'setting': 'Rome forum'},
        {'setting': 'rome forum'},
        {'setting': 'Senate chamber'},
        {'setting': 'Harbor'},
    ]
    keys = select_anchor_settings(scenes, max_anchors=2)
    assert keys == ['rome forum', 'senate chamber']
    assert len(keys) <= MAX_SETTING_ANCHORS


def test_coverage_limits_default_and_override() -> None:
    """Coverage band is configurable; invalid values fall back."""
    assert coverage_limits({}) == (COVERAGE_RATIO_MIN, COVERAGE_RATIO_MAX)
    assert coverage_limits({
        'coverage_ratio_min': 0.8,
        'coverage_ratio_max': 1.2,
    }) == (0.8, 1.2)
    low, high = coverage_limits({
        'coverage_ratio_min': 'nope',
        'coverage_ratio_max': None,
    })
    assert (low, high) == (COVERAGE_RATIO_MIN, COVERAGE_RATIO_MAX)


def test_select_anchor_settings_skips_blank_and_zero_cap() -> None:
    """Empty settings are ignored; a zero cap yields no keys."""
    scenes = [
        {'setting': ''},
        {'setting': '   '},
        {'setting': 'Harbor'},
    ]
    assert select_anchor_settings(scenes, max_anchors=0) == []
    assert select_anchor_settings(scenes) == ['harbor']


def test_max_hero_scenes_invalid_present_value_falls_back() -> None:
    """A present but unreadable cap still clamps, using the default."""
    from server.apps.pipelines.logic.scene_density import (
        DEFAULT_MAX_HERO_SCENES,
        max_hero_scenes,
    )

    assert max_hero_scenes({'max_hero_scenes': 'nope'}) == (
        DEFAULT_MAX_HERO_SCENES
    )
    assert max_hero_scenes({'max_hero_scenes': -3}) == 0
