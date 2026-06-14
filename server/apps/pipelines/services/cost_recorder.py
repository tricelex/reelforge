from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.apps.pipelines.models import StageExecution


class CostRecorder:
    """Records provider cost entries; accumulates total for an execution."""

    def __init__(self, execution: 'StageExecution') -> None:
        """Initialise with the StageExecution that will own the costs."""
        self._execution = execution
        self._total = Decimal(0)

    async def record(
        self,
        provider: str,
        operation: str,
        units: float | Decimal,
        unit_cost_usd: float | Decimal,
    ) -> None:
        """Write a CostRecord row and add to the running total."""
        from server.apps.pipelines.models import CostRecord  # noqa: PLC0415

        units_d = Decimal(str(units))
        unit_cost_d = Decimal(str(unit_cost_usd))
        total = units_d * unit_cost_d
        await CostRecord.objects.acreate(
            stage_execution=self._execution,
            provider=provider,
            operation=operation,
            units=units_d,
            unit_cost_usd=unit_cost_d,
            total_usd=total,
        )
        self._total += total

    @property
    def total_usd(self) -> Decimal:
        """Return accumulated cost in USD across all recorded entries."""
        return self._total
