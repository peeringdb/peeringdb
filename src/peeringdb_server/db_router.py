"""
Custom django database routers.

Split read and write database connections if needed.
"""


class DatabaseRouter:
    """
    A very basic database router that routes to a different
    read and write db.
    """

    def db_for_read(self, model, **hints):
        return "read"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True


class TestRouter(DatabaseRouter):
    def db_for_read(self, model, **hints):
        return "default"
