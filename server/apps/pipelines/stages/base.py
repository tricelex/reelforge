import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from server.apps.channels.models import Channel
    from server.apps.pipelines.models import PipelineRun, StageExecution
    from server.apps.pipelines.services.asset_writer import AssetWriter
    from server.apps.pipelines.services.cost_recorder import CostRecorder
    from server.apps.pipelines.services.prompt_renderer import PromptRenderer


@dataclass(frozen=True)
class StageContext:
    """Immutable context passed to every Stage.run() invocation."""

    run: 'PipelineRun'
    execution: 'StageExecution'
    channel: 'Channel'
    config: dict[str, Any]
    upstream: dict[str, dict[str, Any]]
    prompts: 'PromptRenderer'
    costs: 'CostRecorder'
    assets: 'AssetWriter'


STAGE_REGISTRY: dict[str, type['Stage']] = {}


def register_stage(cls: type['Stage']) -> type['Stage']:
    """Register a Stage subclass in the global registry by its key."""
    STAGE_REGISTRY[cls.key] = cls
    return cls


class Stage(ABC):
    """Abstract base class for all pipeline stages."""

    key: ClassVar[str]
    queue: ClassVar[str] = 'api'
    max_retries: ClassVar[int] = 3
    timeout_s: ClassVar[int] = 600

    @abstractmethod
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Execute the stage and return the output dict."""
        ...

    def fan_out(
        self,
        ctx: StageContext,
    ) -> list[dict[str, Any]] | None:
        """Return per-shard input dicts to spawn child executions, or None."""
        return None


def compute_input_hash(input_snapshot: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON serialization of input_snapshot."""
    canonical = json.dumps(input_snapshot, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
