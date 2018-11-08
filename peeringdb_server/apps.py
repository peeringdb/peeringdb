from django.apps import AppConfig


class PeeringDBServerAppConfig(AppConfig):
    name = "peeringdb_server"
    verbose_name = "PeeringDB"

    def ready(self):
        import peeringdb_server.signals
