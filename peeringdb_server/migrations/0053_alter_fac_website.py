# Generated by Django 2.2.14 on 2020-09-08 21:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('peeringdb_server', '0052_deactivate_in_dfz'),
    ]

    operations = [
        migrations.AlterField(
            model_name='facility',
            name='website',
            field=models.URLField(verbose_name='Website'),
        ),
    ]
