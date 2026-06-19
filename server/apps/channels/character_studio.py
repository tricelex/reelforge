"""Character Studio business logic."""

import asyncio
import uuid
from decimal import Decimal
from typing import Any, final

import attrs
import httpx
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.channels.character_selectors import (
    get_character_detail,
    get_character_session,
)
from server.apps.channels.logic.value_objects import (
    CharacterApprovePayload,
    CharacterCreatePayload,
    CharacterDetailPayload,
    CharacterPatchPayload,
    CharacterRoundCreatePayload,
    CharacterRoundResultPayload,
    CharacterSessionPayload,
    CharacterSheetExpandPayload,
    CharacterSheetExpandResultPayload,
    CharacterSheetItemPayload,
)
from server.apps.channels.models import (
    Character,
    CharacterGenerationSession,
    CharacterOrigin,
    CharacterSheetItem,
    CharacterStatus,
)
from server.apps.generation.clients import fal as fal_client

_COST_PER_IMAGE_USD = Decimal('0.025')


def _download_image(url: str) -> bytes:
    with httpx.Client(timeout=60) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _ref_image_url(ref_asset_id: str | None) -> str | None:
    if not ref_asset_id:
        return None
    asset = LibraryAsset.objects.get(id=ref_asset_id)
    return asset.file.url if asset.file else None


def _save_character_ref(
    character: Character,
    image_bytes: bytes,
    *,
    suffix: str,
) -> LibraryAsset:
    return LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name=f'{character.name} {suffix}',
        channel_id=character.channel_id,
        file=ContentFile(image_bytes, name=f'{uuid.uuid4()}.png'),
    )


async def _generate_candidates_async(
    prompt: str,
    *,
    model: str,
    n: int,
    ref_asset_ids: list[str] | None,
) -> list[str]:
    ref_url = _ref_image_url(ref_asset_ids[0]) if ref_asset_ids else None
    urls: list[str] = []
    for _ in range(min(n, 4)):
        result = await fal_client.generate_image(
            prompt=prompt,
            model=model,
            image_url=ref_url,
        )
        urls.append(str(result['url']))
    return urls


@final
@attrs.define(slots=True, frozen=True)
class CharacterStudioService:
    """Create characters and run Studio iteration loops."""

    def create(self, payload: CharacterCreatePayload) -> CharacterDetailPayload:
        """Create a draft character."""
        character = Character.objects.create(
            name=payload.name,
            channel_id=(
                uuid.UUID(payload.channel_id)
                if payload.channel_id
                else None
            ),
            appearance_prompt=payload.appearance_prompt,
            persona=payload.persona,
            status=CharacterStatus.DRAFT,
        )
        return get_character_detail(str(character.id))

    def patch(
        self,
        character_id: str,
        payload: CharacterPatchPayload,
    ) -> CharacterDetailPayload:
        """Update character fields."""
        character = Character.objects.get(id=uuid.UUID(character_id))
        if payload.name is not None:
            character.name = payload.name
        if payload.appearance_prompt is not None:
            character.appearance_prompt = payload.appearance_prompt
        if payload.persona is not None:
            character.persona = payload.persona
        if payload.status is not None:
            character.status = payload.status
        character.save()
        return get_character_detail(str(character.id))

    def start_session(self, character_id: str) -> CharacterSessionPayload:
        """Start a new generation session."""
        character = Character.objects.get(id=uuid.UUID(character_id))
        session = CharacterGenerationSession.objects.create(
            character=character,
            rounds=[],
        )
        return get_character_session(str(session.id))

    def generate_round(
        self,
        character_id: str,
        session_id: str,
        payload: CharacterRoundCreatePayload,
    ) -> CharacterRoundResultPayload:
        """Run one image generation round."""
        character = Character.objects.get(id=uuid.UUID(character_id))
        session = CharacterGenerationSession.objects.get(
            id=uuid.UUID(session_id),
            character=character,
        )
        urls = asyncio.run(
            _generate_candidates_async(
                payload.prompt,
                model=payload.model,
                n=payload.n,
                ref_asset_ids=payload.ref_asset_ids,
            ),
        )
        candidate_ids: list[str] = []
        for index, url in enumerate(urls):
            asset = _save_character_ref(
                character,
                _download_image(url),
                suffix=f'candidate-{index + 1}',
            )
            candidate_ids.append(str(asset.id))

        cost = _COST_PER_IMAGE_USD * len(candidate_ids)
        round_data: dict[str, Any] = {
            'prompt': payload.prompt,
            'model': payload.model,
            'n': payload.n,
            'ref_asset_ids': payload.ref_asset_ids or [],
            'candidate_asset_ids': candidate_ids,
            'cost_usd': str(cost),
            'picked': None,
        }
        rounds = list(session.rounds)
        rounds.append(round_data)
        session.rounds = rounds
        session.save(update_fields=['rounds'])

        character.total_creation_cost_usd += cost
        character.save(update_fields=['total_creation_cost_usd'])

        return CharacterRoundResultPayload(
            session_id=str(session.id),
            candidate_asset_ids=candidate_ids,
            cost_usd=str(cost),
        )

    def approve(
        self,
        character_id: str,
        payload: CharacterApprovePayload,
    ) -> CharacterDetailPayload:
        """Lock winning asset and mark character approved."""
        character = Character.objects.get(id=uuid.UUID(character_id))
        asset = LibraryAsset.objects.get(
            id=uuid.UUID(payload.winning_asset_id),
            kind=LibraryAssetKind.CHARACTER_REF,
        )
        character.hero_ref_id = asset.id
        if payload.appearance_prompt:
            character.appearance_prompt = payload.appearance_prompt
        character.status = CharacterStatus.APPROVED
        character.save()
        return get_character_detail(str(character.id))

    def promote(self, character_id: str) -> CharacterDetailPayload:
        """Promote a run-origin character to the library."""
        character = Character.objects.get(id=uuid.UUID(character_id))
        if character.status != CharacterStatus.APPROVED:
            msg = 'Character must be approved before promotion'
            raise ValidationError(msg)
        character.origin = CharacterOrigin.LIBRARY
        character.source_run_id = None
        character.save(update_fields=['origin', 'source_run_id'])
        return get_character_detail(str(character.id))

    def expand_sheet(
        self,
        character_id: str,
        payload: CharacterSheetExpandPayload,
    ) -> CharacterSheetExpandResultPayload:
        """Generate labeled sheet variants from the hero ref."""
        character = Character.objects.get(id=uuid.UUID(character_id))
        if not character.hero_ref_id:
            msg = 'Character needs an approved hero reference'
            raise ValidationError(msg)
        if not character.appearance_prompt:
            msg = 'Character needs an appearance prompt'
            raise ValidationError(msg)

        items: list[CharacterSheetItemPayload] = []
        ref_ids = [str(character.hero_ref_id)]
        for label in payload.labels[:8]:
            prompt = f'{character.appearance_prompt}, {label}'
            urls = asyncio.run(
                _generate_candidates_async(
                    prompt,
                    model=payload.model,
                    n=1,
                    ref_asset_ids=ref_ids,
                ),
            )
            asset = _save_character_ref(
                character,
                _download_image(urls[0]),
                suffix=label.replace(' ', '-'),
            )
            sheet_item = CharacterSheetItem.objects.create(
                character=character,
                asset=asset,
                label=label,
            )
            items.append(
                CharacterSheetItemPayload(
                    id=str(sheet_item.id),
                    label=sheet_item.label,
                    asset_id=str(asset.id),
                ),
            )
        return CharacterSheetExpandResultPayload(items=items)
