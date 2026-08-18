"""
Custom django database routers.

Split read and write database connections if needed.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from peeringdb_server.db_replica import use_replica_for_read


class DatabaseRouter:
    """
    Routes reads to the "read" replica only when the request middleware
    has opted-in for this request via a thread-local flag.

    Writes always go to "default" (primary).

    See peeringdb_server.db_replica for the middleware that drives this.
    """

    # hints is Django's router hint mapping: an open-ended,
    # version-dependent dict (e.g. may carry an "instance"), so it stays Any.
    def db_for_read(self, model: type[models.Model], **hints: Any) -> str:
        if use_replica_for_read():
            return "read"
        return "default"

    def db_for_write(self, model: type[models.Model], **hints: Any) -> str:
        return "default"

    def allow_relation(
        self, obj1: models.Model, obj2: models.Model, **hints: Any
    ) -> bool:
        return True

    def allow_migrate(
        self,
        db: str,
        app_label: str,
        model_name: str | None = None,
        **hints: Any,
    ) -> bool:
        # Never run migrations against the read replica — it should be
        # a strict copy of primary maintained by replication.
        if db == "read":
            return False
        return True
