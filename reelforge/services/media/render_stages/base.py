from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class RenderStageError(Exception):
    """Raised when a pipeline render stage fails.

    Wraps the original exception with stage identity so callers know exactly
    which stage failed without parsing error strings.
    """

    def __init__(self, stage_name: str, stage_order: int, cause: Exception) -> None:
        self.stage_name = stage_name
        self.stage_order = stage_order
        self.cause = cause
        super().__init__(f"Stage {stage_order} ({stage_name}) failed: {cause}")


class RenderStage(ABC):
    """Abstract base for a single pipeline render stage.

    Each stage reads one video file, processes it, writes a new file,
    and returns the output path. If should_run() returns False the stage
    is marked SKIPPED and the input path is passed through unchanged.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short snake_case identifier, e.g. 'trim_and_crop'."""
        ...

    @property
    @abstractmethod
    def order(self) -> int:
        """1-based position in the pipeline."""
        ...

    def should_run(self) -> bool:
        """Return False to mark this stage SKIPPED."""
        return True

    @abstractmethod
    def run(self, input_path: Path) -> Path:
        """Process input_path, write output to a new file, return its path."""
        ...
