"""Auto character design for character_design_mode=auto."""

from typing import Any

import structlog

from server.apps.channels.character_studio import CharacterStudioService
from server.apps.channels.logic.value_objects import (
    CharacterApprovePayload,
    CharacterRoundCreatePayload,
)
from server.apps.pipelines.models import (
    CastDesignStatus,
    CastImportance,
    PipelineRun,
    RunCast,
)

logger = structlog.get_logger(__name__)

# Tunable floor for accepting a candidate without a second round.
_SCORE_THRESHOLD = 0.65
_MAX_ROUNDS = 2
_CANDIDATES_PER_ROUND = 4


def _score_candidates(
    prompt: str,
    candidate_ids: list[str],
) -> list[tuple[str, float]]:
    """Rank candidates; prefer earlier IDs when no vision judge is wired.

    A future vision/LLM judge can replace this heuristic. Scores are
    deterministic and testable: first candidate starts at 0.7, each next
    drops by 0.05 (still above/below threshold depending on order).
    """
    assert prompt  # reserved for future vision/LLM judge context
    scored: list[tuple[str, float]] = []
    for index, asset_id in enumerate(candidate_ids):
        score = max(0.0, 0.7 - (0.05 * index))
        scored.append((asset_id, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _design_one(
    studio: CharacterStudioService,
    row: RunCast,
) -> dict[str, Any]:
    """Run up to two Studio rounds and approve the best candidate."""
    character = row.character
    prompt = row.draft_prompt or character.appearance_prompt
    if prompt and character.appearance_prompt != prompt:
        character.appearance_prompt = prompt
        character.save(update_fields=['appearance_prompt'])

    session = studio.start_session(str(character.id))
    best_id: str | None = None
    best_score = -1.0
    rounds_used = 0
    all_scores: list[dict[str, float]] = []

    for round_idx in range(_MAX_ROUNDS):
        rounds_used = round_idx + 1
        result = studio.generate_round(
            str(character.id),
            session.id,
            CharacterRoundCreatePayload(
                prompt=prompt,
                n=_CANDIDATES_PER_ROUND,
            ),
        )
        scored = _score_candidates(prompt, result.candidate_asset_ids)
        all_scores.append({aid: score for aid, score in scored})
        if not scored:
            continue
        top_id, top_score = scored[0]
        if top_score > best_score:
            best_id = top_id
            best_score = top_score
        if top_score >= _SCORE_THRESHOLD:
            break

    if best_id is None:
        msg = f'Auto Studio produced no candidates for {character.name}'
        raise RuntimeError(msg)

    studio.approve(
        str(character.id),
        CharacterApprovePayload(winning_asset_id=best_id),
    )
    row.design_status = CastDesignStatus.APPROVED
    row.save(update_fields=['design_status'])
    return {
        'cast_id': str(row.id),
        'character_id': str(character.id),
        'winning_asset_id': best_id,
        'score': best_score,
        'rounds': rounds_used,
        'scores': all_scores,
    }


def run_auto_character_design(run: PipelineRun) -> dict[str, Any]:
    """Design mains/secondaries that still need refs; return gate output."""
    studio = CharacterStudioService()
    designed: list[dict[str, Any]] = []
    rows = list(
        RunCast.objects
        .filter(run=run)
        .select_related('character')
        .order_by('created_at'),
    )
    for row in rows:
        if row.importance == CastImportance.BACKGROUND:
            if row.design_status != CastDesignStatus.TEXT_ONLY:
                row.design_status = CastDesignStatus.TEXT_ONLY
                row.save(update_fields=['design_status'])
            continue
        if row.design_status == CastDesignStatus.APPROVED:
            continue
        if row.character.hero_ref_id:
            row.design_status = CastDesignStatus.APPROVED
            row.save(update_fields=['design_status'])
            continue
        designed.append(_design_one(studio, row))

    logger.info(
        'pipeline_character_auto_designed',
        run_id=str(run.id),
        designed_count=len(designed),
    )
    return {
        'auto_designed': True,
        'designed': designed,
        'approved_cast_ids': [
            str(r.id)
            for r in RunCast.objects.filter(
                run=run,
                design_status=CastDesignStatus.APPROVED,
            )
        ],
    }
