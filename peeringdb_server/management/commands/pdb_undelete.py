"""
Restore soft-deleted objects.
"""

import json

import reversion
from django.core.management.base import BaseCommand

from peeringdb_server.models import REFTAG_MAP


class Command(BaseCommand):
    help = "Undo object deletion"

    def add_arguments(self, parser):
        parser.add_argument(
            "reftag", nargs="?", help="object reftag (net, ix, fac etc..)"
        )
        parser.add_argument("id", nargs="?", help="object id")
        parser.add_argument(
            "version_id", nargs="?", help="object version id where it was deleted"
        )
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def log_err(self, msg):
        self.log(f"[error] {msg}")

    def log_warn(self, msg):
        self.log(f"[warning] {msg}")

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.version_id = options.get("version_id")
        self.suppress_warning = None
        self.version = version = reversion.models.Version.objects.get(
            id=self.version_id
        )
        self.date = version.revision.date_created
        self.log(f"UNDELETING FROM DATE: {self.date}")
        self.undelete(options.get("reftag"), options.get("id"))

    def handle_netixlan(self, netixlan):
        model = REFTAG_MAP["netixlan"]
        conflict_ip4, conflict_ip6 = netixlan.ipaddress_conflict()

        if conflict_ip4:
            # ipv4 exists in another netixlan now
            others = model.objects.filter(ipaddr4=netixlan.ipaddr4, status="ok")
            for other in [o for o in others if o.ixlan.ix_id == netixlan.ixlan.ix_id]:
                # netixlan is at same ix as the one being undeleted, delete the other
                # one so we can proceed with undeletion
                self.log(
                    f"Found duplicate netixlan at same ix: {other.ipaddr4} - deleting"
                )
                if self.commit:
                    other.delete()
                else:
                    # when in pretend mode we need suppress the next warning as we
                    # are not deleting the conflict
                    self.suppress_warning = True

            for other in [o for o in others if o.ixlan.ix_id != netixlan.ixlan.ix_id]:
                # unless ipv4 also exists in a netixlan that is NOT at the same ix
                # then we need the warning again
                self.suppress_warning = False

        if conflict_ip6:
            # ipv6 exists in another netixlan now
            others = model.objects.filter(ipaddr6=netixlan.ipaddr6, status="ok")
            for other in [o for o in others if o.ixlan.ix_id == netixlan.ixlan.ix_id]:
                # netixlan is at same ix as the one being undeleted, delete the other
                # one so we can proceed with undeletion
                self.log(
                    f"Found duplicate netixlan at same ix: {other.ipaddr6} - deleting"
                )
                if self.commit:
                    other.delete()
                else:
                    # when in pretend mode we need suppress the next warning as we
                    # are not deleting the conflict
                    self.suppress_warning = True

            for other in [o for o in others if o.ixlan.ix_id != netixlan.ixlan.ix_id]:
                # unless ipv6 also exists in a netixlan that is NOT at the same ix
                # then we need the warning again
                self.suppress_warning = False

    def undelete(self, reftag, _id, parent=None, date=None):
        cls = REFTAG_MAP.get(reftag)
        obj = cls.objects.get(id=_id)
        self.suppress_warning = False

        def _label(obj):
            if hasattr(obj, "descriptive_name"):
                return obj.descriptive_name
            return obj

        if date:
            version = (
                reversion.models.Version.objects.get_for_object(obj)
                .filter(revision__date_created__lt=date)
                .order_by("revision__date_created")
                .last()
            )
            try:
                status = json.loads(version.serialized_data)[0].get("fields")["status"]
            except Exception:
                status = None
            if status == "deleted":
                self.log_warn(
                    f"{_label(obj)} was already deleted at snapshot, skipping .."
                )
                return

        can_undelete_obj = True

        for field in cls._meta.get_fields():
            if field.is_relation:
                if field.many_to_one:
                    # relation parent
                    try:
                        relation = getattr(obj, field.name)
                    except Exception:
                        continue
                    if relation and relation.status == "deleted" and relation != parent:
                        can_undelete_obj = False
                        self.log_warn(
                            f"Cannot undelete {_label(obj)}, dependent relation marked as deleted: {relation}"
                        )

        if not can_undelete_obj:
            return

        if obj.status == "deleted":
            obj.status = "ok"
            self.log(f"Undeleting {_label(obj)}")

            handler = getattr(self, f"handle_{reftag}", None)
            if handler:
                handler(obj)

            try:
                obj.clean()
                if self.commit:
                    obj.save()
            except Exception as exc:
                if not self.suppress_warning:
                    self.log_warn(f"Cannot undelete {_label(obj)}: {exc}")

        for field in cls._meta.get_fields():
            if field.is_relation:
                if not field.many_to_one:
                    # relation child
                    try:
                        relation = getattr(obj, field.name)
                    except Exception:
                        continue
                    if not hasattr(field.related_model, "ref_tag"):
                        continue
                    for child in relation.filter(updated__gte=self.date):
                        self.undelete(child.ref_tag, child.id, obj, date=self.date)
