"""App config for the NexLev integration app."""

from django.apps import AppConfig


class NexlevConfig(AppConfig):
    """Owns NexLev's HTTP client, persisted records, and cache."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.nexlev'
    verbose_name = 'NexLev'
