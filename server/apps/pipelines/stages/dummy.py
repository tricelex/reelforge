from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class DummyStageA(Stage):
    """Test-only stage: returns {'result': 'a_done'}."""

    key = 'dummy_a'
    queue = 'api'
    max_retries = 1
    timeout_s = 30

    async def run(self, ctx: StageContext) -> dict:
        """Return a fixed output for testing."""
        return {'result': 'a_done'}


@register_stage
class DummyStageB(Stage):
    """Test-only stage: echoes dummy_a output and returns 'b_done'."""

    key = 'dummy_b'
    queue = 'api'
    max_retries = 1
    timeout_s = 30

    async def run(self, ctx: StageContext) -> dict:
        """Return output including upstream dummy_a result."""
        upstream_a = ctx.upstream.get('dummy_a', {})
        return {'result': 'b_done', 'saw_a': upstream_a.get('result')}


@register_stage
class DummyStageC(Stage):
    """Test-only stage: returns {'result': 'c_done'}."""

    key = 'dummy_c'
    queue = 'api'
    max_retries = 1
    timeout_s = 30

    async def run(self, ctx: StageContext) -> dict:
        """Return a fixed output for testing."""
        return {'result': 'c_done'}
