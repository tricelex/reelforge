"""Switch default prompt version model to OpenAI GPT 5.6 Terra."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Update PromptVersion.model default from GPT 5.2 to GPT 5.6 Terra."""

    dependencies = [
        ('prompts', '0003_storyformat_niches'),
    ]

    operations = [
        migrations.AlterField(
            model_name='promptversion',
            name='model',
            field=models.CharField(default='gpt-5.6-terra', max_length=60),
        ),
    ]
