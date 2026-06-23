"""Abstract base for clip render stages."""

from abc import ABC, abstractmethod
from pathlib import Path


class RenderStageError(Exception):
    """Raised when a render stage fails, wrapping the underlying cause."""

    def __init__(
        self,
        stage_name: str,
        stage_order: int,
        cause: Exception,
    ) -> None:
        """Initialise with stage identity and the wrapped exception."""
        self.stage_name = stage_name
        self.stage_order = stage_order
        self.cause = cause
        super().__init__(
            f'Stage {stage_order} ({stage_name}) failed: {cause}',
        )


class RenderStage(ABC):
    """Abstract base for a single clip render stage."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this stage."""
        ...

    @property
    @abstractmethod
    def order(self) -> int:
        """Execution order (1-indexed)."""
        ...

    def should_run(self) -> bool:
        """Return True if this stage should execute."""
        return True

    @abstractmethod
    def run(self, input_path: Path) -> Path:
        """Execute the stage and return the output path."""
        ...
