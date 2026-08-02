# Widens assets_asset_kind_valid to allow PACKAGE — backward-compatible because
# existing rows keep their current kind values; only new PACKAGE rows are added.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('assets', '0009_libraryasset_video_kind'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='asset',
            name='assets_asset_kind_valid',
        ),
        migrations.AlterField(
            model_name='asset',
            name='kind',
            field=models.CharField(
                choices=[
                    ('IMAGE', 'Image'),
                    ('VIDEO_SEGMENT', 'Video Segment'),
                    ('AUDIO_VO', 'Audio VO'),
                    ('SUBTITLE', 'Subtitle'),
                    ('FINAL_VIDEO', 'Final Video'),
                    ('THUMBNAIL', 'Thumbnail'),
                    ('TRANSCRIPT', 'Transcript'),
                    ('DOC', 'Document'),
                    ('FOOTAGE', 'Footage'),
                    ('PACKAGE', 'Package'),
                ],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='asset',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        'kind__in',
                        [
                            'IMAGE',
                            'VIDEO_SEGMENT',
                            'AUDIO_VO',
                            'SUBTITLE',
                            'FINAL_VIDEO',
                            'THUMBNAIL',
                            'TRANSCRIPT',
                            'DOC',
                            'FOOTAGE',
                            'PACKAGE',
                        ],
                    ),
                ),
                name='assets_asset_kind_valid',
            ),
        ),
    ]
