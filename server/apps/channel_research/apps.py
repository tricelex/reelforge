from django.apps import AppConfig


class ChannelResearchConfig(AppConfig):
    """AppConfig for the channel research workspace."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.channel_research'
    verbose_name = 'Channel Research'
