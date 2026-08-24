"""
django-peeringdb backend loader (needed for pdb_load_data command)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django_peeringdb.client_adaptor.load import database_settings

if TYPE_CHECKING:
    from types import ModuleType

__backend: ModuleType | None = None


def load_backend(**orm_config: Any) -> ModuleType:  # Any: open-ended ORM config kwargs
    """
    Load the client adaptor module of django_peeringdb
    Assumes config is valid.
    """
    # Any: heterogeneous values (str SECRET_KEY + nested DATABASES config dict)
    settings: dict[str, Any] = {}
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
