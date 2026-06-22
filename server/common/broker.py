import os

from decouple import config
from taskiq import TaskiqEvents, TaskiqState
from taskiq_aio_pika import AioPikaBroker
from taskiq_redis import RedisAsyncResultBackend

from server.common.taskiq_middleware import ObservabilityMiddleware

broker = (
    AioPikaBroker(
        config('RABBITMQ_URL', default='amqp://guest:guest@localhost:5672/'),
        declare_exchange_kwargs={'durable': True},
        declare_queues_kwargs={
            'durable': True,
            'arguments': {'x-queue-type': 'quorum'},
        },
    )
    .with_result_backend(
        RedisAsyncResultBackend(
            config('REDIS_URL', default='redis://localhost:6379/0'),
        ),
    )
    .with_middlewares(ObservabilityMiddleware())
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _setup_django(  # pragma: no cover  # noqa: RUF029
    _state: TaskiqState,
) -> None:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
    import django  # noqa: PLC0415

    django.setup()
