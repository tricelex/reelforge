"""Set per-stage default models on active PromptVersion rows."""

from django.db import migrations

STAGE_MODELS: dict[str, str] = {
    'research': 'gpt-5.6-terra',
    'outline': 'gpt-5.6-terra',
    'script': 'claude-opus-4-8',
    'scene_breakdown': 'gpt-5.6-terra',
    'visual_prompts': 'claude-sonnet-4-6',
    'music_plan': 'gpt-5.6-terra',
    'metadata': 'gpt-5.6-terra',
    'clip_analyze': 'claude-sonnet-4-6',
}


def apply_stage_models(apps, schema_editor) -> None:  # noqa: ANN001
    """Update active prompt versions to stage-specific model defaults."""
    PromptVersion = apps.get_model('prompts', 'PromptVersion')
    for stage_key, model_slug in STAGE_MODELS.items():
        PromptVersion.objects.filter(
            template__key=stage_key,
            is_active=True,
        ).update(model=model_slug)


def revert_stage_models(apps, schema_editor) -> None:  # noqa: ANN001
    """Restore a single global default model on active prompt versions."""
    PromptVersion = apps.get_model('prompts', 'PromptVersion')
    PromptVersion.objects.filter(is_active=True).update(model='gpt-5.6-terra')


class Migration(migrations.Migration):
    """Data migration for per-stage LLM model defaults."""

    dependencies = [
        ('prompts', '0004_alter_promptversion_model_default'),
    ]

    operations = [
        migrations.RunPython(apply_stage_models, revert_stage_models),
    ]
