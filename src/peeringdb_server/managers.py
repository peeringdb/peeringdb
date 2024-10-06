from django.db import models


class CustomManager(models.Manager):
    def bulk_create(self, objs, **kwargs):
        instance = super().bulk_create(objs)
        for obj in instance:
            models.signals.post_save.send(
                sender=self.model, instance=obj, created=True, using="default"
            )
        return instance
