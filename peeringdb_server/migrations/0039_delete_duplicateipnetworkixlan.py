# Generated by Django 2.2.13 on 2020-07-08 20:48

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0038_netixlan_ipaddr_unique"),
    ]

    operations = [
        migrations.DeleteModel(
            name="DuplicateIPNetworkIXLan",
        )
    ]
