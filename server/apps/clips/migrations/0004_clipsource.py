# Generated manually for ClipSource model

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('channels', '0002_character_source_run'),
        ('clips', '0003_phase7'),
        ('pipelines', '0002_pipelineblueprint_pipelines_pipelineblueprint_kind_valid_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClipSource',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'source_type',
                    models.CharField(
                        choices=[
                            ('youtube', 'YouTube'),
                            ('rss', 'RSS'),
                            ('upload', 'Upload'),
                        ],
                        max_length=10,
                    ),
                ),
                ('url', models.TextField(blank=True)),
                ('library_asset_id', models.UUIDField(blank=True, null=True)),
                ('title', models.CharField(blank=True, max_length=300)),
                ('duration_sec', models.FloatField(blank=True, null=True)),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('INGESTING', 'Ingesting'),
                            ('READY', 'Ready'),
                            ('FAILED', 'Failed'),
                        ],
                        default='INGESTING',
                        max_length=10,
                    ),
                ),
                ('error_message', models.TextField(blank=True)),
                (
                    'campaign',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='clip_sources',
                        to='clips.clipcampaign',
                    ),
                ),
                (
                    'channel',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='clip_sources',
                        to='channels.channel',
                    ),
                ),
                (
                    'run',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='clip_sources',
                        to='pipelines.pipelinerun',
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name='clipsource',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('status__in', ['INGESTING', 'READY', 'FAILED']),
                ),
                name='clips_clipsource_status_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='clipsource',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('source_type__in', ['youtube', 'rss', 'upload']),
                ),
                name='clips_clipsource_type_valid',
            ),
        ),
    ]
