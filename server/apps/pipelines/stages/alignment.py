"""Alignment stage — ElevenLabs forced alignment and ASS subtitle generation."""

import tempfile
from pathlib import Path
from typing import Any, override

from django.conf import settings

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import elevenlabs as elevenlabs_client
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
    """Build a minimal ASS subtitle file from aligned segment list."""
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
    """Build a standard SRT file from aligned segment list."""
    blocks: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start = _fmt_srt_time(seg['start'])
        end = _fmt_srt_time(seg['end'])
        text = seg['text'].strip()
        blocks.append(f'{i}\n{start} --> {end}\n{text}')
    return '\n\n'.join(blocks).encode()


def _map_aligned_words(
    words_raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map ElevenLabs FA words to {word, start, end, score}.

    ``score`` stores ElevenLabs ``loss`` (lower is better).
    Whitespace-only tokens are dropped — FA emits them between words.
    """
    mapped: list[dict[str, Any]] = []
    for w in words_raw:
        token = str(w.get('text', w.get('word', '')))
        if not token.strip():
            continue
        mapped.append({
            'word': token,
            'start': float(w.get('start', 0)),
            'end': float(w.get('end', 0)),
            'score': float(w.get('loss', w.get('score', 0))),
        })
    return mapped


def _scene_word_quota(scene: dict[str, Any]) -> int:
    """Prefer word_count; fall back to tokenising narration_text."""
    count = int(scene.get('word_count') or 0)
    if count > 0:
        return count
    return len(str(scene.get('narration_text', '')).split())


def _remap_quota_sizes(n_words: int, quotas: list[int]) -> list[int]:
    """Map scene word quotas onto exactly ``n_words`` slice sizes."""
    assert n_words > 0, 'n_words must be > 0'
    assert quotas, 'quotas must be non-empty'
    n_scenes = len(quotas)
    safe = [max(1, q) for q in quotas]
    total = sum(safe)
    if total == n_words:
        return safe

    raw = [q * n_words / total for q in safe]
    sizes = [int(x) for x in raw]
    rem = n_words - sum(sizes)
    order = sorted(
        range(n_scenes),
        key=lambda i: raw[i] - sizes[i],
        reverse=True,
    )
    for j in range(max(0, rem)):
        sizes[order[j % n_scenes]] += 1
    if n_words < n_scenes:
        return sizes
    for i in range(n_scenes):
        if sizes[i] != 0:
            continue
        donor = max(range(n_scenes), key=lambda k: sizes[k])
        if sizes[donor] > 1:
            sizes[donor] -= 1
            sizes[i] = 1
    return sizes


def _partition_slices(
    n_words: int,
    quotas: list[int],
) -> list[tuple[int, int]]:
    """Cover ``0..n_words`` with one [start, end) slice per quota.

    Exact match when ``sum(quotas) == n_words``. Otherwise uses largest-
    remainder proportional remapping so every speech word is assigned and
    every scene gets ≥1 word when ``n_words >= len(quotas)``.
    """
    sizes = _remap_quota_sizes(n_words, quotas)
    slices: list[tuple[int, int]] = []
    cursor = 0
    for size in sizes:
        slices.append((cursor, cursor + size))
        cursor += size
    if slices:
        start, _ = slices[-1]
        slices[-1] = (start, n_words)
    return slices


def _split_words_into_scenes(
    chapter_scenes: list[dict[str, Any]],
    fa_words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Partition FA words across scene_breakdown rows for one chapter.

    Emits one alignment scene per breakdown scene, carrying the global
    ``scene_idx`` that motion / image_gen already use.
    """
    assert chapter_scenes, 'chapter_scenes must be non-empty'
    speech = [
        w
        for w in fa_words
        if str(w.get('word', '')).strip()
    ]
    if not speech:
        raise ValueError('no speech words in forced-alignment response')

    ordered = sorted(chapter_scenes, key=lambda s: int(s['idx']))
    if len(speech) < len(ordered):
        raise ValueError(
            f'only {len(speech)} speech words for {len(ordered)} scenes',
        )
    quotas = [_scene_word_quota(s) for s in ordered]
    slices = _partition_slices(len(speech), quotas)

    result: list[dict[str, Any]] = []
    for local_idx, (scene, (start_i, end_i)) in enumerate(
        zip(ordered, slices, strict=True),
    ):
        chunk = speech[start_i:end_i]
        assert chunk, f'scene {scene["idx"]} received empty word slice'
        result.append({
            'scene_idx': int(scene['idx']),
            'chapter_idx': int(scene['chapter_idx']),
            'segment_idx': local_idx,
            'start_s': float(chunk[0]['start']),
            'end_s': float(chunk[-1]['end']),
            'text': str(scene.get('narration_text', '')).strip(),
            'words': chunk,
        })
    return result


def _segment_from_alignment(
    transcript_text: str,
    alignment: dict[str, Any],
) -> dict[str, Any]:
    """Build one chapter segment from a Forced Alignment response."""
    word_timings = _map_aligned_words(alignment.get('words', []))
    start_s = word_timings[0]['start'] if word_timings else 0.0
    end_s = word_timings[-1]['end'] if word_timings else 0.0
    return {
        'text': transcript_text,
        'start': start_s,
        'end': end_s,
        'words': word_timings,
    }


def _offset_segment(
    segment: dict[str, Any],
    offset_s: float,
) -> dict[str, Any]:
    """Shift a chapter-relative FA segment onto the absolute timeline."""
    return {
        'text': segment['text'],
        'start': float(segment['start']) + offset_s,
        'end': float(segment['end']) + offset_s,
        'words': [
            {
                **word,
                'start': float(word['start']) + offset_s,
                'end': float(word['end']) + offset_s,
            }
            for word in segment['words']
        ],
    }


def _offset_scenes(
    scenes: list[dict[str, Any]],
    offset_s: float,
) -> list[dict[str, Any]]:
    """Shift chapter-relative scene timings onto the absolute timeline."""
    out: list[dict[str, Any]] = []
    for scene in scenes:
        words = [
            {
                **word,
                'start': float(word['start']) + offset_s,
                'end': float(word['end']) + offset_s,
            }
            for word in scene.get('words', [])
        ]
        out.append({
            **scene,
            'start_s': float(scene['start_s']) + offset_s,
            'end_s': float(scene['end_s']) + offset_s,
            'words': words,
        })
    return out


_SUBTITLE_CHUNK_WORDS = 4


def _chunk_words_into_cues(
    words: list[dict[str, Any]],
    *,
    chunk_size: int = _SUBTITLE_CHUNK_WORDS,
) -> list[dict[str, Any]]:
    """Split word timings into short subtitle cues (start/end/text)."""
    assert chunk_size > 0, f'chunk_size must be > 0, got {chunk_size}'  # noqa: S101
    cues: list[dict[str, Any]] = []
    max_words = len(words)
    for start_i in range(0, max_words, chunk_size):
        assert start_i < max_words, 'chunk start exceeded word list'  # noqa: S101
        chunk = words[start_i : start_i + chunk_size]
        texts = [str(w.get('word', '')).strip() for w in chunk]
        text = ' '.join(t for t in texts if t)
        if not text:
            continue
        cues.append({
            'start': float(chunk[0]['start']),
            'end': float(chunk[-1]['end']),
            'text': text,
        })
    return cues


def _subtitle_segments_from_scenes(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Chunked subtitle cues from aligned scene word timings.

    Uses ~4 words per cue so burn-in stays in sync with narration instead of
    lingering for the full scene.
    """
    segments: list[dict[str, Any]] = []
    for scene in scenes:
        words = scene.get('words') or []
        if isinstance(words, list) and words:
            segments.extend(_chunk_words_into_cues(words))
            continue
        text = str(scene.get('text', '')).strip()
        if text:
            segments.append({
                'start': float(scene['start_s']),
                'end': float(scene['end_s']),
                'text': text,
            })
    return segments


async def _align_one_chapter(
    *,
    shard: dict[str, Any],
    script_chapters: dict[Any, dict[str, Any]],
    breakdown_scenes: list[dict[str, Any]],
    api_key: str,
    chapter_offset: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    """Force-align one TTS chapter; return absolute segment, scenes, span."""
    audio_bytes = await _fetch_audio_bytes(shard['asset_id'])
    chapter = script_chapters.get(shard['chapter_idx'], {})
    transcript_text = chapter.get('text', '')
    if not transcript_text.strip():
        raise FatalProviderError(
            'Script chapter text is empty — cannot align audio',
            provider='elevenlabs',
            error_code='empty_transcript',
        )

    chapter_scenes = [
        s
        for s in breakdown_scenes
        if int(s['chapter_idx']) == int(shard['chapter_idx'])
    ]
    if not chapter_scenes:
        raise FatalProviderError(
            f'No scene_breakdown scenes for chapter '
            f'{shard["chapter_idx"]}',
            provider='alignment',
            error_code='missing_chapter_scenes',
        )

    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
        f.write(audio_bytes)
        audio_path = Path(f.name)

    alignment = await elevenlabs_client.force_align(
        audio_path=audio_path,
        text=transcript_text,
        api_key=api_key,
    )
    segment = _segment_from_alignment(transcript_text, alignment)
    try:
        local_scenes = _split_words_into_scenes(
            chapter_scenes,
            segment['words'],
        )
    except ValueError as exc:
        raise FatalProviderError(
            f'Chapter {shard["chapter_idx"]}: {exc}',
            provider='alignment',
            error_code='scene_timing_failed',
        ) from exc

    chapter_span = max(0.0, float(segment['end']))
    return (
        _offset_segment(segment, chapter_offset),
        _offset_scenes(local_scenes, chapter_offset),
        chapter_span,
    )


@register_stage
class AlignmentStage(Stage):
    """Stage 9: ElevenLabs forced alignment and ASS subtitle generation."""

    key = 'alignment'
    queue = 'api'
    max_retries = 2
    timeout_s = 900

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Align TTS audio per chapter, producing scene word timestamps."""
        api_key: str = getattr(settings, 'ELEVENLABS_API_KEY', '')
        if not api_key:
            raise FatalProviderError(
                'ELEVENLABS_API_KEY is not configured',
                provider='elevenlabs',
                error_code='missing_api_key',
            )

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
        breakdown_scenes = ctx.upstream.get('scene_breakdown', {}).get(
            'scenes',
            [],
        )
        if not breakdown_scenes:
            raise FatalProviderError(
                'scene_breakdown has no scenes — cannot build timing map',
                provider='alignment',
                error_code='missing_scene_breakdown',
            )

        all_scenes: list[dict[str, Any]] = []
        all_segments: list[dict[str, Any]] = []
        total_duration_sec = 0.0
        chapter_offset = 0.0
        chapter_origins: dict[int, float] = {}

        for shard in tts_shards:
            chapter_origins[int(shard['chapter_idx'])] = chapter_offset
            segment, scenes, span = await _align_one_chapter(
                shard=shard,
                script_chapters=script_chapters,
                breakdown_scenes=breakdown_scenes,
                api_key=api_key,
                chapter_offset=chapter_offset,
            )
            all_segments.append(segment)
            all_scenes.extend(scenes)
            total_duration_sec += span
            chapter_offset += span

        await ctx.costs.record(
            provider='elevenlabs',
            operation='forced_alignment',
            units=total_duration_sec / 60.0,
            unit_cost_usd=elevenlabs_client.SCRIBE_COST_PER_MINUTE_USD,
        )

        cue_segments = _subtitle_segments_from_scenes(all_scenes)
        if not cue_segments:
            cue_segments = all_segments
        ass_bytes = _build_ass_content(cue_segments)
        ass_asset = await ctx.assets.save(
            kind=AssetKind.SUBTITLE,
            content=ass_bytes,
            filename='captions.ass',
            mime='text/x-ssa',
        )
        srt_bytes = _build_srt_content(cue_segments)
        srt_asset = await ctx.assets.save(
            kind=AssetKind.SUBTITLE,
            content=srt_bytes,
            filename='captions.srt',
            mime='application/x-subrip',
        )
        return {
            'scenes': all_scenes,
            'chapter_origins': chapter_origins,
            'ass_asset_id': str(ass_asset.id),
            'srt_asset_id': str(srt_asset.id),
        }
