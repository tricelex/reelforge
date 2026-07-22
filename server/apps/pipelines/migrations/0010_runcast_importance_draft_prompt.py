# Generated manually for RunCast importance / draft_prompt / TEXT_ONLY

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pipelines', '0009_pipelinerun_had_manual_edits'),
    ]

    operations = [
        migrations.AddField(
            model_name='runcast',
            name='draft_prompt',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='runcast',
            name='importance',
            field=models.CharField(
                choices=[
                    ('MAIN', 'Main'),
                    ('SECONDARY', 'Secondary'),
                    ('BACKGROUND', 'Background'),
                ],
                default='SECONDARY',
                max_length=10,
            ),
        ),
        migrations.RemoveConstraint(
            model_name='runcast',
            name='pipelines_runcast_design_status_valid',
        ),
        migrations.AddConstraint(
            model_name='runcast',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    design_status__in=[
                        'PROPOSED',
                        'APPROVED',
                        'DEMOTED',
                        'TEXT_ONLY',
                    ],
                ),
                name='pipelines_runcast_design_status_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='runcast',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    importance__in=['MAIN', 'SECONDARY', 'BACKGROUND'],
                ),
                name='pipelines_runcast_importance_valid',
            ),
        ),
    ]
