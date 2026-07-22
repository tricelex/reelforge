"""CharacterGate stage — orchestrator parks runs; sentinel only."""

from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class CharacterGateStage(Stage):
    """Registered sentinel for the character_gate node."""

    key = 'character_gate'
    queue = 'api'
    max_retries = 0
    timeout_s = 1

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        raise RuntimeError(
            'CharacterGateStage.run() was called directly; '
            'gates are handled by the orchestrator (_park_gate_sync).',
        )
