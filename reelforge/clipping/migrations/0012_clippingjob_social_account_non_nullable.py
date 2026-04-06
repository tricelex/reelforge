from __future__ import annotations

import django.db.models.deletion
from django.db import migrations
from django.db import models


# SQL to clean up clipping jobs that have no social_account assigned (dev data only).
# Must cascade through child tables in FK order before deleting the parent rows.
_CLEANUP_SQL = """
DO $$
DECLARE
    orphan_job_ids UUID[];
BEGIN
    SELECT ARRAY(
        SELECT id FROM clipping_clippingjob WHERE social_account_id IS NULL
    ) INTO orphan_job_ids;

    IF array_length(orphan_job_ids, 1) IS NULL THEN
        RETURN;
    END IF;

    -- Delete cascade order: stage_results → posts → renders → timed_overlays
    --   → style_configs → layout_configs → candidates → clippingjobs
    DELETE FROM clipping_cliprenderstageresult
      WHERE render_id IN (
        SELECT id FROM clipping_cliprender
         WHERE candidate_id IN (
           SELECT id FROM clipping_clipcandidate WHERE clipping_job_id = ANY(orphan_job_ids)
         )
      );
    DELETE FROM clipping_clippost
      WHERE render_id IN (
        SELECT id FROM clipping_cliprender
         WHERE candidate_id IN (
           SELECT id FROM clipping_clipcandidate WHERE clipping_job_id = ANY(orphan_job_ids)
         )
      );
    DELETE FROM clipping_cliprender
      WHERE candidate_id IN (
        SELECT id FROM clipping_clipcandidate WHERE clipping_job_id = ANY(orphan_job_ids)
      );
    DELETE FROM clipping_cliptimedoverlay  WHERE candidate_id IN (
        SELECT id FROM clipping_clipcandidate WHERE clipping_job_id = ANY(orphan_job_ids)
    );
    DELETE FROM clipping_clipstyleconfig   WHERE candidate_id IN (
        SELECT id FROM clipping_clipcandidate WHERE clipping_job_id = ANY(orphan_job_ids)
    );
    DELETE FROM clipping_cliplayoutconfig WHERE candidate_id IN (
        SELECT id FROM clipping_clipcandidate WHERE clipping_job_id = ANY(orphan_job_ids)
    );
    DELETE FROM clipping_clipcandidate WHERE clipping_job_id = ANY(orphan_job_ids);
    DELETE FROM clipping_clippingjob    WHERE id = ANY(orphan_job_ids);
END $$;
"""


class Migration(migrations.Migration):
    # Run outside a transaction so that each statement commits independently.
    atomic = False

    dependencies = [
        ("channels", "0011_channel_default_render_mode"),
        ("clipping", "0011_clippingjob_remove_channel_add_social_account"),
    ]

    operations = [
        # Delete any dev rows whose social_account_id is null before making it non-nullable.
        migrations.RunSQL(
            sql=_CLEANUP_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="clippingjob",
            name="social_account",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clipping_jobs",
                to="channels.socialaccount",
            ),
        ),
    ]
