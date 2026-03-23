from __future__ import annotations

from pathlib import Path

from django.conf import settings


def _media(subpath: str) -> Path:
    """Return a Path under MEDIA_ROOT, creating parent dirs as needed."""
    p = Path(settings.MEDIA_ROOT) / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── Voiceover ────────────────────────────────────────────────────────────────


def get_voiceover_segment_path(asset_job_id: str, segment_id: int) -> Path:
    """Return path for a single TTS segment file."""
    return _media(f"audio/segments/{asset_job_id}/seg_{segment_id}.mp3")


def get_voiceover_full_path(asset_job_id: str) -> Path:
    """Return path for the merged full voiceover file."""
    return _media(f"audio/full/{asset_job_id}/voiceover.mp3")


# ── Images ────────────────────────────────────────────────────────────────────


def get_image_path(asset_job_id: str, position_idx: int) -> Path:
    """Return path for a background image file."""
    return _media(f"images/{asset_job_id}/{position_idx}.jpg")


def get_thumbnail_path(asset_job_id: str, option_number: int) -> Path:
    """Return path for a thumbnail option file."""
    return _media(f"thumbnails/options/{asset_job_id}/thumb_{option_number}.jpg")


# ── Video clips ───────────────────────────────────────────────────────────────


def get_clip_path(asset_job_id: str, position_idx: int) -> Path:
    """Return path for an animated video clip file."""
    return _media(f"animations/{asset_job_id}/scene_{position_idx}.mp4")


# ── Audio mix ─────────────────────────────────────────────────────────────────


def get_mixed_audio_path(asset_job_id: str) -> Path:
    """Return path for the final mixed audio (voiceover + music)."""
    return _media(f"audio/mixed/{asset_job_id}/mixed.mp3")


# ── Captions ─────────────────────────────────────────────────────────────────


def get_caption_path(production_job_id: str, fmt: str) -> Path:
    """Return path for a caption file. fmt should be 'srt' or 'ass'."""
    return _media(f"captions/{fmt}/{production_job_id}.{fmt}")


# ── Video renders ─────────────────────────────────────────────────────────────


def get_render_path(production_job_id: str, variant: str = "processed") -> Path:
    """Return path for a rendered video file. variant: raw | processed | shorts."""
    return _media(f"renders/{variant}/{production_job_id}_{variant}.mp4")


# ── Clipping ──────────────────────────────────────────────────────────────────


def get_clip_source_path(clipping_job_id: str) -> Path:
    """Return path for the original source video uploaded for a clipping job."""
    return _media(f"clipping/source/{clipping_job_id}/original.mp4")


def get_clip_downloaded_path(clipping_job_id: str) -> Path:
    """Return path for the downloaded source video for a clipping job."""
    return _media(f"clipping/downloaded/{clipping_job_id}/source.mp4")


def get_clip_render_path(clip_candidate_id: str, fmt: str) -> Path:
    """Return path for a rendered clip candidate. fmt: landscape | portrait | square."""
    return _media(f"clipping/renders/{clip_candidate_id}/{fmt}.mp4")
