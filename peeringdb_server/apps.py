"""
Django apps configuration.
"""

from django.apps import AppConfig


class PeeringDBServerAppConfig(AppConfig):
    name = "peeringdb_server"
    verbose_name = "PeeringDB"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        # do not remove this, its the only place signals.py
        # gets imported, and removing it will break things
        # like verification queue and org usergroup creation
        import peeringdb_server.signals  # noqa
