"""
Django apps configuration.
"""

from __future__ import annotations

from django.apps import AppConfig


class PeeringDBServerAppConfig(AppConfig):
    name: str = "peeringdb_server"
    verbose_name: str = "PeeringDB"
    default_auto_field: str = "django.db.models.AutoField"

    def ready(self) -> None:
        # do not remove this, its the only place signals.py
        # gets imported, and removing it will break things
        # like verification queue and org usergroup creation
        import peeringdb_server.signals  # noqa
