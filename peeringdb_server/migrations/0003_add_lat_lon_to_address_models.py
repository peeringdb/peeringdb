# Generated by Django 1.11.4 on 2017-08-23 11:58


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0002_partnernship_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="facility",
            name="lat",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text=b"Latitude",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="facility",
            name="lon",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text=b"Longitude",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="lat",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text=b"Latitude",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="lon",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text=b"Longitude",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="partnership",
            name="level",
            field=models.PositiveIntegerField(
                choices=[(1, "Data Validation"), (2, "RIR")], default=1
            ),
        ),
    ]
