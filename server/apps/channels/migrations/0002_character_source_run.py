# Generated manually — Phase 2 additive FK for Character -> PipelineRun

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0001_initial'),
        ('pipelines', '0002_pipelineblueprint_pipelines_pipelineblueprint_kind_valid_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='character',
            name='source_run',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='pipelines.pipelinerun',
            ),
        ),
    ]
