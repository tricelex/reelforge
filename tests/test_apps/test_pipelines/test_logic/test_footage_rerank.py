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
        provider='pexels',
        external_id=external_id,
        media_type='video',
        download_url='https://e.test/v.mp4',
        thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p',
        width=width,
        height=1080,
        duration_s=10.0,
        license='pexels',
        license_url='',
        author='A',
        attribution_required=False,
        title=title,
        tags=tags,
    )


def test_matching_title_scores_higher_than_unrelated() -> None:
    """Term overlap with the visual concept raises the score."""
    match = _candidate('1', title='stormy ocean waves at sea')
    miss = _candidate('2', title='a plate of pasta')
    concept = 'stormy ocean waves'
    assert metadata_score(
        match,
        visual_concept=concept,
        negative_terms=[],
    ) > metadata_score(miss, visual_concept=concept, negative_terms=[])


def test_negative_terms_penalise_a_candidate() -> None:
    """A negative term present in metadata reduces the score."""
    candidate = _candidate('1', title='modern cruise ship at sea')
    clean = metadata_score(
        candidate,
        visual_concept='ship at sea',
        negative_terms=[],
    )
    penalised = metadata_score(
        candidate,
        visual_concept='ship at sea',
        negative_terms=['modern'],
    )
    assert penalised < clean


def test_tags_contribute_to_the_score() -> None:
    """Tags are searched as well as the title."""
    tagged = _candidate('1', title='', tags=('ocean', 'waves'))
    untagged = _candidate('2', title='', tags=())
    concept = 'ocean waves'
    assert metadata_score(
        tagged,
        visual_concept=concept,
        negative_terms=[],
    ) > metadata_score(untagged, visual_concept=concept, negative_terms=[])


def test_rank_by_metadata_orders_best_first() -> None:
    """Ranking returns candidates sorted by descending score."""
    candidates = [
        _candidate('miss', title='a plate of pasta'),
        _candidate('hit', title='stormy ocean waves'),
    ]
    ranked = rank_by_metadata(
        candidates,
        visual_concept='stormy ocean waves',
        negative_terms=[],
    )
    assert [c.external_id for c in ranked] == ['hit', 'miss']


def test_rank_by_metadata_is_stable_for_equal_scores() -> None:
    """Equal scores preserve the provider's original ordering."""
    candidates = [_candidate('a'), _candidate('b'), _candidate('c')]
    ranked = rank_by_metadata(
        candidates,
        visual_concept='unrelated',
        negative_terms=[],
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
