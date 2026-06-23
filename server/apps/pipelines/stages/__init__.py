"""Import all production pipeline stages to populate STAGE_REGISTRY."""

from server.apps.pipelines.stages import (
    alignment,  # noqa: F401
    assembly,  # noqa: F401
    clip_analyze,  # noqa: F401
    clip_approval_gate,  # noqa: F401
    clip_distribute,  # noqa: F401
    clip_ingest,  # noqa: F401
    clip_render,  # noqa: F401
    clip_transcribe,  # noqa: F401
    image_gen,  # noqa: F401
    metadata,  # noqa: F401
    motion,  # noqa: F401
    music_plan,  # noqa: F401
    outline,  # noqa: F401
    publish,  # noqa: F401
    qc,  # noqa: F401
    research,  # noqa: F401
    review_gate,  # noqa: F401
    scene_breakdown,  # noqa: F401
    script,  # noqa: F401
    thumbnail,  # noqa: F401
    tts,  # noqa: F401
    visual_prompts,  # noqa: F401
)
