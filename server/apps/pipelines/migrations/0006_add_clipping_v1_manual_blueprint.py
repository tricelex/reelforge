from django.db import migrations

_CLIPPING_V1_MANUAL_GRAPH = {
    'stages': [
        {'key': 'clip_ingest', 'depends_on': []},
        {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
        {'key': 'clip_manual_setup', 'depends_on': ['clip_transcribe']},
        {
            'key': 'clip_approval_gate',
            'depends_on': ['clip_manual_setup'],
            'gate': True,
        },
        {'key': 'clip_render', 'depends_on': ['clip_approval_gate']},
        {'key': 'clip_distribute', 'depends_on': ['clip_render']},
    ],
}


def _add_blueprint(apps, schema_editor):
    PipelineBlueprint = apps.get_model('pipelines', 'PipelineBlueprint')
    PipelineBlueprint.objects.get_or_create(
        name='clipping_v1_manual',
        defaults={
            'kind': 'CLIPPING',
            'graph': _CLIPPING_V1_MANUAL_GRAPH,
            'is_active': True,
            'version': 1,
        },
    )


def _remove_blueprint(apps, schema_editor):
    PipelineBlueprint = apps.get_model('pipelines', 'PipelineBlueprint')
    PipelineBlueprint.objects.filter(name='clipping_v1_manual').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('pipelines', '0005_phase7'),
    ]

    operations = [
        migrations.RunPython(_add_blueprint, _remove_blueprint),
    ]
