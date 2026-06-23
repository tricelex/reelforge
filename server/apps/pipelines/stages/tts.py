"""TTS stage — fan-out per chapter, ElevenLabs synthesis."""

from typing import Any, override

from django.conf import settings

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import elevenlabs as tts_client
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class TtsStage(Stage):
    """Stage 7: synthesise narration audio per chapter (fan-out)."""

    key = 'tts'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Shard by chapter — one TTS child per script chapter."""
        chapters = ctx.upstream.get('script', {}).get('chapters', [])
        return [
            {'chapter_idx': ch['idx'], 'text': ch['text']} for ch in chapters
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Synthesise a single chapter's narration and save as audio asset."""
        snap = ctx.execution.input_snapshot
        chapter_idx: int = snap['chapter_idx']
        text: str = snap['text']

        voice_id: str = getattr(ctx.channel, 'voice_id', '')
        stability = float(getattr(ctx.channel, 'stability', 0.5))
        similarity = float(getattr(ctx.channel, 'similarity_boost', 0.75))
        api_key: str = getattr(settings, 'ELEVENLABS_API_KEY', '')

        audio_bytes = await tts_client.synthesize(
            text=text,
            voice_id=voice_id,
            api_key=api_key,
            stability=stability,
            similarity_boost=similarity,
        )
        asset = await ctx.assets.save(
            kind=AssetKind.AUDIO_VO,
            content=audio_bytes,
            filename=f'chapter_{chapter_idx:03d}.mp3',
            mime='audio/mpeg',
        )
        char_count = len(text)
        await ctx.costs.record(
            provider='elevenlabs',
            operation='tts_chars',
            units=char_count,
            unit_cost_usd=0.00003,
        )
        return {
            'chapter_idx': chapter_idx,
            'asset_id': str(asset.id),
            'char_count': char_count,
        }
