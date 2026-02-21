from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import RootModel


class AgentDecision(BaseModel):
    """Decision recorded by OrchestratorAgent after each stage evaluation."""

    action: str = ""  # "advance" | "retry" | "pause" | "failed" | "approve"
    reason: str = ""
    score: float | None = None
    stage: str = ""


class EventMetadata(RootModel[dict[str, Any]]):
    """Freeform audit event data — structure varies per event_type."""

    root: dict[str, Any] = {}
