from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger("reelforge.agents")


class AgentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reelforge.agents"

    def ready(self) -> None:
        from django.conf import settings

        from reelforge.agents.containers import AgentContainer

        container = AgentContainer()
        container.config.from_dict(
            {
                "serpapi_api_key": getattr(settings, "SERPAPI_API_KEY", ""),
                "tavily_api_key": getattr(settings, "TAVILY_API_KEY", ""),
                "anthropic_api_key": getattr(settings, "ANTHROPIC_API_KEY", ""),
                "openai_api_key": getattr(settings, "OPENAI_API_KEY", ""),
                "elevenlabs_api_key": getattr(settings, "ELEVENLABS_API_KEY", ""),
            }
        )
        container.wire(
            modules=[
                "reelforge.pipeline.tasks",
            ]
        )
        AgentsConfig.container = container  # type: ignore[attr-defined]
        logger.info("AgentContainer wired successfully")
