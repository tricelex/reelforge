"""Create/activate the editor_brief PromptVersion (idempotent)."""

from typing import override

from django.core.management.base import BaseCommand
from django.db import transaction

from server.apps.generation.logic.constants import DEFAULT_LLM_MODEL
from server.apps.generation.logic.model_resolver import STAGE_MODEL_DEFAULTS
from server.apps.prompts.logic.editor_brief_prompts import (
    EDITOR_BRIEF_SYSTEM_PROMPT,
    EDITOR_BRIEF_TEMPLATE_DESCRIPTION,
    EDITOR_BRIEF_TEMPLATE_KEY,
    EDITOR_BRIEF_TEMPLATE_NAME,
    EDITOR_BRIEF_USER_PROMPT,
)
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
)


class Command(BaseCommand):
    """Ensure editor_brief has an active PromptVersion operators can edit."""

    help = (
        'Create (if needed) and activate the editor_brief PromptVersion '
        'for Resolve editor-handoff briefs.'
    )

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Upsert template and activate matching prompt text."""
        template, created = PromptTemplate.objects.update_or_create(
            key=EDITOR_BRIEF_TEMPLATE_KEY,
            defaults={
                'name': EDITOR_BRIEF_TEMPLATE_NAME,
                'scope': PromptScope.GLOBAL,
                'description': EDITOR_BRIEF_TEMPLATE_DESCRIPTION,
            },
        )
        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(f'{action} template: {template.key}'),
        )

        matching = (
            PromptVersion.objects
            .filter(
                template=template,
                system_prompt=EDITOR_BRIEF_SYSTEM_PROMPT,
                user_prompt=EDITOR_BRIEF_USER_PROMPT,
            )
            .order_by('-version')
            .first()
        )
        if matching is not None:
            self._activate(template, matching)
            self.stdout.write(
                self.style.SUCCESS(
                    f'Activated existing {template.key} v{matching.version} '
                    f'(id={matching.id}).',
                ),
            )
            return

        latest = (
            PromptVersion.objects
            .filter(template=template)
            .order_by('-version')
            .values_list('version', flat=True)
            .first()
        )
        next_version = (latest or 0) + 1
        model = STAGE_MODEL_DEFAULTS.get(
            EDITOR_BRIEF_TEMPLATE_KEY,
            DEFAULT_LLM_MODEL,
        )
        with transaction.atomic():
            PromptVersion.objects.filter(template=template).update(
                is_active=False,
            )
            version = PromptVersion.objects.create(
                template=template,
                version=next_version,
                system_prompt=EDITOR_BRIEF_SYSTEM_PROMPT,
                user_prompt=EDITOR_BRIEF_USER_PROMPT,
                model=model,
                temperature=1.0,
                max_tokens=8192,
                is_active=True,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f'Created and activated {template.key} v{version.version} '
                f'(id={version.id}).',
            ),
        )

    def _activate(
        self,
        template: PromptTemplate,
        version: PromptVersion,
    ) -> None:
        with transaction.atomic():
            PromptVersion.objects.filter(template=template).update(
                is_active=False,
            )
            version.is_active = True
            version.save(update_fields=['is_active'])
