import logging
import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db.models.signals import post_save, pre_delete, pre_save
from django.conf import settings

from peeringdb_server import models as pdb_models
from peeringdb_server import signals
from django_peeringdb import models as djpdb_models
from django_peeringdb import sync

def sync_obj(cls, row):
    """
    we need to override django peeringdb's sync_obj function
    because our models differ slightly, not pretty, but good enough
    for now.
    """

    if row.get("status") != "ok":
        return

    try:
        obj = cls.objects.get(pk=row['id'])

    except cls.DoesNotExist:
        obj = cls()

    for k, v in row.items():
        if k in ["latitude", "longitude"] and v:
            v = "{:3.6f}".format(float(v))
        elif k == "fac_id":
            k = "facility_id"
        elif k == "net_id":
            k = "network_id"
        elif k == "info_prefixes4":
            v = max(v, 50000)
        elif k == "info_prefixes6":
            v = max(v, 10000)
        try:
            setattr(obj, k, v)
        except AttributeError:
            pass

    print(obj, obj.id)

    try:
        # we want to validate because it fixes some values
        # but at the same time we don't care about any validation
        # errors, since we can assume that the data from the
        # server is already valid, nor do we want to block import
        # because our validators differ from the servers.
        obj.full_clean()
    except ValidationError as e:
        pass


    for field in cls._meta.get_fields():
        ftyp = cls._meta.get_field(field.name)
        value = getattr(obj, field.name, None)
        if isinstance(value, datetime.datetime):
            setattr(obj, field.name, value.replace(tzinfo=None))
        else:
            if hasattr(ftyp, "related_name") and ftyp.multiple:
                continue
            else:
                try:
                    setattr(obj, field.name, value)
                except AttributeError:
                    pass

    obj.save()
    return

sync.sync_obj = sync_obj


class Command(BaseCommand):
    help = "Load initial data from another peeringdb instance"

    def add_arguments(self, parser):
        parser.add_argument("--url", default="https://www.peeringdb.com/api/", type=str)

    def handle(self, *args, **options):
        if settings.RELEASE_ENV != "dev":
            raise Exception("This command can only be run on dev instances")


        settings.USE_TZ = False
        settings.PEERINGDB_SYNC_URL = options.get("url")
        pre_save.disconnect(signals.addressmodel_save, sender=pdb_models.Facility)

        djpdb_models.all_models = [
            pdb_models.Organization,
            pdb_models.Facility,
            pdb_models.Network,
            pdb_models.InternetExchange,
            pdb_models.InternetExchangeFacility,
            pdb_models.IXLan,
            pdb_models.IXLanPrefix,
            pdb_models.NetworkContact,
            pdb_models.NetworkFacility,
            pdb_models.NetworkIXLan
        ]

        call_command("pdb_sync")
