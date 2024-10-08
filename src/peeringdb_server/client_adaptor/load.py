"""
django-peeringdb backend loader (needed for pdb_load_data command)
"""

from django_peeringdb.client_adaptor.load import database_settings

__backend = None


def load_backend(**orm_config):
    """
    Load the client adaptor module of django_peeringdb
    Assumes config is valid.
    """
    settings = {}
    settings["SECRET_KEY"] = orm_config.get("secret_key", "")

    db_config = orm_config["database"]
    if db_config:
        settings["DATABASES"] = {"default": database_settings(db_config)}

    from peeringdb_server.client_adaptor.setup import configure

    # Override defaults
    configure(**settings)
    # Must import implementation module after configure
    from peeringdb_server.client_adaptor import backend

    migrate = orm_config.get("migrate")
    if migrate and not backend.Backend().is_database_migrated():
        backend.Backend().migrate_database()

    return backend
