"""Business logic for run-scoped character cast."""

import uuid
from typing import final

import attrs
from django.core.exceptions import ValidationError

from server.apps.channels.character_studio import CharacterStudioService
from server.apps.channels.logic.value_objects import (
    CharacterApprovePayload,
    CharacterRoundCreatePayload,
    CharacterRoundResultPayload,
    CharacterSessionPayload,
)
from server.apps.pipelines.logic.value_objects import (
    RunCastApprovePayload,
    RunCastPatchPayload,
    RunCastPayload,
)
from server.apps.pipelines.models import CastDesignStatus, RunCast
from server.apps.pipelines.run_cast_selectors import _to_cast


@final
@attrs.define(slots=True, frozen=True)
class RunCastService:
    """Manage cast assignments during a pipeline run."""

    _studio: CharacterStudioService

    def patch(
        self,
        run_id: str,
        cast_id: str,
        payload: RunCastPatchPayload,
    ) -> RunCastPayload:
        """Update cast role or design status."""
        row = RunCast.objects.select_related('character').get(
            id=uuid.UUID(cast_id),
            run_id=uuid.UUID(run_id),
        )
        update_fields: list[str] = []
        if payload.role is not None:
            row.role = payload.role
            update_fields.append('role')
        if payload.design_status is not None:
            row.design_status = payload.design_status
            update_fields.append('design_status')
        if update_fields:
            row.save(update_fields=update_fields)
        return _to_cast(row)

    def start_session(
        self,
        run_id: str,
        cast_id: str,
    ) -> CharacterSessionPayload:
        """Start a Studio session for a cast member."""
        row = RunCast.objects.get(
            id=uuid.UUID(cast_id),
            run_id=uuid.UUID(run_id),
        )
        row.design_status = CastDesignStatus.PROPOSED
        row.save(update_fields=['design_status'])
        return self._studio.start_session(str(row.character_id))

    def generate_round(
        self,
        run_id: str,
        cast_id: str,
        session_id: str,
        payload: CharacterRoundCreatePayload,
    ) -> CharacterRoundResultPayload:
        """Generate candidates for a cast member."""
        row = RunCast.objects.get(
            id=uuid.UUID(cast_id),
            run_id=uuid.UUID(run_id),
        )
        return self._studio.generate_round(
            str(row.character_id),
            session_id,
            payload,
        )

    def approve(
        self,
        run_id: str,
        cast_id: str,
        payload: RunCastApprovePayload,
    ) -> RunCastPayload:
        """Approve cast member design."""
        row = RunCast.objects.select_related('character').get(
            id=uuid.UUID(cast_id),
            run_id=uuid.UUID(run_id),
        )
        if not payload.winning_asset_id:
            msg = 'winning_asset_id is required'
            raise ValidationError(msg)
        self._studio.approve(
            str(row.character_id),
            CharacterApprovePayload(
                winning_asset_id=payload.winning_asset_id,
            ),
        )
        row.design_status = CastDesignStatus.APPROVED
        row.save(update_fields=['design_status'])
        row = RunCast.objects.select_related('character').get(pk=row.pk)
        return _to_cast(row)
