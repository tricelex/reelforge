"""Quieter music bed default and optional background-music toggle."""

from django.db import migrations, models


def quiet_default_music_beds(apps, schema_editor) -> None:
    """Bump channels still on the old -18 default to the quieter -22 bed."""
    AssemblyStyleConfig = apps.get_model('channels', 'AssemblyStyleConfig')
    AssemblyStyleConfig.objects.filter(music_bed_gain_db=-18.0).update(
        music_bed_gain_db=-22.0,
    )


def restore_legacy_music_beds(apps, schema_editor) -> None:
    """Reverse: restore -22 beds that match the new default back to -18."""
    AssemblyStyleConfig = apps.get_model('channels', 'AssemblyStyleConfig')
    AssemblyStyleConfig.objects.filter(music_bed_gain_db=-22.0).update(
        music_bed_gain_db=-18.0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0009_seed_footage_sourcing_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='assemblystyleconfig',
            name='enable_background_music',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'When false, assembly mixes voiceover only '
                    '(no music bed).'
                ),
            ),
        ),
        migrations.AlterField(
            model_name='assemblystyleconfig',
            name='music_bed_gain_db',
            field=models.FloatField(
                default=-22.0,
                help_text=(
                    'Background music gain in dB relative to dialogue.'
                ),
            ),
        ),
        migrations.RunPython(
            quiet_default_music_beds,
            restore_legacy_music_beds,
        ),
    ]
