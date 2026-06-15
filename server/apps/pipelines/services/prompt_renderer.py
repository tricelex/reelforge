from typing import Any

from jinja2.sandbox import SandboxedEnvironment

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

    async def render(
        self,
        stage_key: str,
        variables: dict[str, Any],
    ) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) with Jinja2 variables substituted.

        Looks up via prompt_snapshot -> PromptVersion.id, or falls back to
        the active version for this template key.
        """
        from server.apps.prompts.models import PromptVersion  # noqa: PLC0415

        version_id = self._snapshot.get(stage_key)
        pv: PromptVersion | None
        if version_id:
            pv = await PromptVersion.objects.aget(id=version_id)
        else:
            pv = await PromptVersion.objects.filter(
                template__key=stage_key,
                is_active=True,
            ).afirst()
        if pv is None:
            return '', ''
        sys = _jinja_env.from_string(pv.system_prompt).render(**variables)
        usr = _jinja_env.from_string(pv.user_prompt).render(**variables)
        return sys, usr
