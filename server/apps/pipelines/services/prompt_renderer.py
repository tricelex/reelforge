from typing import TYPE_CHECKING, Any

from jinja2.sandbox import SandboxedEnvironment

if TYPE_CHECKING:
    from server.apps.prompts.models import PromptVersion

_jinja_env = SandboxedEnvironment(autoescape=False)


class PromptRenderer:
    """Resolves and renders versioned prompt templates for a run.

    Phase 3: full Jinja2 rendering via SandboxedEnvironment.
    """

    def __init__(self, prompt_snapshot: dict[str, Any]) -> None:
        """Initialise with the run's prompt_snapshot."""
        self._snapshot = prompt_snapshot

    async def get_version_id(self, stage_key: str) -> str | None:
        """Return the PromptVersion UUID pinned for this stage, or None."""
        return self._snapshot.get(stage_key)

    async def _get_prompt_version(
        self,
        stage_key: str,
    ) -> 'PromptVersion | None':
        from server.apps.prompts.models import PromptVersion  # noqa: PLC0415

        version_id = self._snapshot.get(stage_key)
        if version_id:
            try:
                return await PromptVersion.objects.aget(id=version_id)
            except PromptVersion.DoesNotExist:
                return None
        return await PromptVersion.objects.filter(
            template__key=stage_key,
            is_active=True,
        ).afirst()

    async def get_model(self, stage_key: str) -> str | None:
        """Return the PromptVersion.model slug for this stage, if configured."""
        pv = await self._get_prompt_version(stage_key)
        if pv is None:
            return None
        return str(pv.model)

    async def render(
        self,
        stage_key: str,
        variables: dict[str, Any],
    ) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) with variables substituted.

        Looks up via prompt_snapshot -> PromptVersion.id, or falls back to
        the active version for this template key.
        """
        pv = await self._get_prompt_version(stage_key)
        if pv is None:
            return '', ''
        sys = _jinja_env.from_string(pv.system_prompt).render(**variables)
        usr = _jinja_env.from_string(pv.user_prompt).render(**variables)
        return sys, usr
