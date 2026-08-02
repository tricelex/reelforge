"""Tests for editor-handoff pure helpers (timecodes, SRT, EDL, detection)."""

import pytest

from server.apps.pipelines.logic.editor_handoff import (
    build_edl_markers,
    build_srt,
    fmt_srt_time,
    fmt_timecode,
    is_clipping_run,
    is_editor_handoff_blueprint,
)


class TestFmtTimecode:
    """Tests for fmt_timecode."""

    def test_zero_seconds(self) -> None:
        """Zero seconds formats as the zero timecode."""
        assert fmt_timecode(0.0) == '00:00:00:00'

    def test_one_hour_at_default_fps(self) -> None:
        """One hour rolls over into the hours field."""
        assert fmt_timecode(3600.0) == '01:00:00:00'

    def test_fractional_seconds_round_to_nearest_frame(self) -> None:
        """Fractional seconds round to the nearest whole frame."""
        # 1.5s @ 24fps = 36 frames = 1s + 12 frames.
        assert fmt_timecode(1.5, fps=24.0) == '00:00:01:12'

    def test_custom_fps(self) -> None:
        """A non-default fps changes the frame component only."""
        assert fmt_timecode(1.0, fps=30.0) == '00:00:01:00'

    def test_negative_seconds_raises(self) -> None:
        """Negative seconds violate the precondition assertion."""
        with pytest.raises(AssertionError):
            fmt_timecode(-1.0)

    def test_zero_fps_raises(self) -> None:
        """A zero fps violates the precondition assertion."""
        with pytest.raises(AssertionError):
            fmt_timecode(1.0, fps=0.0)


class TestFmtSrtTime:
    """Tests for fmt_srt_time."""

    def test_zero(self) -> None:
        """Zero seconds formats as the zero SRT timestamp."""
        assert fmt_srt_time(0.0) == '00:00:00,000'

    def test_sub_second(self) -> None:
        """Sub-second precision is preserved in the milliseconds field."""
        assert fmt_srt_time(1.234) == '00:00:01,234'

    def test_negative_clamped_to_zero(self) -> None:
        """Negative input is clamped to zero instead of raising."""
        assert fmt_srt_time(-5.0) == '00:00:00,000'

    def test_rounding_overflow_carries_into_seconds(self) -> None:
        """Rounding overflow carries into the seconds field."""
        # 1.9996s rounds to 2000ms, not an invalid 4-digit ms field.
        assert fmt_srt_time(1.9996) == '00:00:02,000'


class TestBuildSrt:
    """Tests for build_srt."""

    def test_single_segment(self) -> None:
        """A single segment renders one numbered SRT block."""
        segments = [{'start': 0.0, 'end': 1.5, 'text': 'Hello world'}]
        srt = build_srt(segments)
        assert srt == (b'1\n00:00:00,000 --> 00:00:01,500\nHello world')

    def test_multiple_segments_are_numbered_and_blank_line_separated(
        self,
    ) -> None:
        """Multiple segments are numbered and blank-line separated."""
        segments = [
            {'start': 0.0, 'end': 1.0, 'text': 'One'},
            {'start': 1.0, 'end': 2.0, 'text': 'Two'},
        ]
        srt = build_srt(segments).decode()
        blocks = srt.split('\n\n')
        assert len(blocks) == 2
        assert blocks[0].startswith('1\n')
        assert blocks[1].startswith('2\n')
        assert 'One' in blocks[0]
        assert 'Two' in blocks[1]

    def test_empty_segments_returns_empty_bytes(self) -> None:
        """An empty segment list returns empty bytes."""
        assert build_srt([]) == b''

    def test_blank_text_segments_are_skipped(self) -> None:
        """Segments with blank/whitespace-only text are skipped."""
        segments = [
            {'start': 0.0, 'end': 1.0, 'text': '   '},
            {'start': 1.0, 'end': 2.0, 'text': 'Real text'},
        ]
        srt = build_srt(segments).decode()
        assert 'Real text' in srt
        assert srt.count('-->') == 1


