from __future__ import annotations

import pytest

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.clipping.tests.factories import ClipRenderFactory


# ── Task 1: model field tests ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_clip_candidate_has_render_gates_field() -> None:
    candidate = ClipCandidateFactory()
    assert candidate.render_gates == []
    candidate.render_gates = [1, 3, 5]
    candidate.save(update_fields=["render_gates"])
    candidate.refresh_from_db()
    assert candidate.render_gates == [1, 3, 5]


def test_clip_render_has_paused_at_gate_status() -> None:
    assert "PAUSED_AT_GATE" in ClipRender.RenderStatus.values


@pytest.mark.django_db
def test_clip_render_has_paused_at_stage_field() -> None:
    render = ClipRenderFactory()
    assert render.paused_at_stage is None
    render.paused_at_stage = 3
    render.save(update_fields=["paused_at_stage"])
    render.refresh_from_db()
    assert render.paused_at_stage == 3
