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
        nested = self._snapshot.get('prompts')
        if isinstance(nested, dict) and stage_key in nested:
            return str(nested[stage_key])
        value = self._snapshot.get(stage_key)
        return str(value) if value else None

    async def _get_prompt_version(
        self,
        stage_key: str,
    ) -> 'PromptVersion | None':
        from server.apps.prompts.models import PromptVersion  # noqa: PLC0415

        nested = self._snapshot.get('prompts')
        version_id = (
            nested.get(stage_key) if isinstance(nested, dict) else None
        ) or self._snapshot.get(stage_key)
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

    async def get_generation_settings(
        self,
        stage_key: str,
    ) -> dict[str, Any]:
        """Return max_tokens / temperature for this stage's PromptVersion.

        Falls back to PromptVersion field defaults when no version is pinned.
        """
        pv = await self._get_prompt_version(stage_key)
        if pv is None:
            return {'max_tokens': 8192, 'temperature': 1.0}
        return {
            'max_tokens': int(pv.max_tokens),
            'temperature': float(pv.temperature),
        }

    async def get_raw_templates(
        self,
        stage_key: str,
    ) -> tuple[str, str]:
        """Return unrendered (system_prompt, user_prompt) for this stage.

        Looks up via prompt_snapshot -> PromptVersion.id, or falls back to
        the active version for this template key. Returns ('', '') when no
        version is available.
        """
        pv = await self._get_prompt_version(stage_key)
        if pv is None:
            return '', ''
        return str(pv.system_prompt), str(pv.user_prompt)

    async def render(
        self,
        stage_key: str,
        variables: dict[str, Any],
    ) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) with variables substituted.

        Looks up via prompt_snapshot -> PromptVersion.id, or falls back to
        the active version for this template key.
        """
        sys_raw, usr_raw = await self.get_raw_templates(stage_key)
        if not sys_raw and not usr_raw:
            return '', ''
        sys = _jinja_env.from_string(sys_raw).render(**variables)
        usr = _jinja_env.from_string(usr_raw).render(**variables)
        return sys, usr
