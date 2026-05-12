"""
Custom django database routers.

Split read and write database connections if needed.
"""

from peeringdb_server.db_replica import use_replica_for_read


class DatabaseRouter:
    """
    Routes reads to the "read" replica only when the request middleware
    has opted-in for this request via a thread-local flag.

    Writes always go to "default" (primary).

    See peeringdb_server.db_replica for the middleware that drives this.
    """

    def db_for_read(self, model, **hints):
        if use_replica_for_read():
            return "read"
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Never run migrations against the read replica — it should be
        # a strict copy of primary maintained by replication.
        if db == "read":
            return False
        return True
