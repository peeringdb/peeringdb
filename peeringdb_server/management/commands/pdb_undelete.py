from django.core.management.base import BaseCommand

from peeringdb_server.models import REFTAG_MAP

import reversion
import json


class Command(BaseCommand):
    help = "Undo object deletion"

    def add_arguments(self, parser):
        parser.add_argument("reftag", nargs="?",
                            help="object reftag (net, ix, fac etc..)")
        parser.add_argument("id", nargs="?", help="object id")
        parser.add_argument("version_id", nargs="?",
                            help="object version id where it was deleted")
        parser.add_argument('--commit', action='store_true',
                            help="will commit the changes")

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write("[pretend] {}".format(msg))

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.version_id = options.get("version_id")
        version = reversion.models.Version.objects.get(id=self.version_id)
        self.date = version.revision.date_created
        self.log("UNDELETING FROM DATE: {}".format(self.date))
        self.undelete(options.get("reftag"), options.get("id"))

    def undelete(self, reftag, _id, parent=None, date=None):
        cls = REFTAG_MAP.get(reftag)
        obj = cls.objects.get(id=_id)

        if date:
            version = reversion.models.Version.objects.get_for_object(
                obj).filter(revision__date_created__lt=date).order_by(
                    "revision__date_created").last()
            try:
                status = json.loads(
                    version.serialized_data)[0].get("fields")["status"]
            except:
                status = None
            if status == "deleted":
                self.log(
                    "{} was already deleted at snapshot, skipping ..".format(
                        obj))
                return

        can_undelete_obj = True

        for field in cls._meta.get_fields():
            if field.is_relation:
                if field.many_to_one:
                    # relation parent
                    try:
                        relation = getattr(obj, field.name)
                    except:
                        continue
                    if relation.status == "deleted" and relation != parent:
                        can_undelete_obj = False
                        self.log(
                            "Cannot undelete {}, dependent relation marked as deleted: {}".
                            format(obj, relation))

        if not can_undelete_obj:
            return

        if obj.status == "deleted":
            obj.status = "ok"
            self.log("Undeleting {}".format(obj))
            if self.commit:
                obj.save()

        for field in cls._meta.get_fields():
            if field.is_relation:
                if not field.many_to_one:
                    # relation child
                    try:
                        relation = getattr(obj, field.name)
                    except:
                        continue
                    if not hasattr(field.related_model, "ref_tag"):
                        continue
                    for child in relation.filter(updated__gte=self.date):
                        self.undelete(child.ref_tag, child.id, obj,
                                      date=self.date)
