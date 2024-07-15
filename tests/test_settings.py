import json
import os

import pytest
from allauth.account.signals import email_confirmed, user_signed_up
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

import peeringdb_server.inet as pdbinet
from mainsite.settings import _set_bool, _set_option
from peeringdb_server import models, serializers
from peeringdb_server import settings as pdb_settings

from .util import SettingsCase

# TODO: this override is used in multiple modules now, should be moved to a common location
# and imported from there
RdapLookup_get_asn = pdbinet.RdapLookup.get_asn


@pytest.mark.django_db
def setup_module(module):
    # RDAP LOOKUP OVERRIDE
    # Since we are working with fake ASNs throughout the api tests
    # we need to make sure the RdapLookup client can fake results
    # for us

    # These ASNs will be seen as valid and a prepared json object
    # will be returned for them (data/api/rdap_override.json)
    #
    # ALL ASNs outside of this range will raise a RdapNotFoundError
    ASN_RANGE_OVERRIDE = list(range(9000000, 9000999))

    with open(
        os.path.join(os.path.dirname(__file__), "data", "api", "rdap_override.json"),
    ) as fh:
        pdbinet.RdapLookup.override_result = json.load(fh)

    def get_asn(self, asn):
        if asn in ASN_RANGE_OVERRIDE:
            return pdbinet.RdapAsn(self.override_result)
        elif pdbinet.asn_is_bogon(asn):
            return RdapLookup_get_asn(self, asn)
        else:
            raise pdbinet.RdapNotFoundError()

    pdbinet.RdapLookup.get_asn = get_asn


@pytest.mark.django_db
def teardown_module(module):
    pdbinet.RdapLookup.get_asn = RdapLookup_get_asn


class TestAutoVerifyUser(SettingsCase):
    settings = {"AUTO_VERIFY_USERS": True}

    @pytest.mark.django_db
    def test_setting(self):
        user = get_user_model().objects.create_user(
            "user_a", "user_a@localhost", "user_a"
        )
        user_signed_up.send(sender=None, request=None, user=user)
        assert user.is_verified_user is True
        assert user.status == "ok"


class TestAutoApproveAffiliation(SettingsCase):
    settings = {"AUTO_APPROVE_AFFILIATION": True}

    @pytest.mark.django_db
    def test_setting(self):
        org = models.Organization.objects.create(name="Test Org", status="ok")
        net = models.Network.objects.create(
            name="Test Net", org=org, asn=63311, status="ok"
        )
        user = get_user_model().objects.create_user(
            "user_a", "user_a@localhost", "user_a"
        )
        user_b = get_user_model().objects.create_user(
            "user_b", "user_b@localhost", "user_b"
        )
        user.set_verified()
        user_b.set_verified()

        uoar = models.UserOrgAffiliationRequest.objects.create(
            user=user, org=org, asn=net.asn
        )
        assert user.is_org_admin(org) is True

        uoar = models.UserOrgAffiliationRequest.objects.create(user=user, asn=9000000)
        net = models.Network.objects.get(asn=9000000)
        assert user.is_org_admin(net.org) is True

        uoar = models.UserOrgAffiliationRequest.objects.create(
            user=user, org_name="Test Org 2"
        )
        org = models.Organization.objects.get(name="Test Org 2")
        assert user.is_org_admin(org) is True

        uoar = models.UserOrgAffiliationRequest.objects.create(user=user_b, asn=9000000)
        assert user_b.is_org_admin(net.org) is False
        assert user_b.is_org_member(net.org) is False


@pytest.mark.django_db
def test_set_option():
    context = {}
    _set_option("TEST_SETTING", "hello", context)
    assert context["TEST_SETTING"] == "hello"


@pytest.mark.django_db
def test_set_option_w_env_var():
    """
    Environment variables take precedence over provided options
    """
    context = {}
    os.environ["TEST_SETTING"] = "world"
    _set_option("TEST_SETTING", "hello", context)
    assert context["TEST_SETTING"] == "world"


@pytest.mark.django_db
def test_set_option_coerce_env_var():
    """
    We coerce the environment variable to the same type
    as the provided default.
    """
    context = {}
    # env variables can never be set as integers
    os.environ["TEST_SETTING"] = "123"

    # setting an option with a default integer will coerce the env
    # variable as well (fix for issue #888)
    _set_option("TEST_SETTING", 321, context)
    assert context["TEST_SETTING"] == 123

    # setting an option with a default string will coerce the env
    # variable as well
    _set_option("TEST_SETTING", "321", context)
    assert context["TEST_SETTING"] == "123"

    _set_option("TEST_SETTING", 123.1, context)
    assert context["TEST_SETTING"] == 123.0


@pytest.mark.django_db
def test_set_option_booleans():
    context = {}
    # env variables can only be set as strings
    os.environ["TEST_SETTING"] = "False"

    # setting the option with a boolean
    # will use set_bool to handle the
    # type coercion of the env variable
    _set_option("TEST_SETTING", False, context)
    assert context["TEST_SETTING"] is False

    # the environment variable has precedence
    _set_option("TEST_SETTING", True, context)
    assert context["TEST_SETTING"] is False

    del os.environ["TEST_SETTING"]
    del context["TEST_SETTING"]
    _set_option("TEST_SETTING", True, context)
    # We can set boolean values without env vars as well
    assert context["TEST_SETTING"] is True


@pytest.mark.django_db
def test_set_bool():
    """
    We coerce the environment variable to a boolean
    """
    context = {}

    # 0 is interpreted as False
    os.environ["TEST_SETTING"] = "0"
    # env variables can never be set as integers
    _set_bool("TEST_SETTING", False, context)
    assert context["TEST_SETTING"] is False

    # the environment variable has precedence
    _set_bool("TEST_SETTING", True, context)
    assert context["TEST_SETTING"] is False

    # We raise an error if the env variable
    # cannot be reasonably coerced to a bool

    os.environ["TEST_SETTING"] = "100"
    with pytest.raises(ValueError):
        _set_option("TEST_SETTING", True, context)


@pytest.mark.django_db
def test_set_options_none():
    """
    We coerce the environment variable to a boolean
    """
    context = {}

    # 0 is interpreted as False
    os.environ["TEST_SETTING"] = "0"

    # setting an option with None without setting the
    # envvar_type raises an error
    with pytest.raises(ValueError):
        _set_option("TEST_SETTING", None, context)

    # setting an option with None but setting the
    # envvar_type is fine
    _set_option("TEST_SETTING", None, context, envvar_type=int)
    assert context["TEST_SETTING"] == 0

    _set_option("TEST_SETTING", None, context, envvar_type=str)
    assert context["TEST_SETTING"] == "0"
