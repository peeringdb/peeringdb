from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("peeringdb_server", "0158_alter_network_irr_as_set")]

    operations = [
        migrations.AddField(
            model_name="facility",
            name="location_method",
            field=models.CharField(
                blank=True, default="", editable=False, max_length=16
            ),
        ),
        migrations.AddField(
            model_name="facility",
            name="location_place_id",
            field=models.CharField(
                blank=True, default="", editable=False, max_length=512
            ),
        ),
    ]
