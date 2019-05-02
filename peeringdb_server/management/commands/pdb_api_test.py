#!/bin/env python
# -*- coding: utf-8 -*-
"""
series of integration/unit tests for the pdb api
"""
import copy
import unittest
import uuid
import random
import re
import time
import datetime

from types import NoneType

from twentyc.rpc import RestClient, PermissionDeniedException, InvalidRequestException, NotFoundException
from django_namespace_perms.constants import PERM_READ, PERM_UPDATE, PERM_CREATE, PERM_DELETE
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.conf import settings
from django.db.utils import IntegrityError

from rest_framework import serializers

from peeringdb_server.models import (
    REFTAG_MAP, QUEUE_ENABLED, User, Organization, Network, InternetExchange,
    Facility, NetworkContact, NetworkIXLan, NetworkFacility, IXLan,
    IXLanPrefix, InternetExchangeFacility)

from peeringdb_server.serializers import REFTAG_MAP as REFTAG_MAP_SLZ
from peeringdb_server import inet, settings as pdb_settings

START_TIMESTAMP = time.time()

SHARED = {}

NUMERIC_TESTS = {
    "lt": "Less",
    "lte": "LessEqual",
    "gt": "Greater",
    "gte": "GreaterEqual",
    "": "Equal"
}

DATETIME = datetime.datetime.now()
DATE = DATETIME.date()
DATE_YDAY = DATE - datetime.timedelta(days=1)
DATE_TMRW = DATE - datetime.timedelta(days=-1)
DATES = {
    "today": (DATE, DATE.strftime("%Y-%m-%d")),
    "yesterday": (DATE_YDAY, DATE_YDAY.strftime("%Y-%m-%d")),
    "tomorrow": (DATE_TMRW, DATE_TMRW.strftime("%Y-%m-%d"))
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
USER = {"user": "api_test", "password": "89c8ec05-b897"}

USER_ORG_ADMIN = {"user": "api_test_org_admin", "password": "89c8ec05-b897"}

USER_ORG_MEMBER = {"user": "api_test_org_member", "password": "89c8ec05-b897"}

USER_CRUD = {
    "delete": {
        "user": "api_test_crud_delete",
        "password": "89c8ec05-b897"
    },
    "update": {
        "user": "api_test_crud_update",
        "password": "89c8ec05-b897"
    },
    "create": {
        "user": "api_test_crud_create",
        "password": "89c8ec05-b897"
    }
}

# server location
URL = settings.API_URL

# common
CITY = "Chicago"
COUNTRY = "US"
CONTINENT = "North America"
PHONE = "12345"
WEBSITE = "http://www.test.apitest"
STATE = "IL"
ZIPCODE = "1-2345"
NOTE = "This is a test entry made by a script to test out the API"
EMAIL = "test@20c.com"

VERBOSE = False


class TestJSON(unittest.TestCase):

    rest_client = RestClient

    PREFIX_COUNT = 110
    IP4_COUNT = 1
    IP6_COUNT = 1

    @classmethod
    def get_ip6(cls):
        r = u"2001:7f8:4::1154:%d" % cls.IP6_COUNT
        cls.IP6_COUNT += 1
        return r

    @classmethod
    def get_ip4(cls):
        r = u"1.1.1.%d" % cls.IP4_COUNT
        cls.IP4_COUNT += 1
        return r

    @classmethod
    def get_prefix4(cls):
        r = u"206.41.{}.0/24".format(cls.PREFIX_COUNT)
        cls.PREFIX_COUNT += 1
        return r

    @classmethod
    def get_prefix6(cls):
        r = u"2001:504:41:{}::/64".format(cls.PREFIX_COUNT)
        cls.PREFIX_COUNT += 1
        return r


    def setUp(self):
        self.db_guest = self.rest_client(URL, verbose=VERBOSE)
        self.db_user = self.rest_client(URL, verbose=VERBOSE, **USER)
        self.db_org_member = self.rest_client(URL, verbose=VERBOSE,
                                              **USER_ORG_MEMBER)
        self.db_org_admin = self.rest_client(URL, verbose=VERBOSE,
                                             **USER_ORG_ADMIN)
        for p, specs in USER_CRUD.items():
            setattr(self, "db_crud_%s" % p,
                    self.rest_client(URL, verbose=VERBOSE, **specs))

    def all_dbs(self, exclude=[]):
        return [
            db
            for db in [
                self.db_guest, self.db_org_member, self.db_user,
                self.db_org_admin, self.db_crud_create, self.db_crud_delete,
                self.db_crud_update
            ] if db not in exclude
        ]

    def readonly_dbs(self, exclude=[]):
        return [
            db for db in [self.db_guest, self.db_org_member, self.db_user]
            if db not in exclude
        ]

    ##########################################################################

    @classmethod
    def make_data_org(self, **kwargs):
        data = {
            "name": self.make_name("Test"),
            "website": WEBSITE,
            "notes": NOTE,
            "address1": "address",
            "address2": "address",
            "city": CITY,
            "country": COUNTRY,
            "state": "state",
            "zipcode": "12345"
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
            "proto_unicast": True,
            "proto_multicast": False,
            "proto_ipv6": True,
            "website": WEBSITE,
            "url_stats": "%s/stats" % WEBSITE,
            "tech_email": EMAIL,
            "tech_phone": PHONE,
            "policy_email": EMAIL,
            "policy_phone": PHONE
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
            "clli": str(uuid.uuid4())[:6].upper(),
            "rencode": str(uuid.uuid4())[:6].upper(),
            "npanxx": "000-111",
            "latitude": None,
            "longitude": None,
            "notes": NOTE
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
            "irr_as_set": "AS-XX-XXXXXX",
            "info_type": "NSP",
            "info_prefixes4": 11000,
            "info_prefixes6": 12000,
            "info_traffic": "1 Tbps+",
            "info_ratio": "Mostly Outbound",
            "info_scope": "Global",
            "info_unicast": True,
            "info_multicast": False,
            "info_ipv6": True,
            "notes": NOTE,
            "policy_url": "%s/policy" % WEBSITE,
            "policy_general": "Restrictive",
            "policy_locations": "Required - International",
            "policy_ratio": True,
            "policy_contracts": "Required"
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_poc(self, **kwargs):

        data = {
            "net_id": 1,
            "role": "Technical",
            "visible": "Private",
            "name": "NOC",
            "phone": PHONE,
            "email": EMAIL,
            "url": WEBSITE
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_ixlan(self, **kwargs):
        data = {
            "ix_id": 1,
            "name": self.make_name("Test"),
            "descr": NOTE,
            "mtu": 12345,
            "dot1q_support": False,
            "rs_asn": 12345,
            "arp_sponge": None
        }
        data.update(**kwargs)
        return data

    ##########################################################################

    @classmethod
    def make_data_ixpfx(self, **kwargs):
        data = {
            "ixlan_id": SHARED["ixlan_r_ok"].id,
            "protocol": "IPv4",
            "prefix": "10.%d.10.0/23" % (self.PREFIX_COUNT + 1)
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
            "ipaddr4": self.get_ip4(),
            "ipaddr6": self.get_ip6()
        }

        data.update(**kwargs)
        for k, v in rename.items():
            data[v] = data[k]
            del data[k]
        return data

    ##########################################################################

    @classmethod
    def make_name(self, name):
        return "api-test:%s:%s" % (name, uuid.uuid4())

    ##########################################################################

    @classmethod
    def serializer_related_fields(cls, serializer_class):
        """
        Returns declared relation fields on the provided serializer class

        Returned value will be a tuple in which the first item is a list of
        field names for primary key related fields and the second item is a list
        of fields names for related sets
        """

        pk_rel = []
        nested_rel = []

        for name, fld in serializer_class._declared_fields.items():
            if type(fld) == serializers.PrimaryKeyRelatedField:
                pk_rel.append(name[:-3])
            elif isinstance(fld, serializers.ListSerializer):
                nested_rel.append((name, fld.child))

        return (pk_rel, nested_rel)

    ##########################################################################

    def assert_handleref_integrity(self, data):
        """
        here we assert the integrity of a handleref (which is
        the base of all the models exposed on the api)

        we do this by making sure all of the handleref fields
        exist in the data
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
            for k, v in func().items():
                if k in ignore:
                    continue
                if type(v) in [str, unicode]:
                    self.assertIn(
                        type(data.get(k)),
                        [str, unicode], msg=msg % k)
                elif type(v) in [int, long]:
                    self.assertIn(type(data.get(k)), [int, long], msg=msg % k)
                else:
                    self.assertEqual(type(v), type(data.get(k)), msg=msg % k)

    ##########################################################################

    def assert_get_single(self, data):
        self.assertEqual(len(data), 1)
        return data[0]

    ##########################################################################

    def assert_get_forbidden(self, db, typ, id):
        with self.assertRaises(PermissionDeniedException) as cm:
            db.get(typ, id)

    ##########################################################################

    def assert_get_handleref(self, db, typ, id):
        data = self.assert_get_single(db.get(typ, id))
        self.assert_handleref_integrity(data)
        self.assert_data_integrity(data, typ)
        return data

    ##########################################################################

    def assert_existing_fields(self, a, b, ignore={}):
        for k, v in a.items():
            if ignore and k in ignore:
                continue
            if k in ["suggest"]:
                continue
            self.assertEqual(v, b.get(k))

    ##########################################################################

    def assert_delete(self, db, typ, test_success=None, test_failure=None):
        if test_success:
            db.rm(typ, test_success)
            with self.assertRaises(NotFoundException) as cm:
                self.assert_get_handleref(db, typ, test_success)

        if test_failure:
            with self.assertRaises(PermissionDeniedException) as cm:
                db.rm(typ, test_failure)
            try:
                self.assert_get_handleref(db, typ, test_failure)
            except PermissionDeniedException:
                pass

    ##########################################################################

    def assert_create(self, db, typ, data, test_failures=None,
                      test_success=True, **kwargs):
        if test_success:
            r_data = self.assert_get_single(
                db.create(typ, data, return_response=True).get("data"))
            self.assert_existing_fields(data, r_data,
                                        ignore=kwargs.get("ignore"))
            self.assertGreater(r_data.get("id"), 0)
            status_checked = False
            for model in QUEUE_ENABLED:
                if hasattr(model, "handleref") and model.handleref.tag == typ:
                    self.assertEqual(r_data.get("status"), "pending")
                    status_checked = True

            if not status_checked:
                self.assertEqual(r_data.get("status"), "ok")
        else:
            r_data = {}

        # if test_failures is set we want to test fail conditions
        if test_failures:

            # we test fail because of invalid data
            if "invalid" in test_failures:
                data_invalid = copy.copy(data)
                for k, v in test_failures["invalid"].items():
                    data_invalid[k] = v

                with self.assertRaises(InvalidRequestException) as inst:
                    r = db.create(typ, data_invalid, return_response=True)
                    for k, v in test_failures["invalid"].items():
                        self.assertIn(k, r.keys())

                self.assertEqual("400 Unknown", str(inst.exception[1]))

            # we test fail because of parent entity status
            if "status" in test_failures:
                data_status = copy.copy(data)
                for k, v in test_failures["status"].items():
                    data_status[k] = v

                with self.assertRaises(InvalidRequestException) as inst_status:
                    r = db.create(typ, data_status, return_response=True)
                self.assertIn("not yet been approved",
                              str(inst_status.exception))

            # we test fail because of permissions
            if "perms" in test_failures:
                data_perms = copy.copy(data)
                for k, v in test_failures["perms"].items():
                    data_perms[k] = v

                with self.assertRaises(PermissionDeniedException) as inst:
                    db.create(typ, data_perms, return_response=True)

        return r_data

    ##########################################################################

    def assert_create_status_failure(self, db, typ, data):
        """
        Wrapper for assert_create for assertion of permission failure
        """
        self.assert_create(db, typ, data, test_failures={"status": {}},
                           test_success=False)

    ##########################################################################

    def assert_update(self, db, typ, id, data, test_failures=False,
                      test_success=True):

        if test_success:
            orig = self.assert_get_handleref(db, typ, id)
            orig.update(**data)
        else:
            orig = {"id": id}
            orig.update(**data)

        for k, v in orig.items():
            if k[-3:] == "_id" and k[:-3] in orig:
                del orig[k[:-3]]

        if test_success:
            db.update(typ, **orig)
            u_data = self.assert_get_handleref(db, typ, id)
            if type(test_success) == list:
                for test in test_success:
                    if test and callable(test):
                        test(data, u_data)
            else:
                # self.assertGreater(u_data["version"], orig["version"])
                for k, v in data.items():
                    self.assertEqual(u_data.get(k), v)

        # if test_failures is set we want to test fail conditions
        if test_failures:

            # we test fail because of invalid data
            if "invalid" in test_failures:
                data_invalid = copy.copy(orig)
                for k, v in test_failures["invalid"].items():
                    data_invalid[k] = v

                with self.assertRaises(InvalidRequestException) as inst:
                    db.update(typ, **data_invalid)

                self.assertEqual("400 Unknown", str(inst.exception[1]))

            # we test fail because of permissions
            if "perms" in test_failures:
                data_perms = copy.copy(orig)
                for k, v in test_failures["perms"].items():
                    data_perms[k] = v

                with self.assertRaises(PermissionDeniedException) as inst:
                    db.update(typ, **data_perms)

            # we test failure to update readonly fields
            if "readonly" in test_failures:
                data_ro = copy.copy(orig)
                b_data = self.assert_get_handleref(db, typ, id)
                data_ro.update(**test_failures["readonly"])
                db.update(typ, **data_ro)
                u_data = self.assert_get_handleref(db, typ, id)
                for k, v in test_failures["readonly"].items():
                    self.assertEqual(u_data.get(k), b_data.get(k))

    ##########################################################################

    def assert_list_filter_related(self, target, rel, fld="id", valid=None,
                                   valid_m=None):
        #if not valid:
        #    valid = [o.id for k, o in SHARED.items() if type(
        #             o) != int and k.find("%s_" % target) == 0]

        if fld != "id":
            qfld = "_%s" % fld
        else:
            qfld = fld

        ids = [
            getattr(SHARED["%s_r_ok" % rel], fld),
            getattr(SHARED["%s_rw_ok" % rel], fld)
        ]
        kwargs_s = {
            "%s_%s" % (rel, qfld): getattr(SHARED["%s_r_ok" % rel], fld)
        }
        kwargs_m = {
            "%s_%s__in" % (rel, qfld): ",".join([str(id) for id in ids])
        }

        if hasattr(REFTAG_MAP[target], "%s" % rel):

            valid_s = [
                r.id
                for r in REFTAG_MAP[target].objects.filter(**kwargs_s)
                .filter(status="ok")
            ]

            valid_m = [
                r.id
                for r in REFTAG_MAP[target]
                .objects.filter(**{
                    "%s_%s__in" % (rel, qfld): ids
                }).filter(status="ok")
            ]

        elif target == "poc":
            valid_s = [SHARED["%s_r_ok_public" % target].id]

            valid_m = [
                SHARED["%s_r_ok_public" % target].id,
                SHARED["%s_rw_ok_public" % target].id
            ]
        else:

            valid_s = [SHARED["%s_r_ok" % target].id]

            valid_m = [
                SHARED["%s_r_ok" % target].id, SHARED["%s_rw_ok" % target].id
            ]

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

    def assert_related_depth(self, obj, serializer_class, r_depth, t_depth,
                             note_tag, typ="listing", list_exclude=[]):
        """
        Assert the data indegrity of structures within a result that have
        been expanded via the depth parameter
        """

        # get all the realtion ship properties declared in the serializer
        pk_flds, n_flds = self.serializer_related_fields(serializer_class)

        # some tag so we can track where the assertions fail since this will
        # be doing nested checks
        note_tag = "%s(%d/%d)" % (note_tag, r_depth, t_depth)

        # first check that the provided object is not None, as this should
        # never be the case
        self.assertNotEqual(type(obj), NoneType, msg=note_tag)

        # single primary key relation fields
        for pk_fld in pk_flds:

            # serializer has marked field as to be excluded from serialized data
            # dont check for it
            if pk_fld in list_exclude:
                continue

            if typ == "listing":
                # in listing mode, depth should never expand pk relations
                self.assertEqual(
                    obj.get(pk_fld), None, msg="PK Relation %s %s" % (note_tag,
                                                                      pk_fld))
            else:
                # in single get mode, expand everything as long as we are at
                # a relative depth greater than 1
                if r_depth >= 1:
                    self.assert_related_depth(
                        obj.get(pk_fld), REFTAG_MAP_SLZ.get(pk_fld),
                        r_depth - 1, t_depth, "%s.%s" % (note_tag,
                                                         pk_fld), typ=typ)
                else:
                    self.assertIn(
                        type(obj.get(pk_fld)),
                        [int, long, NoneType],
                        msg="PK Relation %s %s" % (note_tag, pk_fld))

        # nested set relations
        for n_fld, n_fld_cls in n_flds:
            if r_depth > 1:

                # sets should be expanded to objects
                self.assertIn(n_fld, obj,
                              msg="Nested set existing (dN) %s %s" % (note_tag,
                                                                      n_fld))

                # make sure set exists and is of the correct type
                self.assertEqual(
                    type(obj[n_fld]), list,
                    msg="Nested set list type (dN) %s %s" % (note_tag, n_fld))

                # assert further depth expansions on all expanded objects in
                # the set
                for row in obj[n_fld]:
                    self.assert_related_depth(
                        row, n_fld_cls, r_depth - 2, t_depth, "%s.%s" %
                        (note_tag, n_fld), typ=typ, list_exclude=getattr(
                            n_fld_cls.Meta, "list_exclude", []))

            elif r_depth == 1:

                # sets should be expanded to ids
                self.assertIn(n_fld, obj,
                              msg="Nested set existing (d1) %s %s" % (note_tag,
                                                                      n_fld))

                # make sure set exists and is of the correct type
                self.assertEqual(
                    type(obj[n_fld]), list,
                    msg="Nested set list type (d1) %s %s" % (note_tag, n_fld))

                # make all values in the set are of type int or long
                for row in obj[n_fld]:
                    self.assertIn(
                        type(row),
                        [long, int],
                        msg="Nested set containing ids (d1) %s %s" % (note_tag,
                                                                      n_fld))
            else:
                # sets should not exist
                self.assertNotIn(n_fld, obj,
                                 msg="Netsted set not existing (d0) %s %s" %
                                 (note_tag, n_fld))

    ##########################################################################
    # TESTS WITH USER THAT IS NOT A MEMBER OF AN ORGANIZATION
    ##########################################################################

    def test_user_001_GET_org(self):
        self.assert_get_handleref(self.db_user, "org", SHARED["org_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_net(self):
        data = self.assert_get_handleref(self.db_user, "net",
                                         SHARED["net_r_ok"].id)
        self.assertNotEqual(len(data.get("poc_set")), 0)

    ##########################################################################

    def test_user_001_GET_ix(self):
        self.assert_get_handleref(self.db_user, "ix", SHARED["ix_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_ix_net_count(self):
        data = self.assert_get_handleref(self.db_user, "ix",
                                         SHARED["ix_r_ok"].id)
        self.assertEqual(data.get("net_count"), 1)

    ##########################################################################

    def test_user_001_GET_fac(self):
        self.assert_get_handleref(self.db_user, "fac", SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_fac_netcount(self):
        data = self.assert_get_handleref(self.db_user, "fac",
                                         SHARED["fac_r_ok"].id)
        self.assertEqual(data.get("net_count"), 1)

    ##########################################################################

    def test_user_001_GET_poc_public(self):
        self.assert_get_handleref(self.db_user, "poc",
                                  SHARED["poc_r_ok_public"].id)

    ##########################################################################

    def test_user_001_GET_poc_users(self):
        self.assert_get_handleref(self.db_user, "poc",
                                  SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_user_001_GET_poc_private(self):
        self.assert_get_forbidden(self.db_user, "poc",
                                  SHARED["poc_r_ok_private"].id)

    ##########################################################################

    def test_user_001_GET_nefac(self):
        self.assert_get_handleref(self.db_user, "netfac",
                                  SHARED["netfac_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_netixlan(self):
        self.assert_get_handleref(self.db_user, "netixlan",
                                  SHARED["netixlan_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_ixfac(self):
        self.assert_get_handleref(self.db_user, "ixfac",
                                  SHARED["ixfac_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_ixlan(self):
        self.assert_get_handleref(self.db_user, "ixlan",
                                  SHARED["ixlan_r_ok"].id)

    ##########################################################################

    def test_user_001_GET_ixpfx(self):
        self.assert_get_handleref(self.db_user, "ixpfx",
                                  SHARED["ixpfx_r_ok"].id)

    ##########################################################################

    def test_user_005_list_poc(self):
        data = self.db_guest.all("poc", limit=1000)
        for row in data:
            self.assertIn(row.get("visible"), ["Users", "Public"])
        data = self.db_guest.all("poc", visible="Private", limit=100)
        self.assertEqual(0, len(data))

    ##########################################################################

    def test_user_001_GET_as_set(self):
        data = self.db_guest.all("as_set")
        networks = Network.objects.filter(status="ok")
        print(data)
        for net in networks:
            self.assertEqual(data[0].get(u"{}".format(net.asn)), net.irr_as_set)


    ##########################################################################
    # TESTS WITH USER THAT IS ORGANIZATION MEMBER
    ##########################################################################

    def test_org_member_001_GET_poc_public(self):
        self.assert_get_handleref(self.db_org_member, "poc",
                                  SHARED["poc_r_ok_public"].id)

    ##########################################################################

    def test_org_member_001_GET_poc_users(self):
        self.assert_get_handleref(self.db_org_member, "poc",
                                  SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_org_member_001_GET_poc_private(self):
        self.assert_get_handleref(self.db_org_member, "poc",
                                  SHARED["poc_r_ok_private"].id)

    ##########################################################################
    # TESTS WITH USER THAT IS ORGANIZATION ADMINISTRATOR
    ##########################################################################

    ##########################################################################

    def test_org_admin_001_GET_poc_public(self):
        self.assert_get_handleref(self.db_org_admin, "poc",
                                  SHARED["poc_r_ok_public"].id)

    ##########################################################################

    def test_org_admin_001_GET_poc_users(self):
        self.assert_get_handleref(self.db_org_admin, "poc",
                                  SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_org_admin_001_GET_poc_private(self):
        # org admin is admin of rw org, so trying to access the private poc of the r org
        # should still be forbidden
        self.assert_get_forbidden(self.db_org_admin, "poc",
                                  SHARED["poc_r_ok_private"].id)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ix(self):

        data = self.make_data_ix(prefix=self.get_prefix4())

        r_data = self.assert_create(
            self.db_org_admin,
            "ix",
            data,
            ignore=["prefix"],
            test_failures={
                "invalid": {
                    "prefix": self.get_prefix4(),
                    "name": ""
                },
                "perms": {
                    "prefix": self.get_prefix4(),
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    # set org to an organization the user doesnt have perms to
                    "org_id": SHARED["org_r_ok"].id
                },
                "status": {
                    # need to set name again so it doesnt fail unique validation
                    "prefix": self.get_prefix4(),
                    "name": self.make_name("Test"),
                    "org_id": SHARED["org_rwp"].id
                }
            })

        SHARED["ix_id"] = r_data.get("id")

        self.assert_update(self.db_org_admin, "ix", SHARED["ix_id"],
                           {"name": self.make_name("Test")}, test_failures={
                               "invalid": {
                                   "name": ""
                               },
                               "perms": {
                                   "id": SHARED["ix_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "ix",
                           test_success=SHARED["ix_id"],
                           test_failure=SHARED["ix_r_ok"].id)

        self.assert_create(
            self.db_org_admin, "ix", data, test_success=False, test_failures={
                "invalid": {
                    "prefix": self.get_prefix4(),
                    "policy_email": "",
                    "tech_email": ""
                },
            })

        self.assert_create(self.db_org_admin, "ix", data, test_success=False,
                           test_failures={
                               "invalid": {
                                   "prefix": ""
                               },
                           })

        # test ix creation with a ipv6 prefix
        data = self.make_data_ix(prefix=self.get_prefix6())
        self.assert_create(self.db_org_admin, "ix", data, ignore=["prefix"])



    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_fac(self):
        data = self.make_data_fac()

        r_data = self.assert_create(
            self.db_org_admin,
            "fac",
            data,
            test_failures={
                "invalid": {
                    "name": ""
                },
                "perms": {
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    # set org to an organization the user doesnt have perms to
                    "org_id": SHARED["org_r_ok"].id
                },
                "status": {
                    "name": self.make_name("Test"),
                    "org_id": SHARED["org_rwp"].id
                }
            })

        SHARED["fac_id"] = r_data.get("id")

        self.assert_update(
            self.db_org_admin,
            "fac",
            SHARED["fac_id"],
            {"name": self.make_name("Test")},
            test_failures={
                "invalid": {
                    "name": ""
                },
                "perms": {
                    "id": SHARED["fac_r_ok"].id
                },
                "readonly": {
                    "latitude": 1,  #this should not take as it is read only
                    "longitude": 1  #this should not take as it is read only
                }
            },
        )

        self.assert_delete(self.db_org_admin, "fac",
                           test_success=SHARED["fac_id"],
                           test_failure=SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_net(self):
        data = self.make_data_net(asn=9000900)

        r_data = self.assert_create(
            self.db_org_admin,
            "net",
            data,
            test_failures={
                "invalid": {
                    "name": ""
                },
                "perms": {
                    # need to set name again so it doesnt fail unique validation
                    "name": self.make_name("Test"),
                    "asn": data["asn"] + 1,
                    # set org to an organization the user doesnt have perms to
                    "org_id": SHARED["org_r_ok"].id
                },
                "status": {
                    "org_id": SHARED["org_rwp"].id,
                    "asn": data["asn"] + 1,
                    "name": self.make_name("Test")
                }
            })

        SHARED["net_id"] = r_data.get("id")

        self.assert_update(self.db_org_admin, "net", SHARED["net_id"],
                           {"name": self.make_name("Test")}, test_failures={
                               "invalid": {
                                   "name": ""
                               },
                               "perms": {
                                   "id": SHARED["net_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "net",
                           test_success=SHARED["net_id"],
                           test_failure=SHARED["net_r_ok"].id)

        # Test RiR not found failure

        r_data = self.assert_create(
            self.db_org_admin, "net", data,
            test_failures={"invalid": {
                "asn": 9999999
            }}, test_success=False)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_as_set(self):

        """
        The as-set endpoint is readonly, so all of these should
        fail
        """
        data = self.make_data_net(asn=9000900)

        with self.assertRaises(Exception) as exc:
            r_data = self.assert_create(self.db_org_admin,"as_set",data)
        self.assertIn("You do not have permission", str(exc.exception))

        with self.assertRaises(Exception) as exc:
            self.db_org_admin.update("as_set", {"9000900":"AS-XXX"})
        self.assertIn("You do not have permission", str(exc.exception))

        with self.assertRaises(Exception) as exc:
            self.db_org_admin.rm("as_set", SHARED["net_rw_ok"].asn)
        self.assertIn("You do not have permission", str(exc.exception))

    ##########################################################################

    def test_org_admin_002_POST_net_bogon_asn(self):

        # Test bogon asn failure

        data = self.make_data_net()
        for bogon_asn in inet.BOGON_ASN_RANGES:
            r_data = self.assert_create(
                self.db_org_admin, "net", data,
                test_failures={"invalid": {
                    "asn": bogon_asn[0]
                }}, test_success=False)

        # server running in tutorial mode should be allowed
        # to create networks with bogon asns, so we test that
        # as well

        pdb_settings.TUTORIAL_MODE = True

        for bogon_asn in inet.TUTORIAL_ASN_RANGES:
            data = self.make_data_net(asn=bogon_asn[0])
            r_data = self.assert_create(self.db_org_admin, "net", data)

        pdb_settings.TUTORIAL_MODE = False

    ##########################################################################

    def test_org_admin_002_PUT_net_write_only_fields(self):
        """
        with this we check that certain fields that are allowed to be
        set via the api, but sre not supposed to be rendered in the
        api data, work correctly
        """

        def test_write_only_fields_missing(orig, updated):
            assert (updated.has_key("allow_ixp_update") == False)

        net = SHARED["net_rw_ok"]
        self.assertEqual(net.allow_ixp_update, False)

        self.assert_update(self.db_org_admin, "net", net.id,
                           {"allow_ixp_update": True},
                           test_success=[test_write_only_fields_missing])

        net.refresh_from_db()
        self.assertEqual(net.allow_ixp_update, True)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_netfac(self):

        data = {
            "net_id": SHARED["net_rw_ok"].id,
            "fac_id": SHARED["fac_rw_ok"].id,
            "local_asn": 12345
        }

        r_data = self.assert_create(
            self.db_org_admin,
            "netfac",
            data,
            test_failures={
                "invalid": {
                    "net_id": ""
                },
                "perms": {
                    # set network to one the user doesnt have perms to
                    "net_id": SHARED["net_r_ok"].id
                },
                "status": {
                    "net_id": SHARED["net_rw_pending"].id,
                    "fac_id": SHARED["fac_rw_pending"].id,
                }
            })

        SHARED["netfac_id"] = r_data.get("id")

        self.assert_update(self.db_org_admin, "netfac", SHARED["netfac_id"],
                           {"local_asn": random.randint(999, 9999)},
                           test_failures={
                               "invalid": {
                                   "fac_id": ""
                               },
                               "perms": {
                                   "net_id": SHARED["net_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "netfac",
                           test_success=SHARED["netfac_id"],
                           test_failure=SHARED["netfac_r_ok"].id)

        # re-create deleted netfac
        r_data = self.assert_create(self.db_org_admin, "netfac", data)
        # re-delete
        self.assert_delete(self.db_org_admin, "netfac",
                           test_success=SHARED["netfac_id"])

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_poc(self):
        data = self.make_data_poc(net_id=SHARED["net_rw_ok"].id)

        r_data = self.assert_create(
            self.db_org_admin,
            "poc",
            data,
            test_failures={
                "invalid": {
                    "net_id": ""
                },
                "perms": {
                    # set network to one the user doesnt have perms to
                    "net_id": SHARED["net_r_ok"].id
                },
                "status": {
                    "net_id": SHARED["net_rw_pending"].id
                }
            })

        SHARED["poc_id"] = r_data.get("id")

        self.assert_update(self.db_org_admin, "poc", SHARED["poc_id"],
                           {"role": "Sales"}, test_failures={
                               "invalid": {
                                   "role": "NOPE"
                               },
                               "perms": {
                                   "net_id": SHARED["net_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "poc",
                           test_success=SHARED["poc_id"],
                           test_failure=SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ixlan(self):
        data = self.make_data_ixlan(ix_id=SHARED["ix_rw_ok"].id)

        r_data = self.assert_create(
            self.db_org_admin, "ixlan", data, test_failures={
                "invalid": {
                    "ix_id": ""
                },
                "perms": {
                    "ix_id": SHARED["ix_r_ok"].id
                },
                "status": {
                    "ix_id": SHARED["ix_rw_pending"].id
                }
            })

        SHARED["ixlan_id"] = r_data["id"]

        self.assert_update(self.db_org_admin, "ixlan", SHARED["ixlan_id"],
                           {"name": self.make_name("Test")}, test_failures={
                               "invalid": {
                                   "mtu": "NEEDS TO BE INT"
                               },
                               "perms": {
                                   "ix_id": SHARED["ix_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "ixlan",
                           test_success=SHARED["ixlan_id"],
                           test_failure=SHARED["ixlan_r_ok"].id)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ixpfx(self):
        data = self.make_data_ixpfx(ixlan_id=SHARED["ixlan_rw_ok"].id,
                                    prefix="206.126.236.0/25")

        r_data = self.assert_create(
            self.db_org_admin, "ixpfx", data, test_failures={
                "invalid": {
                    "prefix": "127.0.0.0/8"
                },
                "perms": {
                    "prefix": "205.127.237.0/24",
                    "ixlan_id": SHARED["ixlan_r_ok"].id
                },
                "status": {
                    "prefix": "205.127.237.0/24",
                    "ixlan_id": SHARED["ixlan_rw_pending"].id
                }
            })

        SHARED["ixpfx_id"] = r_data["id"]

        #self.assert_create(self.db_org_admin, "ixpfx", data, test_failures={
        #    "invalid": {
        #        "prefix": "206.126.236.0/25"
        #    },
        #}, test_success=False)

        self.assert_update(self.db_org_admin, "ixpfx", SHARED["ixpfx_id"],
                           {"prefix": "206.126.236.0/24"}, test_failures={
                               "invalid": {
                                   "prefix": "NEEDS TO BE VALID PREFIX"
                               },
                               "perms": {
                                   "ixlan_id": SHARED["ixlan_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "ixpfx",
                           test_success=SHARED["ixpfx_id"],
                           test_failure=SHARED["ixpfx_r_ok"].id)

        # re-create deleted ixpfx
        r_data = self.assert_create(self.db_org_admin, "ixpfx", data)
        # re-delete
        self.assert_delete(self.db_org_admin, "ixpfx",
                           test_success=SHARED["ixpfx_id"])

        # re-creating a deleted ixpfx that we dont have write permissions do
        # should fail
        pfx = IXLanPrefix.objects.create(ixlan=SHARED["ixlan_r_ok"],
                                         prefix=u"205.127.237.0/24",
                                         protocol="IPv4")
        pfx.delete()

        data.update(prefix="205.127.237.0/24")
        r_data = self.assert_create(self.db_org_admin, "ixpfx", data,
                                    test_failures={"invalid": {
                                    }}, test_success=False)

        # make sure protocols are validated
        r_data = self.assert_create(self.db_org_admin, "ixpfx", data,
                                    test_failures={
                                        "invalid": {
                                            "prefix": "207.128.238.0/24",
                                            "protocol": "IPv6"
                                        },
                                    }, test_success=False)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_netixlan(self):
        data = self.make_data_netixlan(net_id=SHARED["net_rw_ok"].id,
                                       ixlan_id=SHARED["ixlan_rw_ok"].id)

        r_data = self.assert_create(
            self.db_org_admin,
            "netixlan",
            data,
            test_failures={
                "invalid": {
                    "ipaddr4": u"a b c"
                },
                "perms": {
                    # set network to one the user doesnt have perms to
                    "ipaddr4": self.get_ip4(),
                    "ipaddr6": self.get_ip6(),
                    "net_id": SHARED["net_r_ok"].id
                }
            })

        SHARED["netixlan_id"] = r_data.get("id")

        self.assert_update(self.db_org_admin, "netixlan",
                           SHARED["netixlan_id"], {"speed": 2000},
                           test_failures={
                               "invalid": {
                                   "ipaddr4": "NEEDS TO BE VALID IP"
                               },
                               "perms": {
                                   "net_id": SHARED["net_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "netixlan",
                           test_success=SHARED["netixlan_id"],
                           test_failure=SHARED["netixlan_r_ok"].id)

    ##########################################################################

    def test_org_admin_002_POST_PUT_DELETE_ixfac(self):
        data = {
            "fac_id": SHARED["fac_rw2_ok"].id,
            "ix_id": SHARED["ix_rw2_ok"].id
        }

        r_data = self.assert_create(
            self.db_org_admin,
            "ixfac",
            data,
            test_failures={
                "invalid": {
                    "ix_id": ""
                },
                "perms": {
                    # set network to one the user doesnt have perms to
                    "ix_id": SHARED["ix_r_ok"].id
                },
                "status": {
                    "fac_id": SHARED["fac_rw2_pending"].id,
                    "ix_id": SHARED["ix_rw2_pending"].id
                }
            })

        SHARED["ixfac_id"] = r_data.get("id")

        self.assert_update(self.db_org_admin, "ixfac", SHARED["ixfac_id"],
                           {"fac_id": SHARED["fac_r2_ok"].id}, test_failures={
                               "invalid": {
                                   "fac_id": ""
                               },
                               "perms": {
                                   "ix_id": SHARED["ix_r_ok"].id
                               }
                           })

        self.assert_delete(self.db_org_admin, "ixfac",
                           test_success=SHARED["ixfac_id"],
                           test_failure=SHARED["ixfac_r_ok"].id)

    ##########################################################################

    def test_org_admin_003_PUT_org(self):
        self.assert_update(self.db_org_admin, "org", SHARED["org_rw_ok"].id,
                           {"name": self.make_name("Test")}, test_failures={
                               "invalid": {
                                   "name": ""
                               },
                               "perms": {
                                   "id": SHARED["org_r_ok"].id
                               }
                           })

    ##########################################################################

    def test_zz_org_admin_004_DELETE_org(self):

        self.assert_delete(self.db_org_admin, "org",
                           test_success=SHARED["org_rw_ok"].id,
                           test_failure=SHARED["org_r_ok"].id)

    ##########################################################################
    # GUEST TESTS
    ##########################################################################

    def test_guest_001_GET_org(self):
        self.assert_get_handleref(self.db_guest, "org", SHARED["org_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_net(self):
        data = self.assert_get_handleref(self.db_guest, "net",
                                         SHARED["net_r_ok"].id)
        for poc in data.get("poc_set"):
            self.assertEqual(poc["visible"], "Public")

    ##########################################################################

    def __test_guest_001_GET_asn(self):
        """
        ASN endpoint is currently disabled
        """
        return
        self.assert_get_handleref(self.db_guest, "asn", SHARED["net_r_ok"].asn)

        with self.assertRaises(InvalidRequestException) as inst:
            self.assert_get_handleref(self.db_guest, "asn",
                                      "%s[" % SHARED["net_r_ok"].asn)

    ##########################################################################

    def test_guest_001_GET_ix(self):
        self.assert_get_handleref(self.db_guest, "ix", SHARED["ix_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_fac(self):
        self.assert_get_handleref(self.db_guest, "fac", SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_poc_private(self):
        self.assert_get_forbidden(self.db_guest, "poc",
                                  SHARED["poc_r_ok_private"].id)

    ##########################################################################

    def test_guest_001_GET_poc_users(self):
        self.assert_get_forbidden(self.db_guest, "poc",
                                  SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_guest_001_GET_poc_public(self):
        self.assert_get_handleref(self.db_guest, "poc",
                                  SHARED["poc_r_ok_public"].id)

    ##########################################################################

    def test_guest_001_GET_nefac(self):
        self.assert_get_handleref(self.db_guest, "netfac",
                                  SHARED["netfac_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_netixlan(self):
        self.assert_get_handleref(self.db_guest, "netixlan",
                                  SHARED["netixlan_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_ixfac(self):
        self.assert_get_handleref(self.db_guest, "ixfac",
                                  SHARED["ixfac_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_ixlan(self):
        self.assert_get_handleref(self.db_guest, "ixlan",
                                  SHARED["ixlan_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_ixpfx(self):
        self.assert_get_handleref(self.db_guest, "ixpfx",
                                  SHARED["ixpfx_r_ok"].id)

    ##########################################################################

    def test_guest_001_GET_list_404(self):
        for tag in REFTAG_MAP:
            with self.assertRaises(NotFoundException) as inst:
                data = self.db_guest.all(tag, limit=1, id=99999999)
            if tag == "net":
                with self.assertRaises(NotFoundException) as inst:
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

    def test_guest_005_fields_filter(self):
        data = self.db_guest.all("org", limit=10, fields=",".join(
            ["name", "status"]))
        self.assertGreater(len(data), 0)
        for row in data:
            self.assertEqual(sorted(row.keys()), sorted([u"name", u"status"]))

        data = self.db_guest.get("org", 1, fields=",".join(["name", "status"]))
        self.assertGreater(len(data), 0)
        self.assertEqual(sorted(data[0].keys()), sorted([u"name", u"status"]))

    ##########################################################################

    def test_guest_005_list_limit(self):
        data = self.db_guest.all("org", limit=10)
        self.assertEqual(len(data), 10)
        self.assert_handleref_integrity(data[0])
        self.assert_data_integrity(data[0], "org")

    ##########################################################################

    def test_guest_005_list_pagination(self):
        n = 1
        for i in range(0, 10):
            data = self.db_guest.all("org", skip=i * 10, limit=10)
            for row in data:
                self.assertEqual(row.get("id"), n)
                n += 1

    ##########################################################################

    def test_guest_005_list_since(self):
        data = self.db_guest.all("net", since=int(START_TIMESTAMP) - 10,
                                 status="deleted")
        self.assertEqual(len(data), 2)
        self.assert_handleref_integrity(data[0])
        self.assert_data_integrity(data[0], "net")

    ##########################################################################

    def test_guest_005_get_depth_all(self):
        """
        Test all end points single object GET with all valid depths
        This also asserts data structure integrity for objects expanded
        by the depth parameter
        """

        for depth in [0, 1, 2, 3, 4]:
            for tag, slz in REFTAG_MAP_SLZ.items():
                note_tag = "(%s %s)" % (tag, depth)
                if tag == "poc":
                    o = SHARED["%s_r_ok_public" % tag]
                else:
                    o = SHARED["%s_r_ok" % tag]
                data = self.db_guest.get(tag, o.id, depth=depth)
                self.assertEqual(len(data), 1, msg="Data length %s" % note_tag)
                pk_flds, n_flds = self.serializer_related_fields(slz)

                obj = data[0]
                self.assert_related_depth(obj, slz, depth, depth, note_tag,
                                          typ="single")

    ##########################################################################

    def test_guest_005_list_depth_all(self):
        """
        Tests all end points multiple object GET with all valid depths
        This also asserts data structure integrity for objects expanded
        by the depth parameter
        """

        for depth in [0, 1, 2, 3]:
            for tag, slz in REFTAG_MAP_SLZ.items():
                note_tag = "(%s %s)" % (tag, depth)
                if tag == "poc":
                    o = SHARED["%s_r_ok_public" % tag]
                else:
                    o = SHARED["%s_r_ok" % tag]
                data = self.db_guest.all(tag, id=o.id, depth=depth)
                self.assertEqual(len(data), 1, msg="Data length %s" % note_tag)
                pk_flds, n_flds = self.serializer_related_fields(slz)

                obj = data[0]
                self.assert_related_depth(obj, slz, depth, depth, note_tag,
                                          typ="listing")

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
        for flt, ass in NUMERIC_TESTS.items():
            for fld in ["created", "updated"]:

                if flt in ["gt", "gte"]:
                    DATE = DATES["yesterday"]
                elif flt in ["lt"]:
                    DATE = DATES["tomorrow"]
                else:
                    DATE = DATES["today"]

                if flt:
                    kwargs = {"%s__%s" % (fld, flt): DATE[1]}
                else:
                    kwargs = {fld: DATE[1]}
                data = self.db_guest.all("fac", limit=10, **kwargs)
                self.assertGreater(
                    len(data), 0, msg="%s_%s - data length assertion" % (fld,
                                                                         flt))
                for row in data:
                    self.assert_data_integrity(row, "fac")
                    try:
                        dt = datetime.datetime.strptime(
                            row[fld], "%Y-%m-%dT%H:%M:%SZ").date()
                    except ValueError:
                        dt = datetime.datetime.strptime(
                            row[fld], "%Y-%m-%dT%H:%M:%S.%fZ").date()
                    fnc = getattr(self, "assert%s" % ass)
                    fnc(dt, DATE[0],
                        msg="%s__%s: %s, %s" % (fld, flt, row[fld], DATE[1]))

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
            self.assertLessEqual(long(fac["id"]), SHARED["fac_rw_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_lt(self):
        data = self.db_guest.all("fac", id__lt=SHARED["fac_rw_ok"].id)
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertLess(long(fac["id"]), SHARED["fac_rw_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_gte(self):
        data = self.db_guest.all("fac", id__gte=SHARED["fac_r_ok"].id)
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertGreaterEqual(long(fac["id"]), SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_gt(self):
        data = self.db_guest.all("fac", id__gt=SHARED["fac_r_ok"].id)
        self.assertGreater(len(data), 0)
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertGreater(long(fac["id"]), SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_guest_005_list_filter_numeric_in(self):
        ids = [SHARED["fac_r_ok"].id, SHARED["fac_rw_ok"].id]
        data = self.db_guest.all("fac", id__in="%s,%s" % tuple(ids))
        self.assertEqual(len(data), len(ids))
        self.assert_data_integrity(data[0], "fac")
        for fac in data:
            self.assertIn(long(fac["id"]), ids)

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

    def test_guest_005_list_filter_ix_name_search(self):
        data = self.db_guest.all("ix", name_search=SHARED["ix_r_ok"].name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], SHARED["ix_r_ok"].id)

        data = self.db_guest.all("ix", name_search=SHARED["ix_r_ok"].name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], SHARED["ix_r_ok"].id)

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

        # create ixlan at each exchange
        ixlans = [
            IXLan.objects.create(status="ok",
                                 **self.make_data_ixlan(ix_id=ix.id))
            for ix in exchanges
        ]

        # all three networks peer at first exchange
        for net in networks:
            NetworkIXLan.objects.create(network=net, ixlan=ixlans[0],
                                        status="ok", asn=net.asn, speed=0)

        # only the first two networks peer at second exchange
        for net in networks[:2]:
            NetworkIXLan.objects.create(network=net, ixlan=ixlans[1],
                                        status="ok", asn=net.asn, speed=0)

        # do test queries

        # query #1 - test overlapping exchanges for all 3 asns - should return first ix
        data = self.db_guest.all("ix", asn_overlap=",".join(
            [str(net.asn) for net in networks]))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], exchanges[0].id)

        # query #2 - test overlapping exchanges for first 2 asns - should return both ixs
        data = self.db_guest.all("ix", asn_overlap=",".join(
            [str(net.asn) for net in networks[:2]]))
        self.assertEqual(len(data), 2)
        for row in data:
            self.assertIn(row["id"], [ix.id for ix in exchanges])

        # query #3 - should error when only passing one asn
        with self.assertRaises(InvalidRequestException) as inst:
            self.db_guest.all("ix", asn_overlap=networks[0].asn)

        # query #4 - should error when passing too many asns
        with self.assertRaises(InvalidRequestException):
            self.db_guest.all("ix", asn_overlap=",".join(
                [str(i) for i in range(0, 30)]))

        # clean up data
        for net in networks:
            net.delete(hard=True)
        for ix in exchanges:
            ix.delete(hard=True)

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

    def test_guest_005_list_filter_fac_net_count(self):
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

    def test_guest_005_list_filter_ix_net_count(self):
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
            NetworkFacility.objects.create(network=net, facility=facilities[0],
                                           status="ok")

        # only the first two networks peer at second facility
        for net in networks[:2]:
            NetworkFacility.objects.create(network=net, facility=facilities[1],
                                           status="ok")

        # do test queries

        # query #1 - test overlapping facilities for all 3 asns - should return first facility
        data = self.db_guest.all("fac", asn_overlap=",".join(
            [str(net.asn) for net in networks]))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], facilities[0].id)

        # query #2 - test overlapping facilities for first 2 asns - should return both facs
        data = self.db_guest.all("fac", asn_overlap=",".join(
            [str(net.asn) for net in networks[:2]]))
        self.assertEqual(len(data), 2)
        for row in data:
            self.assertIn(row["id"], [ix.id for ix in facilities])

        # query #3 - should error when only passing one asn
        with self.assertRaises(InvalidRequestException):
            self.db_guest.all("fac", asn_overlap=networks[0].asn)

        # query #4 - should error when passing too many asns
        with self.assertRaises(InvalidRequestException):
            self.db_guest.all("fac", asn_overlap=",".join(
                [str(i) for i in range(0, 30)]))

        # clean up data
        for net in networks:
            net.delete(hard=True)
        for fac in facilities:
            fac.delete(hard=True)

    ##########################################################################

    def test_guest_005_list_filter_netixlan_related(self):
        self.assert_list_filter_related("netixlan", "net")
        self.assert_list_filter_related("netixlan", "ixlan")
        self.assert_list_filter_related("netixlan", "ix")

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
        data = self.db_guest.all("netfac", country=SHARED["fac_rw_ok"].country)
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
        test filtering with accented search terms
        """

        #TODO: sqlite3 is being used as the testing backend, and django 1.11
        #seems to be unable to set a collation on it, so we can't properly test
        #the other way atm, for now this test at least confirms that the term is
        #unaccented correctly.
        #
        #on production we run mysql with flattened accents so both ways should work
        #there regardless.

        org = Organization.objects.create(name="org unaccented", status="ok")
        net = Network.objects.create(asn=12345, name=u"net unaccented",
                                     status="ok", org=org)
        ix = InternetExchange.objects.create(org=org, name=u"ix unaccented", status="ok")
        fac = Facility.objects.create(org=org, name=u"fac unaccented", status="ok")

        for tag in ["org","net","ix","fac"]:
            data = self.db_guest.all(tag, name=u"{} unãccented".format(tag))
            self.assertEqual(len(data), 1)



    ##########################################################################
    # READONLY PERMISSION TESTS
    # These tests assert that the readonly users cannot write anything
    ##########################################################################

    ##########################################################################

    def test_readonly_users_003_PUT_org(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "org", SHARED["org_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_002_POST_ix(self):
        for db in self.readonly_dbs():
            self.assert_create(db, "ix",
                               self.make_data_ix(prefix=self.get_prefix4()),
                               test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_ix(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "ix", SHARED["ix_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_ix(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "ix", test_success=False,
                               test_failure=SHARED["ix_r_ok"].id)

    ##########################################################################

    def test_readonly_users_002_POST_fac(self):
        for db in self.readonly_dbs():
            self.assert_create(db, "fac", self.make_data_fac(),
                               test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_fac(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "fac", SHARED["fac_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_fac(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "fac", test_success=False,
                               test_failure=SHARED["fac_r_ok"].id)

    ##########################################################################

    def test_readonly_users_002_POST_netfac(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db, "netfac", {
                    "net_id": SHARED["net_r_ok"].id,
                    "fac_id": SHARED["fac_r2_ok"].id,
                    "local_asn": 12345
                }, test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_netfac(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "netfac", SHARED["netfac_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_netfac(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "netfac", test_success=False,
                               test_failure=SHARED["netfac_r_ok"].id)

    ##########################################################################

    def test_readonly_users_002_POST_ixfac(self):
        for db in self.readonly_dbs():
            self.assert_create(db, "ixfac", {
                "ix_id": SHARED["ix_r_ok"].id,
                "fac_id": SHARED["fac_r2_ok"].id
            }, test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_ixfac(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "ixfac", SHARED["ixfac_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_ixfac(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "ixfac", test_success=False,
                               test_failure=SHARED["ixfac_r_ok"].id)

    ##########################################################################

    def test_readonly_users_002_POST_poc(self):
        for db in self.readonly_dbs():
            self.assert_create(
                db, "poc", self.make_data_poc(net_id=SHARED["net_rw_ok"].id),
                test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_poc(self):
        for db in self.readonly_dbs(exclude=[self.db_user]):
            self.assert_update(db, "poc", SHARED["poc_r_ok_public"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })
            self.assert_update(db, "poc", SHARED["poc_r_ok_private"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })
            self.assert_update(db, "poc", SHARED["poc_r_ok_users"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_poc(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "poc", test_success=False,
                               test_failure=SHARED["poc_r_ok_public"].id)
            self.assert_delete(db, "poc", test_success=False,
                               test_failure=SHARED["poc_r_ok_private"].id)
            self.assert_delete(db, "poc", test_success=False,
                               test_failure=SHARED["poc_r_ok_users"].id)

    ##########################################################################

    def test_readonly_users_002_POST_ixlan(self):
        for db in self.readonly_dbs():
            self.assert_create(db, "ixlan", self.make_data_ixlan(),
                               test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_ixlan(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "ixlan", SHARED["ixlan_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_ixlan(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "ixlan", test_success=False,
                               test_failure=SHARED["ixlan_r_ok"].id)

    ##########################################################################

    def test_readonly_users_002_POST_ixpfx(self):
        for db in self.readonly_dbs():
            self.assert_create(db, "ixpfx",
                               self.make_data_ixpfx(prefix="200.100.200.0/22"),
                               test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_ixpfx(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "ixpfx", SHARED["ixpfx_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_ixpfx(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "ixpfx", test_success=False,
                               test_failure=SHARED["ixpfx_r_ok"].id)

    ##########################################################################

    def test_readonly_users_002_POST_netixlan(self):
        for db in self.readonly_dbs():
            self.assert_create(db, "netixlan", self.make_data_netixlan(),
                               test_failures={"perms": {}}, test_success=False)

    ##########################################################################

    def test_readonly_users_003_PUT_netixlan(self):
        for db in self.readonly_dbs():
            self.assert_update(db, "netixlan", SHARED["netixlan_r_ok"].id, {},
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    ##########################################################################

    def test_readonly_users_004_DELETE_netixlan(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "netixlan", test_success=False,
                               test_failure=SHARED["netixlan_r_ok"].id)

    ##########################################################################

    def test_readonly_users_004_DELETE_org(self):
        for db in self.readonly_dbs():
            self.assert_delete(db, "org", test_success=False,
                               test_failure=SHARED["org_r_ok"].id)

    ##########################################################################
    # CRUD PERMISSION TESTS
    ##########################################################################

    def test_z_crud_002_create(self):

        # user with create perms should be allowed to create a new poc under net_rw3_ok
        # but not under net_rw2_ok
        self.assert_create(self.db_crud_create, "poc",
                           self.make_data_poc(net_id=SHARED["net_rw3_ok"].id),
                           test_failures={
                               "perms": {
                                   "net_id": SHARED["net_rw2_ok"].id
                               }
                           })

        # user with create perms should not be able to create an ixlan under
        # net_rw_ix
        self.assert_create(self.db_crud_create, "ixlan",
                           self.make_data_ixlan(ix_id=SHARED["ix_rw3_ok"].id),
                           test_failures={"perms": {}}, test_success=False)

        # other crud test users should not be able to create a new poc under
        # net_rw3_ok
        for p in ["delete", "update"]:
            self.assert_create(
                getattr(self, "db_crud_%s" % p), "poc",
                self.make_data_poc(net_id=SHARED["net_rw3_ok"].id),
                test_failures={"perms": {}}, test_success=False)

    def test_z_crud_003_update(self):

        # user with update perms should be allowed to update net_rw3_ok
        # but not net_rw2_ok
        self.assert_update(self.db_crud_update, "net", SHARED["net_rw3_ok"].id,
                           {"name": self.make_name("Test")}, test_failures={
                               "perms": {
                                   "id": SHARED["net_rw2_ok"].id
                               }
                           })

        # user with update perms should not be allowed to update ix_rw3_ok
        self.assert_update(self.db_crud_update, "ix", SHARED["ix_rw3_ok"].id,
                           {"name": self.make_name("Test")},
                           test_failures={"perms": {}}, test_success=False)

        # other crud test users should not be able to update net_rw3_ok
        for p in ["delete", "create"]:
            self.assert_update(
                getattr(self, "db_crud_%s" % p), "net",
                SHARED["net_rw3_ok"].id, {"name": self.make_name("Test")},
                test_failures={"perms": {}}, test_success=False)

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
        self.assert_delete(self.db_crud_delete, "net", SHARED["net_rw3_ok"].id,
                           test_failure=SHARED["net_rw2_ok"].id)

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

    def test_z_misc_002_dupe_netixlan_ip(self):

        # test that addint duplicate netixlan ips is impossible

        A = SHARED["netixlan_rw_ok"]
        self.assert_create(self.db_org_admin, "netixlan",
                           self.make_data_netixlan(ixlan_id=A.ixlan_id,
                                                   net_id=A.network_id),
                           test_success=False, test_failures={
                               "invalid": {
                                   "ipaddr4": unicode(A.ipaddr4)
                               }
                           })

        self.assert_create(self.db_org_admin, "netixlan",
                           self.make_data_netixlan(
                               ixlan_id=A.ixlan_id,
                               net_id=A.network_id,
                           ), test_success=False, test_failures={
                               "invalid": {
                                   "ipaddr6": unicode(A.ipaddr6)
                               }
                           })

    def test_z_misc_002_dupe_name_update(self):

        # test that changing the name of entity A (status=ok)
        # to name of entity B (status=deleted) does raise the approporiate
        # unique key error and does not undelete entity B

        A = SHARED["fac_rw_dupe_ok"]
        B = SHARED["fac_rw_dupe_deleted"]

        self.assertEqual(A.status, "ok")
        self.assertEqual(B.status, "deleted")

        self.assert_update(self.db_org_admin, "fac", A.id, {}, test_failures={
            "invalid": {
                "name": B.name
            }
        })

        B.refresh_from_db()
        self.assertEqual(B.status, "deleted")

    def test_z_misc_001_org_create(self):

        # no one should be allowed to create an org via the api
        # at this point in time

        for db in self.all_dbs():
            self.assert_create(db, "org",
                               self.make_data_org(name=self.make_name("Test")),
                               test_success=False, test_failures={
                                   "perms": {}
                               })

    def test_z_misc_001_suggest_net(self):
        # test network suggestions

        data = self.make_data_net(
            asn=9000901, org_id=settings.SUGGEST_ENTITY_ORG, suggest=True)

        r_data = self.assert_create(self.db_user, "net", data)

        self.assertEqual(r_data["org_id"], settings.SUGGEST_ENTITY_ORG)
        self.assertEqual(r_data["status"], "pending")

        net = Network.objects.get(id=r_data["id"])
        self.assertEqual(net.org_id, settings.SUGGEST_ENTITY_ORG)

        data = self.make_data_net(
            asn=9000902, org_id=settings.SUGGEST_ENTITY_ORG, suggest=True)

        r_data = self.assert_create(self.db_guest, "net", data,
                                    test_success=False, test_failures={
                                        "perms": {}
                                    })

    def test_z_misc_001_suggest_fac(self):
        # test facility suggestions

        data = self.make_data_fac(org_id=settings.SUGGEST_ENTITY_ORG,
                                  suggest=True)

        r_data = self.assert_create(self.db_user, "fac", data)

        self.assertEqual(r_data["org_id"], settings.SUGGEST_ENTITY_ORG)
        self.assertEqual(r_data["status"], "pending")

        fac = Facility.objects.get(id=r_data["id"])
        self.assertEqual(fac.org_id, settings.SUGGEST_ENTITY_ORG)

        data = self.make_data_fac(org_id=settings.SUGGEST_ENTITY_ORG,
                                  suggest=True)

        r_data = self.assert_create(self.db_guest, "fac", data,
                                    test_success=False, test_failures={
                                        "perms": {}
                                    })

    def test_z_misc_001_suggest_ix(self):
        # test exchange suggestions

        data = self.make_data_ix(org_id=settings.SUGGEST_ENTITY_ORG,
                                 suggest=True, prefix=self.get_prefix4())

        r_data = self.assert_create(self.db_user, "ix", data,
                                    ignore=["prefix", "suggest"])

        self.assertEqual(r_data["org_id"], settings.SUGGEST_ENTITY_ORG)
        self.assertEqual(r_data["status"], "pending")

        ix = InternetExchange.objects.get(id=r_data["id"])
        self.assertEqual(ix.org_id, settings.SUGGEST_ENTITY_ORG)

        data = self.make_data_ix(org_id=settings.SUGGEST_ENTITY_ORG,
                                 suggest=True, prefix=self.get_prefix4())

        r_data = self.assert_create(self.db_guest, "ix", data, ignore=[
            "prefix", "suggest"
        ], test_success=False, test_failures={
            "perms": {}
        })

    def test_z_misc_001_suggest_outside_of_post(self):
        # The `suggest` keyword should only be allowed for
        # `POST` events

        for reftag in ["ix", "fac", "net"]:
            ent = SHARED["{}_rw_ok".format(reftag)]
            org_id = ent.org_id
            self.assert_update(self.db_org_admin, reftag, ent.id,
                               {"notes": "bla"}, test_failures={
                                   "invalid": {
                                       "suggest": True
                                   }
                               })

            ent.refresh_from_db()
            self.assertEqual(ent.org_id, org_id)

    def test_z_misc_001_fac_address_geocode(self):
        # test that facility gets marked for geocode sync after address field
        # change
        fac = SHARED["fac_rw_ok"]
        fac.geocode_status = True
        fac.save()

        self.assert_update(self.db_org_admin, "fac", fac.id, {
            "address1": "This is a test"
        })

        fac.refresh_from_db()
        self.assertEqual(fac.geocode_status, False)

        # reset geocode status
        fac.geocode_status = True
        fac.save()

        # test that facility does NOT get marked for geocode sync after non relevant
        # fields are changed

        self.assert_update(self.db_org_admin, "fac", fac.id, {
            "website": "http://example.com",
            "name": fac.name + " Geocode Test"
        })
        fac.refresh_from_db()
        self.assertEqual(fac.geocode_status, True)


class Command(BaseCommand):
    help = "This runs the api test harness. All write ops are performed under an organization specifically made for testing, so running to against a prod environment should be fine in theory."

    def add_arguments(self, parser):
        parser.add_argument("--only", help="only run this test", dest="only")
        parser.add_argument("--setup",
                            help="runs api test setup (user, org create) only",
                            dest="setup", action="store_true")

    @classmethod
    def log(cls, msg):
        print msg

    @classmethod
    def create_entity(cls, model, prefix="rw", unset=[], key_suffix=None,
                      name_suffix=None, **kwargs):
        tag = model.handleref.tag
        status = kwargs.get("status", "ok")
        name = "API Test:%s:%s:%s" % (tag.upper(), prefix.upper(), status)
        if name_suffix:
            name = "%s%s" % (name, name_suffix)
        data = {"status": status}
        if tag in ["ix", "net", "fac", "org"]:
            data["name"] = name

        data.update(**kwargs)
        try:
            obj = model.objects.get(**data)
            cls.log(
                "%s with status '%s' for %s testing already exists, skipping!"
                % (tag.upper(), status, prefix.upper()))
        except model.DoesNotExist:
            fn = getattr(TestJSON, "make_data_%s" % tag, None)
            if fn:
                data = fn(**data)
            for k in unset:
                if k in data:
                    del data[k]
            obj = model.objects.create(**data)
            cls.log("%s with status '%s' for %s testing created! (%s)" %
                    (tag.upper(), status, prefix.upper(), obj.updated))

        id = "%s_%s_%s" % (tag, prefix, status)
        if key_suffix:
            id = "%s_%s" % (id, key_suffix)
        SHARED[id] = obj
        return obj

    @classmethod
    def create_user(cls, USER):
        try:
            user = User.objects.get(username=USER.get("user"))
            cls.log("USER '%s' already exists, skipping!" % USER.get("user"))
            user.groups.clear()
            user.userpermission_set.all().delete()
        except User.DoesNotExist:
            user = User.objects.create(username=USER.get("user"))
            user.set_password(USER.get("password"))
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
        for p, specs in USER_CRUD.items():
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
        for crud_user in crud_users.values():
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
            org_rwp = Organization.objects.create(status="pending",
                                                  name=ORG_RW_PENDING)
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
            cls.log(
                "NET for status 'deleted' testing already exists, skipping!")
        except Network.DoesNotExist:
            net_rd = Network.objects.create(**TestJSON.make_data_net(
                name=NET_R_DELETED, org_id=org_r.id))
            cls.log("NET for status 'deleted' testing created!")
        net_rd.delete()

        SHARED["net_rd"] = net_rd

        # create various entities for rw testing

        for model in [Network, Facility, InternetExchange]:
            for status in ["ok", "pending"]:
                for prefix in ["r", "rw"]:
                    cls.create_entity(model, status=status, prefix=prefix,
                                      org_id=SHARED["org_%s_%s" % (prefix,
                                                                   status)].id)
                    cls.create_entity(
                        model, status=status, prefix="%s2" % prefix,
                        org_id=SHARED["org_%s_%s" % (prefix, status)].id)
                    cls.create_entity(
                        model, status=status, prefix="%s3" % prefix,
                        org_id=SHARED["org_%s_%s" % (prefix, status)].id)

        # create entities for duplicate validation testing

        for model in [Network, Facility, InternetExchange]:
            cls.create_entity(model, status="deleted", prefix="rw_dupe",
                              name_suffix=" DUPE",
                              org_id=SHARED["org_rw_ok"].id)
            cls.create_entity(model, status="ok", prefix="rw_dupe",
                              name_suffix=" DUPE !",
                              org_id=SHARED["org_rw_ok"].id)

        for status in ["ok", "pending"]:
            for prefix in ["r", "rw"]:
                cls.create_entity(IXLan, status=status, prefix=prefix,
                                  ix_id=SHARED["ix_%s_%s" % (prefix,
                                                             status)].id)
                cls.create_entity(
                    IXLanPrefix,
                    status=status,
                    prefix=prefix,
                    ixlan_id=SHARED["ixlan_%s_%s" % (prefix, status)].id,
                )
                cls.create_entity(
                    InternetExchangeFacility, status=status, prefix=prefix,
                    facility_id=SHARED["fac_%s_%s" % (prefix, status)].id,
                    ix_id=SHARED["ix_%s_%s" % (prefix, status)].id)
                cls.create_entity(
                    NetworkFacility, status=status, prefix=prefix, unset=[
                        "net_id"
                    ], facility_id=SHARED["fac_%s_%s" % (prefix, status)].id,
                    network_id=SHARED["net_%s_%s" % (prefix, status)].id)
                cls.create_entity(
                    NetworkIXLan, status=status, prefix=prefix, unset=[
                        "net_id"
                    ], ixlan_id=SHARED["ixlan_%s_%s" % (prefix, status)].id,
                    network_id=SHARED["net_%s_%s" % (prefix, status)].id)

                for v in ["Private", "Users", "Public"]:
                    cls.create_entity(NetworkContact, status=status,
                                      prefix=prefix, visible=v,
                                      network_id=SHARED["net_%s_%s" %
                                                        (prefix, status)].id,
                                      unset=["net_id"], key_suffix=v.lower())

        # set up permissions for crud permission tests
        crud_users["delete"].userpermission_set.create(
            namespace=SHARED["net_rw3_ok"].nsp_namespace,
            permissions=PERM_READ | PERM_DELETE)
        crud_users["create"].userpermission_set.create(
            namespace=SHARED["net_rw3_ok"].nsp_namespace,
            permissions=PERM_READ | PERM_CREATE)
        crud_users["update"].userpermission_set.create(
            namespace=SHARED["net_rw3_ok"].nsp_namespace,
            permissions=PERM_READ | PERM_UPDATE)

        # undelete in case they got flagged as deleted
        for name, obj in SHARED.items():
            if hasattr(
                    obj, "status"
            ) and obj.status == "deleted" and obj != net_rd and getattr(
                    obj, "name", "").find("DUPE") == -1:
                obj.status = "ok"
                obj.save()

        Organization.objects.create(name="Suggested Entitites", status="ok",
                                    id=settings.SUGGEST_ENTITY_ORG)

        cls.log("Setup for API testing completed!")

    @classmethod
    def cleanup(cls, *args, **options):
        cls.log("Cleaning up...")

        deleted = 0

        for k, obj in SHARED.items():
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

        print "Deleted", deleted, "objects"

    def handle(self, *args, **options):
        try:
            self.prepare()
        except IntegrityError, inst:
            print inst
            self.cleanup()
            print "Cleaned up after inegrity error, please try again .."
            return
        if options['setup']:
            return
        if not options['only']:
            suite = unittest.TestLoader().loadTestsFromTestCase(TestJSON)
        else:
            only = options["only"].split(",")
            funcs = []
            for key in vars(TestJSON).keys():
                for o in only:
                    if key[:5] == "test_" and key.find(o) > -1:
                        funcs.append(
                            "peeringdb_server.management.commands.pdb_api_test.TestJSON.%s"
                            % key)

            funcs = sorted(funcs)

            suite = unittest.TestLoader().loadTestsFromNames(funcs)
        unittest.TextTestRunner(verbosity=2).run(suite)

        self.cleanup()
