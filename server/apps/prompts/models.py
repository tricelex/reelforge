from django.db import models

from server.apps.core.models import TimeStampedModel, UUIDModel


class PromptScope(models.TextChoices):
    GLOBAL = 'GLOBAL', 'Global'
    NICHE = 'NICHE', 'Niche'
    CHANNEL = 'CHANNEL', 'Channel'


class PromptTemplate(UUIDModel, TimeStampedModel):
    """A named prompt slot (e.g. 'scene_breakdown'). Versioned separately."""

    name = models.CharField(max_length=120)
    key = models.CharField(max_length=60, unique=True)
    scope = models.CharField(max_length=10, choices=PromptScope.choices)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name='prompts_prompttemplate_scope_valid',
                condition=models.Q(scope__in=PromptScope.values),
            ),
        ]

    def __str__(self) -> str:
        return self.key


class PromptVersion(UUIDModel, TimeStampedModel):
    """One version of a prompt template. Only one should be active at a time."""

    template = models.ForeignKey(
        PromptTemplate, on_delete=models.CASCADE, related_name='versions', db_index=True
    )
    version = models.PositiveIntegerField()
    system_prompt = models.TextField()
    user_prompt = models.TextField()
    model = models.CharField(max_length=60, default='claude-opus-4-8')
    temperature = models.FloatField(default=1.0)
    max_tokens = models.PositiveIntegerField(default=8192)
    is_active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'version'], name='uq_prompt_template_version'
            )
        ]

    def __str__(self) -> str:
        return f'{self.template.key} v{self.version}'


class StoryFormat(UUIDModel, TimeStampedModel):
    """Narrative architecture definition: beats, pacing, music moods.

    Rows represent formats like 'true_crime_case', 'fantasy_story', 'listicle'.
    Adding a new niche format is an admin task — no code change needed.
    """

    key = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    fiction = models.BooleanField(default=False)
    narration_pov = models.CharField(max_length=30, default='narrator')
    beats = models.JSONField()
    pacing = models.JSONField(default=dict)
    prompt_overrides = models.JSONField(default=dict)
    music_mood_map = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name
