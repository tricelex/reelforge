"""Alignment stage — WhisperX forced alignment and ASS subtitle generation."""

import operator
import tempfile
from typing import Any, override

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import whisperx as whisperx_client
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


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
        tts_shards = ctx.upstream.get('tts', {}).get('shards', [])
        script_chapters = {
            ch['idx']: ch
            for ch in ctx.upstream.get('script', {}).get('chapters', [])
        }

        all_scenes: list[dict[str, Any]] = []
        all_segments: list[dict[str, Any]] = []

        for shard in sorted(tts_shards, key=operator.itemgetter('chapter_idx')):
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
        return {
            'scenes': all_scenes,
            'ass_asset_id': str(ass_asset.id),
        }
