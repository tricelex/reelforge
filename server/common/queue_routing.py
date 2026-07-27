"""Map logical pipeline queue names to physical TaskIQ worker queues."""

from typing import Literal

PhysicalQueue = Literal['api', 'render']


def physical_queue(logical: str) -> PhysicalQueue:
    """Return the RabbitMQ queue a logical queue name should use.

    ``gpu`` and ``orchestrator`` are routed to the api worker for now.
    """
    if logical == 'render':
        return 'render'
    return 'api'
