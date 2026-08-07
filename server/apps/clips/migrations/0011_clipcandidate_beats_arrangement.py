# Generated manually for Hook/Story/Payoff beat structure.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('clips', '0010_portrait_composition'),
    ]

    operations = [
        migrations.AddField(
            model_name='clipcandidate',
            name='beats',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='clipcandidate',
            name='arrangement',
            field=models.CharField(
                choices=[
                    ('contiguous', 'Contiguous'),
                    ('cold_open', 'Cold Open'),
                ],
                default='contiguous',
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='clipcandidate',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    arrangement__in=['contiguous', 'cold_open'],
                ),
                name='clips_clipcandidate_arrangement_valid',
            ),
        ),
    ]
