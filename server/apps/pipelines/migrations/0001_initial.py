import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('channels', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PipelineBlueprint',
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
                ('name', models.CharField(max_length=100)),
                (
                    'kind',
                    models.CharField(
                        choices=[
                            ('LONGFORM', 'Long-form'),
                            ('SHORTS', 'Shorts'),
                            ('CLIPPING', 'Clipping'),
                        ],
                        max_length=10,
                    ),
                ),
                ('graph', models.JSONField()),
                ('is_active', models.BooleanField(default=True)),
                ('version', models.PositiveIntegerField(default=1)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='PipelineRun',
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
                ('blueprint_snapshot', models.JSONField()),
                ('prompt_snapshot', models.JSONField(default=dict)),
                ('topic', models.TextField()),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('PENDING', 'Pending'),
                            ('RUNNING', 'Running'),
                            ('AWAITING_REVIEW', 'Awaiting review'),
                            ('BUDGET_HOLD', 'Budget hold'),
                            ('PUBLISHING', 'Publishing'),
                            ('COMPLETED', 'Completed'),
                            ('FAILED', 'Failed'),
                            ('CANCELLED', 'Cancelled'),
                        ],
                        default='PENDING',
                        max_length=20,
                    ),
                ),
                (
                    'total_cost_usd',
                    models.DecimalField(
                        decimal_places=4, default=0, max_digits=10
                    ),
                ),
                (
                    'started_at',
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    'finished_at',
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    'blueprint',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='runs',
                        to='pipelines.pipelineblueprint',
                    ),
                ),
                (
                    'channel',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='runs',
                        to='channels.channel',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='StageExecution',
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
                    'stage_key',
                    models.CharField(db_index=True, max_length=64),
                ),
                (
                    'shard_index',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('PENDING', 'Pending'),
                            ('QUEUED', 'Queued'),
                            ('RUNNING', 'Running'),
                            ('SUCCEEDED', 'Succeeded'),
                            ('FAILED', 'Failed'),
                            ('NEEDS_INPUT', 'Needs input'),
                            ('SKIPPED', 'Skipped'),
                            ('STALE', 'Stale'),
                            ('CANCELLED', 'Cancelled'),
                        ],
                        default='PENDING',
                        max_length=15,
                    ),
                ),
                ('attempt', models.PositiveIntegerField(default=0)),
                ('max_retries', models.PositiveIntegerField(default=3)),
                (
                    'input_hash',
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ('input_snapshot', models.JSONField(default=dict)),
                ('output', models.JSONField(default=dict)),
                ('error', models.JSONField(blank=True, null=True)),
                (
                    'cost_usd',
                    models.DecimalField(
                        decimal_places=4, default=0, max_digits=10
                    ),
                ),
                ('queue', models.CharField(default='api', max_length=32)),
                (
                    'started_at',
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    'finished_at',
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    'parent',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='children',
                        to='pipelines.stageexecution',
                    ),
                ),
                (
                    'run',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='stages',
                        to='pipelines.pipelinerun',
                    ),
                ),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(
                        fields=['run', 'stage_key', 'shard_index', 'attempt'],
                        name='uq_stage_attempt',
                        nulls_distinct=False,
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name='CostRecord',
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
                ('provider', models.CharField(max_length=32)),
                ('operation', models.CharField(max_length=64)),
                (
                    'units',
                    models.DecimalField(decimal_places=4, max_digits=12),
                ),
                (
                    'unit_cost_usd',
                    models.DecimalField(decimal_places=6, max_digits=10),
                ),
                (
                    'total_usd',
                    models.DecimalField(decimal_places=4, max_digits=10),
                ),
                (
                    'stage_execution',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='costs',
                        to='pipelines.stageexecution',
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name='RunCast',
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
                ('role', models.CharField(max_length=60)),
                ('is_ephemeral', models.BooleanField(default=False)),
                (
                    'design_status',
                    models.CharField(
                        choices=[
                            ('PROPOSED', 'Proposed'),
                            ('APPROVED', 'Approved'),
                            ('DEMOTED', 'Demoted'),
                        ],
                        default='PROPOSED',
                        max_length=10,
                    ),
                ),
                (
                    'character',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='+',
                        to='channels.character',
                    ),
                ),
                (
                    'run',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='cast',
                        to='pipelines.pipelinerun',
                    ),
                ),
            ],
        ),
    ]
