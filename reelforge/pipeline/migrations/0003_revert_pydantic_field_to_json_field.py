from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0002_use_pydantic_field_for_json_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pipelinerun",
            name="last_agent_decision",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Last decision made by OrchestratorAgent",
            ),
        ),
        migrations.AlterField(
            model_name="pipelineevent",
            name="metadata",
            field=models.JSONField(
                default=dict,
                help_text="Structured event data",
            ),
        ),
    ]
