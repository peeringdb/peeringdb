"""
Migration 0164 drops the allauth socialaccount tables where they exist and
forgets their migrations (#514).
"""

from importlib import import_module

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

migration = import_module("peeringdb_server.migrations.0164_drop_socialaccount_tables")

# MySQL commits DDL implicitly, so these tests cannot run in a rolled back
# transaction.
pytestmark = pytest.mark.django_db(transaction=True)


def socialaccount_tables():
    return set(migration.SOCIALACCOUNT_TABLES) & set(
        connection.introspection.table_names()
    )


def run_migration():
    with connection.schema_editor(atomic=False) as schema_editor:
        migration.drop_socialaccount_tables(apps, schema_editor)


# The foreign keys of allauth's schema, so the drop order is exercised.
SCHEMA = [
    "CREATE TABLE socialaccount_socialapp (id integer primary key)",
    "CREATE TABLE socialaccount_socialapp_sites (id integer primary key,"
    " socialapp_id integer NOT NULL,"
    " FOREIGN KEY (socialapp_id) REFERENCES socialaccount_socialapp (id))",
    "CREATE TABLE socialaccount_socialaccount (id integer primary key)",
    "CREATE TABLE socialaccount_socialtoken (id integer primary key,"
    " account_id integer NOT NULL, app_id integer NULL,"
    " FOREIGN KEY (account_id) REFERENCES socialaccount_socialaccount (id),"
    " FOREIGN KEY (app_id) REFERENCES socialaccount_socialapp (id))",
]


@pytest.fixture
def socialaccount_state():
    with connection.cursor() as cursor:
        for statement in SCHEMA:
            cursor.execute(statement)
    MigrationRecorder.Migration.objects.create(app="socialaccount", name="0001_initial")
    yield
    with connection.cursor() as cursor:
        for table in migration.SOCIALACCOUNT_TABLES:
            cursor.execute(f"DROP TABLE IF EXISTS {connection.ops.quote_name(table)}")
    MigrationRecorder.Migration.objects.filter(app="socialaccount").delete()


def test_drops_existing_tables(socialaccount_state):
    assert socialaccount_tables() == set(migration.SOCIALACCOUNT_TABLES)
    run_migration()
    assert not socialaccount_tables()
    assert not MigrationRecorder.Migration.objects.filter(app="socialaccount").exists()


def test_absent_tables_are_skipped():
    assert not socialaccount_tables()
    run_migration()
    assert not socialaccount_tables()
