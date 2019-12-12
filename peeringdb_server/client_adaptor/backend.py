from collections import defaultdict

from django.db.models import OneToOneRel
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import IntegrityError

from peeringdb import resource

import peeringdb_server.models as models

from django_peeringdb.client_adaptor.backend import (
    Backend as BaseBackend,
    reftag_to_cls,
    )

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

    def get_resource(self, cls):
        """
        Override this so it doesn't hard fail on a non
        existing resource. As sync will try to obtain resources
        for relationships in peeringdb_server that aren't
        really resources (sponsorships, partnerships etc.)
        """

        return self.CONCRETE_MAP.get(cls)

    @reftag_to_cls
    def get_fields(self, concrete):
        """
        Sync currently doesnt support OneToOne relationships
        and none of the ones that exist in peeringdb_server
        are relevant to the data we want to sync.

        However they still get processed, causing errors.

        Here we make sure to not process OneToOneRel relationships
        """

        _fields = super(Backend, self).get_fields(concrete)
        fields = []
        for field in _fields:
            if isinstance(field, OneToOneRel):
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
        return super(Backend, self).set_relation_many_to_many(
            obj, field_name, objs)


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

        if isinstance(obj, models.Network):
            obj.info_prefixes4 = min(obj.info_prefixes4, settings.DATA_QUALITY_MAX_PREFIX_V4_LIMIT)
            obj.info_prefixes6 = min(obj.info_prefixes6, settings.DATA_QUALITY_MAX_PREFIX_V6_LIMIT)

        obj.clean_fields()
        obj.validate_unique()

        if not isinstance(obj, (models.IXLanPrefix, models.NetworkIXLan, models.NetworkFacility)):
            obj.clean()


    def save(self, obj):
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

        error_dict = getattr(
            exc, "error_dict", getattr(
                exc, "message_dict", {}
            )
        )

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

        error_dict = getattr(
            exc, "error_dict", getattr(
                exc, "message_dict", {}
            )
        )

        for name, err in error_dict.items():
            # check if it was a relationship that doesnt exist locally
            pattern = r".+ with id (\d+) does not exist.+"
            m = re.match(pattern, str(err))
            if m:
                field = obj._meta.get_field(name)
                res = self.get_resource(field.related_model)
                missing[res].add(int(m.group(1)))
        return missing
