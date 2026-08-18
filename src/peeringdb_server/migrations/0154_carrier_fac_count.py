from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "peeringdb_server",
            "0153_alter_ixfmemberdata_speed_alter_networkixlan_speed_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="carrier",
            name="fac_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="number of facilities for this carrier",
                verbose_name="number of facilities for this carrier",
            ),
        ),
    ]
