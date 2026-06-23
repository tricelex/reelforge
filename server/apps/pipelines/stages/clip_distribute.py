"""ClipDistribute stage — fan-out per pending ClipPost → post to platform."""

from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class ClipDistributeStage(Stage):
    """Stage 6: fan-out per ClipPost → post to social platform (stub)."""

    key = 'clip_distribute'
    queue = 'api'
    max_retries = 2
    timeout_s = 600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Return one shard per pending ClipPost, or None if there are none."""
        from server.apps.clips.logic.constants import (  # noqa: PLC0415
            PostStatus,
        )
        from server.apps.clips.models import ClipPost  # noqa: PLC0415

        posts = list(
            ClipPost.objects.filter(
                candidate__run=ctx.run,
                status=PostStatus.PENDING,
            ).values('id'),
        )
        if not posts:
            return None
        return [{'post_id': str(p['id'])} for p in posts]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Post clip to social platform (stub — not yet implemented)."""
        post_id: str = ctx.execution.input_snapshot.get('post_id', '')
        return {'post_id': post_id, 'status': 'skipped_stub'}
