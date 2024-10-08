# Generated by Django 4.2.10 on 2024-03-11 16:20

import django.db.models.deletion
import django_peeringdb.fields
import django_peeringdb.models.abstract
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.OAUTH2_PROVIDER_GRANT_MODEL),
        migrations.swappable_dependency(settings.OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL),
        ("peeringdb_server", "0124_ixfmemberdata_bfd_support_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="OAuthGrantInfo",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "amr",
                    models.CharField(
                        blank=True,
                        help_text="Authentication method reference",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "grant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grant_info",
                        to=settings.OAUTH2_PROVIDER_GRANT_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "OAuth Grant Info",
                "verbose_name_plural": "OAuth Grant Info",
                "db_table": "peeringdb_oauth_grant_info",
            },
        ),
        migrations.CreateModel(
            name="OAuthAccessTokenInfo",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "amr",
                    models.CharField(
                        blank=True,
                        help_text="Authentication method reference",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "access_token",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_token_info",
                        to=settings.OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "OAuth Access Token Info",
                "verbose_name_plural": "OAuth Access Token Info",
                "db_table": "peeringdb_oauth_access_token_info",
            },
        ),
    ]
