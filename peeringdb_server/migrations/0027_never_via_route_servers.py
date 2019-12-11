# -*- coding: utf-8 -*-
# Generated by Django 1.11.23 on 2019-12-11 16:33
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('peeringdb_server', '0026_help_text_228'),
    ]

    operations = [
        migrations.AddField(
            model_name='network',
            name='info_never_via_route_servers',
            field=models.BooleanField(default=False, help_text='Indicates if this network will announce its routes via rout servers or not'),
        ),
    ]
