"""Motion stage — fan-out: Kling I2V for heroes, Ken Burns otherwise."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, override

import httpx

from server.apps.assets.models import Asset, AssetKind
from server.apps.generation.clients import fal as fal_client
from server.apps.pipelines.logic.pool_rotation import pick_cyclic
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

_KEN_BURNS_PRESETS = [
    "zoompan=z='zoom+0.001':d=150:s=1920x1080",
    "zoompan=z='1.08-0.001*on':d=150:s=1920x1080",
    "zoompan=x='iw/2-(iw/zoom/2)+on*2':z=1.05:d=150:s=1920x1080",
    "zoompan=x='iw-(iw/zoom/2)-on*2':z=1.05:d=150:s=1920x1080",
]

_DEFAULT_CAMERA_MOVEMENT = 'push_in'
_MOVEMENT_PROMPT_PHRASES = {
    'push_in': 'Slow cinematic push-in',
    'pan_left': 'Smooth pan left',
    'pan_right': 'Smooth pan right',
    'static_hold': 'Static hold with subtle parallax',
}


def _pick_camera_movement(pool: list[str], scene_idx: int) -> str:
    """Cycle through the channel's camera-movement pool by scene index."""
    return pick_cyclic(pool, scene_idx, _DEFAULT_CAMERA_MOVEMENT)


async def _load_image_asset(asset_id: str) -> Asset:
    """Load the scene image Asset; raise if id is missing."""
    assert asset_id, 'asset_id is required'
    return await Asset.objects.aget(id=asset_id)


async def _run_ken_burns(
    image_bytes: bytes,
    duration_s: float,
    preset_idx: int = 0,
) -> bytes:
    """Apply Ken Burns zoom/pan to image bytes via FFmpeg subprocess."""
    assert image_bytes, 'image_bytes must be non-empty'
    assert duration_s > 0, f'duration_s must be > 0, got {duration_s}'

    with (
        tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as img_f,
        tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as vid_f,
    ):
        img_path = img_f.name
        vid_path = vid_f.name
    await asyncio.to_thread(Path(img_path).write_bytes, image_bytes)

    frames = int(duration_s * 30)
    vf = _KEN_BURNS_PRESETS[preset_idx % len(_KEN_BURNS_PRESETS)].replace(
        'd=150',
        f'd={frames}',
    )
    cmd = [
        'ffmpeg',
        '-y',
        '-loop',
        '1',
        '-i',
        img_path,
        '-vf',
        vf,
        '-t',
        str(duration_s),
        '-r',
        '30',
        '-c:v',
        'libx264',
        '-crf',
        '16',
        '-pix_fmt',
        'yuv420p',
        '-an',
        vid_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f'FFmpeg Ken Burns failed: {stderr.decode()[:300]}')

    video_bytes = await asyncio.to_thread(Path(vid_path).read_bytes)
    assert video_bytes, 'Ken Burns produced empty video'
    return video_bytes


@register_stage
class MotionStage(Stage):
    """Stage 8: add motion to each scene image (fan-out)."""

    key = 'motion'
    queue = 'render'
    max_retries = 2
    timeout_s = 600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Shard by scene — one child per image_gen shard result."""
        shards = ctx.upstream.get('image_gen', {}).get('shards', [])
        scenes_map = {
            s['idx']: s
            for s in ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        }
        return [
            {
                'scene_idx': sh['scene_idx'],
                'asset_id': sh['asset_id'],
                'is_hero': scenes_map.get(sh['scene_idx'], {}).get(
                    'is_hero',
                    False,
                ),
                'est_seconds': scenes_map.get(sh['scene_idx'], {}).get(
                    'est_seconds',
                    8.0,
                ),
                'visual_concept': scenes_map.get(sh['scene_idx'], {}).get(
                    'visual_concept',
                    '',
                ),
            }
            for sh in shards
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Apply Kling I2V or Ken Burns motion to the scene."""
        snap = ctx.execution.input_snapshot
        scene_idx: int = snap['scene_idx']
        asset_id: str = snap.get('asset_id', '')
        is_hero: bool = snap.get('is_hero', False)
        est_seconds: float = snap.get('est_seconds', 8.0)
        visual_concept: str = snap.get('visual_concept', '')

        if not asset_id:
            raise ValueError(
                f'Motion scene {scene_idx}: missing asset_id '
                '(image_gen must return asset_id)',
            )

        image_asset = await _load_image_asset(asset_id)

        if is_hero:
            image_url = image_asset.file.url if image_asset.file else ''
            if not image_url:
                raise ValueError(
                    f'Motion scene {scene_idx}: asset {asset_id} '
                    'has no file URL for Kling I2V',
                )
            model = ctx.config.get(
                'i2v_model',
                'fal-ai/kling-video/v2.1/standard/image-to-video',
            )
            movement_pool = getattr(
                ctx.channel,
                'assembly_style_camera_movements',
                [],
            )
            movement = _pick_camera_movement(movement_pool, scene_idx)
            phrase = _MOVEMENT_PROMPT_PHRASES.get(
                movement,
                _MOVEMENT_PROMPT_PHRASES[_DEFAULT_CAMERA_MOVEMENT],
            )
            result = await fal_client.generate_video_kling(
                image_url=image_url,
                prompt=f'{phrase}. Cinematic motion. {visual_concept}',
                duration=5,
                model=model,
            )
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(result['video_url'])
                resp.raise_for_status()
                video_bytes = resp.content
            method = 'kling'
            await ctx.costs.record(
                provider='kling',
                operation='i2v_5s',
                units=1,
                unit_cost_usd=0.52,
            )
        else:
            image_bytes = await asyncio.to_thread(image_asset.file.read)
            video_bytes = await _run_ken_burns(
                image_bytes=image_bytes,
                duration_s=est_seconds,
                preset_idx=scene_idx,
            )
            method = 'ken_burns'

        asset = await ctx.assets.save(
            kind=AssetKind.VIDEO_SEGMENT,
            content=video_bytes,
            filename=f'scene_{scene_idx:04d}_{method}.mp4',
            mime='video/mp4',
        )
        return {
            'scene_idx': scene_idx,
            'asset_id': str(asset.id),
            'duration_s': est_seconds,
            'method': method,
        }
