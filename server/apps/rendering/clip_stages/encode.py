"""Shared FFmpeg encode flags for clip filter stages."""


def clip_filter_encode_args(
    *,
    crf: int,
    preset: str,
    fps: int = 30,
    audio_bitrate: str = '192k',
) -> list[str]:
    """Return libx264 + AAC flags for filter stages."""
    return [
        '-c:v',
        'libx264',
        '-crf',
        str(crf),
        '-preset',
        preset,
        '-pix_fmt',
        'yuv420p',
        '-fps_mode',
        'cfr',
        '-r',
        str(fps),
        '-c:a',
        'aac',
        '-b:a',
        audio_bitrate,
    ]
