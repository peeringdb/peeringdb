# Generated by Django 4.2.13 on 2024-06-17 12:02

import django_peeringdb.models.abstract
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0130_strip_string_fields"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="organization",
            managers=[],
        ),
        migrations.AddField(
            model_name="oauthapplication",
            name="allowed_origins",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Allowed origins list to enable CORS, space separated",
            ),
        ),
        migrations.AddField(
            model_name="oauthapplication",
            name="hash_client_secret",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="campus",
            name="website",
            field=django_peeringdb.models.abstract.URLField(
                blank=True, default="", max_length=255, verbose_name="Website"
            ),
        ),
        migrations.AlterField(
            model_name="carrier",
            name="website",
            field=django_peeringdb.models.abstract.URLField(
                blank=True, default="", max_length=255, verbose_name="Website"
            ),
        ),
        migrations.AlterField(
            model_name="network",
            name="policy_general",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Open", "Open"),
                    ("Selective", "Selective"),
                    ("Restrictive", "Restrictive"),
                    ("No", "No"),
                ],
                help_text="Peering with the routeserver and BFD support is shown with an icon",
                max_length=72,
                verbose_name="General Policy",
            ),
        ),
        migrations.AlterField(
            model_name="network",
            name="website",
            field=django_peeringdb.models.abstract.URLField(
                blank=True, max_length=255, verbose_name="Website"
            ),
        ),
        migrations.AlterField(
            model_name="oauthapplication",
            name="post_logout_redirect_uris",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Allowed Post Logout URIs list, space separated",
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="website",
            field=django_peeringdb.models.abstract.URLField(
                blank=True, default="", max_length=255, verbose_name="Website"
            ),
        ),
    ]
