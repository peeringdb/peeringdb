# Generated by Django 3.2.14 on 2022-08-29 14:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("peeringdb_server", "0095_emailaddressdata"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="flagged_for_deletion",
            field=models.DateTimeField(
                blank=True,
                help_text="Account is orphaned and has been flagged for deletion at this date",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="notified_for_deletion",
            field=models.DateTimeField(
                blank=True,
                help_text="User has been notified about pending account deletion at this date",
                null=True,
            ),
        ),
    ]
