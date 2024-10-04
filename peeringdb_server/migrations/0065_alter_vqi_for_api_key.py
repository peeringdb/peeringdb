# Generated by Django 2.2.17 on 2021-01-07 00:51

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0064_api_keys"),
    ]

    operations = [
        migrations.AddField(
            model_name="verificationqueueitem",
            name="org_key",
            field=models.ForeignKey(
                blank=True,
                help_text="The item that this queue is attached to was created by this organization api key",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="vqitems",
                to="peeringdb_server.OrganizationAPIKey",
            ),
        ),
    ]
