"""ScriptGate stage — orchestrator parks runs; this class is a sentinel."""

from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class ScriptGateStage(Stage):
    """Registered sentinel for the script_gate node."""

    key = 'script_gate'
    queue = 'api'
    max_retries = 0
    timeout_s = 1

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        raise RuntimeError(
            'ScriptGateStage.run() was called directly; '
            'gates are handled by the orchestrator (_park_gate_sync).',
        )
