from django.db import migrations

from peeringdb_server.models import CarrierFacility


def update_carrierfac_status(apps, schema_editor):
    CarrierFacility.objects.filter(status="pending").update(status="ok")


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0110_social_media"),
    ]

    operations = [
        migrations.RunPython(update_carrierfac_status, migrations.RunPython.noop),
    ]
