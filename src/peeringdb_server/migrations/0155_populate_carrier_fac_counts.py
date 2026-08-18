from django.db import migrations


def populate_carrier_fac_counts(apps, schema_editor):
    Carrier = apps.get_model("peeringdb_server", "Carrier")
    CarrierFacility = apps.get_model("peeringdb_server", "CarrierFacility")

    # Iterate carriers manually rather than annotating; keeps the backfill
    # simple and avoids join/annotation edge cases on historical models.
    for carrier in Carrier._default_manager.all():
        count = CarrierFacility._default_manager.filter(
            carrier_id=carrier.id, status="ok"
        ).count()
        if carrier.fac_count != count:
            carrier.fac_count = count
            carrier.save(update_fields=["fac_count"])


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0154_carrier_fac_count"),
    ]

    operations = [
        migrations.RunPython(
            populate_carrier_fac_counts, reverse_code=migrations.RunPython.noop
        ),
    ]