class TestBuildEdlMarkers:
    """Tests for build_edl_markers."""

    def test_header_includes_title(self) -> None:
        """The EDL header includes the given title and frame mode."""
        edl = build_edl_markers([], title='My Video')
        assert 'TITLE: My Video' in edl
        assert 'FCM: NON-DROP FRAME' in edl

    def test_one_event_emits_clip_name_and_timecodes(self) -> None:
        """One event emits its clip name and start/end timecodes."""
        events = [{'name': 'Scene 1', 'start_sec': 0.0, 'end_sec': 5.0}]
        edl = build_edl_markers(events, title='Run')
        assert '* FROM CLIP NAME: Scene 1' in edl
        assert '00:00:00:00' in edl
        assert '00:00:05:00' in edl

    def test_multiple_events_are_sequentially_numbered(self) -> None:
        """Multiple events are numbered sequentially starting at 001."""
        events = [
            {'name': 'A', 'start_sec': 0.0, 'end_sec': 1.0},
            {'name': 'B', 'start_sec': 1.0, 'end_sec': 2.0},
        ]
        edl = build_edl_markers(events, title='Run')
        assert '001' in edl
        assert '002' in edl

    def test_long_names_are_truncated(self) -> None:
        """Clip names longer than 32 characters are truncated."""
        long_name = 'X' * 100
        events = [{'name': long_name, 'start_sec': 0.0, 'end_sec': 1.0}]
        edl = build_edl_markers(events, title='Run')
        assert f'* FROM CLIP NAME: {"X" * 32}' in edl
        assert 'X' * 33 not in edl

    def test_missing_name_defaults_to_event_index(self) -> None:
        """A missing clip name falls back to an event-index default."""
        events = [{'start_sec': 0.0, 'end_sec': 1.0}]
        edl = build_edl_markers(events, title='Run')
        assert '* FROM CLIP NAME: Event_1' in edl

    def test_custom_fps_changes_timecode_frames(self) -> None:
        """A non-default fps changes the emitted timecode frames."""
        events = [{'name': 'A', 'start_sec': 1.0, 'end_sec': 2.0}]
        edl = build_edl_markers(events, title='Run', fps=30.0)
        assert '00:00:01:00' in edl


class TestIsEditorHandoffBlueprint:
    """Tests for is_editor_handoff_blueprint."""

    def test_known_names_match(self) -> None:
        """Known blueprint names are recognized as editor-handoff."""
        assert is_editor_handoff_blueprint('longform_editor_v1')
        assert is_editor_handoff_blueprint('clipping_editor_v1')

    def test_name_containing_editor_substring_matches(self) -> None:
        """Any name containing the ``_editor_`` substring matches."""
        assert is_editor_handoff_blueprint('some_editor_variant')

    def test_unrelated_name_does_not_match(self) -> None:
        """An unrelated blueprint name does not match."""
        assert not is_editor_handoff_blueprint('longform_v1')

    def test_snapshot_handoff_flag_matches(self) -> None:
        """A snapshot with the editor_package handoff flag matches."""
        snapshot = {'handoff': 'editor_package'}
        assert is_editor_handoff_blueprint(snapshot=snapshot)

    def test_snapshot_without_flag_does_not_match(self) -> None:
        """A snapshot without the handoff flag does not match."""
        snapshot: dict[str, object] = {'stages': []}
        assert not is_editor_handoff_blueprint(snapshot=snapshot)

    def test_no_args_returns_false(self) -> None:
        """Calling with no arguments at all returns False."""
        assert not is_editor_handoff_blueprint()


class TestIsClippingRun:
    """Tests for is_clipping_run."""

    def test_clip_ingest_upstream_marks_clipping(self) -> None:
        """A clip_ingest key in upstream marks the run as clipping."""
        assert is_clipping_run({'clip_ingest': {}})

    def test_clip_approval_gate_upstream_marks_clipping(self) -> None:
        """A clip_approval_gate key in upstream marks it as clipping."""
        assert is_clipping_run({'clip_approval_gate': {}})

    def test_longform_upstream_is_not_clipping(self) -> None:
        """Longform-only upstream keys are not treated as clipping."""
        upstream = {'script': {}, 'scene_breakdown': {}, 'alignment': {}}
        assert not is_clipping_run(upstream)

    def test_empty_upstream_is_not_clipping(self) -> None:
        """An empty upstream dict is not treated as clipping."""
        assert not is_clipping_run({})
