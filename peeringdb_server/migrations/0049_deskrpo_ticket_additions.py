# Generated by Django 2.2.14 on 2020-07-24 13:53

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0048_environmentsetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="deskproticket",
            name="deskpro_id",
            field=models.IntegerField(
                blank=True, help_text="Ticket id on the DeskPRO side", null=True
            ),
        ),
        migrations.AddField(
            model_name="deskproticket",
            name="deskpro_ref",
            field=models.CharField(
                blank=True,
                help_text="Ticket reference on the DeskPRO side",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="ixfmemberdata",
            name="deskpro_id",
            field=models.IntegerField(
                blank=True, help_text="Ticket id on the DeskPRO side", null=True
            ),
        ),
        migrations.AddField(
            model_name="ixfmemberdata",
            name="deskpro_ref",
            field=models.CharField(
                blank=True,
                help_text="Ticket reference on the DeskPRO side",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="deskproticket",
            name="published",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
