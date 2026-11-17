import re

from django.db import migrations
from oauth2_provider import settings


def forwards_func(apps, schema_editor):
    """
    The application form used to store allowed origins comma separated, but
    django-oauth-toolkit matches them space separated, so apps with several
    origins matched none of them (#2022).
    """
    for model_name in {"peeringdb_server.OAuthApplication", settings.APPLICATION_MODEL}:
        Application = apps.get_model(model_name)
        for app in Application._default_manager.filter(allowed_origins__contains=","):
            origins = [o for o in re.split(r"[\s,]+", app.allowed_origins) if o]
            Application._default_manager.filter(pk=app.pk).update(
                allowed_origins=" ".join(origins)
            )


class Migration(migrations.Migration):
    dependencies = [
        ("oauth2_provider", "0010_application_allowed_origins"),
        ("peeringdb_server", "0164_drop_socialaccount_tables"),
    ]

    operations = [
        migrations.RunPython(forwards_func, migrations.RunPython.noop),
    ]
