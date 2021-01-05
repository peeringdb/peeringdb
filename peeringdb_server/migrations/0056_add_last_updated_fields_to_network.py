# Generated by Django 2.2.17 on 2021-01-05 20:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('peeringdb_server', '0055_update_network_type_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='network',
            name='netfac_updated',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='network',
            name='netixlan_updated',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='network',
            name='poc_updated',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
