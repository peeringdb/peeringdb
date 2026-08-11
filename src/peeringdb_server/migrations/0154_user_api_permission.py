# Generated for scoped UserAPIKey permissions

import django.db.models.deletion
import django_grainy.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "peeringdb_server",
            "0153_alter_ixfmemberdata_speed_alter_networkixlan_speed_and_more",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="UserAPIPermission",
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
                    "namespace",
                    models.CharField(
                        help_text="Permission namespace (A '.' delimited list of keys",
                        max_length=255,
                    ),
                ),
                ("permission", django_grainy.fields.PermissionField(default=1)),
                (
                    "api_key",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grainy_permissions",
                        to="peeringdb_server.userapikey",
                    ),
                ),
            ],
            options={
                "verbose_name": "User API key Permission",
                "verbose_name_plural": "User API key Permission",
                "base_manager_name": "objects",
            },
        ),
    ]
