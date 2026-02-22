from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0002_use_pydantic_field_for_json_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productionjob",
            name="render_spec",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Full render configuration consumed by VideoRenderer.",
            ),
        ),
        migrations.AlterField(
            model_name="productionjob",
            name="qa_results",
            field=models.JSONField(
                default=dict,
                help_text="QA check results: check_name → pass/fail.",
            ),
        ),
    ]
