#!/bin/env python
"""
Series of integration/unit tests for the PDB API.
"""

import copy
import datetime
import ipaddress
import json
import re
import time
import unittest
import uuid
from unittest.mock import Mock, patch

import pytest
import reversion
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.cache import caches
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.utils import IntegrityError
from django.test.utils import override_settings
from django.utils import timezone
from grainy.const import PERM_CREATE, PERM_DELETE, PERM_READ, PERM_UPDATE
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from twentyc.rpc import (
    InvalidRequestException,
    NotFoundException,
    PermissionDeniedException,
    RestClient,
)

import peeringdb_server.geo as geo
from peeringdb_server import inet
from peeringdb_server import settings as pdb_settings
from peeringdb_server.inet import RdapLookup
from peeringdb_server.models import (
    QUEUE_ENABLED,
    REFTAG_MAP,
    Campus,
    Carrier,
    CarrierFacility,
    DeskProTicket,
    Facility,
    GeoCoordinateCache,
    InternetExchange,
    InternetExchangeFacility,
    IXFMemberData,
    IXLan,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    User,
)
from peeringdb_server.rest import NetworkViewSet
from peeringdb_server.serializers import REFTAG_MAP as REFTAG_MAP_SLZ

START_TIMESTAMP = time.time()

SHARED = {}

NUMERIC_TESTS = {
    "lt": "Less",
    "lte": "LessEqual",
    "gt": "Greater",
    "gte": "GreaterEqual",
    "": "Equal",
}

DATETIME = datetime.datetime.now()
DATE = DATETIME.date()
DATE_YDAY = DATE - datetime.timedelta(days=1)
DATE_TMRW = DATE - datetime.timedelta(days=-1)
DATES = {
    "today": (DATE, DATE.strftime("%Y-%m-%d")),
    "yesterday": (DATE_YDAY, DATE_YDAY.strftime("%Y-%m-%d")),
    "tomorrow": (DATE_TMRW, DATE_TMRW.strftime("%Y-%m-%d")),
}

# entity names
ORG_RW = "API Test Organization RW"
ORG_RW_PENDING = "%s:Pending" % ORG_RW
ORG_R = "API Test Organization R"
NET_R = "%s:Network" % ORG_R
NET_R_PENDING = "%s:Pending" % NET_R
NET_R_DELETED = "%s:Deleted" % NET_R
IX_R = "%s:Exchange" % ORG_R
FAC_R = "%s:Facility" % ORG_R

# user specs
USER = {"user": "api_test", "password": "api_test"}

USER_ORG_ADMIN = {
    "user": "api_test_org_admin",
    "password": "api_test_org_admin",
    "email": "admin@org.com",
}

USER_ORG_MEMBER = {"user": "api_test_org_member", "password": "api_test_org_member"}

USER_CRUD = {
    "delete": {"user": "api_test_crud_delete", "password": "api_test_crud_delete"},
    "update": {"user": "api_test_crud_update", "password": "api_test_crud_update"},
    "create": {"user": "api_test_crud_create", "password": "api_test_crud_create"},
}

# server location
URL = settings.API_URL

# common
CITY = "Chicago"
COUNTRY = "US"
CONTINENT = "North America"
PHONE = "+12065550199"
WEBSITE = "http://www.test.apitest"
STATE = "IL"
ZIPCODE = "1-2345"
NOTE = "This is a test entry made by a script to test out the API"
EMAIL = "test@20c.com"
SOCIAL_MEDIA = [{"service": "website", "identifier": "http://www.test.apitest"}]

VERBOSE = False

PREFIXES_V4 = [
    "206.223.114.0/24",
    "206.223.115.0/24",
    "206.223.116.0/24",
    "206.223.117.0/24",
    "206.223.118.0/24",
    "206.223.119.0/24",
    "206.223.120.0/24",
    "206.223.121.0/24",
    "206.223.122.0/24",
]

PREFIXES_V6 = [
    "2001:504:0:1::/64",
    "2001:504:0:2::/64",
    "2001:504:0:3::/64",
    "2001:504:0:4::/64",
    "2001:504:0:5::/64",
    "2001:504:0:6::/64",
    "2001:504:0:7::/64",
    "2001:504:0:8::/64",
    "2001:504:0:9::/64",
]


def clear_negative_cache():
    caches["negative"].clear()


