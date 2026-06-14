from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.apps.pipelines.models import StageExecution


async def find_cached_output(
    stage_key: str,
    shard_index: int | None,
    input_hash: str,
) -> 'StageExecution | None':
    """Return a SUCCEEDED execution matching the given input_hash.

    Cross-run cache: same inputs produce same outputs, saving API cost.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    return await (
        StageExecution.objects
        .filter(
            stage_key=stage_key,
            shard_index=shard_index,
            input_hash=input_hash,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-created_at')
        .afirst()
    )
