from django.db import migrations, models


def copy_info_type_to_info_types(apps, schema_editor):
    # Temporarily disable auto_now for the 'updated' field
    Network = apps.get_model("peeringdb_server", "Network")
    updated_field = Network._meta.get_field("updated")
    updated_field_auto_now = updated_field.auto_now
    updated_field.auto_now = False

    # Perform a batch update
    Network.handleref.exclude(info_type="Not Disclosed").update(
        info_types=models.F("info_type")
    )

    # Re-enable auto_now for the 'updated' field
    updated_field.auto_now = updated_field_auto_now


def reverse_copy_info_types_to_info_type(apps, schema_editor):
    # Temporarily disable auto_now for the 'updated' field
    Network = apps.get_model("peeringdb_server", "Network")
    updated_field = Network._meta.get_field("updated")
    updated_field_auto_now = updated_field.auto_now
    updated_field.auto_now = False

    for network in Network.handleref.all():
        if not network.info_types:
            continue
        info_types_list = network.info_types
        if info_types_list:
            network.info_type = info_types_list[0]
            network.save()

    # Re-enable auto_now for the 'updated' field
    updated_field.auto_now = updated_field_auto_now


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0118_network_info_types"),
    ]

    operations = [
        migrations.RunPython(
            copy_info_type_to_info_types, reverse_copy_info_types_to_info_type
        ),
    ]
