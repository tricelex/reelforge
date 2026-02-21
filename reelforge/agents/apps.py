from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger("***REMOVED***.agents")


class AgentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "***REMOVED***.agents"

    def ready(self) -> None:
        from django.conf import settings

        from ***REMOVED***.agents.containers import AgentContainer

        container = AgentContainer()
        container.config.from_dict(
            {
                "youtube_api_key": getattr(settings, "YOUTUBE_API_KEY", ""),
                "reddit_client_id": getattr(settings, "REDDIT_CLIENT_ID", ""),
                "reddit_client_secret": getattr(settings, "REDDIT_CLIENT_SECRET", ""),
                "perplexity_api_key": getattr(settings, "PERPLEXITY_API_KEY", ""),
                "anthropic_api_key": getattr(settings, "ANTHROPIC_API_KEY", ""),
                "openai_api_key": getattr(settings, "OPENAI_API_KEY", ""),
            }
        )
        container.wire(
            modules=[
                "***REMOVED***.pipeline.tasks",
            ]
        )
        AgentsConfig.container = container  # type: ignore[attr-defined]
        logger.info("AgentContainer wired successfully")
