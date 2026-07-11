"""Alignment stage — WhisperX forced alignment and ASS subtitle generation."""

import tempfile
from typing import Any, override

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import whisperx as whisperx_client
from server.apps.pipelines.services.tts_shards import load_tts_chapter_shards
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError


async def _fetch_audio_bytes(asset_id: str) -> bytes:
    """Retrieve audio bytes from S3 storage for a given Asset ID."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return asset.file.read()  # type: ignore[no-any-return]


def _build_ass_content(segments: list[dict[str, Any]]) -> bytes:
    """Build a minimal ASS subtitle file from WhisperX segment list."""
    lines = [
        '[Script Info]',
        'ScriptType: v4.00+',
        'PlayResX: 1920',
        'PlayResY: 1080',
        '',
        '[V4+ Styles]',
        (
            'Format: Name,Fontname,Fontsize,PrimaryColour,Bold,Italic,'
            'Underline,StrikeOut,Alignment,MarginL,MarginR,MarginV'
        ),
        'Style: Default,Arial,72,&H00FFFFFF,0,0,0,0,2,80,80,60',
        '',
        '[Events]',
        'Format: Layer,Start,End,Style,Text',
    ]
    for seg in segments:
        start = _fmt_ass_time(seg['start'])
        end = _fmt_ass_time(seg['end'])
        text = seg['text'].strip()
        lines.append(f'Dialogue: 0,{start},{end},Default,{text}')
    return '\n'.join(lines).encode()


def _fmt_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f'{h}:{m:02d}:{s:05.2f}'


def _fmt_srt_time(seconds: float) -> str:
    """Format seconds as SRT's HH:MM:SS,mmm.

    Rounds to whole milliseconds and carries any rounding overflow (e.g.
    1.9996 -> 2.000) into seconds instead of ever emitting an invalid
    4-digit millisecond field.
    """
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}'


def _build_srt_content(segments: list[dict[str, Any]]) -> bytes:
    """Build a standard SRT file from WhisperX segment list."""
    blocks: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start = _fmt_srt_time(seg['start'])
        end = _fmt_srt_time(seg['end'])
        text = seg['text'].strip()
        blocks.append(f'{i}\n{start} --> {end}\n{text}')
    return '\n\n'.join(blocks).encode()


@register_stage
class AlignmentStage(Stage):
    """Stage 9: WhisperX forced alignment and ASS subtitle generation."""

    key = 'alignment'
    queue = 'gpu'
    max_retries = 2
    timeout_s = 900

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Align TTS audio per chapter, producing scene word timestamps."""
        tts_shards = await load_tts_chapter_shards(ctx.run)
        if not tts_shards:
            raise FatalProviderError(
                'No succeeded TTS chapter shards found for alignment',
                provider='tts',
                error_code='missing_tts_shards',
            )
        script_chapters = {
            ch['idx']: ch
            for ch in ctx.upstream.get('script', {}).get('chapters', [])
        }

        all_scenes: list[dict[str, Any]] = []
        all_segments: list[dict[str, Any]] = []

        for shard in tts_shards:
            audio_bytes = await _fetch_audio_bytes(shard['asset_id'])
            chapter = script_chapters.get(shard['chapter_idx'], {})
            transcript_text = chapter.get('text', '')

            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                f.write(audio_bytes)
                audio_path = f.name

            alignment = await whisperx_client.align(
                audio_path=audio_path,
                transcript_text=transcript_text,
            )
            segments = alignment.get('segments', [])
            all_segments.extend(segments)

            for i, seg in enumerate(segments):
                all_scenes.append({
                    'chapter_idx': shard['chapter_idx'],
                    'segment_idx': i,
                    'start_s': seg['start'],
                    'end_s': seg['end'],
                    'text': seg['text'].strip(),
                    'words': seg.get('words', []),
                })

        ass_bytes = _build_ass_content(all_segments)
        ass_asset = await ctx.assets.save(
            kind=AssetKind.SUBTITLE,
            content=ass_bytes,
            filename='captions.ass',
            mime='text/x-ssa',
        )
        srt_bytes = _build_srt_content(all_segments)
        srt_asset = await ctx.assets.save(
            kind=AssetKind.SUBTITLE,
            content=srt_bytes,
            filename='captions.srt',
            mime='application/x-subrip',
        )
        return {
            'scenes': all_scenes,
            'ass_asset_id': str(ass_asset.id),
            'srt_asset_id': str(srt_asset.id),
        }
