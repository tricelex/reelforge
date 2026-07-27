import os

from decouple import config
from taskiq import TaskiqEvents, TaskiqState
from taskiq_aio_pika import AioPikaBroker
from taskiq_redis import RedisAsyncResultBackend

from server.common.taskiq_middleware import (
    DjangoDbMiddleware,
    ObservabilityMiddleware,
)


def _build_broker(queue_name: str) -> AioPikaBroker:
    return (
        AioPikaBroker(
            config('RABBITMQ_URL', default='amqp://guest:guest@localhost:5672/'),
            queue_name=queue_name,
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
        .with_middlewares(DjangoDbMiddleware(), ObservabilityMiddleware())
    )


api_broker = _build_broker('api')
render_broker = _build_broker('render')

# Backward-compatible alias — api queue is the default broker.
broker = api_broker


def _register_django_startup(target_broker: AioPikaBroker) -> None:
    @target_broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def _setup_django(  # pragma: no cover  # noqa: RUF029
        _state: TaskiqState,
    ) -> None:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
        import django  # noqa: PLC0415

        django.setup()


_register_django_startup(api_broker)
_register_django_startup(render_broker)
