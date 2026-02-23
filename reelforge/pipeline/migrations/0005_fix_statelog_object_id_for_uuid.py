from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    """Alter django_fsm_log.StateLog.object_id from PositiveIntegerField to VARCHAR(255).

    The installed django-fsm-log uses PositiveIntegerField for object_id, which is
    incompatible with our UUID primary keys. This migration alters the column type in
    the database so FSM transition logging works correctly with all our models.
    """

    dependencies = [
        ("django_fsm_log", "0004_add_source_state"),
        ("pipeline", "0004_alter_pipelineevent_metadata_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE django_fsm_log_statelog
                    DROP CONSTRAINT IF EXISTS django_fsm_log_statelog_object_id_check,
                    ALTER COLUMN object_id TYPE varchar(255);
            """,
            reverse_sql="""
                ALTER TABLE django_fsm_log_statelog
                    ALTER COLUMN object_id TYPE integer USING object_id::integer;
            """,
        ),
    ]
