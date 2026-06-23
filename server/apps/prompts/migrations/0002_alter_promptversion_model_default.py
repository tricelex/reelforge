"""Switch default prompt version model to OpenAI GPT 5.2."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Update PromptVersion.model default from Claude to GPT 5.2."""

    dependencies = [
        ('prompts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='promptversion',
            name='model',
            field=models.CharField(default='gpt-5.2', max_length=60),
        ),
    ]
