"""Read-only query helpers for characters and niche config."""

from server.apps.channels.logic.value_objects import (
    CharacterDetailPayload,
    CharacterListPayload,
    CharacterRoundPayload,
    CharacterSessionPayload,
    CharacterSummaryPayload,
)
from server.apps.channels.models import Character, CharacterGenerationSession


def _to_character_summary(character: Character) -> CharacterSummaryPayload:
    return CharacterSummaryPayload(
        id=str(character.id),
        channel_id=str(character.channel_id) if character.channel_id else None,
        name=character.name,
        status=character.status,
        origin=character.origin,
        hero_ref_asset_id=(
            str(character.hero_ref_id) if character.hero_ref_id else None
        ),
    )


def list_characters(
    *,
    channel_id: str | None = None,
    status: str | None = None,
) -> CharacterListPayload:
    """Return characters with optional filters."""
    qs = Character.objects.order_by('name')
    if channel_id:
        qs = qs.filter(channel_id=channel_id)
    if status:
        qs = qs.filter(status=status)
    items = [_to_character_summary(c) for c in qs]
    return CharacterListPayload(items=items, total=len(items))


def get_character_detail(character_id: str) -> CharacterDetailPayload:
    """Return full character detail."""
    character = Character.objects.get(id=character_id)
    return CharacterDetailPayload(
        id=str(character.id),
        channel_id=str(character.channel_id) if character.channel_id else None,
        name=character.name,
        status=character.status,
        appearance_prompt=character.appearance_prompt,
        persona=character.persona,
        hero_ref_asset_id=(
            str(character.hero_ref_id) if character.hero_ref_id else None
        ),
        total_creation_cost_usd=str(character.total_creation_cost_usd),
        origin=character.origin,
        source_run_id=(
            str(character.source_run_id) if character.source_run_id else None
        ),
    )


def _round_to_payload(raw: object) -> CharacterRoundPayload:
    data = raw if isinstance(raw, dict) else {}
    asset_ids = data.get('candidate_asset_ids', [])
    if not isinstance(asset_ids, list):
        asset_ids = []
    return CharacterRoundPayload(
        prompt=str(data.get('prompt', '')),
        model=str(data.get('model', '')),
        n=int(data.get('n', 0)),
        cost_usd=str(data.get('cost_usd', '0')),
        candidate_asset_ids=[str(value) for value in asset_ids],
        picked=(
            str(data['picked']) if data.get('picked') is not None else None
        ),
    )


def get_character_session(session_id: str) -> CharacterSessionPayload:
    """Return one generation session."""
    session = CharacterGenerationSession.objects.get(id=session_id)
    rounds = [_round_to_payload(r) for r in list(session.rounds)]
    return CharacterSessionPayload(
        id=str(session.id),
        character_id=str(session.character_id),
        rounds=rounds,
        created_at=session.created_at.isoformat(),
    )
