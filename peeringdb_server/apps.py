from django.apps import AppConfig


class PeeringDBServerAppConfig(AppConfig):
    name = "peeringdb_server"
    verbose_name = "PeeringDB"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        pass
