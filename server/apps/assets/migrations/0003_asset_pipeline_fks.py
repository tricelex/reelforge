# Generated manually — Phase 2 additive FKs for Asset -> PipelineRun / StageExecution

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0002_initial'),
        ('pipelines', '0002_pipelineblueprint_pipelines_pipelineblueprint_kind_valid_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='run',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assets',
                to='pipelines.pipelinerun',
            ),
        ),
        migrations.AddField(
            model_name='asset',
            name='stage_execution',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assets',
                to='pipelines.stageexecution',
            ),
        ),
    ]
