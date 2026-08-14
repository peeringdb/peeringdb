from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import models


class CustomManager(models.Manager):
    # **kwargs mirrors Manager.bulk_create's open-ended signature.
    def bulk_create(
        self, objs: Iterable[models.Model], **kwargs: Any
    ) -> list[models.Model]:
        instance = super().bulk_create(objs)
        for obj in instance:
            models.signals.post_save.send(
                sender=self.model, instance=obj, created=True, using="default"
            )
        return instance
