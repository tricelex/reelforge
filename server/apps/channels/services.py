"""Business logic for channels and YouTube OAuth."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, final
from urllib.parse import urlencode

import attrs
import django.utils.timezone as tz
import httpx
from django.conf import settings
from django.core.exceptions import ValidationError

from server.apps.assets.models import LibraryAsset
from server.apps.channels.logic.value_objects import (
    ChannelBrandingPatchPayload,
    ChannelBrandingPayload,
    ChannelCreatePayload,
    ChannelDetailPayload,
    ChannelPatchPayload,
    NicheConfigPatchPayload,
    NicheConfigPayload,
    YouTubeCallbackPayload,
    YouTubeConnectPayload,
    YouTubeConnectResultPayload,
    YouTubeStatusPayload,
)
from server.apps.channels.models import (
    Channel,
    ChannelBranding,
    NicheConfig,
    YouTubeCredential,
)
from server.apps.channels.selectors import (
    get_channel_branding,
    get_channel_detail,
    get_niche_config,
)

_YOUTUBE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
_YOUTUBE_TOKEN_URL = 'https://oauth2.googleapis.com/token'  # noqa: S105
_YOUTUBE_SCOPES = (
    'https://www.googleapis.com/auth/youtube.upload '
    'https://www.googleapis.com/auth/youtube'
)


def _apply_patch_fields(
    instance: object,
    payload: object,
    field_names: tuple[str, ...],
) -> list[str]:
    update_fields: list[str] = []
    for name in field_names:
        value = getattr(payload, name)
        if value is not None:
            setattr(instance, name, value)
            update_fields.append(name)
    return update_fields


def _set_fk(
    instance: ChannelBranding,
    field_name: str,
    asset_id: str | None,
    update_fields: list[str],
) -> None:
    if asset_id is None:
        return
    asset = LibraryAsset.objects.get(id=uuid.UUID(asset_id))
    setattr(instance, field_name, asset)
    update_fields.append(f'{field_name}_id')


@final
@attrs.define(slots=True, frozen=True)
class ChannelService:
    """Create and update channels, branding, and YouTube OAuth."""

    def create(self, payload: ChannelCreatePayload) -> ChannelDetailPayload:
        """Create a channel with default branding row."""
        channel = Channel.objects.create(
            name=payload.name,
            kind=payload.kind,
            publish_mode=payload.publish_mode,
            gates=payload.gates or [],
            character_design_mode=payload.character_design_mode,
            default_budget_usd=(
                Decimal(payload.default_budget_usd)
                if payload.default_budget_usd is not None
                else None
            ),
            voice_id=payload.voice_id,
            stability=payload.stability,
            similarity_boost=payload.similarity_boost,
            wpm=payload.wpm,
        )
        ChannelBranding.objects.get_or_create(channel=channel)
        return get_channel_detail(str(channel.id))

    def patch(
        self,
        channel_id: str,
        payload: ChannelPatchPayload,
    ) -> ChannelDetailPayload:
        """Update channel fields."""
        channel = Channel.objects.get(id=uuid.UUID(channel_id))
        update_fields = _apply_patch_fields(
            channel,
            payload,
            (
                'name',
                'publish_mode',
                'gates',
                'character_design_mode',
                'voice_id',
                'stability',
                'similarity_boost',
                'wpm',
                'is_active',
            ),
        )
        if payload.default_budget_usd is not None:
            channel.default_budget_usd = Decimal(payload.default_budget_usd)
            update_fields.append('default_budget_usd')
        if update_fields:
            channel.save(update_fields=update_fields)
        return get_channel_detail(str(channel.id))

    def patch_branding(
        self,
        channel_id: str,
        payload: ChannelBrandingPatchPayload,
    ) -> ChannelBrandingPayload:
        """Update channel branding."""
        channel = Channel.objects.get(id=uuid.UUID(channel_id))
        branding, _ = ChannelBranding.objects.get_or_create(channel=channel)
        update_fields: list[str] = []
        _set_fk(branding, 'intro', payload.intro_asset_id, update_fields)
        _set_fk(branding, 'outro', payload.outro_asset_id, update_fields)
        _set_fk(
            branding,
            'watermark',
            payload.watermark_asset_id,
            update_fields,
        )
        _set_fk(
            branding,
            'caption_style',
            payload.caption_style_asset_id,
            update_fields,
        )
        scalar_fields = _apply_patch_fields(
            branding,
            payload,
            ('watermark_position', 'watermark_opacity', 'music_pool_tags'),
        )
        update_fields.extend(scalar_fields)
        if payload.thumbnail_palette is not None:
            branding.thumbnail_palette = dict(payload.thumbnail_palette)
            update_fields.append('thumbnail_palette')
        if update_fields:
            branding.save(update_fields=update_fields)
        if payload.font_asset_ids is not None:
            branding.fonts.set(
                [uuid.UUID(value) for value in payload.font_asset_ids],  # type: ignore[misc]
            )
        return get_channel_branding(str(channel.id))

    def patch_niche(
        self,
        channel_id: str,
        payload: NicheConfigPatchPayload,
    ) -> NicheConfigPayload:
        """Update niche configuration."""
        channel = Channel.objects.get(id=uuid.UUID(channel_id))
        niche, _ = NicheConfig.objects.get_or_create(channel=channel)
        update_fields = _apply_patch_fields(
            niche,
            payload,
            ('audience', 'angle', 'banned_topics', 'lore_document'),
        )
        if payload.format_id is not None:
            niche.format_id = (
                uuid.UUID(payload.format_id) if payload.format_id else None
            )
            update_fields.append('format_id')
        if update_fields:
            niche.save(update_fields=update_fields)
        return get_niche_config(str(channel.id))

    def youtube_connect_url(
        self,
        channel_id: str,
        redirect_uri: str,
    ) -> YouTubeConnectPayload:
        """Build Google OAuth authorization URL."""
        if not settings.YOUTUBE_CLIENT_ID:
            msg = 'YouTube OAuth is not configured'
            raise ValidationError(msg)
        Channel.objects.get(id=uuid.UUID(channel_id))
        params = {
            'client_id': settings.YOUTUBE_CLIENT_ID,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': _YOUTUBE_SCOPES,
            'access_type': 'offline',
            'prompt': 'consent',
            'state': channel_id,
        }
        return YouTubeConnectPayload(
            authorization_url=f'{_YOUTUBE_AUTH_URL}?{urlencode(params)}',
        )

    def youtube_complete_oauth(
        self,
        channel_id: str,
        payload: YouTubeCallbackPayload,
    ) -> YouTubeConnectResultPayload:
        """Exchange authorization code for tokens and store credential."""
        if not settings.YOUTUBE_CLIENT_ID or not settings.YOUTUBE_CLIENT_SECRET:
            msg = 'YouTube OAuth is not configured'
            raise ValidationError(msg)

        channel = Channel.objects.get(id=uuid.UUID(channel_id))
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                _YOUTUBE_TOKEN_URL,
                data={
                    'code': payload.code,
                    'client_id': settings.YOUTUBE_CLIENT_ID,
                    'client_secret': settings.YOUTUBE_CLIENT_SECRET,
                    'redirect_uri': payload.redirect_uri,
                    'grant_type': 'authorization_code',
                },
            )
        if resp.status_code != 200:
            msg = f'YouTube token exchange failed: {resp.status_code}'
            raise ValidationError(msg)

        data: dict[str, Any] = resp.json()
        access_token = str(data['access_token'])
        refresh_token = str(data.get('refresh_token', ''))
        if not refresh_token:
            msg = 'YouTube did not return a refresh token'
            raise ValidationError(msg)
        expires_in = int(data.get('expires_in', 3600))
        scope = str(data.get('scope', _YOUTUBE_SCOPES))

        YouTubeCredential.objects.update_or_create(
            channel=channel,
            defaults={
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expiry': tz.now()
                + dt.timedelta(seconds=expires_in - 60),
                'scope': scope,
            },
        )
        return YouTubeConnectResultPayload(connected=True, scope=scope)

    def youtube_status(self, channel_id: str) -> YouTubeStatusPayload:
        """Return whether YouTube is connected (no token values)."""
        Channel.objects.get(id=uuid.UUID(channel_id))
        try:
            cred = YouTubeCredential.objects.get(
                channel_id=uuid.UUID(channel_id),
            )
        except YouTubeCredential.DoesNotExist:
            return YouTubeStatusPayload(connected=False)
        return YouTubeStatusPayload(
            connected=True,
            scope=cred.scope or None,
            token_expiry=(
                cred.token_expiry.isoformat() if cred.token_expiry else None
            ),
        )
