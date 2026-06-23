"""TaskIQ tasks for analytics view maintenance."""

from server.common.broker import broker


@broker.task(retry_on_error=False, queue='api')
async def refresh_analytics_views() -> None:
    """REFRESH MATERIALIZED VIEW CONCURRENTLY for all three analytics views."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415
    from django.db import connection  # noqa: PLC0415

    views = [
        'analytics_run_cost_summary',
        'analytics_channel_roi',
        'analytics_stage_performance',
    ]

    def _refresh() -> None:
        with connection.cursor() as cursor:
            for view in views:
                cursor.execute(
                    f'REFRESH MATERIALIZED VIEW CONCURRENTLY {view}',
                )

    await sync_to_async(_refresh)()
