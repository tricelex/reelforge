from django.apps import AppConfig


class ChannelsConfig(AppConfig):
    """AppConfig for the channels app."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'server.apps.channels'
    verbose_name = 'Channels'
