import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.apps.pipelines.models import StageExecution


async def find_cached_output(
    run_id: uuid.UUID,
    stage_key: str,
    shard_index: int | None,
    input_hash: str,
) -> 'StageExecution | None':
    """Return a SUCCEEDED execution matching the given input_hash.

    Scoped to this run only. Stages have side effects tied to run identity
    (e.g. cast_proposal creates RunCast/Character rows, image/tts/motion
    stages save Assets owned by the current run) and prompt content is
    seeded from channel data (niche, lore, branding, cast) that isn't part
    of the hash — a cross-run/cross-channel cache would silently reuse
    another run's output and skip those side effects entirely.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    return await (
        StageExecution.objects
        .filter(
            run_id=run_id,
            stage_key=stage_key,
            shard_index=shard_index,
            input_hash=input_hash,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-created_at')
        .afirst()
    )
