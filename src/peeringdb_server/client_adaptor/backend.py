"""
peeringdb sync backend to use for pdb_load_data
command
"""

import re
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import OneToOneRel
from django_peeringdb.client_adaptor.backend import Backend as BaseBackend
from django_peeringdb.client_adaptor.backend import reftag_to_cls
from peeringdb import resource

import peeringdb_server.models as models

__version__ = "1.0"


class Backend(BaseBackend):
    """
    Custom tailored peeringdb_server backend for the
    peeringdb client we can use to sync data from
    another peeringdb server instance.

    We can inherit most of the official django-peeringdb
    Backend, however we need bind resources to the peeringdb
    models and fix some issues with validation and relationships.
    """

    # map peeringdb_server models to peeringdb client resources

    RESOURCE_MAP = {
        resource.Carrier: models.Carrier,
        resource.CarrierFacility: models.CarrierFacility,
        resource.Campus: models.Campus,
        resource.Facility: models.Facility,
        resource.InternetExchange: models.InternetExchange,
        resource.InternetExchangeFacility: models.InternetExchangeFacility,
        resource.InternetExchangeLan: models.IXLan,
        resource.InternetExchangeLanPrefix: models.IXLanPrefix,
        resource.Network: models.Network,
        resource.NetworkContact: models.NetworkContact,
        resource.NetworkFacility: models.NetworkFacility,
        resource.NetworkIXLan: models.NetworkIXLan,
        resource.Organization: models.Organization,
    }

    @classmethod
    def setup(cls):
        # in order to copy updated / created times from server
        # we need to turn off auto updating of those fields
        # during update and add
        for model in cls.RESOURCE_MAP.values():
            for field in model._meta.fields:
                if field.name in ["created", "updated"]:
                    field.auto_now_add = False
                    field.auto_now = False

    def get_resource(self, cls):
        """
        Override this so it doesn't hard fail on a non
        existing resource. As sync will try to obtain resources
        for relationships in peeringdb_server that aren't
        really resources (sponsorships, partnerships etc.)
        """

        return self.CONCRETE_MAP.get(cls)

    @reftag_to_cls
    def get_fields(self, concrete, ignore_fields=None):
        """
        Sync currently doesnt support OneToOne relationships
        and none of the ones that exist in peeringdb_server
        are relevant to the data we want to sync.

        However they still get processed, causing errors.

        Here we make sure to not process OneToOneRel relationships
        """
        if not ignore_fields:
            ignore_fields = ["ixf_import_request_user"]

        _fields = super().get_fields(concrete)
        fields = []
        for field in _fields:
            if isinstance(field, OneToOneRel):
                continue
            if field.name in ignore_fields:
                continue
            fields.append(field)
        return fields

    def set_relation_many_to_many(self, obj, field_name, objs):
        """
        Sync will try to process sponsorship_set off of `org`
        and run into an error, so we make sure to ignore it
        when handling many 2 many relationships during sync
        """

        if field_name in ["sponsorship_set"]:
            return
        return super().set_relation_many_to_many(obj, field_name, objs)

    def clean(self, obj):
        """
        We override the object validation here to handle
        common validation issues that exist in the official production
        db, where valdiators are set, but data has not yet been
        fixed retroactively.

        These instances are:

        - info_prefixes4 on networks (adjust data)
        - info_prefixes6 on networks (adjust data)
        - overlapping prefixes on ixlan prefixes (skip validation)
        - invalid prefix length on ixlan prefixes (skip validation)
        - ipaddr4 out of prefix address space on netixlans (skip validation)
        - ipaddr6 out of prefix address space on netixlans (skip validation)
        """

        obj.updated = (
            obj._meta.get_field("updated")
            .to_python(obj.updated)
            .replace(tzinfo=models.UTC())
        )
        obj.created = (
            obj._meta.get_field("created")
            .to_python(obj.created)
            .replace(tzinfo=models.UTC())
        )

    def save(self, obj):
        # make sure all datetime values have their timezone set

        for field in obj._meta.get_fields():
            if field.get_internal_type() == "DateTimeField":
                value = getattr(obj, field.name)
                if not value:
                    continue
                if isinstance(value, str):
                    value = field.to_python(value)
                value = value.replace(tzinfo=models.UTC())
                setattr(obj, field.name, value)

            elif field.get_internal_type() == "DecimalField":
                value = getattr(obj, field.name)
                if not value:
                    continue
                if isinstance(value, str):
                    value = field.to_python(value)
                setattr(obj, field.name, value)

        if obj.HandleRef.tag == "ix":
            obj.save(create_ixlan=False)
        else:
            obj.save()

    def detect_uniqueness_error(self, exc):
        """
        Parse error, and if it describes any violations of a uniqueness constraint,
        return the corresponding fields, else None
        """
        pattern = r"(\w+) with this (\w+) already exists"

        fields = []
        if isinstance(exc, IntegrityError):
            return self._detect_integrity_error(exc)
        assert isinstance(exc, ValidationError), TypeError

        error_dict = getattr(exc, "error_dict", getattr(exc, "message_dict", {}))

        for name, err in error_dict.items():
            if re.search(pattern, str(err)):
                fields.append(name)
        return fields or None

    def detect_missing_relations(self, obj, exc):
        """
        Parse error messages and collect the missing-relationship errors
        as a dict of Resource -> {id set}
        """
        missing = defaultdict(set)

        error_dict = getattr(exc, "error_dict", getattr(exc, "message_dict", {}))

        for name, err in error_dict.items():
            # check if it was a relationship that doesnt exist locally
            pattern = r".+ with id (\d+) does not exist.+"
            m = re.match(pattern, str(err))
            if m:
                field = obj._meta.get_field(name)
                res = self.get_resource(field.related_model)
                missing[res].add(int(m.group(1)))
        return missing
