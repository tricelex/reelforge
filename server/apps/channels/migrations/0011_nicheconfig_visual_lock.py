"""Persist NicheConfig visual bible, medium, tokens, and negatives."""

import django.contrib.***REMOVED***.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0010_assemblystyle_music_bed_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='nicheconfig',
            name='style_negatives',
            field=django.contrib.***REMOVED***.fields.ArrayField(
                base_field=models.CharField(max_length=80),
                blank=True,
                db_default=[],
                default=list,
            ),
        ),
        migrations.AddField(
            model_name='nicheconfig',
            name='style_tokens',
            field=django.contrib.***REMOVED***.fields.ArrayField(
                base_field=models.CharField(max_length=80),
                blank=True,
                db_default=[],
                default=list,
            ),
        ),
        migrations.AddField(
            model_name='nicheconfig',
            name='visual_bible',
            field=models.TextField(blank=True, db_default=''),
        ),
        migrations.AddField(
            model_name='nicheconfig',
            name='visual_medium',
            field=models.CharField(
                blank=True,
                choices=[
                    ('2d_animation', '2D animation'),
                    ('3d_cgi', '3D CGI'),
                    ('motion_graphics', 'Motion graphics'),
                    ('photoreal', 'Photoreal'),
                    ('live_action_stock', 'Live-action stock'),
                    ('mixed', 'Mixed'),
                ],
                db_default='',
                default='',
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name='nicheconfig',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        'visual_medium__in',
                        [
                            '2d_animation',
                            '3d_cgi',
                            'motion_graphics',
                            'photoreal',
                            'live_action_stock',
                            'mixed',
                            '',
                        ],
                    ),
                ),
                name='channels_nicheconfig_visual_medium_valid',
            ),
        ),
    ]