class TestJSON(unittest.TestCase):
    rest_client = RestClient

    PREFIX_COUNT = 110
    IP4_COUNT = 1
    IP6_COUNT = 1

    @classmethod
    def get_ip6(cls, ixlan):
        hosts = []
        for host in (
            ixlan.ixpfx_set.filter(status=ixlan.status, protocol="IPv6")
            .first()
            .prefix.hosts()
        ):
            if len(hosts) < 100:
                hosts.append(host)
            else:
                break

        r = f"{hosts[cls.IP6_COUNT]}"
        cls.IP6_COUNT += 1
        return r

    @classmethod
    def get_ip4(cls, ixlan):
        hosts = []
        for host in (
            ixlan.ixpfx_set.filter(status=ixlan.status, protocol="IPv4")
            .first()
            .prefix.hosts()
        ):
            if len(hosts) < 100:
                hosts.append(host)
            else:
                break

        r = f"{hosts[cls.IP4_COUNT]}"
        cls.IP4_COUNT += 1
        return r

    @classmethod
    def get_prefix4(cls):
        r = f"206.41.{cls.PREFIX_COUNT}.0/24"
        cls.PREFIX_COUNT += 1
        return r

    @classmethod
    def get_prefix6(cls):
        r = f"2001:504:41:{cls.PREFIX_COUNT}::/64"
        cls.PREFIX_COUNT += 1
        return r

    def setUp(self):
        self.db_anon = self.rest_client(URL, verbose=VERBOSE, anon=True)
        self.db_guest = self.rest_client(URL, verbose=VERBOSE)
        self.db_user = self.rest_client(URL, verbose=VERBOSE, **USER)
        self.db_org_member = self.rest_client(URL, verbose=VERBOSE, **USER_ORG_MEMBER)
        self.db_org_admin = self.rest_client(URL, verbose=VERBOSE, **USER_ORG_ADMIN)

        self.user_org_admin = User.objects.get(username="api_test_org_admin")
        self.user_org_member = User.objects.get(username="api_test_org_member")

        for p, specs in list(USER_CRUD.items()):
            setattr(
                self, "db_crud_%s" % p, self.rest_client(URL, verbose=VERBOSE, **specs)
            )

    def all_dbs(self, exclude=[]):
        return [
            db
            for db in [
                self.db_guest,
                self.db_org_member,
                self.db_user,
                self.db_org_admin,
                self.db_crud_create,
                self.db_crud_delete,
                self.db_crud_update,
            ]
            if db not in exclude
        ]

    def readonly_dbs(self, exclude=[]):
        return [
            db
            for db in [self.db_guest, self.db_org_member, self.db_user]
            if db not in exclude
        ]

    ##########################################################################

    @classmethod
    def make_data_org(self, **kwargs):
        data = {
            "name": self.make_name("Test"),
            "website": WEBSITE,
            "social_media": SOCIAL_MEDIA,
            "notes": NOTE,
            "address1": "address",
            "address2": "address",
            "city": CITY,
            "country": COUNTRY,
            "state": "state",
            "zipcode": "12345",
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_ix(self, **kwargs):
        data = {
            "name": self.make_name("Test"),
            "org_id": SHARED["org_rw_ok"].id,
            "name_long": self.make_name("Test Long Name"),
            "city": CITY,
            "country": COUNTRY,
            "region_continent": CONTINENT,
            "media": "Ethernet",
            "notes": NOTE,
            "website": WEBSITE,
            "social_media": SOCIAL_MEDIA,
            "url_stats": "%s/stats" % WEBSITE,
            "tech_email": EMAIL,
            "tech_phone": PHONE,
            "policy_email": EMAIL,
            "policy_phone": PHONE,
            "sales_email": EMAIL,
            "sales_phone": PHONE,
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_fac(self, **kwargs):
        data = {
            "name": self.make_name("Test"),
            "org_id": SHARED["org_rw_ok"].id,
            "website": WEBSITE,
            "social_media": SOCIAL_MEDIA,
            "city": CITY,
            "zipcode": ZIPCODE,
            "address1": "Some street",
            "clli": str(uuid.uuid4())[:6].upper(),
            "rencode": "",
            "npanxx": "000-111",
            "latitude": 30.091435,
            "longitude": 31.25435,
            "notes": NOTE,
            "country": COUNTRY,
            "tech_email": EMAIL,
            "tech_phone": PHONE,
            "sales_email": EMAIL,
            "sales_phone": PHONE,
            "diverse_serving_substations": True,
            "available_voltage_services": ["48 VDC", "400 VAC"],
            "property": "Owner",
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_net(self, **kwargs):
        try:
            asn = Network.objects.order_by("-asn").first().asn
        except AttributeError:
            asn = 90000000
        if asn < 90000000:
            asn = 90000000
        else:
            asn = asn + 1
        data = {
            "name": self.make_name("Test"),
            "org_id": SHARED["org_rw_ok"].id,
            "aka": self.make_name("Also known as"),
            "asn": asn,
            "website": WEBSITE,
            "social_media": SOCIAL_MEDIA,
            "irr_as_set": "AS-ZZ-ZZZZZZ@RIPE",
            "info_types": ["NSP"],
            "info_prefixes4": 11000,
            "info_prefixes6": 12000,
            "info_traffic": "1-5Tbps",
            "info_ratio": "Mostly Outbound",
            "info_scope": "Global",
            "info_unicast": True,
            "info_multicast": False,
            "info_ipv6": True,
            "info_never_via_route_servers": True,
            "notes": NOTE,
            "policy_url": "%s/policy" % WEBSITE,
            "policy_general": "Restrictive",
            "policy_locations": "Required - International",
            "policy_ratio": True,
            "policy_contracts": "Required",
            "allow_ixp_update": False,
        }
        data.update(**kwargs)
        return data

    @classmethod
    def make_data_carrier(cls, **kwargs):
        data = {
            "name": cls.make_name("Test"),
            "org_id": SHARED["org_rw_ok"].id,
            "aka": cls.make_name("Also known as"),
            "website": WEBSITE,
            "social_media": SOCIAL_MEDIA,
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_campus(cls, **kwargs):
        data = {
            "name": cls.make_name("Test"),
            "org_id": SHARED["org_rw_ok"].id,
            "aka": cls.make_name("Also known as"),
            "website": WEBSITE,
            "social_media": SOCIAL_MEDIA,
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_poc(self, **kwargs):
        data = {
            "net_id": 1,
            "role": "Technical",
            "visible": "Users",
            "name": "NOC",
            "phone": PHONE,
            "email": EMAIL,
            "url": WEBSITE,
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_ixlan(self, **kwargs):
        data = {
            "ix_id": 1,
            "id": 1,
            "name": self.make_name("Test"),
            "descr": NOTE,
            "mtu": 1500,
            "dot1q_support": False,
            "ixf_ixp_member_list_url_visible": "Private",
            "rs_asn": 12345,
            "arp_sponge": None,
        }
        if "ix_id" in kwargs:
            data["id"] = kwargs.get("ix_id")
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_ixpfx(self, **kwargs):
        data = {
            "ixlan_id": SHARED["ixlan_r_ok"].id,
            "protocol": "IPv4",
            "prefix": "10.%d.10.0/23" % (self.PREFIX_COUNT + 1),
            "in_dfz": True,
        }
        if "prefix" not in kwargs:
            self.PREFIX_COUNT += 1
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_netixlan(self, rename={}, **kwargs):
        data = {
            "net_id": SHARED["net_r_ok"].id,
            "ixlan_id": SHARED["ixlan_r_ok"].id,
            "notes": NOTE,
            "speed": 30000,
            "asn": 12345,
        }

        data.update(**kwargs)
        for k, v in list(rename.items()):
            data[v] = data[k]
            del data[k]

        data.update(
            ipaddr4=self.get_ip4(IXLan.objects.get(id=data["ixlan_id"])),
            ipaddr6=self.get_ip6(IXLan.objects.get(id=data["ixlan_id"])),
        )
        return data

    ##########################################################################

    @classmethod
    def make_name(self, name):
        return f"api-test:{name}:{uuid.uuid4()}"

    ##########################################################################

    @classmethod
    def extract_timestamps(self, data):
        timestamps = []

        if isinstance(data, dict):
            fields_to_check = [
                "created",
                "updated",
                "rir_status_updated",
                "ixf_import_request",
                "ixf_last_import",
            ]

            for field in fields_to_check:
                if field in data and data[field]:
                    timestamps.append(data[field])

            for key, value in data.items():
                timestamps.extend(self.extract_timestamps(value))

        elif isinstance(data, list):
            for item in data:
                timestamps.extend(self.extract_timestamps(item))

        return timestamps

    ##########################################################################

    @classmethod
    def serializer_related_fields(cls, serializer_class):
        """
        Returns declared relation fields on the provided serializer class.

        Returned value will be a tuple in which the first item is a list of
        field names for primary key related fields and the second item is a list
        of field names for related sets.
        """

        pk_rel = []
        nested_rel = []

        for name, fld in list(serializer_class._declared_fields.items()):
            if isinstance(fld, serializers.PrimaryKeyRelatedField):
                pk_rel.append(name[:-3])
            elif isinstance(fld, serializers.ListSerializer):
                nested_rel.append((name, fld.child))

        return (pk_rel, nested_rel)

    ##########################################################################

    def assert_handleref_integrity(self, data):
        """
        Assert the integrity of a handleref (which is
        the base of all the models exposed on the API).

        This is done by making sure all the handleref fields
        exist in the data.
        """

        self.assertIn("status", data)
        # self.assertIn("version", data)
        self.assertIn("id", data)
        self.assertIn("created", data)
        self.assertIn("updated", data)
        self.assertNotEqual("created", None)

    ##########################################################################

    def assert_data_integrity(self, data, typ, ignore=[]):
        if hasattr(self, "make_data_%s" % typ):
            msg = "data integrity failed on key '%s'"
            func = getattr(self, "make_data_%s" % typ)
            for timestamp in self.extract_timestamps(data):
                self.assertTrue(timestamp.endswith("Z") and "." not in timestamp)
            for k, v in list(func().items()):
                if k in ignore:
                    continue
                if type(v) in [str, str]:
                    self.assertIn(type(data.get(k)), [str, str], msg=msg % k)
                elif type(v) in [int, int]:
                    self.assertIn(type(data.get(k)), [int, int], msg=msg % k)
                elif type(v) in [list, list]:
                    self.assertIn(type(data.get(k)), [dict, list], msg=msg % k)
                else:
                    self.assertEqual(type(v), type(data.get(k)), msg=msg % k)

    ##########################################################################

    def assert_get_single(self, data):
        self.assertEqual(len(data), 1)
        return data[0]

    ##########################################################################

    def assert_get_forbidden(self, db, typ, id):
        with pytest.raises(PermissionDeniedException):
            db.get(typ, id)

    ##########################################################################

    def assert_get_handleref(self, db, typ, id, ignore=list()):
        data = self.assert_get_single(db.get(typ, id))
        self.assert_handleref_integrity(data)
        self.assert_data_integrity(data, typ, ignore=ignore)
        return data

    ##########################################################################

    def assert_existing_fields(self, a, b, ignore={}):
        for k, v in list(a.items()):
            if ignore and k in ignore:
                continue
            if k in ["suggest"]:
                continue
            self.assertEqual(v, b.get(k))

    ##########################################################################

    def assert_delete(
        self, db, typ, test_success=None, test_failure=None, test_protected=None
    ):
        if test_success:
            db.rm(typ, test_success)
            with pytest.raises(NotFoundException):
                self.assert_get_handleref(db, typ, test_success)

        if test_failure:
            with pytest.raises(PermissionDeniedException):
                db.rm(typ, test_failure)
            try:
                self.assert_get_handleref(db, typ, test_failure)
            except PermissionDeniedException:
                pass

        if test_protected:
            with pytest.raises(PermissionDeniedException):
                db.rm(typ, test_protected)
            assert DeskProTicket.objects.filter(
                subject__icontains=f"{typ}-{test_protected}"
            ).exists()

    ##########################################################################

    def assert_create(
        self, db, typ, data, test_failures=None, test_success=True, **kwargs
    ):
        if test_success:
            r_data = self.assert_get_single(
                db.create(typ, data, return_response=True).get("data")
            )
            self.assert_existing_fields(data, r_data, ignore=kwargs.get("ignore"))
            self.assertGreater(r_data.get("id"), 0)
            status_checked = False
            for model in QUEUE_ENABLED:
                if hasattr(model, "handleref") and model.handleref.tag == typ:
                    self.assertEqual(r_data.get("status"), "pending")
                    status_checked = True

            if not status_checked:
                expected_status = kwargs.get("expected_status", "ok")
                self.assertEqual(r_data.get("status"), expected_status)
        else:
            r_data = {}

        # if test_failures is set we want to test fail conditions
        if test_failures:
            # we test fail because of invalid data
            if "invalid" in test_failures:
                tests = test_failures["invalid"]
                if not isinstance(tests, list):
                    tests = [tests]

                for test in tests:
                    data_invalid = copy.copy(data)
                    for k, v in list(test.items()):
                        data_invalid[k] = v

                    with pytest.raises(InvalidRequestException) as excinfo:
                        db.create(typ, data_invalid, return_response=True)

                    assert "400 Bad Request" in str(excinfo.value)

            # we test fail because of parent entity status
            if "status" in test_failures:
                data_status = copy.copy(data)
                for k, v in list(test_failures["status"].items()):
                    data_status[k] = v

                with pytest.raises(InvalidRequestException) as excinfo:
                    db.create(typ, data_status, return_response=True)

                assert "not yet been approved" in str(excinfo.value)

            # we test fail because of permissions
            if "perms" in test_failures:
                data_perms = copy.copy(data)
                for k, v in list(test_failures["perms"].items()):
                    data_perms[k] = v

                with pytest.raises(PermissionDeniedException):
                    db.create(typ, data_perms, return_response=True)

                # clear negative cache after testing for perm failures
                # as we may run successive tests with different permissions
                # and dont want to get a false positive
                clear_negative_cache()

        return r_data

    ##########################################################################

    def assert_create_status_failure(self, db, typ, data):
        """
        Wrapper for assert_create for assertion of permission failure.
        """
        self.assert_create(
            db, typ, data, test_failures={"status": {}}, test_success=False
        )

    ##########################################################################

    def assert_update(
        self, db, typ, id, data, test_failures=False, test_success=True, **kwargs
    ):
        ignore = kwargs.pop("ignore", [])

        if test_success:
            orig = self.assert_get_handleref(db, typ, id, ignore=ignore)
            print("ORIG", orig)
            orig.update(**data)
        else:
            orig = {"id": id}
            orig.update(**data)

        for k, v in list(orig.items()):
            if k[-3:] == "_id" and k[:-3] in orig:
                del orig[k[:-3]]

        if test_success:
            db.update(typ, **orig)
            u_data = self.assert_get_handleref(db, typ, id, ignore=ignore)
            if isinstance(test_success, list):
                for test in test_success:
                    if test and callable(test):
                        test(data, u_data)
            else:
                # self.assertGreater(u_data["version"], orig["version"])
                for k, v in list(data.items()):
                    if k in ignore:
                        continue
                    self.assertEqual(u_data.get(k), v)

        # if test_failures is set we want to test fail conditions
        if test_failures:
            # we test fail because of invalid data
            if "invalid" in test_failures:
                tests = test_failures["invalid"]

                # `invalid` test_failures can be a list to
                # test multiple instances of invalid values
                # however we also support passing a single
                # dict of fields, in which case we wrap
                # it in a list here.

                if not isinstance(tests, list):
                    tests = [tests]

                for test in tests:
                    data_invalid = copy.copy(orig)
                    for k, v in list(test.items()):
                        data_invalid[k] = v

                    with pytest.raises(InvalidRequestException) as excinfo:
                        db.update(typ, **data_invalid)
                    assert "400 Bad Request" in str(excinfo.value)

            # we test fail because of permissions
            if "perms" in test_failures:
                data_perms = copy.copy(orig)
                for k, v in list(test_failures["perms"].items()):
                    data_perms[k] = v

                # if data is empty set something so we don't
                # trigger the empty data error
                data_perms["_dummy_"] = 1

                with pytest.raises(PermissionDeniedException):
                    db.update(typ, **data_perms)

            # we test failure to update readonly fields
            if "readonly" in test_failures:
                data_ro = copy.copy(orig)
                b_data = self.assert_get_handleref(db, typ, id, ignore=ignore)
                data_ro.update(**test_failures["readonly"])
                db.update(typ, **data_ro)
                u_data = self.assert_get_handleref(db, typ, id, ignore=ignore)
                for k, v in list(test_failures["readonly"].items()):
                    self.assertEqual(u_data.get(k), b_data.get(k))

    ##########################################################################

    def assert_list_filter_related(
        self, target, rel, fld="id", valid=None, valid_m=None
    ):
        # if not valid:
        #    valid = [o.id for k, o in SHARED.items() if type(
        #             o) != int and k.find("%s_" % target) == 0]

        if fld != "id":
            qfld = "_%s" % fld
        else:
            qfld = fld

        ids = [
            getattr(SHARED["%s_r_ok" % rel], fld),
            getattr(SHARED["%s_rw_ok" % rel], fld),
        ]
        kwargs_s = {f"{rel}_{qfld}": getattr(SHARED["%s_r_ok" % rel], fld)}
        kwargs_m = {f"{rel}_{qfld}__in": ",".join([str(id) for id in ids])}

        attr = getattr(REFTAG_MAP[target], rel, None)
        if attr and not isinstance(attr, property):
            valid_s = [
                r.id
                for r in REFTAG_MAP[target]
                .objects.filter(**kwargs_s)
                .filter(status="ok")
            ]

            valid_m = [
                r.id
                for r in REFTAG_MAP[target]
                .objects.filter(**{f"{rel}_{qfld}__in": ids})
                .filter(status="ok")
            ]

        elif target == "poc":
            valid_s = [SHARED["%s_r_ok_public" % target].id]

            valid_m = [
                SHARED["%s_r_ok_public" % target].id,
                SHARED["%s_rw_ok_public" % target].id,
            ]
        elif target == "ixpfx":
            valid_s = [
                SHARED["%s_r_ok" % target].id,
                SHARED["%s_r_v6_ok" % target].id,
            ]

            valid_m = [
                SHARED["%s_r_ok" % target].id,
                SHARED["%s_rw_ok" % target].id,
                SHARED["%s_r_v6_ok" % target].id,
                SHARED["%s_rw_v6_ok" % target].id,
            ]

        else:
            valid_s = [SHARED["%s_r_ok" % target].id]

            valid_m = [SHARED["%s_r_ok" % target].id, SHARED["%s_rw_ok" % target].id]

        # exact
        data = self.db_guest.all(target, **kwargs_s)
        self.assertGreater(len(data), 0)
        for row in data:
            self.assert_data_integrity(row, target)
            self.assertIn(row["id"], valid_s)

        # in
        data = self.db_guest.all(target, **kwargs_m)
        self.assertGreater(len(data), 0)
        for row in data:
            self.assert_data_integrity(row, target)
            self.assertIn(row["id"], valid_m)

    ##########################################################################

    def assert_related_depth(
        self,
        obj,
        serializer_class,
        r_depth,
        t_depth,
        note_tag,
        typ="listing",
        list_exclude=[],
        field_name=None,
    ):
        """
        Asserts the data integrity of structures within a result that has
        been expanded via the depth parameter.
        """

        # get all the realtion ship properties declared in the serializer
        pk_flds, n_flds = self.serializer_related_fields(serializer_class)

        # some tag so we can track where the assertions fail since this will
        # be doing nested checks
        note_tag = "%s(%d/%d)" % (note_tag, r_depth, t_depth)

        # first check that the provided object is not None, as this should
        # never be the case
        #
        # special case: facility.campus is allowed to be None
        if field_name not in ["campus"]:
            self.assertNotEqual(obj, None, msg=note_tag)
        elif obj is None:
            return

        # single primary key relation fields
        for pk_fld in pk_flds:
            # serializer has marked field as to be excluded from serialized data
            # don't check for it
            if pk_fld in list_exclude:
                continue

            if typ == "listing":
                # in listing mode, depth should never expand pk relations
                self.assertEqual(
                    obj.get(pk_fld), None, msg=f"PK Relation {note_tag} {pk_fld}"
                )
            else:
                # in single get mode, expand everything as long as we are at
                # a relative depth greater than 1
                if r_depth >= 1:
                    serializer_class = REFTAG_MAP_SLZ.get(pk_fld)
                    if serializer_class:
                        self.assert_related_depth(
                            obj.get(pk_fld),
                            serializer_class,
                            r_depth - 1,
                            t_depth,
                            f"{note_tag}.{pk_fld}",
                            typ=typ,
                            field_name=pk_fld,
                        )
                else:
                    self.assertIn(
                        type(obj.get(pk_fld)),
                        [int, type(None)],
                        msg=f"PK Relation {note_tag} {pk_fld}",
                    )

        # nested set relations
        for n_fld, n_fld_cls in n_flds:
            # make exception for social media field, as that is a JSON field
            # and will exist in its expanded form even at depth 0
            if n_fld == "social_media":
                continue

            if r_depth > 1:
                # sets should be expanded to objects
                self.assertIn(
                    n_fld, obj, msg=f"Nested set existing (dN) {note_tag} {n_fld}"
                )

                # make sure set exists and is of the correct type
                self.assertEqual(
                    type(obj[n_fld]),
                    list,
                    msg=f"Nested set list type (dN) {note_tag} {n_fld}",
                )

                # assert further depth expansions on all expanded objects in
                # the set
                for row in obj[n_fld]:
                    self.assert_related_depth(
                        row,
                        n_fld_cls,
                        r_depth - 2,
                        t_depth,
                        f"{note_tag}.{n_fld}",
                        typ=typ,
                        list_exclude=getattr(n_fld_cls.Meta, "list_exclude", []),
                        field_name=n_fld,
                    )

            elif r_depth == 1:
                # sets should be expanded to ids
                self.assertIn(
                    n_fld, obj, msg=f"Nested set existing (d1) {note_tag} {n_fld}"
                )

                # make sure set exists and is of the correct type
                self.assertEqual(
                    type(obj[n_fld]),
                    list,
                    msg=f"Nested set list type (d1) {note_tag} {n_fld}",
                )

                # make all values in the set are of type int or long
                for row in obj[n_fld]:
                    self.assertIn(
                        type(row),
                        [int, int],
                        msg=f"Nested set containing ids (d1) {note_tag} {n_fld}",
                    )
            else:
                # sets should not exist
                self.assertNotIn(
                    n_fld,
                    obj,
                    msg=f"Netsted set not existing (d0) {note_tag} {n_fld}",
                )

    ##########################################################################
    # TESTS WITH USER THAT IS NOT A MEMBER OF AN ORGANIZATION
    ##########################################################################

    def test_user_001_GET_org(self):
        self.assert_get_handleref(self.db_user, "org", SHARED["org_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_net(self):
        data = self.assert_get_handleref(self.db_user, "net", SHARED["net_r_ok"].id)
        self.assertNotEqual(len(data.get("poc_set")), 0)

    def test_user_001_GET_net_filter_legacy_info_type(self):
        """
        Test that API filters legacy info_type values correctly.

        The expected behaviour is that filters targeting the old info_type field
        are behaving correctly and return the expected results (via the new info_types set field)
        """

        net = SHARED["net_r_ok"]

        # test equality

        data = self.db_user.all("net", id=net.id, info_type="NSP", depth=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        # not found, raises 404
        with pytest.raises(NotFoundException):
            data = self.db_user.all("net", id=net.id, info_type="Content", depth=0)

        net.info_types = ["Content", "NSP"]
        net.save()

        data = self.db_user.all("net", id=net.id, info_type="NSP", depth=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        data = self.db_user.all("net", id=net.id, info_type="Content", depth=0)
        self.assertEqual(len(data), 1)

        # test __in

        data = self.db_user.all("net", id=net.id, info_type__in="NSP", depth=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        data = self.db_user.all("net", id=net.id, info_type__in="Content,NSP", depth=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        data = self.db_user.all(
            "net", id=net.id, info_type__in="Enterprise,NSP", depth=0
        )
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        with pytest.raises(NotFoundException):
            data = self.db_user.all(
                "net", id=net.id, info_type__in="Enterprise", depth=0
            )

        # test __contains

        data = self.db_user.all("net", id=net.id, info_type__contains="NSP", depth=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        data = self.db_user.all(
            "net", id=net.id, info_type__contains="Content", depth=0
        )
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        # test __startswith
        # should match on indiviudal values

        data = self.db_user.all("net", id=net.id, info_type__startswith="NS", depth=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        data = self.db_user.all("net", id=net.id, info_type__startswith="Co", depth=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], SHARED["net_r_ok"].id)

        with pytest.raises(NotFoundException):
            data = self.db_user.all(
                "net", id=net.id, info_type__startswith="En", depth=0
            )

    ##########################################################################

    def test_user_001_GET_net_obj_count(self):
        network = SHARED["net_r_ok"]

        # need to modify objects for signals to propagate
        netixlan = network.netixlan_set.first()

        netfac = network.netfac_set.first()

        data = self.assert_get_handleref(self.db_user, "net", network.id)
        self.assertEqual(data.get("ix_count"), 0)
        self.assertEqual(data.get("fac_count"), 0)

        # test that values are updated when we add connections
        with reversion.create_revision():
            netixlan.status = "ok"
            netixlan.save()

        with reversion.create_revision():
            netfac.status = "ok"
            netfac.save()

        data = self.assert_get_handleref(self.db_user, "net", network.id)
        self.assertEqual(data.get("ix_count"), 1)
        self.assertEqual(data.get("fac_count"), 1)

    ##########################################################################

    def test_user_001_GET_ix(self):
        self.assert_get_handleref(self.db_user, "ix", SHARED["ix_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_ix_obj_count(self):
        ix = SHARED["ix_r_ok"]
        # need to modify objects for signals to propagate
        netixlan = ix.ixlan.netixlan_set.first()

        ixfac = ix.ixfac_set.first()

        data = self.assert_get_handleref(self.db_user, "ix", ix.id)
        self.assertEqual(data.get("net_count"), 0)
        self.assertEqual(data.get("fac_count"), 0)

        # test that values are updated when we add connections
        with reversion.create_revision():
            netixlan.status = "ok"
            netixlan.save()

        with reversion.create_revision():
            ixfac.status = "ok"
            ixfac.save()

        data = self.assert_get_handleref(self.db_user, "ix", ix.id)
        self.assertEqual(data.get("net_count"), 1)
        self.assertEqual(data.get("fac_count"), 1)

    ##########################################################################

    def test_user_001_GET_ix_protocols(self):
        ix = SHARED["ix_r_ok"]
        ixlan = ix.ixlan

        data = self.assert_get_handleref(self.db_user, "ix", SHARED["ix_r_ok"].id)
        self.assertEqual(data.get("proto_unicast"), True)
        self.assertEqual(data.get("proto_ipv6"), True)

        for ixpfx in ixlan.ixpfx_set.all():
            ixpfx.delete(force=True)

        data = self.assert_get_handleref(self.db_user, "ix", SHARED["ix_r_ok"].id)

        # If there's no ipv4 prefix, proto_unicast should be False
        self.assertEqual(data.get("proto_unicast"), False)

        # If there's no ipv6 prefix, proto_unicast should be False
        self.assertEqual(data.get("proto_ipv6"), False)

    ##########################################################################

    def test_user_001_GET_carrier(self):
        self.assert_get_handleref(self.db_user, "carrier", SHARED["carrier_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_campus(self):
        self.assert_get_handleref(self.db_user, "campus", SHARED["campus_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_carrierfac(self):
        self.assert_get_handleref(
            self.db_user, "carrierfac", SHARED["carrierfac_r_ok"].id
        )

    ##########################################################################

    def test_user_001_GET_fac(self):
        self.assert_get_handleref(self.db_user, "fac", SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_fac_obj_count(self):
        facility = SHARED["fac_r_ok"]
        # Need to create revisions to send signals
        with reversion.create_revision():
            ixfac = facility.ixfac_set.first()
            ixfac.status = "pending"
            ixfac.save()

        with reversion.create_revision():
            netfac = facility.netfac_set.first()
            netfac.status = "pending"
            netfac.save()

        data = self.assert_get_handleref(self.db_user, "fac", SHARED["fac_r_ok"].id)
        self.assertEqual(data.get("net_count"), 0)
        self.assertEqual(data.get("ix_count"), 0)

        # Check that counts are updated with new connections
        with reversion.create_revision():
            # Need to create a revision
            ixfac.status = "ok"
            ixfac.save()

        with reversion.create_revision():
            netfac.status = "ok"
            netfac.save()

        data = self.assert_get_handleref(self.db_user, "fac", SHARED["fac_r_ok"].id)
        self.assertEqual(data.get("net_count"), 1)
        self.assertEqual(data.get("ix_count"), 1)

    ##########################################################################

    def test_user_001_GET_fac_with_filter_diverse_serving_substations(self):
        fac_data_with_diverse = self.make_data_fac(diverse_serving_substations=True)
        facility_with_diverse = Facility.objects.create(
            status="ok", **fac_data_with_diverse
        )

        fac_data_without_diverse = self.make_data_fac(diverse_serving_substations=False)
        facility_without_diverse = Facility.objects.create(
            status="ok", **fac_data_without_diverse
        )

        response = self.db_user._request(
            "fac?diverse_serving_substations=true", method="GET"
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn(facility_with_diverse.name, [f["name"] for f in data["data"]])
        self.assertNotIn(
            facility_without_diverse.name, [f["name"] for f in data["data"]]
        )

        response_false = self.db_user._request(
            "fac?diverse_serving_substations=false", method="GET"
        )
        self.assertEqual(response_false.status_code, 200)

        data_false = response_false.json()
        self.assertIn(
            facility_without_diverse.name, [f["name"] for f in data_false["data"]]
        )
        self.assertNotIn(
            facility_with_diverse.name, [f["name"] for f in data_false["data"]]
        )

    ##########################################################################

    def test_user_001_GET_poc_public(self):
        self.assert_get_handleref(self.db_user, "poc", SHARED["poc_r_ok_public"].id)

    ##########################################################################

    def test_user_001_GET_poc_users(self):
        self.assert_get_handleref(self.db_user, "poc", SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_user_001_GET_poc_private(self):
        self.assert_get_forbidden(self.db_user, "poc", SHARED["poc_r_ok_private"].id)

    ##########################################################################

    def test_user_001_GET_nefac(self):
        self.assert_get_handleref(self.db_user, "netfac", SHARED["netfac_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_netixlan(self):
        self.assert_get_handleref(self.db_user, "netixlan", SHARED["netixlan_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_ixfac(self):
        data = self.assert_get_handleref(self.db_user, "ixfac", SHARED["ixfac_r_ok"].id)
        assert data.get("name")
        assert data.get("city")
        assert data.get("country")

    ##########################################################################

    def test_user_001_GET_ixlan(self):
        data = self.assert_get_handleref(self.db_user, "ixlan", SHARED["ixlan_r_ok"].id)
        assert data.get("ixf_ixp_import_enabled") != None

    ##########################################################################

    def test_user_001_GET_ixlan_ixf_ixp_member_list_url(self):
        for ixlan in self.db_user.all(
            "ixlan", ixf_ixp_member_list_url__startswith="http"
        ):
            if ixlan["ixf_ixp_member_list_url_visible"] in ["Public", "Users"]:
                assert ixlan["ixf_ixp_member_list_url"] == "http://localhost"
            else:
                assert "ixf_ixp_member_list_url" not in ixlan

    ##########################################################################

    def test_user_001_GET_ixpfx(self):
        self.assert_get_handleref(self.db_user, "ixpfx", SHARED["ixpfx_r_ok"].id)

    ##########################################################################

    def test_user_005_list_poc(self):
        data = self.db_guest.all("poc", limit=1000)
        for row in data:
            self.assertIn(row.get("visible"), ["Users", "Public"])

        # next assert should remain as long as there are private pocs left
        # in the database, once all private pocs have been changed/removed
        # this test can be remove as well (#944)
        data = self.db_guest.all("poc", visible="Private", limit=100)
        self.assertEqual(0, len(data))

    ##########################################################################

    def test_user_001_GET_as_set(self):
        data = self.db_guest.all("as_set")
        networks = Network.objects.filter(status="ok")
        for net in networks:
            self.assertEqual(data[0].get(f"{net.asn}"), net.irr_as_set)

    ##########################################################################
    # TESTS WITH USER THAT IS ORGANIZATION MEMBER
    ##########################################################################

    def test_org_member_001_GET_poc_public(self):
        self.assert_get_handleref(
            self.db_org_member, "poc", SHARED["poc_r_ok_public"].id
        )

    ##########################################################################

    def test_org_member_001_GET_poc_users(self):
        self.assert_get_handleref(
            self.db_org_member, "poc", SHARED["poc_r_ok_users"].id
        )

    ##########################################################################

    def test_org_member_001_GET_poc_private(self):
        self.assert_get_handleref(
            self.db_org_member, "poc", SHARED["poc_r_ok_private"].id
        )

    #########################################################################

    def test_org_member_001_GET_ixlan_ixf_ixp_member_list_url(self):
        for ixlan in self.db_org_member.all(
            "ixlan", ixf_ixp_member_list_url__startswith="http"
        ):
            if ixlan["ixf_ixp_member_list_url_visible"] in ["Public", "Users"]:
                assert ixlan["ixf_ixp_member_list_url"] == "http://localhost"
            else:
                if ixlan["id"] == SHARED["ixlan_r3_ok"].id:
                    assert ixlan["ixf_ixp_member_list_url"] == "http://localhost"
                else:
                    assert "ixf_ixp_member_list_url" not in ixlan

    #########################################################################

    def test_org_member_001_POST_ix_with_perms(self):
        data = self.make_data_ix(prefix=self.get_prefix4())
        org = SHARED["org_rw_ok"]

        org.usergroup.user_set.add(self.user_org_member)
        self.user_org_member.grainy_permissions.add_permission(org, "cr")

        self.assert_create(
            self.db_org_member,
            "ix",
            data,
            ignore=["prefix"],
        )

    ##########################################################################

    def test_atomicity(self):
        """
        Test that POST, PUT and DELETE requests to the api use
        atomic database transactions
        """

        # cause POST, PUT and DELETE to fail before returning
        # a response
        NetworkViewSet._test_mode_force_failure = True

        # test POST atomicity

        data = self.make_data_net(asn=9000900)

        with patch.object(
            RdapLookup,
            "get_asn",
            side_effect=lambda *args, **kwargs: Mock(emails=["admin@org.com"]),
        ):
            with pytest.raises(Exception) as exc:
                self.assert_create(self.db_org_admin, "net", data)

        assert "simulated" in str(exc.value)

        assert not Network.objects.filter(asn=9009000).exists()

        # test PUT atomicty

        net = SHARED["net_rw_ok"]
        orig_name = net.name

        with pytest.raises(Exception) as exc:
            self.assert_update(
                self.db_org_admin,
                "net",
                net.id,
                {"name": self.make_name("Test Atomicity")},
            )

        assert "simulated" in str(exc.value)

        net.refresh_from_db()
        assert net.name == orig_name

        # test DELETE atomicity

        unprotected_net = Network.objects.create(
            name="Unprotected Network", asn=90009000, org=net.org, status="ok"
        )

        assert unprotected_net.status == "ok"

        with pytest.raises(Exception) as exc:
            self.assert_delete(
                self.db_org_admin,
                "net",
                test_success=unprotected_net.id,
            )

        assert "simulated" in str(exc.value)

        unprotected_net.refresh_from_db()
        assert unprotected_net.status == "ok"

        unprotected_net.delete(hard=True)

        # reset test mode
        NetworkViewSet._test_mode_force_failure = False

    ##########################################################################
    # TESTS WITH USER THAT IS ORGANIZATION ADMINISTRATOR
    ##########################################################################

    ##########################################################################

    def test_org_admin_001_GET_poc_public(self):
        self.assert_get_handleref(
            self.db_org_admin, "poc", SHARED["poc_r_ok_public"].id
        )

    ##########################################################################

    def test_org_admin_001_GET_poc_users(self):
        self.assert_get_handleref(self.db_org_admin, "poc", SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_org_admin_001_GET_poc_private(self):
        # org admin is admin of rw org, so trying to access the private poc of the r org
        # should still be forbidden
        self.assert_get_forbidden(
            self.db_org_admin, "poc", SHARED["poc_r_ok_private"].id
        )

    #########################################################################

    def test_org_admin_001_GET_ixlan_ixf_ixp_member_list_url(self):
        for ixlan in self.db_org_admin.all(
            "ixlan", ixf_ixp_member_list_url__startswith="http"
        ):
            if ixlan["ixf_ixp_member_list_url_visible"] in ["Public", "Users"]:
                assert ixlan["ixf_ixp_member_list_url"] == "http://localhost"
            else:
                if ixlan["id"] == SHARED["ixlan_rw3_ok"].id:
                    assert ixlan["ixf_ixp_member_list_url"] == "http://localhost"
                else:
                    assert "ixf_ixp_member_list_url" not in ixlan

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ix(self):
        data = self.make_data_ix(prefix=self.get_prefix4())

        r_data = self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            ignore=["prefix"],
            test_failures={
                "invalid": {"prefix": self.get_prefix4(), "name": ""},
                "perms": {
                    "prefix": self.get_prefix4(),
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    # set org to an organization the user doesnt have perms to
                    "org_id": SHARED["org_r_ok"].id,
                },
                "status": {
                    # need to set name again so it doesnt fail unique validation
                    "prefix": self.get_prefix4(),
                    "name": self.make_name("Test"),
                    "org_id": SHARED["org_rwp"].id,
                },
                "readonly": {
                    "proto_multicast": True,
                    "proto_unicast": True,
                    "proto_ipv6": False,
                },
            },
        )

        # test that ixlan id and prefix id were return in the POST
        # response (see #609)
        assert r_data.get("ixlan_id") > 0
        assert r_data.get("ixpfx_id") > 0

        SHARED["ix_id"] = r_data.get("id")

        # make sure ixlan was created and has matching id
        ix = InternetExchange.objects.get(id=SHARED["ix_id"])
        assert ix.ixlan
        assert ix.ixlan.id == ix.id

        self.assert_update(
            self.db_org_admin,
            "ix",
            SHARED["ix_id"],
            {"name": self.make_name("Test")},
            test_failures={
                "invalid": {"name": ""},
                "perms": {"id": SHARED["ix_r_ok"].id},
                "readonly": {"ixf_net_count": 50, "ixf_last_import": "not even valid"},
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "ix",
            test_success=SHARED["ix_id"],
            test_failure=SHARED["ix_r_ok"].id,
        )

        self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            test_success=False,
            test_failures={
                "invalid": {
                    "prefix": self.get_prefix4(),
                    "tech_email": "",
                },
            },
        )

        self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            test_success=False,
            test_failures={
                "invalid": {
                    "prefix": self.get_prefix4(),
                    "website": "",
                },
            },
        )

        self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            test_success=False,
            test_failures={
                "invalid": {
                    "social_media": {"", ""},
                },
            },
        )

        self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            test_success=False,
            test_failures={
                "invalid": {"prefix": ""},
            },
        )

        # test ix creation with a ipv6 prefix
        data = self.make_data_ix(prefix=self.get_prefix6())
        self.assert_create(self.db_org_admin, "ix", data, ignore=["prefix"])

        # check protected ix validation
        self.assert_delete(
            self.db_org_admin,
            "ix",
            test_protected=SHARED["ix_rw_ok"].id,
        )

    ##########################################################################

    def test_org_admin_002_PUT_ix_media(self):
        ix = SHARED["ix_rw_ok"]
        data = self.assert_get_handleref(self.db_org_admin, "ix", ix.id)
        data.update(media="ATM")
        self.db_org_admin.update("ix", **data)

        data = self.assert_get_handleref(self.db_org_admin, "ix", ix.id)
        assert data["media"] == "Ethernet"

    ##########################################################################

    def test_org_admin_002_POST_ix_request_ixf_import(self):
        ix = SHARED["ix_rw_ok"]

        data = (
            self.db_org_admin._request(
                f"ix/{ix.id}/request_ixf_import", method="POST", data="{}"
            )
            .json()
            .get("data")[0]
        )

        assert data["ixf_import_request"]
        assert data["ixf_import_request_status"] == "queued"

        resp = self.db_org_admin._request(
            f"ix/{ix.id}/request_ixf_import", method="POST", data="{}"
        )

        assert resp.status_code == 429

        resp = self.db_org_member._request(
            f"ix/{ix.id}/request_ixf_import", method="POST", data="{}"
        )

        assert resp.status_code in [401, 403]

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_fac(self):
        data = self.make_data_fac()

        r_data = self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            ignore=["latitude", "longitude"],
            test_failures={
                "invalid": [
                    {"name": ""},
                    {"name": self.make_name("Test"), "website": ""},
                ],
                "perms": {
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    # set org to an organization the user doesnt have perms to
                    "org_id": SHARED["org_r_ok"].id,
                },
                "status": {
                    "name": self.make_name("Test"),
                    "org_id": SHARED["org_rwp"].id,
                },
            },
        )

        SHARED["fac_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "fac",
            SHARED["fac_id"],
            {"name": self.make_name("Test")},
            ignore=["latitude", "longitude"],
            test_failures={
                "invalid": {"name": ""},
                "perms": {"id": SHARED["fac_r_ok"].id},
                "readonly": {
                    "rencode": str(uuid.uuid4())[
                        :6
                    ].upper(),  # this should not take as it is read only
                },
            },
        )

        self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            test_success=False,
            test_failures={
                "invalid": {
                    "social_media": {"service": "website"},
                },
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "fac",
            test_success=SHARED["fac_id"],
            test_failure=SHARED["fac_r_ok"].id,
        )

        # check protected ix validation
        self.assert_delete(
            self.db_org_admin,
            "fac",
            test_protected=SHARED["fac_rw_ok"].id,
        )

        # Create new data with a non-null rencode
        data_new = self.make_data_fac()
        obsolete_rencode = str(uuid.uuid4())[:6].upper()
        data_new["rencode"] = obsolete_rencode

        # Data should be successfully created
        r_data_new = self.assert_get_single(
            self.db_org_admin.create("fac", data_new, return_response=True).get("data")
        )

        # But rencode should be null
        assert r_data_new["rencode"] == ""

    ##########################################################################

    def test_org_admin_002_POST_PUT_fac_region_continent(self):
        data = self.make_data_fac()

        # test: we attempt to create a facility and providing a value
        # for region_continent, since the field is read only the server
        # should ignore this value, and come back with North America
        # in the response

        data["region_continent"] = "Europe"

        r_data = self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            # tell `assert_create` to not compare the value we pass
            # for region_continent with the value returned from the save
            ignore=["region_continent", "latitude", "longitude"],
            test_failures={},
        )
        fac_id = r_data.get("id")

        assert r_data["region_continent"] == "North America"
        fac = Facility.objects.get(id=fac_id)
        assert fac.region_continent == "North America"

        # test: we attempt to update the facility, trying to set a
        # value for region_continent, the server should ignoe this

        self.assert_update(
            self.db_org_admin,
            "fac",
            fac_id,
            {"region_continent": "Europe"},
            # tell `assert_update` to not compare the value we pass
            # for region_continent with the value returned from the save
            ignore=["region_continent", "latitude", "longitude"],
        )

        fac = Facility.objects.get(id=fac_id)
        assert fac.region_continent == "North America"

    ##########################################################################

    def geo_mock_init(self, key, timeout):
        pass

    def geo_gmaps_mock_geocode_freeform(location):
        return {"lat": 30.091435, "lng": 31.25435}

    @patch.object(geo.GoogleMaps, "__init__", geo_mock_init)
    @patch.object(geo.Melissa, "__init__", geo_mock_init)
    @override_settings(MELISSA_KEY="")
    @override_settings(GOOGLE_GEOLOC_API_KEY="")
    def test_org_admin_002_PUT_fac_geocode_missing_geocode(self):
        with patch.object(
            geo.GoogleMaps,
            "geocode_freeform",
            side_effect=lambda location: {"lat": 30.091435, "lng": 31.25435},
        ):
            data = self.make_data_fac()
            data.pop("latitude")
            data.pop("longitude")
            r_data = self.assert_create(
                self.db_org_admin,
                "fac",
                data,
            )
            fac_id = r_data.get("id")

            assert r_data["latitude"] == None
            assert r_data["longitude"] == None

            self.assert_update(
                self.db_org_admin,
                "fac",
                fac_id,
                {"latitude": 30.093435, "longitude": 31.255350},
                test_failures={
                    "invalid": [
                        {"latitude": 35.689487, "longitude": 139.691711},
                    ],
                },
                ignore=["latitude", "longitude"],
            )

    ##########################################################################

    @patch.object(geo.GoogleMaps, "__init__", geo_mock_init)
    @patch.object(geo.Melissa, "__init__", geo_mock_init)
    def test_org_admin_002_PUT_fac_geocode_existing_geocode(self):
        with patch.object(
            geo.GoogleMaps,
            "geocode_freeform",
            side_effect=lambda location: {"lat": 30.091435, "lng": 31.25435},
        ):
            data = self.make_data_fac()
            r_data = self.assert_create(
                self.db_org_admin,
                "fac",
                data,
                ignore=["latitude", "longitude"],
            )
            fac_id = r_data.get("id")

            Facility.objects.filter(id=fac_id).update(
                latitude=data.get("latitude"), longitude=data.get("longitude")
            )

            self.assert_update(
                self.db_org_admin,
                "fac",
                fac_id,
                {"latitude": 30.093445, "longitude": 31.24535},
                test_failures={
                    "invalid": [
                        {"latitude": 30.059545, "longitude": 31.24935},
                    ],
                },
            )

    ##########################################################################

    def test_org_admin_002_POST_PUT_fac_available_voltage(self):
        data = self.make_data_fac()

        r_data = self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            test_failures={
                "invalid": [
                    {"available_voltage_services": ["Invalid"]},
                ],
            },
            ignore=["longitude", "latitude"],
        )

        SHARED["fac_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "fac",
            SHARED["fac_id"],
            {"available_voltage_services": ["480 VAC"]},
            test_failures={
                "invalid": {"available_voltage_services": ["Invalid"]},
            },
            ignore=["longitude", "latitude"],
        )

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_fac_zipcode(self):
        data = self.make_data_fac()

        # Requires a zipcode if country is a country
        # with postal codes (ie US)
        r_data = self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            test_failures={
                "invalid": [
                    {"name": self.make_name("Test"), "zipcode": ""},
                ],
            },
            test_success=False,
        )

        # Change to country w/o postal codes
        data["country"] = "ZW"
        data["zipcode"] = ""

        r_data = self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            ignore=["longitude", "latitude"],
        )
        assert r_data["zipcode"] == ""

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_carrier(self):
        data = self.make_data_carrier()

        r_data = self.assert_create(
            self.db_org_admin,
            "carrier",
            data,
            test_failures={
                "invalid": {"name": ""},
                "perms": {
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    # set org to an organization the user doesnt have perms to
                    "org_id": SHARED["org_r_ok"].id,
                },
                "status": {
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    "org_id": SHARED["org_rwp"].id,
                },
            },
        )

        SHARED["carrier_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "carrier",
            SHARED["carrier_id"],
            {"name": self.make_name("Test")},
            test_failures={
                "invalid": {"name": ""},
                "perms": {"id": SHARED["carrier_r_ok"].id},
            },
        )

        self.assert_create(
            self.db_org_admin,
            "carrier",
            data,
            test_success=False,
            test_failures={
                "invalid": {
                    "social_media": {"service": "website"},
                },
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "carrier",
            test_success=SHARED["carrier_id"],
            test_failure=SHARED["carrier_r_ok"].id,
        )

    ##########################################################################

    def test_org_admin_002_approve_carrierfac(self):
        """
        Tests the carrier-facility creation and approval
        processes

        As of #1344 all carrierfac objects are automatically approved.
        """

        # create carrer-facility

        carrier = SHARED["carrier_rw_ok"]
        facility = SHARED["fac_r_ok"]

        data = {"carrier_id": carrier.id, "fac_id": facility.id}

        r_data = (
            self.db_org_admin._request("carrierfac", method="POST", data=data)
            .json()
            .get("data")[0]
        )

        SHARED["carrierfac_id"] = r_data.get("id")

        carrierfac = CarrierFacility.objects.get(id=SHARED["carrierfac_id"])

        # assert that the carrier-facility is status pending (needs to be approved)

        assert carrierfac.facility == facility
        assert carrierfac.carrier == carrier
        assert carrierfac.status == "ok"

    def test_org_admin_002_auto_approve_carrierfac(self):
        """
        Tests the carrier-facility creation and AUTO approval
        processes

        When the carrier and the facility have the same org, connection
        should be automatically approvued
        """

        # create carrier-facility

        carrier = SHARED["carrier_rw_ok"]
        facility = SHARED["fac_rw_ok"]

        SHARED["carrierfac_rw_ok"].delete(hard=True)

        data = {"carrier_id": carrier.id, "fac_id": facility.id}

        r_data = (
            self.db_org_admin._request("carrierfac", method="POST", data=data)
            .json()
            .get("data")[0]
        )

        SHARED["carrierfac_id"] = r_data.get("id")

        carrierfac = CarrierFacility.objects.get(id=SHARED["carrierfac_id"])

        # assert that the carrier-facility is status ok

        assert carrierfac.facility == facility
        assert carrierfac.carrier == carrier
        assert carrierfac.status == "ok"

    def test_org_admin_002_POST_PUT_DELETE_campus(self):
        data = self.make_data_campus()

        r_data = self.assert_create(
            self.db_org_admin,
            "campus",
            data,
            test_failures={
                "invalid": {"name": ""},
                "perms": {
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    # set org to an organization the user doesnt have perms to
                    "org_id": SHARED["org_r_ok"].id,
                },
                "status": {
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    "org_id": SHARED["org_rwp"].id,
                },
            },
            expected_status="pending",
        )

        SHARED["campus_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "campus",
            SHARED["campus_id"],
            {"name": self.make_name("Test")},
            test_failures={
                "invalid": {"name": ""},
                "perms": {"id": SHARED["campus_r_ok"].id},
            },
        )

        self.assert_create(
            self.db_org_admin,
            "carrier",
            data,
            test_success=False,
            test_failures={
                "invalid": {
                    "social_media": {"service": "website"},
                },
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "campus",
            test_success=SHARED["campus_id"],
            test_failure=SHARED["campus_r_ok"].id,
        )

    ##########################################################################

    def test_api_filter(self):
        ix_count = InternetExchange.objects.filter(status="ok").count()
        ix_count_json = InternetExchange.objects.exclude(status="deleted").count()

        # /api/ix return all IX with status "ok"
        assert (
            len(self.db_guest._request("ix", method="GET").json().get("data"))
            == ix_count
        )

        assert (
            len(self.db_guest._request("ix?limit=5", method="GET").json().get("data"))
            == 5
        )

        # /api/ix.json return all IX with status not "deleted"
        assert (
            len(self.db_guest._request("ix.json", method="GET").json().get("data"))
            == ix_count_json
        )

        assert (
            len(
                self.db_guest._request("ix.json?limit=5", method="GET")
                .json()
                .get("data")
            )
            == 5
        )

    def test_api_filter_netixlan_port(self):
        # Create a NetworkIXLan instance
        data = self.make_data_netixlan(
            network_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
            status="ok",
            net_side=SHARED["fac_r_ok"],
            ix_side=SHARED["fac_rw_ok"],
        )
        data.pop("net_id")
        _ = NetworkIXLan.objects.create(**data)

        # Get queryset of netixlan with status="ok"
        netixlan_ids = NetworkIXLan.objects.filter(status="ok").values_list(
            "id", flat=True
        )

        # Define helper function to check response
        def check_side_response(port_name, port_id):
            response = (
                self.db_guest._request(f"netixlan?{port_name}={port_id}", method="GET")
                .json()
                .get("data")
            )
            for item in response:
                assert (
                    item["id"] in netixlan_ids
                ), f"{port_name} {item['id']} not found in netixlan queryset"

        # Check ix_side and net_side
        check_side_response("ix_side", SHARED["fac_rw_ok"].id)
        check_side_response("net_side", SHARED["fac_r_ok"].id)

    def test_campus_status(self):
        data = self.make_data_campus()

        cam = Campus.objects.create(**data)

        fac_data = self.make_data_fac()
        fac_data["latitude"] = 40.736844
        fac_data["longitude"] = -74.173402

        fac = Facility.objects.create(status="ok", **fac_data)
        self.db_org_admin._request(
            f"campus/{cam.id}/add-facility/{fac.id}", method="POST", data="{}"
        ).json().get("data")[0]

        fac_data2 = self.make_data_fac()
        fac_data2["latitude"] = 40.717723
        fac_data2["longitude"] = -74.008299

        fac2 = Facility.objects.create(status="ok", **fac_data2)
        self.db_org_admin._request(
            f"campus/{cam.id}/add-facility/{fac2.id}", method="POST", data="{}"
        ).json().get("data")[0]

        cam = Campus.objects.get(id=cam.id)
        cam.name_long = "test lomng"
        cam.save()

        assert cam.status == "ok"

        self.db_org_admin._request(
            f"campus/{cam.id}/remove-facility/{fac2.id}", method="POST", data="{}"
        ).json().get("data")[0]

        cam = Campus.objects.get(id=cam.id)
        cam.name_long = "test long"
        cam.save()

        assert cam.status == "pending"

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_net(self):
        data = self.make_data_net(asn=9000900)
        # test fail email mismatch
        with patch.object(
            RdapLookup,
            "get_asn",
            side_effect=lambda *args, **kwargs: Mock(emails=["admin@org123.com"]),
        ):
            self.assert_create(
                self.db_org_admin,
                "net",
                data,
                test_failures={
                    "invalid": {"asn": "Your email address and ASN emails mismatch"},
                },
                test_success=False,
            )

        # test fail email mismatch in tutorial mode if not bogon asn
        pdb_settings.TUTORIAL_MODE = True
        self.assert_create(
            self.db_org_admin,
            "net",
            data,
            test_failures={
                "invalid": {"asn": "Your email address and ASN emails mismatch"},
            },
            test_success=False,
        )
        pdb_settings.TUTORIAL_MODE = False

        # test success
        with patch.object(
            RdapLookup,
            "get_asn",
            side_effect=lambda *args, **kwargs: Mock(
                emails=["admin@org.com", "admin@org123.com"]
            ),
        ):
            r_data = self.assert_create(
                self.db_org_admin,
                "net",
                data,
                test_failures={
                    "invalid": {"name": ""},
                    "perms": {
                        # need to set name again so it doesnt fail unique validation
                        "name": self.make_name("Test"),
                        "asn": data["asn"] + 1,
                        # set org to an organization the user doesnt have perms to
                        "org_id": SHARED["org_r_ok"].id,
                    },
                    "status": {
                        "org_id": SHARED["org_rwp"].id,
                        "asn": data["asn"] + 1,
                        "name": self.make_name("Test"),
                    },
                },
            )

        SHARED["net_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "net",
            SHARED["net_id"],
            {"name": self.make_name("Test")},
            test_failures={
                "invalid": {"name": ""},
                "perms": {"id": SHARED["net_r_ok"].id},
            },
        )

        # Test ASN cannot update
        self.assert_update(
            self.db_org_admin,
            "net",
            SHARED["net_id"],
            data,
            test_failures={
                "invalid": {"asn": data["asn"] + 1},
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "net",
            test_success=SHARED["net_id"],
            test_failure=SHARED["net_r_ok"].id,
        )

        # Test RiR not found failure

        r_data = self.assert_create(
            self.db_org_admin,
            "net",
            data,
            test_failures={"invalid": {"asn": 9999999}},
            test_success=False,
        )

    ###########################################################################

    def test_org_admin_002_POST_PUT_net_legacy_info_type(self):
        """
        Tests that setting the legacy info_type field during network
        create and update will clobber the value correctly into
        the new info_types field as a single value in a set
        """

        data = self.make_data_net(asn=9000900, info_type="NSP")

        with patch.object(
            RdapLookup,
            "get_asn",
            side_effect=lambda *args, **kwargs: Mock(emails=["admin@org.com"]),
        ):
            r_data = self.assert_create(
                self.db_org_admin,
                "net",
                data,
            )

        assert r_data["info_type"] == "NSP"
        assert r_data["info_types"] == ["NSP"]

        SHARED["net_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "net",
            SHARED["net_id"],
            {"info_type": "Content"},
        )

        net = Network.objects.get(id=SHARED["net_id"])

        assert net.info_type == "Content"
        assert net.info_types == ["Content"]

    ##########################################################################

    def test_org_admin_002_POST_net_rir_status(self):
        """
        Implements `Anytime` network update logic for RIR status handling
        laid out in https://github.com/peeringdb/peeringdb/issues/1280

        Anytime a network is saved:

        if an ASN is added, set rir_status="ok" and set rir_status_updated=created
        """

        # Create network with the ASN is flagged OK automatically
        data = self.make_data_net(asn=9000900)
        with patch.object(
            RdapLookup,
            "get_asn",
            side_effect=lambda *args, **kwargs: Mock(
                emails=["admin@org.com", "admin@org123.com"]
            ),
        ):
            r_data = self.assert_create(
                self.db_org_admin,
                "net",
                data,
            )
        assert r_data.get("rir_status") == "ok"

    ##########################################################################

    def test_org_admin_002_PUT_net_toggle_allow_ixp_update(self):
        net = SHARED["net_rw_ok"]
        ixlan = SHARED["ixlan_rw_ok"]
        ip4 = self.get_ip4(ixlan)
        ip6 = self.get_ip6(ixlan)

        IXFDATA = {
            "asnum": net.asn,
            "member_type": "peering",
            "connection_list": [
                {
                    "ixp_id": 20,
                    "state": "active",
                    "if_list": [{"if_speed": 10000}],
                    "vlan_list": [
                        {
                            "ipv4": {"address": ip4, "routeserver": True},
                            "ipv6": {"address": ip6, "routeserver": True},
                        }
                    ],
                }
            ],
        }

        member_data = IXFMemberData.objects.create(
            asn=net.asn,
            ipaddr4=ip4,
            ipaddr6=ip6,
            ixlan=ixlan,
            speed=10000,
            operational=True,
            is_rs_peer=True,
            fetched=DATETIME,
            data=json.dumps(IXFDATA),
            status="ok",
        )

        ixlan.ixf_ixp_import_enabled = True
        ixlan.save()

        qset_assert = NetworkIXLan.objects.filter(
            ixlan=ixlan,
            network=net,
            ipaddr4=member_data.ipaddr4,
            ipaddr6=member_data.ipaddr6,
        )

        assert not qset_assert.exists()

        self.assert_update(
            self.db_org_admin,
            "net",
            SHARED["net_rw_ok"].id,
            {"name": self.make_name("TesT")},
        )

        assert not qset_assert.exists()

        assert (
            net.poc_set_active.filter(
                role__in=["Technical", "NOC", "Policy"], visible__in=["Users", "Public"]
            )
            .exclude(email="")
            .exists()
        )

        self.assert_update(
            self.db_org_admin,
            "net",
            SHARED["net_rw_ok"].id,
            {"allow_ixp_update": True},
        )

        for netixlan in net.netixlan_set_active.all():
            print(netixlan)

        assert qset_assert.exists()

        net_without_poc = Network.objects.create(status="ok", **self.make_data_net())

        assert not (
            net_without_poc.poc_set_active.filter(
                role__in=["Technical", "NOC", "Policy"], visible__in=["Users", "Public"]
            )
            .exclude(email="")
            .exists()
        )

        self.assert_update(
            self.db_org_admin,
            "net",
            net_without_poc.id,
            {"allow_ixp_update": True},
            test_success=False,
            test_failures={
                "invalid": {
                    "allow_ixp_update": "Cannot be enabled - must have a Technical, NOC, or Policy point of contact with valid email."
                }
            },
        )

    ##########################################################################

    def test_org_admin_002_GET_net_rir_status(self):
        net = SHARED["net_rw_ok"]

        now = timezone.now()
        net.rir_status = "assigned"
        net.rir_status_updated = now
        net.save()

        api_data = self.db_org_admin.get("net", SHARED["net_rw_ok"].id)

        net.refresh_from_db()
        assert api_data[0]["rir_status"] == "ok"
        assert net.rir_status == "assigned"
        assert net.rir_status_updated == now

    ##########################################################################

    def test_org_admin_002_POST_net_looking_glass_url(self):
        with patch.object(
            RdapLookup,
            "get_asn",
            side_effect=lambda *args, **kwargs: Mock(
                emails=["admin@org.com", "admin@org123.com"]
            ),
        ):
            for scheme in ["http", "https", "ssh", "telnet"]:
                r_data = self.assert_create(
                    self.db_org_admin,
                    "net",
                    self.make_data_net(
                        asn=9000900, looking_glass=f"{scheme}://foo.bar"
                    ),
                    test_failures={"invalid": {"looking_glass": "foo://www.bar.com"}},
                )
                Network.objects.get(id=r_data["id"]).delete(hard=True)

    ##########################################################################

    def test_org_admin_002_POST_net_route_server_url(self):
        with patch.object(
            RdapLookup,
            "get_asn",
            side_effect=lambda *args, **kwargs: Mock(
                emails=["admin@org.com", "admin@org123.com"]
            ),
        ):
            for scheme in ["http", "https", "ssh", "telnet"]:
                r_data = self.assert_create(
                    self.db_org_admin,
                    "net",
                    self.make_data_net(asn=9000900, route_server=f"{scheme}://foo.bar"),
                    test_failures={"invalid": {"route_server": "foo://www.bar.com"}},
                )
                Network.objects.get(id=r_data["id"]).delete(hard=True)

    ##########################################################################

    def test_org_admin_002_POST_net_deleted(self):
        data = self.make_data_net(asn=SHARED["net_rw_dupe_deleted"].asn)

        with pytest.raises(InvalidRequestException) as excinfo:
            self.db_org_admin.create("net", data, return_response=True)

        # check exception vs value
        assert "Network has been deleted. Please contact" in excinfo.value.extra["asn"]

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_as_set(self):
        """
        The as-set endpoint is readonly, so all of these should
        fail.
        """
        data = self.make_data_net(asn=9000900)

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.assert_create(self.db_org_admin, "as_set", data)
        assert "You do not have permission" in str(excinfo.value)

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_org_admin.update("as_set", {"9000900": "AS-ZZZ"})
        assert "You do not have permission" in str(excinfo.value)

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_org_admin.rm("as_set", SHARED["net_rw_ok"].asn)
        assert "You do not have permission" in str(excinfo.value)

    ##########################################################################

    def test_org_admin_002_POST_net_bogon_asn(self):
        # Test bogon asn failure

        data = self.make_data_net()
        for bogon_asn in inet.BOGON_ASN_RANGES:
            self.assert_create(
                self.db_org_admin,
                "net",
                data,
                test_failures={"invalid": {"asn": bogon_asn[0]}},
                test_success=False,
            )

        # server running in tutorial mode should be allowed
        # to create networks with bogon asns, so we test that
        # as well

        pdb_settings.TUTORIAL_MODE = True

        for bogon_asn in inet.TUTORIAL_ASN_RANGES:
            data = self.make_data_net(asn=bogon_asn[0])
            self.assert_create(self.db_org_admin, "net", data)

        pdb_settings.TUTORIAL_MODE = False

    ##########################################################################

    def test_org_admin_002_POST_net_website_required(self):
        # Test bogon asn failure

        data = self.make_data_net(website="")

        self.assert_create(
            self.db_org_admin,
            "net",
            data,
            test_failures={"invalid": {"website": ""}},
            test_success=False,
        )

    ##########################################################################

    def test_org_admin_002_POST_net_social_media_required(self):
        # Test bogon asn failure

        data = self.make_data_net(social_media="")

        self.assert_create(
            self.db_org_admin,
            "net",
            data,
            test_failures={"invalid": {"social_media": ""}},
            test_success=False,
        )

    ##########################################################################

    def test_org_admin_002_POST_ix_website_required(self):
        # Test bogon asn failure

        data = self.make_data_ix(website="")

        self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            test_failures={"invalid": {"website": ""}},
            test_success=False,
        )

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_netfac(self):
        # remove the existing netfac that was created
        # in the setup
        NetworkFacility.objects.get(
            network_id=SHARED["net_rw_ok"].id, facility_id=SHARED["fac_rw_ok"].id
        ).delete(hard=True)
        NetworkFacility.objects.get(
            network_id=SHARED["net_rw_pending"].id,
            facility_id=SHARED["fac_rw_pending"].id,
        ).delete(hard=True)

        data = {
            "net_id": SHARED["net_rw_ok"].id,
            "fac_id": SHARED["fac_rw_ok"].id,
        }

        r_data = self.assert_create(
            self.db_org_admin,
            "netfac",
            data,
            test_failures={
                "invalid": {"net_id": ""},
                "perms": {
                    # set network to one the user doesnt have perms to
                    "net_id": SHARED["net_r_ok"].id
                },
                "status": {
                    "net_id": SHARED["net_rw_pending"].id,
                    "fac_id": SHARED["fac_rw_pending"].id,
                },
            },
        )

        SHARED["netfac_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "netfac",
            SHARED["netfac_id"],
            data,
            test_success=False,
            test_failures={
                "invalid": {"fac_id": ""},
                "perms": {"net_id": SHARED["net_r_ok"].id},
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "netfac",
            test_success=SHARED["netfac_id"],
            test_failure=SHARED["netfac_r_ok"].id,
        )

        # re-create deleted netfac
        r_data = self.assert_create(self.db_org_admin, "netfac", data)
        # re-delete
        self.assert_delete(
            self.db_org_admin, "netfac", test_success=SHARED["netfac_id"]
        )

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_poc(self):
        data = self.make_data_poc(net_id=SHARED["net_rw_ok"].id, role="Abuse")

        r_data = self.assert_create(
            self.db_org_admin,
            "poc",
            data,
            test_failures={
                "invalid": {"net_id": ""},
                "perms": {
                    # set network to one the user doesnt have perms to
                    "net_id": SHARED["net_r_ok"].id
                },
                "status": {"net_id": SHARED["net_rw_pending"].id},
            },
        )

        SHARED["poc_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "poc",
            SHARED["poc_id"],
            {"role": "Sales"},
            test_failures={
                "invalid": {"role": "INVALID"},
                "perms": {"net_id": SHARED["net_r_ok"].id},
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "poc",
            test_success=SHARED["poc_id"],
            test_failure=SHARED["poc_r_ok_users"].id,
        )

        # soft-deleted pocs should return blank
        # values for sensitive fields (#569)

        poc = self.db_org_admin.all("poc", id=SHARED["poc_id"], since=1)[0]
        assert poc["name"] == ""
        assert poc["phone"] == ""
        assert poc["email"] == ""
        assert poc["url"] == ""

        # pocs can no longer be made private (#944)

        self.assert_update(
            self.db_org_admin,
            "poc",
            SHARED["poc_rw_ok_users"].id,
            {},
            test_success=False,
            test_failures={
                "invalid": {"visible": "Private"},
            },
        )
        r_data = self.assert_create(
            self.db_org_admin,
            "poc",
            {},
            test_success=False,
            test_failures={
                "invalid": {"visible": "Private"},
            },
        )

        # pocs require email or phone to be set

        self.assert_update(
            self.db_org_admin,
            "poc",
            SHARED["poc_rw_ok_users"].id,
            {"email": "test@localhost", "phone": ""},
            test_failures={
                "invalid": {"email": "", "phone": ""},
            },
        )

        data = self.make_data_poc(net_id=SHARED["net_rw_ok"].id, role="Abuse")
        data["email"] = ""

        r_data = self.assert_create(
            self.db_org_admin,
            "poc",
            data,
            test_failures={
                "invalid": {"email": "", "phone": ""},
            },
        )

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ixlan(self):
        data = self.make_data_ixlan(ix_id=SHARED["ix_rw_ok"].id)

        with self.assertRaises(Exception) as exc:
            self.assert_create(
                self.db_org_admin,
                "ixlan",
                data,
                test_failures={
                    "invalid": {"ix_id": ""},
                    "perms": {"ix_id": SHARED["ix_r_ok"].id},
                    "status": {"ix_id": SHARED["ix_rw_pending"].id},
                },
            )
        self.assertIn('Method "POST" not allowed', str(exc.exception))

        self.assert_update(
            self.db_org_admin,
            "ixlan",
            SHARED["ixlan_rw_ok"].id,
            {"name": self.make_name("Test")},
            test_failures={
                "invalid": {"mtu": "7000"},
                "perms": {"ix_id": SHARED["ix_r_ok"].id},
            },
        )

        with self.assertRaises(Exception) as exc:
            self.assert_delete(
                self.db_org_admin,
                "ixlan",
                test_success=SHARED["ixlan_rw_ok"].id,
                test_failure=SHARED["ixlan_r_ok"].id,
            )
        self.assertIn('Method "DELETE" not allowed', str(exc.exception))

    ##########################################################################

    def test_org_admin_002_PUT_ixlan_dot1qsupport(self):
        ixlan = SHARED["ixlan_rw_ok"]
        data = self.assert_get_handleref(self.db_org_admin, "ixlan", ixlan.id)
        data.update(dot1q_support=True)
        self.db_org_admin.update("ixlan", **data)

        data = self.assert_get_handleref(self.db_org_admin, "ixlan", ixlan.id)
        assert data["dot1q_support"] is False

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ixpfx(self):
        data = self.make_data_ixpfx(
            ixlan_id=SHARED["ixlan_rw_ok"].id, prefix="206.126.236.0/25"
        )

        r_data = self.assert_create(
            self.db_org_admin,
            "ixpfx",
            data,
            test_failures={
                "invalid": [{"prefix": "127.0.0.0/8"}, {"in_dfz": False}],
                "perms": {
                    "prefix": "205.127.237.0/24",
                    "ixlan_id": SHARED["ixlan_r_ok"].id,
                },
                "status": {
                    "prefix": "205.127.237.0/24",
                    "ixlan_id": SHARED["ixlan_rw_pending"].id,
                },
            },
        )

        SHARED["ixpfx_id"] = r_data["id"]

        self.assert_update(
            self.db_org_admin,
            "ixpfx",
            SHARED["ixpfx_id"],
            {"prefix": "206.127.236.0/26"},
            test_failures={
                "invalid": [{"prefix": "NEEDS TO BE VALID PREFIX"}, {"in_dfz": False}],
                "perms": {"ixlan_id": SHARED["ixlan_r_ok"].id},
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "ixpfx",
            test_success=SHARED["ixpfx_id"],
            test_failure=SHARED["ixpfx_r_ok"].id,
        )

        # re-create deleted ixpfx
        r_data = self.assert_create(self.db_org_admin, "ixpfx", data)
        # re-delete
        self.assert_delete(self.db_org_admin, "ixpfx", test_success=SHARED["ixpfx_id"])

        # re-creating a deleted ixpfx that is under another exchange
        # that we don't have write perms too
        pfx = IXLanPrefix.objects.create(
            ixlan=SHARED["ixlan_r_ok"], prefix="205.127.237.0/24", protocol="IPv4"
        )
        pfx.delete()

        data.update(prefix="205.127.237.0/24")
        r_data = self.assert_create(
            self.db_org_admin,
            "ixpfx",
            data,
        )

        # make sure protocols are validated
        r_data = self.assert_create(
            self.db_org_admin,
            "ixpfx",
            data,
            test_failures={
                "invalid": {"prefix": "207.128.238.0/24", "protocol": "IPv6"},
            },
            test_success=False,
        )

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_netixlan(self):
        data = self.make_data_netixlan(
            net_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
        )

        r_data = self.assert_create(
            self.db_org_admin,
            "netixlan",
            data,
            test_failures={
                "invalid": {"ipaddr4": "a b c"},
                "perms": {
                    # set network to one the user doesnt have perms to
                    "ipaddr4": self.get_ip4(SHARED["ixlan_rw_ok"]),
                    "ipaddr6": self.get_ip6(SHARED["ixlan_rw_ok"]),
                    "net_id": SHARED["net_r_ok"].id,
                },
            },
        )

        assert r_data["operational"]

        SHARED["netixlan_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "netixlan",
            SHARED["netixlan_id"],
            {"speed": 2000},
            test_failures={
                "invalid": {"ipaddr4": "NEEDS TO BE VALID IP"},
                "perms": {"net_id": SHARED["net_r_ok"].id},
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "netixlan",
            test_success=SHARED["netixlan_id"],
            test_failure=SHARED["netixlan_r_ok"].id,
        )

    ##########################################################################

    def test_org_admin_002_POST_netixlan_no_net_contact(self):
        network = SHARED["net_rw_ok"]

        for poc in network.poc_set_active.all():
            poc.role = "Abuse"
            poc.delete()

        data = self.make_data_netixlan(
            net_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
        )

        # When we create this netixlan it should fail with a
        # non-field-error.

        self.assert_create(
            self.db_org_admin,
            "netixlan",
            data,
            test_failures={"invalid": {"n/a": "n/a"}},
            test_success=False,
        )

        # Undelete poc but blank email
        poc = network.poc_set.first()
        poc.status = "ok"
        poc.email = ""
        poc.visible = "Public"
        poc.save()
        network.refresh_from_db()

        # Also fails with network contact that is
        # missing an email
        self.assert_create(
            self.db_org_admin,
            "netixlan",
            data,
            test_failures={"invalid": {"n/a": "n/a"}},
            test_success=False,
        )

    ##########################################################################

    def test_org_admin_002_POST_netixlan_reclaim(self):
        # create 1 deleted netixlan

        data_a = self.make_data_netixlan(
            network_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
            status="deleted",
        )
        data_a.pop("net_id")
        netixlan_a = NetworkIXLan.objects.create(**data_a)

        # create new netixlan re-claiming ipv4 and ipv6
        # addresses from the 2 netixlans we created earlier
        # ipv4 from netixlan a
        # ipv6 from netixlan b

        data_c = self.make_data_netixlan(
            net_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
        )
        data_c.update(ipaddr4=f"{netixlan_a.ipaddr4}", ipaddr6=f"{netixlan_a.ipaddr6}")

        r_data = self.assert_create(
            self.db_org_admin,
            "netixlan",
            data_c,
        )

        assert r_data["ipaddr4"] == f"{netixlan_a.ipaddr4}"
        assert r_data["ipaddr6"] == f"{netixlan_a.ipaddr6}"
        assert r_data["id"] == netixlan_a.id

    ##########################################################################

    def test_org_admin_002_POST_netixlan_reclaim_separated(self):
        # create 2 deleted netixlans

        data_a = self.make_data_netixlan(
            network_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
            status="deleted",
        )
        data_a.pop("net_id")
        netixlan_a = NetworkIXLan.objects.create(**data_a)

        data_b = self.make_data_netixlan(
            network_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
            status="deleted",
        )
        data_b.pop("net_id")
        netixlan_b = NetworkIXLan.objects.create(**data_b)

        # create new netixlan re-claiming ipv4 and ipv6
        # addresses from the 2 netixlans we created earlier
        # ipv4 from netixlan a
        # ipv6 from netixlan b

        data_c = self.make_data_netixlan(
            net_id=SHARED["net_rw_ok"].id,
            ixlan_id=SHARED["ixlan_rw_ok"].id,
            asn=SHARED["net_rw_ok"].asn,
        )
        data_c.update(ipaddr4=f"{netixlan_a.ipaddr4}", ipaddr6=f"{netixlan_b.ipaddr6}")

        r_data = self.assert_create(
            self.db_org_admin,
            "netixlan",
            data_c,
        )

        assert r_data["ipaddr4"] == f"{netixlan_a.ipaddr4}"
        assert r_data["ipaddr6"] == f"{netixlan_b.ipaddr6}"
        assert r_data["id"] == netixlan_a.id

        netixlan_a.refresh_from_db()
        netixlan_b.refresh_from_db()

        assert netixlan_b.ipaddr6 is None

    ##########################################################################

    def test_org_admin_002_POST_PUT_netixlan_validation(self):
        data = self.make_data_netixlan(
            net_id=SHARED["net_rw_ok"].id, ixlan_id=SHARED["ixlan_rw_ok"].id
        )

        test_failures = [
            # test failure if ip4 not in prefix
            {"invalid": {"ipaddr4": self.get_ip4(SHARED["ixlan_r_ok"])}},
            # test failure if ip6 not in prefix
            {"invalid": {"ipaddr6": self.get_ip6(SHARED["ixlan_r_ok"])}},
            # test failure if speed is below limit
            {"invalid": {"speed": 1}},
            # test failure if speed is above limit
            {"invalid": {"speed": 5250000}},
            # test failure if speed is None
            {"invalid": {"speed": None}},
        ]

        for test_failure in test_failures:
            self.assert_create(
                self.db_org_admin,
                "netixlan",
                data,
                test_failures=test_failure,
                test_success=False,
            )

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ixfac(self):
        data = {"fac_id": SHARED["fac_rw2_ok"].id, "ix_id": SHARED["ix_rw2_ok"].id}

        r_data = self.assert_create(
            self.db_org_admin,
            "ixfac",
            data,
            test_failures={
                "invalid": {"ix_id": ""},
                "perms": {
                    # set network to one the user doesnt have perms to
                    "ix_id": SHARED["ix_r_ok"].id
                },
                "status": {
                    "fac_id": SHARED["fac_rw2_pending"].id,
                    "ix_id": SHARED["ix_rw2_pending"].id,
                },
            },
        )

        SHARED["ixfac_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "ixfac",
            SHARED["ixfac_id"],
            {"fac_id": SHARED["fac_r2_ok"].id},
            test_failures={
                "invalid": {"fac_id": ""},
                "perms": {"ix_id": SHARED["ix_r_ok"].id},
            },
        )

        self.assert_delete(
            self.db_org_admin,
            "ixfac",
            test_success=SHARED["ixfac_id"],
            test_failure=SHARED["ixfac_r_ok"].id,
        )

    ##########################################################################

    def test_org_admin_003_PUT_org(self):
        self.assert_update(
            self.db_org_admin,
            "org",
            SHARED["org_rw_ok"].id,
            {"name": self.make_name("Test")},
            test_failures={
                "invalid": {"name": ""},
                "perms": {"id": SHARED["org_r_ok"].id},
            },
        )

    ##########################################################################

    def test_zz_org_admin_004_DELETE_org(self):
        org = Organization.objects.create(name="Deletable org", status="ok")
        org.admin_usergroup.user_set.add(self.user_org_admin)

        self.assert_delete(
            self.db_org_admin,
            "org",
            # can delete the org we just made
            test_success=org.id,
            # cant delete the org we don't have write perms to
            test_failure=SHARED["org_r_ok"].id,
        )
        self.assert_delete(
            self.db_org_admin,
            "org",
            # cant delete the org that we have write perms to
            # but is not empty
            test_failure=SHARED["org_rw_ok"].id,
        )

    ##########################################################################

    def test_org_admin_002_fac_901_circumvent_verification(self):
        """
        Tests that issue #901 is fixed

        When a verified (Status=ok) facility is soft-deleted
        re-creating another facility with an identical name
        should NOT have it skip verification queue and status
        should be pending.
        """

        org = SHARED["org_rw_ok"]

        fac = Facility.objects.create(org=org, status="ok", name="Facility Issue 901")

        assert fac.status == "ok"

        # soft-delete fac
        fac.delete()

        assert fac.status == "deleted"

        data = self.make_data_fac(name=fac.name)

        r_data = self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            ignore=["latitude", "longitude"],
        )

        assert r_data["status"] == "pending"
        fac.refresh_from_db()
        assert fac.status == "deleted"
        assert fac.id != r_data["id"]

    ##########################################################################

    def test_org_admin_002_ix_901_internal_error(self):
        """
        Tests that issue #901 is fixed

        When a verified (Status=ok) exchange is soft-deleted
        re-creating another exchange  with an identical name
        should NOT have it skip verification queue and status
        should be pending.
        """

        org = SHARED["org_rw_ok"]

        ix = InternetExchange(org=org, status="ok", name="Exchange Issue 901")
        ix.save()

        IXLanPrefix.objects.create(
            ixlan=ix.ixlan, status="ok", prefix=self.get_prefix4()
        )

        assert ix.status == "ok"

        # soft-delete ix
        ix.delete()

        assert ix.status == "deleted"

        data = self.make_data_ix(name=ix.name, prefix=self.get_prefix4())

        r_data = self.assert_create(self.db_org_admin, "ix", data, ignore=["prefix"])

        assert r_data["status"] == "pending"
        ix.refresh_from_db()
        assert ix.status == "deleted"
        assert ix.id != r_data["id"]

    ##########################################################################

    def test_org_admin_002_ix_ixlan_status_mismatch_1077(self):
        """
        Tests that issue #1077 is fixed

        Re-claiming the name of a soft-deleted exchange should not leave
        the exchange object as pending and the ixlan object as deleted.

        Instead both the exchange object and ixlan object should be pending
        """

        org = SHARED["org_rw_ok"]

        ix = InternetExchange(org=org, status="ok", name="Exchange Issue 1077")
        ix.save()

        prefix = self.get_prefix4()

        IXLanPrefix.objects.create(ixlan=ix.ixlan, status="ok", prefix=prefix)

        assert ix.status == "ok"

        ixpfx = IXLanPrefix.objects.get(prefix=prefix)
        assert ixpfx.status == "ok"

        # soft-delete ix
        ix.delete()

        assert ix.status == "deleted"
        assert ix.ixlan.status == "deleted"

        ixpfx.refresh_from_db()
        assert ixpfx.status == "deleted"

        data = self.make_data_ix(name=ix.name, prefix=self.get_prefix4())

        r_data = self.assert_create(self.db_org_admin, "ix", data, ignore=["prefix"])

        ix_new = InternetExchange.objects.get(id=r_data.get("id"))

        assert ix_new.status == "pending"
        assert ix_new.ixlan.status == "pending"
        assert ix_new.ixlan.ixpfx_set.first().status == "pending"

        assert ix.status == "deleted"
        assert ix.id != r_data["id"]

    ##########################################################################
    # GUEST TESTS
    ##########################################################################

    def test_guest_001_GET_org(self):
        self.assert_get_handleref(self.db_guest, "org", SHARED["org_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_net(self):
        data = self.assert_get_handleref(self.db_guest, "net", SHARED["net_r_ok"].id)
        for poc in data.get("poc_set"):
            self.assertEqual(poc["visible"], "Public")

    ##########################################################################

    def test_guest_001_GET_ix(self):
        self.assert_get_handleref(self.db_guest, "ix", SHARED["ix_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_fac(self):
        self.assert_get_handleref(self.db_guest, "fac", SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_poc_private(self):
        self.assert_get_forbidden(self.db_guest, "poc", SHARED["poc_r_ok_private"].id)

    ##########################################################################

    def test_guest_001_GET_poc_users(self):
        self.assert_get_forbidden(self.db_guest, "poc", SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_guest_001_GET_poc_public(self):
        self.assert_get_handleref(self.db_guest, "poc", SHARED["poc_r_ok_public"].id)

    ##########################################################################

    def test_guest_001_GET_nefac(self):
        self.assert_get_handleref(self.db_guest, "netfac", SHARED["netfac_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_netixlan(self):
        self.assert_get_handleref(self.db_guest, "netixlan", SHARED["netixlan_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_ixfac(self):
        self.assert_get_handleref(self.db_guest, "ixfac", SHARED["ixfac_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_ixlan(self):
        data = self.assert_get_handleref(
            self.db_guest, "ixlan", SHARED["ixlan_r_ok"].id
        )
        assert data.get("ixf_ixp_import_enabled") != None

    ##########################################################################

    def test_guest_001_GET_ixlan_ixf_ixp_member_list_url(self):
        for ixlan in self.db_guest.all(
            "ixlan", ixf_ixp_member_list_url__startswith="http"
        ):
            if ixlan["ixf_ixp_member_list_url_visible"] == "Public":
                assert ixlan["ixf_ixp_member_list_url"] == "http://localhost"
            else:
                assert "ixf_ixp_member_list_url" not in ixlan

    ##########################################################################

    def test_guest_001_GET_ixpfx(self):
        self.assert_get_handleref(self.db_guest, "ixpfx", SHARED["ixpfx_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_list_404(self):
        for tag in REFTAG_MAP:
            with pytest.raises(NotFoundException):
                data = self.db_guest.all(tag, limit=1, id=99999999)
            if tag == "net":
                with pytest.raises(NotFoundException):
                    data = self.db_guest.all(tag, limit=1, asn=99999999999)

        for tag in REFTAG_MAP:
            if tag == "poc":
                data = self.db_guest.all(tag, id=SHARED["poc_r_ok_public"].id)
            else:
                data = self.db_guest.all(tag, id=SHARED["%s_r_ok" % tag].id)
            self.assertEqual(len(data), 1)
            self.assert_handleref_integrity(data[0])

    ##########################################################################

    def test_guest_005_list_all(self):
        data = self.db_guest.all("org")
        self.assertGreater(len(data), 1)
        self.assert_handleref_integrity(data[0])
        self.assert_data_integrity(data[0], "org")

    ##########################################################################

    def test_guest_005_list_all_tags(self):
        for tag in REFTAG_MAP:
            if tag == "poc":
                continue
            data = self.db_guest.all(tag, limit=10)
            self.assertLess(len(data), 11)
            self.assert_handleref_integrity(data[0])

        data = self.db_guest.all("poc", limit=10, visible="Public")
        self.assertLess(len(data), 11)
        self.assert_handleref_integrity(data[0])

    ##########################################################################

    def test_org_admin_005_list(self):
        for tag in REFTAG_MAP:
            data = self.db_org_admin.all(tag, limit=10)
            self.assertLess(len(data), 11)
            self.assert_handleref_integrity(data[0])

            for row in data:
                self.assertEqual(row["status"], "ok")

    ##########################################################################

    def test_guest_005_org_fields_filter(self):
        data = self.db_guest.all("org", limit=10, fields=",".join(["name", "status"]))
        self.assertGreater(len(data), 0)
        for row in data:
            self.assertEqual(sorted(row.keys()), sorted(["name", "status"]))

        data = self.db_guest.get(
            "org", Organization.objects.first().id, fields=",".join(["name", "status"])
        )
        self.assertGreater(len(data), 0)
        self.assertEqual(sorted(data[0].keys()), sorted(["name", "status"]))

    ##########################################################################

    def test_guest_005_carrier_fields_filter(self):
        data = self.db_guest.all(
            "carrier", limit=10, fields=",".join(["name", "org_id"])
        )
        self.assertEqual(len(data), 3)

        for row in data:
            self.assertTrue(
                set(sorted(row.keys())).issubset({"name", "org_id", "website"})
            )

        data = self.db_guest.get(
            "carrier", Carrier.objects.first().id, fields=",".join(["name", "org_id"])
        )
        self.assertGreater(len(data), 0)
        for row in data:
            self.assertEqual(sorted(row.keys()), sorted(["name", "org_id", "website"]))

    ##########################################################################

    def test_guest_005_ixlan_fields_filter(self):
        """
        Tests the specific issue of #829 where a GET to an ixlan
        with fields parameter set would raise a 500 error for
        unauthenticated users.
        """
        data = self.db_guest.get(
            "ixlan", SHARED["ixlan_rw_ok"].id, fields="ixpfx_set", depth=2
        )
        assert len(data) == 1
        row = data[0]
        assert list(row.keys()) == ["ixpfx_set"]

    ##########################################################################

    def test_guest_005_list_limit(self):
        data = self.db_guest.all("org", limit=10)
        self.assertEqual(len(data), 10)
        self.assert_handleref_integrity(data[0])
        self.assert_data_integrity(data[0], "org")

    ##########################################################################

    def test_guest_005_list_pagination(self):
        org_ids = [org.id for org in Organization.objects.filter(status="ok")]

        for n in range(0, 1):
            data_a = self.db_guest.all("org", skip=n * 3, limit=3)
            for i in range(n, n + 3):
                assert data_a[i]["id"] == org_ids[i]

    ##########################################################################

    def test_guest_005_list_since(self):
        data = self.db_guest.all(
            "net", since=int(START_TIMESTAMP) - 10, status="deleted"
        )
        self.assertEqual(len(data), 2)
        self.assert_handleref_integrity(data[0])
        self.assert_data_integrity(data[0], "net")

    ##########################################################################

    def test_guest_005_list_campus_since(self):
        # test that pending campuses are included in incremental update
        # query (?since parameter)

        data = self.db_guest.all(
            "campus", since=int(START_TIMESTAMP) - 10, status="pending"
        )
        self.assertEqual(len(data), 7)
        self.assert_handleref_integrity(data[0])
        self.assert_data_integrity(data[0], "campus")

        for row in data:
            assert row["status"] == "pending"

    ##########################################################################

    def test_guest_005_list_carrier_no_website(self):
        carrier = SHARED["carrier_rw_ok"]
        carrier.website = ""
        carrier.save()

        data = self.db_guest.all("carrier", since=int(START_TIMESTAMP) - 10)
        self.assertEqual(len(data), 3)
        self.assert_handleref_integrity(data[0])
        self.assert_data_integrity(data[0], "carrier")

    ##########################################################################

    def test_guest_005_get_depth_all(self):
        """
        Tests all end points single object GET with all valid depths.
        This also asserts data structure integrity for objects expanded
        by the depth parameter.
        """

        for depth in [0, 1, 2, 3, 4]:
            for tag, slz in list(REFTAG_MAP_SLZ.items()):
                note_tag = f"({tag} {depth})"
                if tag == "poc":
                    o = SHARED["%s_r_ok_public" % tag]
                else:
                    o = SHARED["%s_r_ok" % tag]
                data = self.db_guest.get(tag, o.id, depth=depth)
                self.assertEqual(len(data), 1, msg="Data length %s" % note_tag)
                pk_flds, n_flds = self.serializer_related_fields(slz)

                obj = data[0]
                self.assert_related_depth(
                    obj, slz, depth, depth, note_tag, typ="single"
                )

    ##########################################################################

    def test_guest_005_list_depth_all(self):
        """
        Tests all end points multiple object GET with all valid depths.
        This also asserts data structure integrity for objects expanded
        by the depth parameter.
        """

        for depth in [0, 1, 2, 3]:
            for tag, slz in list(REFTAG_MAP_SLZ.items()):
                note_tag = f"({tag} {depth})"
                if tag == "poc":
                    o = SHARED["%s_r_ok_public" % tag]
                else:
                    o = SHARED["%s_r_ok" % tag]
                data = self.db_guest.all(tag, id=o.id, depth=depth)
                self.assertEqual(len(data), 1, msg="Data length %s" % note_tag)
                pk_flds, n_flds = self.serializer_related_fields(slz)

                obj = data[0]
                self.assert_related_depth(
                    obj, slz, depth, depth, note_tag, typ="listing"
                )

    ##########################################################################

    def test_guest_005_list_depth_not_set(self):
        data = self.db_guest.all("org", id=SHARED["org_r_ok"].id)
        self.assertEqual(data[0].get("net_set"), None)

    ##########################################################################

    def test_guest_005_list_depth_0(self):
        data = self.db_guest.all("org", id=SHARED["org_r_ok"].id, depth=0)
        self.assertEqual(data[0].get("net_set"), None)

    ##########################################################################

    def test_guest_005_list_depth_1(self):
        data = self.db_guest.all("org", id=SHARED["org_r_ok"].id, depth=1)
        self.assertEqual(len(data[0].get("net_set")), 3)
        self.assertEqual(data[0].get("net_set")[0], SHARED["net_r_ok"].id)
        self.assertEqual(data[0].get("net_set")[1], SHARED["net_r2_ok"].id)
        self.assertEqual(data[0].get("net_set")[2], SHARED["net_r3_ok"].id)

    #############################################################################

    def test_guest_005_list_depth_2(self):
        data = self.db_guest.all("org", id=SHARED["org_r_ok"].id, depth=2)
        self.assertEqual(len(data[0].get("net_set")), 3)
        obj = data[0].get("net_set")[0]
        self.assertEqual(obj.get("id"), SHARED["net_r_ok"].id)
        self.assert_data_integrity(obj, "net", ignore=["org_id"])

    #############################################################################

    def test_guest_005_list_depth_3(self):
        data = self.db_guest.all("org", id=SHARED["org_r_ok"].id, depth=3)
        self.assertEqual(len(data[0].get("net_set")), 3)
        obj = data[0].get("net_set")[0]
        self.assertEqual(obj.get("id"), SHARED["net_r_ok"].id)
        self.assert_data_integrity(obj, "net", ignore=["org_id"])

        obj = obj.get("netfac_set")
        self.assertEqual(len(obj), 1)
        self.assertEqual(obj[0], SHARED["netfac_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_dates_numeric(self):
        for flt, ass in list(NUMERIC_TESTS.items()):
            for fld in ["created", "updated"]:
                if flt in ["gt", "gte"]:
                    DATE = DATES["yesterday"]
                elif flt in ["lt"]:
                    DATE = DATES["tomorrow"]
                else:
                    DATE = DATES["today"]

                if flt:
                    kwargs = {f"{fld}__{flt}": DATE[1]}
                else:
                    kwargs = {fld: DATE[1]}
                data = self.db_guest.all("fac", limit=10, **kwargs)
                self.assertGreater(
                    len(data), 0, msg=f"{fld}_{flt} - data length assertion"
                )
                for row in data:
                    self.assert_data_integrity(row, "fac")
                    try:
                        dt = datetime.datetime.strptime(
                            row[fld], "%Y-%m-%dT%H:%M:%SZ"
                        ).date()
                    except ValueError:
                        dt = datetime.datetime.strptime(
                            row[fld], "%Y-%m-%dT%H:%M:%S.%fZ"
                        ).date()
                    fnc = getattr(self, "assert%s" % ass)
                    fnc(
                        dt,
                        DATE[0],
                        msg=f"{fld}__{flt}: {row[fld]}, {DATE[1]}",
                    )

    ##########################################################################

    def test_guest_005_list_filter_numeric(self):
        data = self.db_guest.all("net", asn=SHARED["net_r_ok"].asn)
        self.assertEqual(len(data), 1)
        self.assert_data_integrity(data[0], "net")
        self.assertEqual(data[0]["asn"], SHARED["net_r_ok"].asn)

    ##########################################################################

    def test_guest_005_list_filter_numeric_lte(self):
        data = self.db_guest.all("fac", id__lte=SHARED["fac_rw_ok"].id)
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertLessEqual(int(fac["id"]), SHARED["fac_rw_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_lt(self):
        data = self.db_guest.all("fac", id__lt=SHARED["fac_rw_ok"].id)
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertLess(int(fac["id"]), SHARED["fac_rw_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_gte(self):
        data = self.db_guest.all("fac", id__gte=SHARED["fac_r_ok"].id)
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertGreaterEqual(int(fac["id"]), SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_gt(self):
        data = self.db_guest.all("fac", id__gt=SHARED["fac_r_ok"].id)
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertGreater(int(fac["id"]), SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_in(self):
        ids = [SHARED["fac_r_ok"].id, SHARED["fac_rw_ok"].id]
        data = self.db_guest.all("fac", id__in="%s,%s" % tuple(ids))
        self.assertEqual(len(data), len(ids))
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertIn(int(fac["id"]), ids)

    ##########################################################################

    def test_guest_005_list_filter_string(self):
        data = self.db_guest.all("ix", name=SHARED["ix_r_ok"].name)
        self.assertEqual(len(data), 1)
        self.assert_data_integrity(data[0], "ix")
        self.assertEqual(data[0]["name"], SHARED["ix_r_ok"].name)

    ##########################################################################

    def test_guest_005_list_filter_string_contains(self):
        token = SHARED["ix_r_ok"].name[3:5]
        data = self.db_guest.all("ix", name__contains=token.lower())
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "ix")
        for ix in data:
            self.assertIn(token, ix["name"])

    ##########################################################################

    def test_guest_005_list_filter_string_startswith(self):
        token = SHARED["ix_r_ok"].name[0:5]
        data = self.db_guest.all("ix", name__startswith=token.lower())
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "ix")
        for ix in data:
            self.assertEqual(ix["name"][:5], token)

    ##########################################################################

    def test_guest_005_list_filter_string_in(self):
        cities = ["API Test:IX:RW:ok", "API Test:IX:R:ok"]
        data = self.db_guest.all("ix", name__in="%s,%s" % tuple(cities))
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "ix")
        for ix in data:
            self.assertIn(ix["name"], cities)

    ##########################################################################

    def test_guest_005_list_filter_relation_basic(self):
        data = self.db_guest.all("ix", org_id=SHARED["ix_r_ok"].org_id)
        self.assertEqual(len(data), 3)
        self.assert_data_integrity(data[0], "ix")
        self.assertEqual(data[0]["org_id"], SHARED["ix_r_ok"].org_id)

    ##########################################################################

    def test_guest_005_list_filter_relation_basic_2(self):
        data = self.db_guest.all("ix", org=SHARED["ix_r_ok"].org_id)
        self.assertEqual(len(data), 3)
        self.assert_data_integrity(data[0], "ix")
        self.assertEqual(data[0]["org_id"], SHARED["ix_r_ok"].org_id)

    ##########################################################################

    def test_guest_005_list_filter_relation_fld_xl(self):
        data = self.db_guest.all("netixlan", net_id__lt=4)
        for row in data:
            self.assertLess(row["net_id"], 4)

    ##########################################################################

    def test_guest_005_list_filter_relation_nested(self):
        data = self.db_user.all("poc", net__asn=SHARED["net_r_ok"].asn)
        self.assertEqual(len(data), 2)
        for row in data:
            self.assertEqual(row.get("net_id"), SHARED["net_r_ok"].id)

        # also test __id filter (bug issue #1032)

        data = self.db_user.all("poc", net__id=SHARED["net_r_ok"].id)
        self.assertEqual(len(data), 2)

        for row in data:
            self.assertEqual(row.get("net_id"), SHARED["net_r_ok"].id)

        # also test __id__in filter (bug issue #1032)

        data = self.db_user.all("poc", net__id__in=SHARED["net_r_ok"].id)
        self.assertEqual(len(data), 2)

        for row in data:
            self.assertEqual(row.get("net_id"), SHARED["net_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_poc(self):
        data = self.db_guest.all("poc", limit=100)
        for row in data:
            self.assertEqual(row.get("visible"), "Public")

        data = self.db_guest.all("poc", visible__in="Private,Users", limit=100)
        self.assertEqual(0, len(data))

    ##########################################################################

    def test_guest_005_list_filter_net_related(self):
        self.assert_list_filter_related("net", "ix")
        self.assert_list_filter_related("net", "ixlan")
        self.assert_list_filter_related("net", "netixlan")
        self.assert_list_filter_related("net", "netfac")
        self.assert_list_filter_related("net", "fac")
        self.assert_list_filter_related("net", "org")

    ##########################################################################

    def test_guest_005_list_filter_net_not_ix(self):
        ix = SHARED["ix_r_ok"]
        data_a = self.db_guest.all("net", ix=ix.id)
        data_b = self.db_guest.all("net", not_ix=ix.id)
        self.assertGreater(len(data_a), 0)
        self.assertGreater(len(data_b), 0)
        for row_b in data_b:
            for row_a in data_a:
                self.assertNotEqual(row_a["id"], row_b["id"])

    ##########################################################################

    def test_guest_005_list_filter_net_not_fac(self):
        fac = SHARED["fac_r_ok"]
        data_a = self.db_guest.all("net", fac=fac.id)
        data_b = self.db_guest.all("net", not_fac=fac.id)
        self.assertGreater(len(data_a), 0)
        self.assertGreater(len(data_b), 0)
        for row_b in data_b:
            for row_a in data_a:
                self.assertNotEqual(row_a["id"], row_b["id"])

    ##########################################################################

    def test_guest_005_list_filter_ixpfx_related(self):
        self.assert_list_filter_related("ixpfx", "ix")
        self.assert_list_filter_related("ixpfx", "ixlan")

    ##########################################################################

    def test_guest_005_list_filter_ixpfx_whereis(self):
        ixpfx = SHARED["ixpfx_r_ok"]

        ipaddr = f"{ixpfx.prefix[0]}"

        data = self.db_guest.all("ixpfx", whereis=ipaddr)

        assert len(data) == 1
        assert data[0]["id"] == ixpfx.id

    ##########################################################################

    def test_guest_005_list_filter_ix_related(self):
        self.assert_list_filter_related("ix", "ixlan")
        self.assert_list_filter_related("ix", "ixfac")
        self.assert_list_filter_related("ix", "fac")
        self.assert_list_filter_related("ix", "net")
        self.assert_list_filter_related("ix", "net", "asn")
        self.assert_list_filter_related("ix", "org")

    ##########################################################################

    def test_guest_005_list_filter_ix_ipblock(self):
        prefix = str(SHARED["ixpfx_r_ok"].prefix)[:-3]
        data = self.db_guest.all("ix", ipblock=prefix)
        self.assertGreater(len(data), 0)
        for row in data:
            self.assertEqual(row["id"], SHARED["ix_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_ix_capacity(self):
        SHARED["netixlan_r_ok"].speed = 1000
        SHARED["netixlan_r_ok"].save()

        NetworkIXLan.handleref.undeleted()

        data = self.db_guest.all("ix", capacity=1000)
        assert len(data) == 1
        for row in data:
            self.assertEqual(row["id"], SHARED["netixlan_r_ok"].ixlan.ix.id)

        data = self.db_guest.all("ix", capacity__gt=1000)
        assert len(data)
        for row in data:
            self.assertNotEqual(row["id"], SHARED["netixlan_r_ok"].ixlan.ix.id)

        data = self.db_guest.all("ix", capacity__lt=30000)
        assert len(data)
        for row in data:
            self.assertEqual(row["id"], SHARED["netixlan_r_ok"].ixlan.ix.id)

        data = self.db_guest.all("ix", capacity__lt=1000)
        assert not (len(data))

    ##########################################################################

    def test_guest_005_list_filter_ix_all_net(self):
        net_ids = ",".join(
            [
                str(SHARED["net_r_ok"].id),
            ]
        )

        data = self.db_guest.all("ix", all_net=net_ids)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], SHARED["ix_r_ok"].id)

        net_ids = ",".join(
            [
                str(SHARED["net_r_ok"].id),
                str(SHARED["net_rw_ok"].id),
            ]
        )

        data = self.db_guest.all("ix", all_net=net_ids)
        self.assertEqual(len(data), 0)

    ##########################################################################

    def test_guest_005_list_filter_ix_not_net(self):
        net_ids = ",".join(
            [
                str(SHARED["net_r_ok"].id),
            ]
        )

        data = self.db_guest.all("ix", not_net=net_ids)
        self.assertGreater(len(data), 1)
        for row in data:
            self.assertNotEqual(row["id"], SHARED["ix_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_ix_org_present(self):
        data = self.db_guest.all("ix", org_present=SHARED["org_r_ok"].id)
        self.assertEqual(len(data), 1)

        data = self.db_guest.all("ix", org_not_present=SHARED["org_r_ok"].id)
        self.assertGreater(len(data), 1)

    ##########################################################################

    def test_guest_005_list_filter_ix_name_search(self):
        ix = InternetExchange.objects.create(
            status="ok",
            **self.make_data_ix(
                name="Specific Exchange", name_long="This is a very specific exchange"
            ),
        )

        # rebuild search index (name_search requires it)
        call_command("rebuild_index", "--noinput")

        data = self.db_guest.all("ix", name_search=ix.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], ix.id)

        data = self.db_guest.all("ix", name_search=ix.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], ix.id)

        ix.delete(hard=True)

    ##########################################################################

    def test_guest_005_list_filter_ix_asn_overlap(self):
        # create three test networks
        networks = [
            Network.objects.create(status="ok", **self.make_data_net())
            for i in range(0, 3)
        ]

        # create two test exchanges
        exchanges = [
            InternetExchange.objects.create(status="ok", **self.make_data_ix())
            for i in range(0, 2)
        ]

        # collect ixlans
        ixlans = [ix.ixlan for ix in exchanges]

        # all three networks peer at first exchange
        for net in networks:
            NetworkIXLan.objects.create(
                network=net, ixlan=ixlans[0], status="ok", asn=net.asn, speed=0
            )

        # only the first two networks peer at second exchange
        for net in networks[:2]:
            NetworkIXLan.objects.create(
                network=net, ixlan=ixlans[1], status="ok", asn=net.asn, speed=0
            )

        # do test queries

        # query #1 - test overlapping exchanges for all 3 asns - should return first ix
        data = self.db_guest.all(
            "ix", asn_overlap=",".join([str(net.asn) for net in networks])
        )
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], exchanges[0].id)

        # query #2 - test overlapping exchanges for first 2 asns - should return both ixs
        data = self.db_guest.all(
            "ix", asn_overlap=",".join([str(net.asn) for net in networks[:2]])
        )
        self.assertEqual(len(data), 2)
        for row in data:
            self.assertIn(row["id"], [ix.id for ix in exchanges])

        # query #3 - should error when only passing one asn
        with pytest.raises(InvalidRequestException):
            self.db_guest.all("ix", asn_overlap=networks[0].asn)

        # query #4 - should error when passing too many asns
        with pytest.raises(InvalidRequestException):
            self.db_guest.all(
                "ix", asn_overlap=",".join([str(i) for i in range(0, 30)])
            )

        # clean up data
        for net in networks:
            net.delete(hard=True)
        for ix in exchanges:
            ix.delete(hard=True)

    ##########################################################################

    def test_guest_005_list_filter_fac_name_search(self):
        fac = Facility.objects.create(
            status="ok",
            **self.make_data_fac(
                name="Specific Facility", name_long="This is a very specific facility"
            ),
        )

        # rebuild search index (name_search requires it)
        call_command("rebuild_index", "--noinput")

        data = self.db_guest.all("fac", name_search=fac.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        data = self.db_guest.all("fac", name_search=fac.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        fac.delete(hard=True)

    ##########################################################################

    def test_guest_005_list_filter_fac_distance(self):
        # facility coordinates

        lat_fac = 41.876212
        lng_fac = -87.631453

        # city coordinates: chicago

        lat_chi = 41.878114
        lng_chi = -87.629798

        # create geo-coord cache
        # we do this so we dont have to query the google maps api
        # during the test

        GeoCoordinateCache.objects.create(
            country="US", city="Chicago", latitude=lat_chi, longitude=lng_chi
        )

        # pick one of the tests facilities and set its coordinates

        fac = SHARED["fac_r_ok"]
        fac.latitude = lat_fac
        fac.longitude = lng_fac
        fac.save()

        data = self.db_org_member.all("fac", country="US", city="Chicago", distance=10)

        assert len(data) == 1
        assert data[0]["id"] == fac.id

        settings.API_DISTANCE_FILTER_REQUIRE_AUTH = True
        settings.API_DISTANCE_FILTER_REQUIRE_VERIFIED = True

        # unverified users are blocked from doing distance query

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_guest.all("fac", country="US", city="Chicago", distance=10)
        assert "verify" in f"{excinfo.value}"

        # unauthenticated users are blocked from doing distance query

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_anon.all("fac", country="US", city="Chicago", distance=10)
        assert "authenticate" in f"{excinfo.value}"

        # clear negative cache

        caches["negative"].clear()

        # adjust settings to allow the above

        settings.API_DISTANCE_FILTER_REQUIRE_VERIFIED = False
        self.db_guest.all("fac", country="US", city="Chicago", distance=10)

        settings.API_DISTANCE_FILTER_REQUIRE_AUTH = False
        self.db_anon.all("fac", country="US", city="Chicago", distance=10)

    ##########################################################################

    def test_guest_005_list_filter_fac_related(self):
        self.assert_list_filter_related("fac", "ix")
        self.assert_list_filter_related("fac", "net")

    ##########################################################################

    def test_guest_005_list_filter_fac_org_name(self):
        data = self.db_guest.all("fac", org_name=SHARED["org_r_ok"].name[2:10])
        for row in data:
            self.assertEqual(data[0]["org_id"], SHARED["org_r_ok"].id)
        self.assert_data_integrity(data[0], "fac")

    ##########################################################################

    def test_guest_005_list_filter_fac_org_present(self):
        data = self.db_guest.all("fac", org_present=SHARED["org_r_ok"].id)
        self.assertEqual(len(data), 1)

        data = self.db_guest.all("fac", org_not_present=SHARED["org_r_ok"].id)
        self.assertGreater(len(data), 1)

    ##########################################################################

    def test_guest_005_list_filter_fac_all_net(self):
        net_ids = ",".join(
            [
                str(SHARED["net_r_ok"].id),
            ]
        )

        data = self.db_guest.all("fac", all_net=net_ids)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], SHARED["fac_r_ok"].id)

        net_ids = ",".join(
            [
                str(SHARED["net_r_ok"].id),
                str(SHARED["net_rw_ok"].id),
            ]
        )

        data = self.db_guest.all("fac", all_net=net_ids)
        self.assertEqual(len(data), 0)

    ##########################################################################

    def test_guest_005_list_filter_fac_not_net(self):
        net_ids = ",".join(
            [
                str(SHARED["net_r_ok"].id),
            ]
        )

        data = self.db_guest.all("fac", not_net=net_ids)
        self.assertGreater(len(data), 1)
        for row in data:
            self.assertNotEqual(row["id"], SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_fac_net_count(self):
        """
        Issue 834: Users should be able to filter Facilities
        based on the number of Networks they are linked to.
        """
        for facility in Facility.objects.filter(status="ok").all():
            netfac = facility.netfac_set.first()
            if not netfac:
                continue
            netfac.status = "pending"
            netfac.save()
            with reversion.create_revision():
                netfac.status = "ok"
                netfac.save()

        data = self.db_guest.all("fac", net_count=1)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertEqual(row["net_count"], 1)

        data = self.db_guest.all("fac", net_count=0)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertEqual(row["net_count"], 0)

        data = self.db_guest.all("fac", net_count__lt=1)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertEqual(row["net_count"], 0)

        data = self.db_guest.all("fac", net_count__gt=0)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertGreater(row["net_count"], 0)

    ##########################################################################

    def test_guest_005_list_filter_fac_ix_count(self):
        """
        Issue 834: Users should be able to filter Facilities
        based on the number of Exchanges they are linked to.
        """
        for facility in Facility.objects.filter(status="ok").all():
            ixfac = facility.ixfac_set.first()
            if not ixfac:
                continue
            ixfac.status = "pending"
            ixfac.save()
            with reversion.create_revision():
                ixfac.status = "ok"
                ixfac.save()

        data = self.db_guest.all("fac", ix_count=1)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertEqual(row["ix_count"], 1)

        data = self.db_guest.all("fac", ix_count=0)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertEqual(row["ix_count"], 0)

        data = self.db_guest.all("fac", ix_count__lt=1)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertEqual(row["ix_count"], 0)

        data = self.db_guest.all("fac", ix_count__gt=0)
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertGreater(row["ix_count"], 0)

    ##########################################################################

    def test_guest_005_list_filter_fac_region_continent(self):
        """
        Issue 1007: Users should be able to filter Facilities
        based on region_continent
        """
        # set a single facility to europe

        fac = SHARED["fac_rw_ok"]
        fac.country = "DE"
        fac.save()

        # confirm this is true in the db
        assert Facility.objects.filter(region_continent="Europe").count() == 1

        # test that the filter returns only that facility
        data = self.db_guest.all("fac", region_continent="Europe")
        assert len(data) == 1
        for row in data:
            self.assert_data_integrity(row, "fac")
            self.assertEqual(row["region_continent"], "Europe")

        # revert
        fac.country = "US"
        fac.save()

    ##########################################################################

    def test_guest_005_list_filter_ix_net_count(self):
        """
        Issue 836: Users should be able to filter
        Exchanges by the number of Networks linked to them.
        """
        # need to modify objects for signals to propagate
        for ix in InternetExchange.objects.filter(status="ok"):
            netixlan = ix.ixlan.netixlan_set.first()
            if not netixlan:
                continue

            with reversion.create_revision():
                netixlan.status = "ok"
                netixlan.save()

        data = self.db_guest.all("ix", net_count=1)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertEqual(row["net_count"], 1)

        data = self.db_guest.all("ix", net_count=0)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertEqual(row["net_count"], 0)

        data = self.db_guest.all("ix", net_count__lt=1)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertEqual(row["net_count"], 0)

        data = self.db_guest.all("ix", net_count__gt=0)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertGreater(row["net_count"], 0)

        data = self.db_guest.all("ix", net_count__lte=2)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertLessEqual(row["net_count"], 2)

        data = self.db_guest.all("ix", net_count__gte=1)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertGreaterEqual(row["net_count"], 1)

    ##########################################################################

    def test_guest_005_list_filter_ix_fac_count(self):
        """
        Issue 836: Users should be able to filter
        Exchanges by the number of Facilities linked to them.
        """

        for ix in InternetExchange.objects.filter(status="ok").all():
            ixfac = ix.ixfac_set.first()
            if not ixfac:
                continue
            ixfac.status = "pending"
            ixfac.save()
            with reversion.create_revision():
                ixfac.status = "ok"
                ixfac.save()

        data = self.db_guest.all("ix", fac_count=1)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertEqual(row["fac_count"], 1)

        data = self.db_guest.all("ix", fac_count=0)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertEqual(row["fac_count"], 0)

        data = self.db_guest.all("ix", fac_count__lt=1)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertEqual(row["fac_count"], 0)

        data = self.db_guest.all("ix", fac_count__gt=0)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertGreater(row["fac_count"], 0)

        data = self.db_guest.all("ix", fac_count__lte=2)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertLessEqual(row["fac_count"], 2)

        data = self.db_guest.all("ix", fac_count__gte=1)
        for row in data:
            self.assert_data_integrity(row, "ix")
            self.assertGreaterEqual(row["fac_count"], 1)

    ##########################################################################

    def test_guest_005_list_filter_net_ix_count(self):
        """
        Issue 835: One should be able to filter Networks based
        on the number of Exchanges associated with them.
        """

        for network in Network.objects.filter(status="ok").all():
            netixlan = network.netixlan_set.first()
            if not netixlan:
                continue

            with reversion.create_revision():
                netixlan.status = "ok"
                netixlan.save()

        data = self.db_guest.all("net", ix_count=1)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertEqual(row["ix_count"], 1)

        data = self.db_guest.all("net", ix_count=0)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertEqual(row["ix_count"], 0)

        data = self.db_guest.all("net", ix_count__lt=1)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertEqual(row["ix_count"], 0)

        data = self.db_guest.all("net", ix_count__gt=0)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertGreater(row["ix_count"], 0)

        data = self.db_guest.all("net", ix_count__lte=2)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertLessEqual(row["ix_count"], 2)

        data = self.db_guest.all("net", ix_count__gte=1)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertGreaterEqual(row["ix_count"], 1)

    ##########################################################################

    def test_guest_005_list_filter_net_fac_count(self):
        """
        Issue 835: One should be able to filter Networks based
        on the number of Facilities associated with them.
        """

        for network in Network.objects.filter(status="ok").all():
            netfac = network.netfac_set.first()
            if not netfac:
                continue
            netfac.status = "pending"
            netfac.save()
            with reversion.create_revision():
                netfac.status = "ok"
                netfac.save()

        data = self.db_guest.all("net", fac_count=1)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertEqual(row["fac_count"], 1)

        data = self.db_guest.all("net", fac_count=0)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertEqual(row["fac_count"], 0)

        data = self.db_guest.all("net", fac_count__lt=1)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertEqual(row["fac_count"], 0)

        data = self.db_guest.all("net", fac_count__gt=0)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertGreater(row["fac_count"], 0)

        data = self.db_guest.all("net", fac_count__lte=2)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertLessEqual(row["fac_count"], 2)

        data = self.db_guest.all("net", fac_count__gte=1)
        for row in data:
            self.assert_data_integrity(row, "net")
            self.assertGreaterEqual(row["fac_count"], 1)

    ##########################################################################

    def test_guest_005_list_filter_fac_asn_overlap(self):
        # create three test networks
        networks = [
            Network.objects.create(status="ok", **self.make_data_net())
            for i in range(0, 3)
        ]

        # create two test facilities
        facilities = [
            Facility.objects.create(status="ok", **self.make_data_fac())
            for i in range(0, 2)
        ]

        # all three networks peer at first facility
        for net in networks:
            NetworkFacility.objects.create(
                network=net, facility=facilities[0], status="ok"
            )

        # only the first two networks peer at second facility
        for net in networks[:2]:
            NetworkFacility.objects.create(
                network=net, facility=facilities[1], status="ok"
            )

        # do test queries

        # query #1 - test overlapping facilities for all 3 asns - should return first facility
        data = self.db_guest.all(
            "fac", asn_overlap=",".join([str(net.asn) for net in networks])
        )
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], facilities[0].id)

        # query #2 - test overlapping facilities for first 2 asns - should return both facs
        data = self.db_guest.all(
            "fac", asn_overlap=",".join([str(net.asn) for net in networks[:2]])
        )
        self.assertEqual(len(data), 2)
        for row in data:
            self.assertIn(row["id"], [ix.id for ix in facilities])

        # query #3 - should error when only passing one asn
        with pytest.raises(InvalidRequestException):
            self.db_guest.all("fac", asn_overlap=networks[0].asn)

        # query #4 - should error when passing too many asns
        with pytest.raises(InvalidRequestException):
            self.db_guest.all(
                "fac", asn_overlap=",".join([str(i) for i in range(0, 30)])
            )

        # clean up data
        for net in networks:
            net.delete(hard=True)
        for fac in facilities:
            fac.delete(hard=True)

    ##########################################################################

    def test_guest_005_list_filter_org_asn(self):
        data = self.db_guest.all("org", asn=SHARED["net_r_ok"].asn)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], SHARED["org_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_netixlan_related(self):
        self.assert_list_filter_related("netixlan", "net")
        self.assert_list_filter_related("netixlan", "ixlan")
        self.assert_list_filter_related("netixlan", "ix")

    ##########################################################################

    def test_guest_005_list_filter_netixlan_operational(self):
        # all netixlans are operational at this point,
        # filtering by operational=False should return empty list

        data = self.db_guest.all("netixlan", operational=0)
        assert len(data) == 0

        # set one netixlan to not operational

        netixlan = NetworkIXLan.objects.first()
        netixlan.operational = False
        netixlan.save()

        # assert that it is now returned in the operational=False
        # result

        data = self.db_guest.all("netixlan", operational=0)
        assert len(data) == 1
        assert data[0]["id"] == netixlan.id

    ##########################################################################

    def test_guest_005_list_filter_netixlan_related_name(self):
        data = self.db_guest.all("netixlan", name=SHARED["ix_rw_ok"].name)
        self.assertEqual(len(data), 1)
        self.assert_data_integrity(data[0], "netixlan")

    ##########################################################################

    def test_guest_005_list_filter_netfac_related(self):
        self.assert_list_filter_related("netfac", "net")
        self.assert_list_filter_related("netfac", "fac")

    ##########################################################################

    def test_guest_005_list_filter_netfac_related_name(self):
        data = self.db_guest.all("netfac", name=SHARED["fac_rw_ok"].name)
        self.assertEqual(len(data), 1)
        self.assert_data_integrity(data[0], "netfac")

    ##########################################################################

    def test_guest_005_list_filter_netfac_related_city(self):
        data = self.db_guest.all("netfac", city=SHARED["fac_rw_ok"].city)
        self.assertEqual(len(data), 2)
        self.assert_data_integrity(data[0], "netfac")

    ##########################################################################

    def test_guest_005_list_filter_netfac_related_country(self):
        data = self.db_guest.all(
            "netfac", country="{}".format(SHARED["fac_rw_ok"].country)
        )
        self.assertEqual(len(data), 2)
        self.assert_data_integrity(data[0], "netfac")

    ##########################################################################

    def test_guest_005_list_filter_ixlan_related(self):
        self.assert_list_filter_related("ixlan", "ix")

    ##########################################################################

    def test_guest_005_list_filter_ixfac_related(self):
        self.assert_list_filter_related("ixfac", "fac")
        self.assert_list_filter_related("ixfac", "ix")

    ##########################################################################

    def test_guest_005_list_filter_ixfac_related_name(self):
        data = self.db_guest.all("ixfac", name=SHARED["fac_rw_ok"].name)
        self.assertEqual(len(data), 1)
        self.assert_data_integrity(data[0], "ixfac")

    ##########################################################################

    def test_guest_005_list_filter_ixfac_related_city(self):
        data = self.db_guest.all("ixfac", city=SHARED["fac_rw_ok"].city)
        self.assertEqual(len(data), 2)
        self.assert_data_integrity(data[0], "ixfac")

    ##########################################################################

    def test_guest_005_list_filter_ixfac_related_country(self):
        data = self.db_guest.all(
            "ixfac", country="{}".format(SHARED["fac_rw_ok"].country)
        )
        self.assertEqual(len(data), 2)
        self.assert_data_integrity(data[0], "ixfac")

    ##########################################################################

    def test_guest_005_list_filter_poc_related(self):
        self.assert_list_filter_related("poc", "net")
        return
        data = self.db_guest.all("poc", net_id=SHARED["net_r_ok"].id)
        self.assertGreater(len(data), 0)
        for row in data:
            self.assert_data_integrity(row, "poc")
            self.assertEqual(row["net_id"], SHARED["net_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_skip(self):
        data = self.db_guest.all("org", skip=0, limit=20)
        self.assertEqual(len(data), 20)

        target = data[10]

        data = self.db_guest.all("org", skip=10, limit=20)

        self.assertEqual(len(data), 20)

        comp = data[0]

        self.assertEqual(target, comp)

    ##########################################################################

    def test_guest_005_list_filter_accented(self):
        """
        Tests filtering with accented search terms.
        """

        # TODO: sqlite3 is being used as the testing backend, and django 1.11
        # seems to be unable to set a collation on it, so we can't properly test
        # the other way atm, for now this test at least confirms that the term is
        # unaccented correctly.
        #
        # on production we run mysql with flattened accents so both ways should work
        # there regardless.

        org = Organization.objects.create(name="org unaccented", status="ok")
        Network.objects.create(asn=12345, name="net unaccented", status="ok", org=org)
        InternetExchange.objects.create(org=org, name="ix unaccented", status="ok")
        Facility.objects.create(org=org, name="fac unaccented", status="ok")

        for tag in ["org", "net", "ix", "fac"]:
            data = self.db_guest.all(tag, name=f"{tag} unãccented")
            self.assertEqual(len(data), 1)

    ##########################################################################

    def test_guest_005_list_filter_carrier_name_search(self):
        carrier = Carrier.objects.create(
            status="ok",
            **self.make_data_carrier(
                name="Specific Exchange", name_long="This is a very specific exchange"
            ),
        )

        # add facility to carrier using CarrierFacility
        CarrierFacility.objects.create(
            carrier=carrier, facility=SHARED["fac_r_ok"], status="ok"
        )

        # rebuild search index (name_search requires it)
        call_command("rebuild_index", "--noinput")

        data = self.db_guest.all("carrier", name_search=carrier.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], carrier.id)
            self.assertEqual(row["fac_count"], 1)

        data = self.db_guest.all("carrier", name_search=carrier.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], carrier.id)
            self.assertEqual(row["fac_count"], 1)

        carrier.delete(hard=True)

    ##########################################################################
    # READONLY PERMISSION TESTS
    # These tests assert that the readonly users cannot write anything
    ##########################################################################

    ##########################################################################

    def test_readonly_users_003_PUT_org(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "org",
                SHARED["org_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_002_POST_ix(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db,
                "ix",
                self.make_data_ix(prefix=self.get_prefix4()),
                test_failures={"perms": {}},
                test_success=False,
            )

    ##########################################################################

    def test_readonly_users_003_PUT_ix(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "ix",
                SHARED["ix_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_ix(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db, "ix", test_success=False, test_failure=SHARED["ix_r_ok"].id
            )

    ##########################################################################

    def test_readonly_users_002_POST_fac(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db,
                "fac",
                self.make_data_fac(),
                test_failures={"perms": {}},
                test_success=False,
            )

    ##########################################################################

    def test_readonly_users_003_PUT_fac(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "fac",
                SHARED["fac_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_fac(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db, "fac", test_success=False, test_failure=SHARED["fac_r_ok"].id
            )

    ##########################################################################

    def test_readonly_users_002_POST_netfac(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db,
                "netfac",
                {
                    "net_id": SHARED["net_r_ok"].id,
                    "fac_id": SHARED["fac_r2_ok"].id,
                },
                test_failures={"perms": {}},
                test_success=False,
            )

    ##########################################################################

    def test_readonly_users_003_PUT_netfac(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "netfac",
                SHARED["netfac_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_netfac(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db, "netfac", test_success=False, test_failure=SHARED["netfac_r_ok"].id
            )

    ##########################################################################

    def test_readonly_users_002_POST_ixfac(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db,
                "ixfac",
                {"ix_id": SHARED["ix_r_ok"].id, "fac_id": SHARED["fac_r2_ok"].id},
                test_failures={"perms": {}},
                test_success=False,
            )

    ##########################################################################

    def test_readonly_users_003_PUT_ixfac(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "ixfac",
                SHARED["ixfac_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_ixfac(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db, "ixfac", test_success=False, test_failure=SHARED["ixfac_r_ok"].id
            )

    ##########################################################################

    def test_readonly_users_002_POST_poc(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db,
                "poc",
                self.make_data_poc(net_id=SHARED["net_rw_ok"].id),
                test_failures={"perms": {}},
                test_success=False,
            )

    ##########################################################################

    def test_readonly_users_003_PUT_poc(self):
        for db in self.readonly_dbs(exclude=[self.db_user]):
            self.assert_update(
                db,
                "poc",
                SHARED["poc_r_ok_public"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )
            self.assert_update(
                db,
                "poc",
                SHARED["poc_r_ok_private"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )
            self.assert_update(
                db,
                "poc",
                SHARED["poc_r_ok_users"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_poc(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db, "poc", test_success=False, test_failure=SHARED["poc_r_ok_public"].id
            )
            self.assert_delete(
                db,
                "poc",
                test_success=False,
                test_failure=SHARED["poc_r_ok_private"].id,
            )
            self.assert_delete(
                db, "poc", test_success=False, test_failure=SHARED["poc_r_ok_users"].id
            )

    ##########################################################################

    def test_readonly_users_002_POST_ixlan(self):
        for db in self.readonly_dbs():
            with self.assertRaises(Exception) as exc:
                self.assert_create(
                    db,
                    "ixlan",
                    self.make_data_ixlan(),
                    test_failures={"perms": {}},
                    test_success=False,
                )
            self.assertIn('Method "POST" not allowed', str(exc.exception))

    ##########################################################################

    def test_readonly_users_003_PUT_ixlan(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "ixlan",
                SHARED["ixlan_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_ixlan(self):
        for db in self.readonly_dbs():
            with self.assertRaises(Exception) as exc:
                self.assert_delete(
                    db,
                    "ixlan",
                    test_success=False,
                    test_failure=SHARED["ixlan_r_ok"].id,
                )
            self.assertIn('Method "DELETE" not allowed', str(exc.exception))

    ##########################################################################

    def test_readonly_users_002_POST_ixpfx(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db,
                "ixpfx",
                self.make_data_ixpfx(prefix="200.100.200.0/22"),
                test_failures={"perms": {}},
                test_success=False,
            )

    ##########################################################################

    def test_readonly_users_003_PUT_ixpfx(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "ixpfx",
                SHARED["ixpfx_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_ixpfx(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db, "ixpfx", test_success=False, test_failure=SHARED["ixpfx_r_ok"].id
            )

    ##########################################################################

    def test_readonly_users_002_POST_netixlan(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db,
                "netixlan",
                self.make_data_netixlan(),
                test_failures={"perms": {}},
                test_success=False,
            )

    ##########################################################################

    def test_readonly_users_003_PUT_netixlan(self):
        for db in self.readonly_dbs():
            self.assert_update(
                db,
                "netixlan",
                SHARED["netixlan_r_ok"].id,
                {},
                test_success=False,
                test_failures={"perms": {}},
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_netixlan(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db,
                "netixlan",
                test_success=False,
                test_failure=SHARED["netixlan_r_ok"].id,
            )

    ##########################################################################

    def test_readonly_users_004_DELETE_org(self):
        for db in self.readonly_dbs():
            self.assert_delete(
                db, "org", test_success=False, test_failure=SHARED["org_r_ok"].id
            )

    ##########################################################################

    def test_readonly_users_004_list_filter_fac_name_search(self):
        fac = Facility.objects.create(
            status="ok",
            **self.make_data_fac(
                name="Specific Facility", name_long="This is a very specific facility"
            ),
        )

        # rebuild search index (name_search requires it)
        call_command("rebuild_index", "--noinput")

        data = self.db_guest.all("fac", name_search=fac.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        data = self.db_guest.all("fac", name_search=fac.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        fac.delete(hard=True)

    ##########################################################################
    # CRUD PERMISSION TESTS
    ##########################################################################

    def test_z_crud_002_create(self):
        # user with create perms should be allowed to create a new poc under net_rw3_ok
        # but not under net_rw2_ok
        self.assert_create(
            self.db_crud_create,
            "poc",
            self.make_data_poc(net_id=SHARED["net_rw3_ok"].id),
            test_failures={"perms": {"net_id": SHARED["net_rw2_ok"].id}},
        )

        # other crud test users should not be able to create a new poc under
        # net_rw3_ok
        for p in ["delete", "update"]:
            self.assert_create(
                getattr(self, "db_crud_%s" % p),
                "poc",
                self.make_data_poc(net_id=SHARED["net_rw3_ok"].id),
                test_failures={"perms": {}},
                test_success=False,
            )

    def test_z_crud_003_update(self):
        # user with update perms should be allowed to update net_rw3_ok
        # but not net_rw2_ok
        self.assert_update(
            self.db_crud_update,
            "net",
            SHARED["net_rw3_ok"].id,
            {"name": self.make_name("Test")},
            test_failures={"perms": {"id": SHARED["net_rw2_ok"].id}},
        )

        # user with update perms should not be allowed to update ix_rw3_ok
        self.assert_update(
            self.db_crud_update,
            "ix",
            SHARED["ix_rw3_ok"].id,
            {"name": self.make_name("Test")},
            test_failures={"perms": {}},
            test_success=False,
        )

        # other crud test users should not be able to update net_rw3_ok
        for p in ["delete", "create"]:
            self.assert_update(
                getattr(self, "db_crud_%s" % p),
                "net",
                SHARED["net_rw3_ok"].id,
                {"name": self.make_name("Test")},
                test_failures={"perms": {}},
                test_success=False,
            )

    def test_z_crud_004_delete(self):
        # other crud test users should not be able to delete net_rw3_ok
        for p in ["update", "create"]:
            self.assert_delete(
                getattr(self, "db_crud_%s" % p),
                "net",
                test_success=False,
                test_failure=SHARED["net_rw3_ok"].id,
            )

        # user with delete perms should be allowed to update net_rw3_ok
        # but not net_rw2_ok
        self.assert_delete(
            self.db_crud_delete,
            "net",
            SHARED["net_rw3_ok"].id,
            test_failure=SHARED["net_rw2_ok"].id,
        )

        # user with delete perms should not be allowed to delete ix_rw3_ok
        self.assert_delete(
            self.db_crud_delete,
            "ix",
            test_success=False,
            test_failure=SHARED["ix_rw3_ok"].id,
        )

    ##########################################################################
    # MISC TESTS
    ##########################################################################

    ##########################################################################

    def test_misc_GET_netixlan_ipaddr6(self):
        # For issue 913
        # Test that differently formatted ipaddr6
        # can be used to search for same Netixlan
        ipaddr6 = SHARED["netixlan_r_ok"].ipaddr6
        expanded_string = ipaddress.ip_address(ipaddr6).exploded

        data = self.db_user.all("netixlan", ipaddr6=expanded_string)
        print(data)
        print(type(data))
        assert len(data) == 1
        assert data[0]["ipaddr6"] == str(ipaddr6)

    def _test_GET_ixf_ixp_member_list_url(self, db, tests=[], suffix="r"):
        ixlan = SHARED[f"ixlan_{suffix}_ok"]
        ixlan.ixf_ixp_member_list_url = "http://localhost"
        ixlan.save()

        for visible, expected in tests:
            ixlan.ixf_ixp_member_list_url_visible = visible
            ixlan.full_clean()
            ixlan.save()

            data = db.get("ixlan", id=ixlan.id)[0]

            assert data["ixf_ixp_member_list_url_visible"] == visible

            if expected:
                assert data["ixf_ixp_member_list_url"] == ixlan.ixf_ixp_member_list_url
            else:
                assert "ixf_ixp_member_list_url" not in data

    def test_z_misc_GET_ixf_ixp_member_list_url(self):
        """
        Tests the visibility of ixlan.ixf_ixp_member_list_url for
        Guest, User, Org member and org admin.
        """

        self._test_GET_ixf_ixp_member_list_url(
            self.db_user, [("Private", False), ("Users", True), ("Public", True)]
        )

        self._test_GET_ixf_ixp_member_list_url(
            self.db_guest, [("Private", False), ("Users", False), ("Public", True)]
        )

        self._test_GET_ixf_ixp_member_list_url(
            self.db_org_member, [("Private", True), ("Users", True), ("Public", True)]
        )

        self._test_GET_ixf_ixp_member_list_url(
            self.db_org_admin,
            [("Private", True), ("Users", True), ("Public", True)],
            suffix="rw",
        )

    def test_z_misc_POST_ix_fac_missing_phone_fields(self):
        """
        Tests that omitting the *_phone fields during fac
        and ix object creation doesn't error 500.

        TODO: A test that drops all the non-required fields
        and tests for every reftag model.
        """

        data = self.make_data_fac()
        db = self.db_org_admin
        del data["tech_phone"]
        db.create("fac", data, return_response=True).get("data")

        data = self.make_data_fac()
        del data["sales_phone"]
        db.create("fac", data, return_response=True).get("data")

        data = self.make_data_ix(prefix=self.get_prefix4())
        del data["tech_phone"]
        db.create("ix", data, return_response=True).get("data")

        data = self.make_data_ix(prefix=self.get_prefix4())
        del data["policy_phone"]
        db.create("ix", data, return_response=True).get("data")

    def test_z_misc_002_dupe_netixlan_ip(self):
        # test that addint duplicate netixlan ips is impossible

        A = SHARED["netixlan_rw_ok"]
        self.assert_create(
            self.db_org_admin,
            "netixlan",
            self.make_data_netixlan(ixlan_id=A.ixlan_id, net_id=A.network_id),
            test_success=False,
            test_failures={"invalid": {"ipaddr4": str(A.ipaddr4)}},
        )

        self.assert_create(
            self.db_org_admin,
            "netixlan",
            self.make_data_netixlan(
                ixlan_id=A.ixlan_id,
                net_id=A.network_id,
            ),
            test_success=False,
            test_failures={"invalid": {"ipaddr6": str(A.ipaddr6)}},
        )

    def test_z_misc_002_local_asn(self):
        # test that local_asn gets enforced (#186)

        net = SHARED["net_rw_ok"]
        fac = SHARED["fac_rw_ok"]
        ixlan = SHARED["ixlan_rw_ok"]

        # delete the existing netfac and netixlan
        NetworkFacility.objects.get(network=net, facility=fac).delete()
        NetworkIXLan.objects.get(network=net, ixlan=ixlan).delete()

        # test netfac create without asn sent (should auto set)

        data = {"net_id": net.id, "fac_id": fac.id}
        r_data = self.db_org_admin.create("netfac", data, return_response=True).get(
            "data"
        )[0]
        assert r_data["local_asn"] == net.asn

        NetworkFacility.objects.get(id=r_data["id"]).delete()

        # test nefac create with local_asn sent (should ignore and auto set)

        data = {"net_id": net.id, "fac_id": fac.id, "local_asn": 12345}
        r_data = self.db_org_admin.create("netfac", data, return_response=True).get(
            "data"
        )[0]
        assert r_data["local_asn"] == net.asn

        NetworkFacility.objects.get(id=r_data["id"]).delete()

        # test netixlan create without asn sent (should auto set)

        data = self.make_data_netixlan(ixlan_id=ixlan.id, net_id=net.id)
        del data["asn"]
        r_data = self.db_org_admin.create("netixlan", data, return_response=True).get(
            "data"
        )[0]
        assert r_data["asn"] == net.asn

        NetworkIXLan.objects.get(id=r_data["id"]).delete()

        # test neixlan create with asn sent (should ignore and auto set)

        data = self.make_data_netixlan(ixlan_id=ixlan.id, net_id=net.id, asn=12345)
        r_data = self.db_org_admin.create("netixlan", data, return_response=True).get(
            "data"
        )[0]
        assert r_data["asn"] == net.asn

        NetworkIXLan.objects.get(id=r_data["id"]).delete()

    def test_z_misc_002_dupe_name_update(self):
        # test that changing the name of entity A (status=ok)
        # to name of entity B (status=deleted) does raise the approporiate
        # unique key error and does not undelete entity B

        A = SHARED["fac_rw_dupe_ok"]
        B = SHARED["fac_rw_dupe_deleted"]

        self.assertEqual(A.status, "ok")
        self.assertEqual(B.status, "deleted")

        self.assert_update(
            self.db_org_admin,
            "fac",
            A.id,
            {},
            test_failures={"invalid": {"name": B.name}},
        )

        B.refresh_from_db()
        self.assertEqual(B.status, "deleted")

    def test_z_misc_001_ix_phone_number_validation(self):
        data = self.make_data_ix(org_id=SHARED["org_rw_ok"].id)

        # test that valid number comes back properly formatted

        data.update(
            prefix=PREFIXES_V4[-1],
            tech_phone="+1 206 555 0199",
            policy_phone="+1 206 555 0199",
        )

        r_data = self.db_org_admin.create("ix", data, return_response=True).get("data")[
            0
        ]

        assert r_data["tech_phone"] == "+12065550199"
        assert r_data["policy_phone"] == "+12065550199"

        # test that invalid numbers raise validation errors

        self.assert_update(
            self.db_org_admin,
            "ix",
            r_data["id"],
            {},
            test_failures={"invalid": {"tech_phone": "invalid number"}},
        )

        self.assert_update(
            self.db_org_admin,
            "ix",
            r_data["id"],
            {},
            test_failures={"invalid": {"policy_phone": "invalid number"}},
        )

    def test_z_misc_001_poc_phone_number_validation(self):
        data = self.make_data_poc(net_id=SHARED["net_rw_ok"].id)

        # test that valid number comes back properly formatted

        data.update(phone="+1 206 555 0199")

        r_data = self.db_org_admin.create("poc", data, return_response=True).get(
            "data"
        )[0]

        assert r_data["phone"] == "+12065550199"

        # test that invalid numbers raise validation errors

        self.assert_update(
            self.db_org_admin,
            "poc",
            r_data["id"],
            {},
            test_failures={"invalid": {"phone": "invalid number"}},
        )

    def test_z_misc_001_org_create(self):
        # no one should be allowed to create an org via the api
        # at this point in time

        for db in self.all_dbs():
            self.assert_create(
                db,
                "org",
                self.make_data_org(name=self.make_name("Test")),
                test_success=False,
                test_failures={"perms": {}},
            )

    def test_z_misc_001_suggest_net(self):
        # test network suggestions

        data = self.make_data_net(
            asn=9000901, org_id=settings.SUGGEST_ENTITY_ORG, suggest=True
        )

        r_data = self.assert_create(
            self.db_user, "net", data, expected_status="pending"
        )

        self.assertEqual(r_data["org_id"], settings.SUGGEST_ENTITY_ORG)
        # self.assertEqual(r_data["stat/us"], "pending")

        net = Network.objects.get(id=r_data["id"])
        self.assertEqual(net.org_id, settings.SUGGEST_ENTITY_ORG)

        data = self.make_data_net(
            asn=9000902, org_id=settings.SUGGEST_ENTITY_ORG, suggest=True
        )

        r_data = self.assert_create(
            self.db_guest, "net", data, test_success=False, test_failures={"perms": {}}
        )

    def test_z_misc_001_suggest_fac(self):
        # test facility suggestions

        data = self.make_data_fac(org_id=settings.SUGGEST_ENTITY_ORG, suggest=True)

        r_data = self.assert_create(
            self.db_user, "fac", data, ignore=["latitude", "longitude"]
        )

        self.assertEqual(r_data["org_id"], settings.SUGGEST_ENTITY_ORG)
        self.assertEqual(r_data["status"], "pending")

        fac = Facility.objects.get(id=r_data["id"])
        self.assertEqual(fac.org_id, settings.SUGGEST_ENTITY_ORG)

        data = self.make_data_fac(org_id=settings.SUGGEST_ENTITY_ORG, suggest=True)

        r_data = self.assert_create(
            self.db_guest,
            "fac",
            data,
            test_success=False,
            test_failures={"perms": {}},
            ignore=["latitude", "longitude"],
        )

    def test_z_misc_001_add_fac_bug(self):
        """
        Issue 922: Regression test for bug where a user could
        approve a facility by adding, deleting, and re-adding.
        """

        # Add fac
        data = self.make_data_fac()
        r_data = self.assert_create(
            self.db_org_admin, "fac", data, ignore=["latitude", "longitude"]
        )

        self.assertEqual(r_data["status"], "pending")

        fac = Facility.objects.get(id=r_data["id"])
        self.assertEqual(fac.status, "pending")

        # Delete fac
        # fac = Facility.objects.get(id=r_data["id"])
        # fac.delete()
        # fac.refresh_from_db()

        self.assert_delete(self.db_org_admin, "fac", test_success=r_data["id"])
        fac.refresh_from_db()
        self.assertEqual(fac.status, "deleted")

        # Re-add should go back to pending (previously was going to "ok")
        re_add_data = self.assert_create(
            self.db_org_admin, "fac", data, ignore=["latitude", "longitude"]
        )
        self.assertEqual(re_add_data["status"], "pending")
        fac = Facility.objects.get(id=re_add_data["id"])
        self.assertEqual(fac.status, "pending")

    def test_z_misc_001_add_fac_bug_suggest(self):
        """
        Issue 922: Regression test for bug where a user could
        approve a facility by adding, deleting, and re-adding.

        Confirms that this interacts with suggestions properly.
        """

        # Add fac (suggestion)
        data = self.make_data_fac(suggest=True)
        del data["org_id"]
        print(data)

        r_data = self.assert_create(
            self.db_user, "fac", data, ignore=["latitude", "longitude"]
        )

        self.assertEqual(r_data["status"], "pending")
        self.assertEqual(r_data["org_id"], settings.SUGGEST_ENTITY_ORG)

        fac = Facility.objects.get(id=r_data["id"])
        self.assertEqual(fac.status, "pending")
        self.assertEqual(fac.org_id, settings.SUGGEST_ENTITY_ORG)

        # Delete fac
        fac = Facility.objects.get(id=r_data["id"])
        fac.delete()
        fac.refresh_from_db()
        self.assertEqual(fac.status, "deleted")

        """
        self.assertEqual(re_add_data["status"], "pending")
        self.assertEqual(re_add_data["org_id"], settings.SUGGEST_ENTITY_ORG)

        fac = Facility.objects.get(id=re_add_data["id"])
        self.assertEqual(fac.status, "pending")
        self.assertEqual(fac.org_id, settings.SUGGEST_ENTITY_ORG)
        """

    def test_z_misc_001_disable_suggest_ix(self):
        """
        Issue 827: Removes the ability for non-admin users to "suggest" an IX.
        Therefore, change this test so a "suggest" field being set on the API
        request is disregarded, and permission is denied if a user who cannot create an
        IX tries to POST.
        """
        org = SHARED["org_rw_ok"]
        data = self.make_data_ix(org_id=org.id, suggest=True, prefix=self.get_prefix4())
        # Assert that this throws a permission error (previously would "suggest"/create)
        self.assert_create(
            self.db_user,
            "ix",
            data,
            ignore=["prefix", "suggest"],
            test_success=False,
            test_failures={"perms": {}},
        )
        # Assert that this doesn't create a "pending" IX in the
        # suggested entity org
        suggest_entity_org = Organization.objects.get(id=settings.SUGGEST_ENTITY_ORG)
        assert suggest_entity_org.ix_set(manager="handleref").count() == 0

    def test_z_misc_001_suggest_kwarg_on_ix_does_nothing(self):
        """
        Issue 827: Removes the ability for non-admin users to "suggest" an IX.
        If a user tries to "suggest" an IX, this keyword should simply be ignored. Admins
        should still be able to create a "pending" IX even if "suggest" is provided.
        """
        org = SHARED["org_rw_ok"]
        data = self.make_data_ix(org_id=org.id, suggest=True, prefix=self.get_prefix4())
        # Assert that this creates a "pending" IX
        ix = self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            ignore=["prefix", "suggest"],
            test_success=True,
        )
        # Assert that this doesn't create a "pending" IX in the
        # suggested entity org
        suggest_entity_org = Organization.objects.get(id=settings.SUGGEST_ENTITY_ORG)
        assert suggest_entity_org.ix_set(manager="handleref").count() == 0

        # Assert that this does create a "pending" IX in the
        # provided org
        org.refresh_from_db()
        assert ix["status"] == "pending"
        assert InternetExchange.objects.get(name=data["name"])

    def test_z_misc_001_cannot_post_ix_to_suggest_entity_org(self):
        """
        Issue 827: Removes the ability for non-admin users to "suggest" an IX.
        As part of that, remove the ability to POST an IX with an ORG that is
        the special "suggested entity org" even if the POST explicitly tries
        to create an IX with that ORG.
        """
        # Explicity designate org is the SUGGESTED ENTITY ORG
        data = self.make_data_ix(
            org_id=settings.SUGGEST_ENTITY_ORG, suggest=True, prefix=self.get_prefix4()
        )
        self.assert_create(
            self.db_user,
            "ix",
            data,
            ignore=["prefix", "suggest"],
            test_success=False,
            test_failures={"invalid": {"org_id": settings.SUGGEST_ENTITY_ORG}},
        )
        # Assert that this doesn't create a "pending" IX in the
        # suggested entity org
        suggest_entity_org = Organization.objects.get(id=settings.SUGGEST_ENTITY_ORG)
        assert suggest_entity_org.ix_set(manager="handleref").count() == 0

    def test_z_misc_001_suggest_outside_of_post(self):
        # The `suggest` keyword should only do something for
        # `POST` events, on `PUT` events it should be silently
        # ignored

        for reftag in ["fac", "net"]:
            ent = SHARED[f"{reftag}_rw_ok"]
            org_id = ent.org_id
            db = self.db_org_admin
            orig = self.assert_get_handleref(db, reftag, ent.id)
            orig.update(notes="test", suggest=True)
            db.update(reftag, **orig)

            ent.refresh_from_db()
            self.assertEqual(ent.org_id, org_id)

    def test_z_misc_001_fac_address_geocode(self):
        # test that facility gets marked for geocode sync after address field
        # change
        fac = SHARED["fac_rw_ok"]
        fac.geocode_status = True
        fac.save()

        self.assert_update(
            self.db_org_admin, "fac", fac.id, {"address1": "This is a test"}
        )

        fac.refresh_from_db()
        self.assertEqual(fac.geocode_status, False)

        # reset geocode status
        fac.geocode_status = True
        fac.save()

        # test that facility does NOT get marked for geocode sync after non relevant
        # fields are changed

        self.assert_update(
            self.db_org_admin,
            "fac",
            fac.id,
            {"website": "http://example.com", "name": fac.name + " Geocode Test"},
        )
        fac.refresh_from_db()
        self.assertEqual(fac.geocode_status, True)

    def test_z_misc_001_api_errors(self):
        """
        Test empty POST, PUT data error response.
        Test parse error POST, PUT data error response.
        """
        for reftag in list(REFTAG_MAP.keys()):
            self._test_z_misc_001_api_errors(reftag, "post", "create")
            self._test_z_misc_001_api_errors(reftag, "put", "update")

    def _test_z_misc_001_api_errors(self, reftag, method, action):
        factory = APIRequestFactory()
        url = f"/{reftag}/"
        view_action = {method: action}
        view = NetworkViewSet.as_view(view_action)
        fn = getattr(factory, method)

        ERR_PARSE = f"Data supplied with the {method.upper()} request could not be parsed: JSON parse error - Expecting value: line 1 column 1 (char 0)"
        ERR_MISSING = f"No data was supplied with the {method.upper()} request"

        # test posting invalid json error

        request = fn(url, "in{valid json", content_type="application/json")
        response = view(request)
        response.render()
        assert json.loads(response.content)["meta"]["error"] == ERR_PARSE

        # test posting empty json error

        request = fn("/net/", "{}", content_type="application/json")
        response = view(request)
        response.render()
        assert json.loads(response.content)["meta"]["error"] == ERR_MISSING

        # test posting empty json error

        request = fn("/net/", "", content_type="application/json")
        response = view(request)
        response.render()
        assert json.loads(response.content)["meta"]["error"] == ERR_MISSING


class Command(BaseCommand):
    help = "This runs the api test harness. All write ops are performed under an organization specifically made for testing, so running to against a prod environment should be fine in theory."

    def add_arguments(self, parser):
        parser.add_argument("--only", help="only run this test", dest="only")
        parser.add_argument(
            "--setup",
            help="runs api test setup (user, org create) only",
            dest="setup",
            action="store_true",
        )

    @classmethod
    def log(cls, msg):
        print(msg)

    @classmethod
    def create_entity(
        cls, model, prefix="rw", unset=[], key_suffix=None, name_suffix=None, **kwargs
    ):
        tag = model.handleref.tag
        status = kwargs.get("status", "ok")
        name = f"API Test:{tag.upper()}:{prefix.upper()}:{status}"
        if name_suffix:
            name = f"{name}{name_suffix}"
        data = {"status": status}
        if tag in ["ix", "net", "fac", "org", "campus"]:
            data["name"] = name

        data.update(**kwargs)

        if tag == "ixpfx":
            if kwargs.get("protocol", 4) == 4:
                data["protocol"] = "IPv4"
                data["prefix"] = PREFIXES_V4[model.objects.all().count()]
            elif kwargs.get("protocol") == 6:
                data["protocol"] = "IPv6"
                data["prefix"] = PREFIXES_V6[model.objects.all().count()]

        try:
            obj = model.objects.get(**data)
            cls.log(
                "%s with status '%s' for %s testing already exists, skipping!"
                % (tag.upper(), status, prefix.upper())
            )
        except model.DoesNotExist:
            fn = getattr(TestJSON, "make_data_%s" % tag, None)
            if fn:
                data = fn(**data)
            for k in unset:
                if k in data:
                    del data[k]
            obj = model(**data)
            obj.save()

            # cls.log(
            #    "%s with status '%s' for %s testing created! (%s)"
            #    % (tag.upper(), status, prefix.upper(), obj.updated)
            # )

        id = f"{tag}_{prefix}_{status}"
        if key_suffix:
            id = f"{id}_{key_suffix}"
        SHARED[id] = obj
        return obj

    @classmethod
    def create_user(cls, USER):
        try:
            user = User.objects.get(username=USER.get("user"))
            cls.log("USER '%s' already exists, skipping!" % USER.get("user"))
            user.groups.clear()
            user.grainy_permissions.all().delete()
        except User.DoesNotExist:
            user = User.objects.create(username=USER.get("user"))
            user.set_password(USER.get("password"))
            user.email = USER.get("email")
            user.save()
            cls.log("USER '%s' created!" % USER.get("user"))
        return user

    @classmethod
    def prepare(cls, *args, **options):
        cls.log("Running setup for API testing...")

        memberGroup = Group.objects.get(name="user")

        # create API test user

        user = cls.create_user(USER)
        memberGroup.user_set.add(user)

        # create API test user org member

        user_org_member = cls.create_user(USER_ORG_MEMBER)
        memberGroup.user_set.add(user_org_member)

        # create API test user org member

        user_org_admin = cls.create_user(USER_ORG_ADMIN)
        memberGroup.user_set.add(user_org_admin)

        # create API test user for crud testing
        crud_users = {}
        for p, specs in list(USER_CRUD.items()):
            crud_user = cls.create_user(specs)
            crud_users[p] = crud_user
            memberGroup.user_set.add(crud_user)

        # see if we need to create extra organizations (to fill up the
        # database)
        extra_orgs = getattr(cls, "create_extra_orgs", 0)
        i = 0
        while i < extra_orgs:
            cls.create_entity(Organization, prefix="r_%d" % i, status="ok")
            i += 1

        # create API test organization (read & write)

        try:
            org_rw = Organization.objects.get(name=ORG_RW)
            cls.log("ORG for WRITE testing already exists, skipping!")
        except Organization.DoesNotExist:
            org_rw = Organization.objects.create(status="ok", name=ORG_RW)
            cls.log("ORG for WRITE testing created!")

        org_rw.admin_usergroup.user_set.add(user_org_admin)
        for crud_user in list(crud_users.values()):
            org_rw.usergroup.user_set.add(crud_user)

        SHARED["org_id"] = org_rw.id
        SHARED["org_rw"] = SHARED["org_rw_ok"] = org_rw

        # create API test organization (read & write) - status pending

        try:
            org_rwp = Organization.objects.get(name=ORG_RW_PENDING)
            cls.log(
                "ORG for WRITE testing (with status pending) already exists, skipping!"
            )
        except Organization.DoesNotExist:
            org_rwp = Organization.objects.create(status="pending", name=ORG_RW_PENDING)
            cls.log("ORG for WRITE testing (with status pending) created!")

        org_rwp.admin_usergroup.user_set.add(user_org_admin)

        SHARED["org_rwp"] = SHARED["org_rw_pending"] = org_rwp

        # create API test organization (read only)

        try:
            org_r = Organization.objects.get(name=ORG_R)
            cls.log("ORG for READONLY testing already exists, skipping!")
        except Organization.DoesNotExist:
            org_r = Organization.objects.create(name=ORG_R, status="ok")
            cls.log("ORG for READONLY testing created!")

        org_r.usergroup.user_set.add(user_org_member)
        SHARED["org_r"] = SHARED["org_r_ok"] = org_r

        cls.create_entity(Organization, prefix="r", status="pending")

        # create API test network (for status "deleted" tests)

        try:
            net_rd = Network.objects.get(name=NET_R_DELETED, org_id=org_r.id)
            cls.log("NET for status 'deleted' testing already exists, skipping!")
        except Network.DoesNotExist:
            net_rd = Network.objects.create(
                **TestJSON.make_data_net(name=NET_R_DELETED, org_id=org_r.id)
            )
            cls.log("NET for status 'deleted' testing created!")
        net_rd.delete()

        SHARED["net_rd"] = net_rd

        # create various entities for rw testing

        for model in [Network, Facility, InternetExchange, Carrier, Campus]:
            for status in ["ok", "pending"]:
                for prefix in ["r", "rw"]:
                    cls.create_entity(
                        model,
                        status=status,
                        prefix=prefix,
                        org_id=SHARED[f"org_{prefix}_{status}"].id,
                    )
                    cls.create_entity(
                        model,
                        status=status,
                        prefix="%s2" % prefix,
                        org_id=SHARED[f"org_{prefix}_{status}"].id,
                    )
                    cls.create_entity(
                        model,
                        status=status,
                        prefix="%s3" % prefix,
                        org_id=SHARED[f"org_{prefix}_{status}"].id,
                    )

        # create facilities for campus objects that are supposed to have status `ok`
        # since any campus requires at least 2 facilities to not be pending

        for k in list(SHARED.keys()):
            if not k.startswith("campus_") or not k.endswith("_ok"):
                continue

            if "dupe" in k:
                continue

            campus = SHARED[k]
            print(k, campus)

            cls.create_entity(
                Facility,
                status="ok",
                prefix=f"campus{campus.id}_1",
                org_id=campus.org.id,
                longitude=30.091435,
                latitude=31.25435,
                campus_id=campus.id,
            )

            cls.create_entity(
                Facility,
                status="ok",
                prefix=f"campus{campus.id}_2",
                org_id=campus.org.id,
                longitude=30.091435,
                latitude=31.25435,
                campus_id=campus.id,
            )

            campus.refresh_from_db()

            assert campus.status == "ok"

        # create entities for duplicate validation testing

        for model in [Network, Facility, InternetExchange, Carrier, Campus]:
            cls.create_entity(
                model,
                status="deleted",
                prefix="rw_dupe",
                name_suffix=" DUPE",
                org_id=SHARED["org_rw_ok"].id,
            )
            cls.create_entity(
                model,
                status="ok",
                prefix="rw_dupe",
                name_suffix=" DUPE !",
                org_id=SHARED["org_rw_ok"].id,
            )

        visibility = {
            "rw": "Public",
            "rw2": "Users",
            # TODO: "Private" can be removed once all private pocs are
            # cleared out of production database
            "rw3": "Private",
            "r": "Public",
            "r2": "Users",
            # TODO: "Private" can be removed once all private pocs are
            # cleared out of production database
            "r3": "Private",
        }

        for status in ["ok", "pending"]:
            for prefix in ["r", "r2", "r3", "rw", "rw2", "rw3"]:
                ixlan = SHARED[f"ixlan_{prefix}_{status}"] = SHARED[
                    f"ix_{prefix}_{status}"
                ].ixlan
                if prefix in visibility:
                    visible = visibility[prefix]
                    ixlan.ixf_ixp_member_list_url_visible = visible
                    ixlan.ixf_ixp_member_list_url = "http://localhost"
                    ixlan.save()

        for status in ["ok", "pending"]:
            for prefix in ["r", "rw"]:
                cls.create_entity(
                    IXLanPrefix,
                    status=status,
                    prefix=prefix,
                    protocol=4,
                    ixlan_id=SHARED[f"ixlan_{prefix}_{status}"].id,
                )
                cls.create_entity(
                    IXLanPrefix,
                    status=status,
                    prefix=f"{prefix}_v6",
                    protocol=6,
                    ixlan_id=SHARED[f"ixlan_{prefix}_{status}"].id,
                )
                cls.create_entity(
                    InternetExchangeFacility,
                    status=status,
                    prefix=prefix,
                    facility_id=SHARED[f"fac_{prefix}_{status}"].id,
                    ix_id=SHARED[f"ix_{prefix}_{status}"].id,
                )
                cls.create_entity(
                    NetworkFacility,
                    status=status,
                    prefix=prefix,
                    unset=["net_id"],
                    facility_id=SHARED[f"fac_{prefix}_{status}"].id,
                    network_id=SHARED[f"net_{prefix}_{status}"].id,
                )
                cls.create_entity(
                    NetworkIXLan,
                    status=status,
                    prefix=prefix,
                    unset=["net_id"],
                    ixlan_id=SHARED[f"ixlan_{prefix}_{status}"].id,
                    network_id=SHARED[f"net_{prefix}_{status}"].id,
                )
                cls.create_entity(
                    CarrierFacility,
                    status=status,
                    prefix=prefix,
                    facility_id=SHARED[f"fac_{prefix}_{status}"].id,
                    carrier_id=SHARED[f"carrier_{prefix}_{status}"].id,
                )

                # TODO: private can be removed once all private pocs have been
                # cleared out of production database
                for v in ["Private", "Users", "Public"]:
                    cls.create_entity(
                        NetworkContact,
                        status=status,
                        prefix=prefix,
                        visible=v,
                        network_id=SHARED[f"net_{prefix}_{status}"].id,
                        unset=["net_id"],
                        key_suffix=v.lower(),
                    )

        # set up permissions for crud permission tests
        crud_users["delete"].grainy_permissions.create(
            namespace=SHARED["net_rw3_ok"].grainy_namespace,
            permission=PERM_READ | PERM_DELETE,
        )
        crud_users["create"].grainy_permissions.create(
            namespace=SHARED["net_rw3_ok"].grainy_namespace,
            permission=PERM_READ | PERM_CREATE,
        )
        crud_users["update"].grainy_permissions.create(
            namespace=SHARED["net_rw3_ok"].grainy_namespace,
            permission=PERM_READ | PERM_UPDATE,
        )

        # undelete in case they got flagged as deleted
        for name, obj in list(SHARED.items()):
            if (
                hasattr(obj, "status")
                and obj.status == "deleted"
                and obj != net_rd
                and getattr(obj, "name", "").find("DUPE") == -1
            ):
                obj.status = "ok"
                obj.save()

        Organization.objects.create(
            name="Suggested Entitites", status="ok", id=settings.SUGGEST_ENTITY_ORG
        )

        cls.log("Setup for API testing completed!")

    @classmethod
    def cleanup(cls, *args, **options):
        cls.log("Cleaning up...")

        deleted = 0

        for k, obj in list(SHARED.items()):
            if hasattr(obj, "delete"):
                # print "HARD deleting ", obj
                try:
                    obj.delete(hard=True)
                    deleted += 1
                except AssertionError:
                    pass
            elif k[-3:] == "_id":
                reftag = re.match("^(.+)_id$", k).group(1)
                cls = REFTAG_MAP.get(reftag)
                if cls:
                    try:
                        inst = cls.objects.get(id=obj)
                        # print "HARD deleting ",inst
                        deleted += 1
                        inst.delete()
                    except cls.DoesNotExist:
                        pass

        print("Deleted", deleted, "objects")

    def handle(self, *args, **options):
        try:
            self.prepare()
        except IntegrityError as inst:
            print(inst)
            self.cleanup()
            print("Cleaned up after inegrity error, please try again ..")
            return
        if options["setup"]:
            return
        if not options["only"]:
            suite = unittest.TestLoader().loadTestsFromTestCase(TestJSON)
        else:
            only = options["only"].split(",")
            funcs = []
            for key in list(vars(TestJSON).keys()):
                for o in only:
                    if key[:5] == "test_" and key.find(o) > -1:
                        funcs.append(
                            "peeringdb_server.management.commands.pdb_api_test.TestJSON.%s"
                            % key
                        )

            funcs = sorted(funcs)

            suite = unittest.TestLoader().loadTestsFromNames(funcs)
        unittest.TextTestRunner(verbosity=2).run(suite)

        self.cleanup()
