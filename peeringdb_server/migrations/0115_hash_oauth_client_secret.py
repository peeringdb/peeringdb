import oauth2_provider.generators
import oauth2_provider.models
from django.db import migrations
from oauth2_provider import settings


def forwards_func(apps, schema_editor):
    """
    Forward migration touches every application.client_secret which will cause it to be hashed if not already the case.
    """
    Application = apps.get_model(settings.APPLICATION_MODEL)
    applications = Application._default_manager.all()
    for application in applications:
        application.save(update_fields=["client_secret"])


class Migration(migrations.Migration):
    dependencies = [
        ("oauth2_provider", "0005_auto_20211222_2352"),
        (
            "peeringdb_server",
            "0114_oauthapplication_post_logout_redirect_uris_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(forwards_func),
    ]
