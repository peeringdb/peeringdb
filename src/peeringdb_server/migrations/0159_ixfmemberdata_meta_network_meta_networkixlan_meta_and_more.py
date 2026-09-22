# #1751: `meta` document field + generated columns for filterable metadata keys.
#
# Note: adding a STORED generated column runs as ALGORITHM=COPY on MySQL,
# so each generated-column AddField below rebuilds the netixlan table.

import django.db.models.fields.json
import django.db.models.functions.comparison
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0158_alter_network_irr_as_set"),
    ]

    operations = [
        migrations.AddField(
            model_name="ixfmemberdata",
            name="meta",
            field=models.JSONField(blank=True, default=dict, verbose_name="Metadata"),
        ),
        migrations.AddField(
            model_name="network",
            name="meta",
            field=models.JSONField(blank=True, default=dict, verbose_name="Metadata"),
        ),
        migrations.AddField(
            model_name="networkixlan",
            name="meta",
            field=models.JSONField(blank=True, default=dict, verbose_name="Metadata"),
        ),
        migrations.AddField(
            model_name="networkixlan",
            name="meta_planned_status_change_date",
            field=models.GeneratedField(
                db_index=True,
                db_persist=True,
                expression=django.db.models.functions.comparison.Cast(
                    django.db.models.fields.json.KeyTextTransform(
                        "date",
                        django.db.models.fields.json.KeyTextTransform(
                            "planned_status_change", "meta"
                        ),
                    ),
                    output_field=models.DateField(null=True),
                ),
                output_field=models.DateField(null=True),
            ),
        ),
        migrations.AddField(
            model_name="networkixlan",
            name="meta_planned_status_change_status",
            field=models.GeneratedField(
                db_index=True,
                db_persist=True,
                expression=django.db.models.functions.comparison.Cast(
                    django.db.models.fields.json.KeyTextTransform(
                        "status",
                        django.db.models.fields.json.KeyTextTransform(
                            "planned_status_change", "meta"
                        ),
                    ),
                    output_field=models.CharField(max_length=32, null=True),
                ),
                output_field=models.CharField(max_length=32, null=True),
            ),
        ),
        migrations.AddField(
            model_name="networkixlan",
            name="meta_rfc8950",
            field=models.GeneratedField(
                db_index=True,
                db_persist=True,
                expression=models.Q(("meta__rfc8950", True)),
                output_field=models.BooleanField(null=True),
            ),
        ),
    ]
