from django.db import migrations

# allauth.socialaccount was removed from INSTALLED_APPS (#514), so its tables
# are no longer managed by any app. Children first, for the foreign keys.
SOCIALACCOUNT_TABLES = [
    "socialaccount_socialtoken",
    "socialaccount_socialaccount",
    "socialaccount_socialapp_sites",
    "socialaccount_socialapp",
]


def drop_socialaccount_tables(apps, schema_editor):
    connection = schema_editor.connection
    existing = set(connection.introspection.table_names())
    for table in SOCIALACCOUNT_TABLES:
        if table in existing:
            schema_editor.execute(f"DROP TABLE {schema_editor.quote_name(table)}")
    schema_editor.execute(
        "DELETE FROM django_migrations WHERE app = %s", ["socialaccount"]
    )


class Migration(migrations.Migration):
    # MySQL cannot run DDL inside a transaction.
    atomic = False

    dependencies = [
        ("peeringdb_server", "0163_oauthapplication_cimd_expires_at_and_more"),
    ]

    operations = [
        # The reverse does not restore the tables; it only lets a checkout
        # migrate back, where allauth's own migrations recreate them.
        migrations.RunPython(drop_socialaccount_tables, migrations.RunPython.noop),
    ]
