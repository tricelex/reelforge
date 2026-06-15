from django.db import migrations


_UP = """
CREATE MATERIALIZED VIEW analytics_run_cost_summary AS
SELECT
    r.id                                                            AS run_id,
    r.channel_id,
    r.status,
    r.topic,
    r.total_cost_usd,
    r.created_at,
    r.started_at,
    r.finished_at,
    CASE
        WHEN r.finished_at IS NOT NULL AND r.started_at IS NOT NULL
        THEN EXTRACT(EPOCH FROM (r.finished_at - r.started_at))
        ELSE NULL
    END                                                             AS duration_s,
    (
        SELECT jsonb_object_agg(agg.provider, agg.total)
        FROM (
            SELECT cr2.provider, SUM(cr2.total_usd) AS total
            FROM pipelines_stageexecution se2
            LEFT JOIN pipelines_costrecord cr2 ON cr2.stage_execution_id = se2.id
            WHERE se2.run_id = r.id
              AND se2.parent_id IS NULL
              AND cr2.provider IS NOT NULL
            GROUP BY cr2.provider
        ) agg
    )                                                               AS cost_by_provider
FROM pipelines_pipelinerun r
WHERE r.status IN ('COMPLETED', 'FAILED')
WITH DATA;

CREATE UNIQUE INDEX analytics_run_cost_summary_run_id
    ON analytics_run_cost_summary (run_id);

CREATE MATERIALIZED VIEW analytics_channel_roi AS
SELECT
    c.id                                                            AS channel_id,
    c.name                                                          AS channel_name,
    COUNT(r.id)                                                     AS run_count,
    COUNT(r.id) FILTER (WHERE r.status = 'COMPLETED')              AS completed_count,
    COALESCE(SUM(r.total_cost_usd), 0)                             AS total_spend_usd,
    AVG(r.total_cost_usd) FILTER (WHERE r.status = 'COMPLETED')    AS avg_cost_usd
FROM channels_channel c
LEFT JOIN pipelines_pipelinerun r ON r.channel_id = c.id
GROUP BY c.id, c.name
WITH DATA;

CREATE UNIQUE INDEX analytics_channel_roi_channel_id
    ON analytics_channel_roi (channel_id);

CREATE MATERIALIZED VIEW analytics_stage_performance AS
SELECT
    ROW_NUMBER() OVER ()                                            AS id,
    se.stage_key,
    r.channel_id,
    COUNT(se.id)                                                    AS execution_count,
    AVG(
        EXTRACT(EPOCH FROM (se.finished_at - se.started_at))
    )                                                               AS avg_duration_s,
    COALESCE(SUM(cr.total_usd), 0)                                 AS total_cost_usd,
    AVG(cr.total_usd)                                               AS avg_cost_per_execution_usd
FROM pipelines_stageexecution se
JOIN pipelines_pipelinerun r ON r.id = se.run_id
LEFT JOIN pipelines_costrecord cr ON cr.stage_execution_id = se.id
WHERE se.status = 'SUCCEEDED' AND se.parent_id IS NULL
GROUP BY se.stage_key, r.channel_id
WITH DATA;

CREATE INDEX analytics_stage_performance_channel_id
    ON analytics_stage_performance (channel_id);
"""

_DOWN = """
DROP MATERIALIZED VIEW IF EXISTS analytics_stage_performance;
DROP MATERIALIZED VIEW IF EXISTS analytics_channel_roi;
DROP MATERIALIZED VIEW IF EXISTS analytics_run_cost_summary;
"""


class Migration(migrations.Migration):
    """Create three PostgreSQL materialized views for analytics."""

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.RunSQL(sql=_UP, reverse_sql=_DOWN),
    ]
