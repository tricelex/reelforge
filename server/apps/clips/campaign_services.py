"""Business logic for clip campaigns and earnings."""

import uuid
from datetime import datetime
from typing import final

import attrs
import django.utils.timezone as tz
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from server.apps.clips.logic.constants import CampaignStatus
from server.apps.clips.logic.value_objects import (
    ClipCampaignCreatePayload,
    ClipCampaignListPayload,
    ClipCampaignPatchPayload,
    ClipCampaignPayload,
    EarningCreatePayload,
    EarningListPayload,
    EarningPayload,
)
from server.apps.clips.models import ClipCampaign, Earning


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _to_campaign_payload(campaign: ClipCampaign) -> ClipCampaignPayload:
    return ClipCampaignPayload(
        id=str(campaign.id),
        channel_id=str(campaign.channel_id),
        name=campaign.name,
        status=campaign.status,
        notes=campaign.notes,
        created_at=_iso(campaign.created_at),
    )


def _to_earning_payload(earning: Earning) -> EarningPayload:
    return EarningPayload(
        id=str(earning.id),
        campaign_id=str(earning.campaign_id),
        candidate_id=(
            str(earning.candidate_id) if earning.candidate_id else None
        ),
        platform=earning.platform,
        revenue_est_usd=str(earning.revenue_est_usd),
        recorded_at=_iso(earning.recorded_at),
        notes=earning.notes,
    )


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return tz.make_aware(parsed)
    return parsed


@final
@attrs.define(slots=True, frozen=True)
class ClipCampaignService:
    """CRUD for clip campaigns and manual earnings."""

    def list_campaigns(
        self,
        *,
        channel_id: str | None = None,
        limit: int = 20,
    ) -> ClipCampaignListPayload:
        """Return campaigns ordered by newest first."""
        qs = ClipCampaign.objects.order_by('-created_at', '-id')
        if channel_id:
            qs = qs.filter(channel_id=uuid.UUID(channel_id))
        total = qs.count()
        rows = list(qs[: min(max(limit, 1), 50)])
        return ClipCampaignListPayload(
            items=[_to_campaign_payload(row) for row in rows],
            next_cursor=None,
            total=total,
        )

    def create_campaign(
        self,
        payload: ClipCampaignCreatePayload,
    ) -> ClipCampaignPayload:
        """Create a campaign row."""
        from server.apps.channels.models import Channel  # noqa: PLC0415

        try:
            Channel.objects.get(id=uuid.UUID(payload.channel_id))
        except ObjectDoesNotExist as exc:
            msg = f'Channel not found: {payload.channel_id}'
            raise ValidationError(msg) from exc

        campaign = ClipCampaign.objects.create(
            channel_id=payload.channel_id,
            name=payload.name,
            notes=payload.notes,
        )
        return _to_campaign_payload(campaign)

    def patch_campaign(
        self,
        campaign_id: str,
        payload: ClipCampaignPatchPayload,
    ) -> ClipCampaignPayload:
        """Update campaign fields."""
        campaign = ClipCampaign.objects.get(id=uuid.UUID(campaign_id))
        update_fields: list[str] = []
        if payload.name is not None:
            campaign.name = payload.name
            update_fields.append('name')
        if payload.status is not None:
            if payload.status not in CampaignStatus.values:
                msg = f'Invalid status: {payload.status}'
                raise ValidationError(msg)
            campaign.status = payload.status
            update_fields.append('status')
        if payload.notes is not None:
            campaign.notes = payload.notes
            update_fields.append('notes')
        if update_fields:
            campaign.save(update_fields=update_fields)
        return _to_campaign_payload(campaign)

    def get_campaign(self, campaign_id: str) -> ClipCampaignPayload:
        """Return one campaign."""
        campaign = ClipCampaign.objects.get(id=uuid.UUID(campaign_id))
        return _to_campaign_payload(campaign)

    def list_earnings(
        self,
        *,
        campaign_id: str | None = None,
    ) -> EarningListPayload:
        """Return earning rows, optionally filtered by campaign."""
        qs = Earning.objects.order_by('-recorded_at', '-id')
        if campaign_id:
            qs = qs.filter(campaign_id=uuid.UUID(campaign_id))
        rows = list(qs[:100])
        return EarningListPayload(
            items=[_to_earning_payload(row) for row in rows],
            total=len(rows),
        )

    def create_earning(
        self,
        payload: EarningCreatePayload,
    ) -> EarningPayload:
        """Record a manual earning entry."""
        campaign = ClipCampaign.objects.get(
            id=uuid.UUID(payload.campaign_id),
        )
        candidate_id = payload.candidate_id
        if candidate_id is not None:
            from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

            ClipCandidate.objects.get(id=uuid.UUID(candidate_id))

        earning = Earning.objects.create(
            campaign=campaign,
            candidate_id=candidate_id,
            platform=payload.platform,
            revenue_est_usd=payload.revenue_est_usd,
            recorded_at=_parse_dt(payload.recorded_at),
            notes=payload.notes,
        )
        return _to_earning_payload(earning)
