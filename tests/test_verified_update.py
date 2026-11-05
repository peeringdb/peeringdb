import base64
import datetime
import json

from allauth.account.models import EmailAddress
from django.core.cache import caches
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

import peeringdb_server.models as models
from peeringdb_server.validators import validate_verified_update_data


@override_settings(
    MFA_FORCE_SOFT_START=datetime.datetime.now() + datetime.timedelta(days=1),
    MFA_FORCE_HARD_START=datetime.datetime.now() + datetime.timedelta(days=1),
)
class VerifiedUpdateTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # create user and guest group

        call_command("pdb_generate_test_data", limit=2, commit=True)

        for username, email in [
            ("admin", "admin@admin.com"),
            ("user", "test@test.com"),
        ]:
            access = True if username == "admin" else False
            setattr(
                cls,
                username,
                models.User.objects.create_user(
                    username, email, username, is_superuser=access, is_staff=access
                ),
            )
            getattr(cls, username).set_password(username)
            EmailAddress.objects.create(
                user=getattr(cls, username), email=email, verified=True, primary=True
            )
            cls.net = models.Network.objects.first()
            cls.poc = cls.net.poc_set_active.first()
            cls.org = cls.net.org
            cls.org.usergroup.user_set.add(getattr(cls, username))

        # superusers bypass some of the API rules
        cls.orgadmin = models.User.objects.create_user(
            "orgadmin", "orgadmin@localhost", "orgadmin"
        )
        EmailAddress.objects.create(
            user=cls.orgadmin, email="orgadmin@localhost", verified=True, primary=True
        )
        cls.org.admin_usergroup.user_set.add(cls.orgadmin)
        # mock data turns on every flag, including periodic re-authentication
        models.Organization.objects.filter(pk=cls.org.pk).update(
            periodic_reauth=False, restrict_user_emails=False
        )

    def setUp(self):
        # the rate limits count in the default cache
        caches["default"].clear()
        self.client = APIClient()
        self.payload = {
            "source": "pdb",
            "reason": "testing",
            "updates": [
                {
                    "ref_tag": "net",
                    "obj_id": self.net.id,
                    "data": {
                        "info_prefixes4": 4,
                        "info_prefixes6": 6,
                        "info_type": "Content",
                    },
                },
                {
                    "ref_tag": "poc",
                    "obj_id": self.poc.id,
                    "data": {"name": "20C", "role": "Sales", "email": "20c@cc.com"},
                },
            ],
        }
        self.payload_invalid_ref_tag = {
            "source": "pdb",
            "reason": "testing",
            "updates": [
                {
                    "ref_tag": "invalid",
                    "obj_id": self.net.id,
                    "data": {"info_prefixes4": 4, "info_prefixes6": 6},
                }
            ],
        }
        self.payload_invalid_obj_id = {
            "source": "pdb",
            "reason": "testing",
            "updates": [
                {
                    "ref_tag": "net",
                    "obj_id": 999,
                    "data": {"info_prefixes4": 4, "info_prefixes6": 6},
                }
            ],
        }
        self.payload_accept = {
            "data[]": ["net", f"{self.net.id}", "poc", f"{self.poc.id}"],
            "data[][info_prefixes4]": ["4"],
            "data[][info_prefixes6]": ["6"],
            "data[][name]": ["20C"],
            "data[][role]": ["Sales"],
            "data[][email]": ["20c@cc.com"],
            "reason": "testing",
            "source": "pdb",
            "referer": "http://testserver/verified-update",
        }
        self.payload_accept_empty_data = {
            "data[]": ["net", self.net.id, "poc", self.poc.id]
        }

    def _get_encoded_payload(self, payload):
        """
        Helper function to encode a payload into a base64 string
        """
        return base64.b64encode(json.dumps(payload).encode()).decode()

    def test_verified_update(self):
        self.client.login(username="admin", password="admin")
        encoded_payload = self._get_encoded_payload(self.payload)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        print(response.content.decode("utf-8"))
        self.assertIn(
            f"<b>{self.payload['source']}</b> proposes the following changes to:",
            response.content.decode("utf-8"),
        )
        self.assertIn(f"<h3>{self.net} -", response.content.decode("utf-8"))
        self.assertIn(f"<h3>{self.poc} -", response.content.decode("utf-8"))
        self.assertIn(
            '<button type="submit" class="btn btn-primary commit">Accept selected changes</button>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 200)

    def test_verified_update_invalid_ref_tag(self):
        self.client.login(username="admin", password="admin")
        encoded_payload = self._get_encoded_payload(self.payload_invalid_ref_tag)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        self.assertIn(
            "Proposed update contains invalid data: Unknown object type:",
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 400)

    def test_verified_update_invalid_obj_id(self):
        self.client.login(username="admin", password="admin")
        encoded_payload = self._get_encoded_payload(self.payload_invalid_obj_id)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        self.assertIn(
            "Proposed update contains invalid data: object net.999 not found",
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 400)

    def test_verified_update_invalid_permission(self):
        self.client.login(username="user", password="user")
        encoded_payload = self._get_encoded_payload(self.payload)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        self.assertIn(
            "You do not have permissions to make changes to:",
            response.content.decode("utf-8"),
        )
        self.assertIn(f"<p>{self.net} -", response.content.decode("utf-8"))
        self.assertIn(f"<p>{self.poc} -", response.content.decode("utf-8"))
        self.assertNotIn(f"<h3>{self.net} -", response.content.decode("utf-8"))
        self.assertNotIn(f"<h3>{self.poc} -", response.content.decode("utf-8"))
        self.assertNotIn(
            '<button type="submit" class="btn btn-primary commit">Accept selected changes</button>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 200)

    def test_verified_update_accept(self):
        self.assertNotEqual(self.net.info_prefixes4, 4)
        self.assertNotEqual(self.net.info_prefixes6, 6)
        self.assertNotEqual(self.poc.name, "20C")
        self.assertNotEqual(self.poc.role, "Sales")
        self.assertNotEqual(self.poc.email, "20c@cc.com")
        self.client.login(username="admin", password="admin")
        response = self.client.post(
            "/verified-update/accept/",
            data=self.payload_accept,
            follow=True,
        )
        print(response.content.decode("utf-8"))

        self.net.refresh_from_db()
        self.poc.refresh_from_db()
        self.assertIn("<h3>Successfully updated</h3>", response.content.decode("utf-8"))
        self.assertIn(
            f'<li><a href="{self.net.view_url}">{self.net.name}</a></li>',
            response.content.decode("utf-8"),
        )
        self.assertIn(
            f'<li><a href="{self.poc.view_url}">{self.poc.name}</a></li>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(self.net.info_prefixes4, 4)
        self.assertEqual(self.net.info_prefixes6, 6)
        self.assertEqual(self.poc.name, "20C")
        self.assertEqual(self.poc.role, "Sales")
        self.assertEqual(self.poc.email, "20c@cc.com")
        self.assertEqual(response.status_code, 200)

    def test_verified_update_accept_empty_data(self):
        self.client.login(username="admin", password="admin")
        response = self.client.post(
            "/verified-update/accept/",
            data=self.payload_accept_empty_data,
            follow=True,
        )
        self.assertIn(
            "Please select one or more data", response.content.decode("utf-8")
        )
        self.assertEqual(response.status_code, 200)

    def test_verified_update_accept_no_permission(self):
        self.client.login(username="user", password="user")
        response = self.client.post(
            "/verified-update/accept/",
            data=self.payload_accept,
            follow=True,
        )
        self.assertIn(
            "You do not have permissions to make changes to",
            response.content.decode("utf-8"),
        )
        self.assertIn(
            f'<p><a href="{self.net.view_url}">{self.net.name}</a>',
            response.content.decode("utf-8"),
        )
        self.assertIn(
            f'<p><a href="{self.poc.view_url}">{self.poc.name}</a>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 200)

    def test_validate_verified_update_data(self):
        test_data = [
            # success validation
            (
                "net",
                self.net.id,
                {"info_prefixes4": 4, "info_prefixes6": 6},
                (True, {"info_prefixes4": 4, "info_prefixes6": 6}),
            ),
            # success validation with a data has same value as current data
            (
                "net",
                self.net.id,
                {"info_prefixes4": self.net.info_prefixes4, "info_prefixes6": 6},
                (True, {"info_prefixes6": 6}),
            ),
            # fail validation
            (
                "net",
                self.net.id,
                {},
                (False, "Data is empty"),
            ),
            (
                "invalid",
                self.net.id,
                {"info_prefixes4": 4, "info_prefixes6": 6},
                (False, "Unknown object type: invalid"),
            ),
            (
                "net",
                999,
                {"info_prefixes4": 4, "info_prefixes6": 6},
                (False, "object net.999 not found"),
            ),
        ]

        for ref_tag, obj_id, data, validated in test_data:
            with self.subTest(
                ref_tag=ref_tag, obj_id=obj_id, data=data, validated=validated
            ):
                if not validated[0]:
                    self.assertTrue(
                        isinstance(
                            str(
                                validate_verified_update_data(ref_tag, obj_id, data)[1]
                            ),
                            str,
                        )
                    )
                    self.assertTrue(
                        validate_verified_update_data(ref_tag, obj_id, data)[1],
                        validated[1],
                    )
                else:
                    self.assertTrue(
                        isinstance(
                            validate_verified_update_data(ref_tag, obj_id, data)[1],
                            dict,
                        )
                    )
                self.assertEqual(
                    validate_verified_update_data(ref_tag, obj_id, data), validated
                )

    def _accept(self, data, username="orgadmin", **fields):
        self.client.login(username=username, password=username)
        payload = {
            "data[]": data,
            "reason": "testing",
            "source": "pdb",
            "referer": "http://testserver/verified-update",
        }
        payload.update({f"data[][{field}]": value for field, value in fields.items()})
        return self.client.post("/verified-update/accept/", data=payload)

    def _preview(self, ref_tag, obj_id, data, username="orgadmin"):
        self.client.login(username=username, password=username)
        payload = {
            "source": "pdb",
            "reason": "testing",
            "updates": [{"ref_tag": ref_tag, "obj_id": obj_id, "data": data}],
        }
        encoded_payload = self._get_encoded_payload(payload)
        return self.client.get(f"/verified-update/?p={encoded_payload}")

    def _add_technical_contact(self, net):
        # the API takes no exchange connection changes without one
        models.NetworkContact.objects.create(
            network=net,
            role="Technical",
            visible="Public",
            email="tech@localhost",
            status="ok",
        )

    def _net_without_contacts(self):
        net = models.Network.objects.create(
            name="Verified Update No Contacts", asn=63412, org=self.org, status="ok"
        )
        self.assertFalse(net.poc_set_active.exists())
        return net

    def test_verified_update_accept_applies_api_rules(self):
        """
        Accepting a verified update applies the rules an API update does (#525)
        """
        net = self._net_without_contacts()
        for field, value in (
            ("allow_ixp_update", "true"),
            ("irr_as_set", "AS-NOSOURCE"),
        ):
            with self.subTest(field=field):
                response = self._accept(["net", str(net.id)], **{field: value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, field)
                net.refresh_from_db()
                self.assertFalse(net.allow_ixp_update)
                self.assertEqual(net.irr_as_set, "")

    def test_verified_update_preview_leaves_out_refused_changes(self):
        net = self._net_without_contacts()
        response = self._preview(
            "net", net.id, {"irr_as_set": "AS-NOSOURCE", "info_prefixes4": 7}
        )
        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="data[0][info_prefixes4]"', content)
        self.assertNotIn('name="data[0][irr_as_set]"', content)

    def test_verified_update_accept_info_types(self):
        response = self._accept(
            ["net", str(self.net.id)], info_types="Content,NSP", info_prefixes4="9"
        )
        self.assertEqual(response.status_code, 302)
        self.net.refresh_from_db()
        self.assertEqual(sorted(self.net.info_types), ["Content", "NSP"])
        self.assertEqual(self.net.info_prefixes4, 9)

    @override_settings(FACILITY_ADDRESS_SELECTION_ENABLED=True)
    def test_verified_update_facility_location(self):
        """
        Facility address fields still apply, the API serializer would leave
        them unchanged without a location selection
        """
        fac = models.Facility.objects.filter(status="ok").first()

        response = self._preview("fac", fac.id, {"city": "Elsewhere"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="data[0][city]"')

        response = self._accept(["fac", str(fac.id)], city="Elsewhere")
        self.assertEqual(response.status_code, 302)
        fac.refresh_from_db()
        self.assertEqual(fac.city, "Elsewhere")

    def test_verified_update_accept_object_types(self):
        """
        Each supported object type accepts an update through its API serializer
        """
        netixlan = self.net.netixlan_set_active.first()
        ix = netixlan.ixlan.ix
        self._add_technical_contact(self.net)
        fac = models.Facility.objects.filter(status="ok", org=self.org).first()
        for ref_tag, obj, field, value, expected in (
            ("ix", ix, "tech_email", "noc@localhost", "noc@localhost"),
            ("ixlan", netixlan.ixlan, "mtu", "9000", 9000),
            ("netixlan", netixlan, "speed", "20000", 20000),
            ("fac", fac, "clli", "ABCDEFGH", "ABCDEFGH"),
        ):
            with self.subTest(ref_tag=ref_tag):
                response = self._accept(
                    [ref_tag, str(obj.id)], username="admin", **{field: value}
                )
                self.assertIn(response.status_code, (200, 302))
                self.assertNotIn(b"could not be applied", response.content)
                obj.refresh_from_db()
                self.assertEqual(getattr(obj, field), expected)

    def test_verified_update_accept_single_stack_netixlan(self):
        netixlan = self.net.netixlan_set_active.first()
        models.NetworkIXLan.objects.filter(pk=netixlan.pk).update(ipaddr6=None)
        self._add_technical_contact(self.net)
        response = self._accept(
            ["netixlan", str(netixlan.id)], username="admin", speed="30000"
        )
        self.assertNotIn(b"could not be applied", response.content)
        netixlan.refresh_from_db()
        self.assertEqual(netixlan.speed, 30000)
        self.assertIsNone(netixlan.ipaddr6)

    def test_verified_update_accept_keeps_inherited_website(self):
        """
        The API represents a blank website as the organization's, an update
        must not store that on the object
        """
        models.Network.objects.filter(pk=self.net.pk).update(
            website="", social_media=[]
        )
        response = self._accept(["net", str(self.net.id)], info_prefixes4="11")
        self.assertEqual(response.status_code, 302)
        self.net.refresh_from_db()
        self.assertEqual(self.net.info_prefixes4, 11)
        self.assertEqual(self.net.website, "")
        self.assertEqual(self.net.social_media, [])

    def test_verified_update_deleted_object(self):
        poc = models.NetworkContact.objects.create(
            network=self.net,
            role="Policy",
            visible="Public",
            name="Deleted Contact",
            email="deleted@localhost",
            status="deleted",
        )
        response = self._preview("poc", poc.id, {"email": "new@localhost"})
        self.assertEqual(response.status_code, 400)
        response = self._accept(["poc", str(poc.id)], email="new@localhost")
        self.assertContains(response, "Please select one or more data")
        poc.refresh_from_db()
        self.assertEqual(poc.email, "deleted@localhost")
        self.assertEqual(poc.name, "Deleted Contact")

    def test_verified_update_read_only_field(self):
        fac = models.Facility.objects.filter(status="ok", org=self.org).first()
        response = self._preview("fac", fac.id, {"region_continent": "Africa"})
        self.assertNotContains(response, 'name="data[0][region_continent]"')
        response = self._accept(
            ["fac", str(fac.id)], username="admin", region_continent="Africa"
        )
        self.assertContains(response, "region_continent: This field can")

    def test_verified_update_accept_malformed(self):
        client = self.client
        client.login(username="admin", password="admin")
        for data in (["net"], ["net", "abc"], ["net", str(self.net.id), "poc"]):
            with self.subTest(data=data):
                response = client.post(
                    "/verified-update/accept/",
                    {"data[]": data, "data[][info_prefixes4]": "12"},
                )
                self.assertIn(response.status_code, (200, 302))

    def test_verified_update_preview_rate_limit(self):
        """
        The preview runs the API validators, some of which make lookups, so
        it is rate limited (#525)
        """
        statuses = [
            self._preview("net", self.net.id, {"info_prefixes4": 13}).status_code
            for _ in range(4)
        ]
        self.assertEqual(statuses, [200, 200, 200, 400])

    def test_verified_update_stored_values_do_not_refuse(self):
        """
        Values already stored that the API refuses only refuse an update
        that proposes them (#525)
        """
        org = models.Organization.objects.create(name="Verified Update No Website")
        org.admin_usergroup.user_set.add(self.orgadmin)
        net = models.Network.objects.create(
            name="Verified Update No Website",
            asn=63413,
            org=org,
            status="ok",
            website="",
            allow_ixp_update=True,
        )
        poc = models.NetworkContact.objects.create(
            network=net, role="Abuse", phone="not a phone", status="ok"
        )

        response = self._preview("net", net.id, {"info_prefixes4": 21})
        self.assertContains(response, 'name="data[0][info_prefixes4]"')
        response = self._accept(["net", str(net.id)], info_prefixes4="21")
        self.assertEqual(response.status_code, 302)
        net.refresh_from_db()
        self.assertEqual(net.info_prefixes4, 21)
        self.assertEqual(net.website, "")
        self.assertTrue(net.allow_ixp_update)

        response = self._accept(["poc", str(poc.id)], email="abuse@localhost")
        self.assertEqual(response.status_code, 302)
        poc.refresh_from_db()
        self.assertEqual(poc.email, "abuse@localhost")
        self.assertEqual(poc.phone, "not a phone")

        # a refused value is still refused when it is proposed
        response = self._accept(["poc", str(poc.id)], phone="also not a phone")
        self.assertContains(response, "phone:")
        poc.refresh_from_db()
        self.assertEqual(poc.phone, "not a phone")

    def _grant(self, org):
        org.admin_usergroup.user_set.add(self.orgadmin)
        models.Organization.objects.filter(pk=org.pk).update(
            periodic_reauth=False, restrict_user_emails=False
        )

    def test_verified_update_object_checks(self):
        """
        A check of the object as a whole refuses as it does in the API, also
        when the stored object already fails it
        """
        # #826: the network has no contact for its exchange connections
        netixlan = self.net.netixlan_set_active.first()
        speed = netixlan.speed
        response = self._accept(["netixlan", str(netixlan.id)], speed="40000")
        self.assertContains(response, "point of contact")
        netixlan.refresh_from_db()
        self.assertEqual(netixlan.speed, speed)

        # enabling the import of an exchange without a member list
        ixlan = netixlan.ixlan
        self._grant(ixlan.ix.org)
        models.IXLan.objects.filter(pk=ixlan.pk).update(
            ixf_ixp_member_list_url="", ixf_ixp_import_enabled=False
        )
        response = self._accept(["ixlan", str(ixlan.id)], ixf_ixp_import_enabled="true")
        self.assertContains(response, "Cannot enable IX-F import")
        ixlan.refresh_from_db()
        self.assertFalse(ixlan.ixf_ixp_import_enabled)

    def test_verified_update_netixlan_speed(self):
        netixlan = self.net.netixlan_set_active.first()
        speed = netixlan.speed
        self._add_technical_contact(self.net)
        for value in ("1", "6000000"):
            with self.subTest(speed=value):
                response = self._accept(["netixlan", str(netixlan.id)], speed=value)
                self.assertContains(response, "speed:")
                netixlan.refresh_from_db()
                self.assertEqual(netixlan.speed, speed)

    def test_verified_update_ix_without_website(self):
        """
        A stored website problem doesn't refuse a valid phone number, and the
        phone number is still checked
        """
        ix = self.net.netixlan_set_active.first().ixlan.ix
        self._grant(ix.org)
        models.Organization.objects.filter(pk=ix.org_id).update(website="")
        models.InternetExchange.objects.filter(pk=ix.pk).update(
            website="", country="US", tech_phone=""
        )
        response = self._accept(["ix", str(ix.id)], tech_phone="not a phone")
        self.assertContains(response, "tech_phone:")
        ix.refresh_from_db()
        self.assertEqual(ix.tech_phone, "")

        response = self._accept(["ix", str(ix.id)], tech_phone="+12065550100")
        self.assertEqual(response.status_code, 302)
        ix.refresh_from_db()
        self.assertEqual(ix.tech_phone, "+12065550100")
        self.assertEqual(ix.website, "")

    def test_verified_update_accept_info_type(self):
        org = models.Organization.objects.create(name="Verified Update Info Type")
        self._grant(org)
        net = models.Network.objects.create(
            name="Verified Update Info Type", asn=63414, org=org, status="ok"
        )
        response = self._accept(["net", str(net.id)], info_type="Content")
        self.assertEqual(response.status_code, 302)
        net.refresh_from_db()
        self.assertEqual(list(net.info_types), ["Content"])

    @override_settings(FACILITY_ADDRESS_SELECTION_ENABLED=True)
    def test_verified_update_facility_country_and_phone(self):
        fac = models.Facility.objects.filter(status="ok", org=self.org).first()
        models.Facility.objects.filter(pk=fac.pk).update(country="US", tech_phone="")
        response = self._preview(
            "fac", fac.id, {"country": "GB", "tech_phone": "020 7946 0018"}
        )
        self.assertContains(response, 'name="data[0][country]"')
        self.assertNotContains(response, "tech_phone]")

        response = self._accept(
            ["fac", str(fac.id)], country="GB", tech_phone="020 7946 0018"
        )
        self.assertContains(response, "separate updates")
        fac.refresh_from_db()
        self.assertEqual(str(fac.country), "US")
        self.assertEqual(fac.tech_phone, "")

    def test_verified_update_accept_same_object_twice(self):
        for other, message in (
            (f"0{self.net.id}", "only be proposed once"),
            (f"+{self.net.id}", "Invalid object id"),
            (f" {self.net.id}", "Invalid object id"),
        ):
            with self.subTest(other=other):
                response = self._accept(
                    ["net", str(self.net.id), "net", other], info_prefixes4="41"
                )
                self.assertContains(response, message)
                self.net.refresh_from_db()
                self.assertNotEqual(self.net.info_prefixes4, 41)

    def test_verified_update_stored_value_check_fails_on_rerun(self):
        """
        A stored value the checks refuse, where a neutral value is no help,
        refuses with the API's own error instead of a 500
        """
        netixlan = self.net.netixlan_set_active.first()
        self._add_technical_contact(self.net)
        models.NetworkIXLan.objects.filter(pk=netixlan.pk).update(
            speed=1, is_rs_peer=False
        )
        response = self._accept(["netixlan", str(netixlan.id)], is_rs_peer="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "speed:")
        netixlan.refresh_from_db()
        self.assertFalse(netixlan.is_rs_peer)

        response = self._preview("netixlan", netixlan.id, {"is_rs_peer": True})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "is_rs_peer]")

    def test_verified_update_untouched_field_rules(self):
        """
        Field rules apply to the proposed fields only (#525)
        """
        poc = models.NetworkContact.objects.create(
            network=self.net,
            role="Policy",
            visible="Private",
            name="Private Contact",
            email="private@localhost",
            status="ok",
        )
        response = self._accept(["poc", str(poc.id)], email="policy@localhost")
        self.assertEqual(response.status_code, 302)
        poc.refresh_from_db()
        self.assertEqual(poc.email, "policy@localhost")
        self.assertEqual(poc.visible, "Private")

        ix = self.net.netixlan_set_active.first().ixlan.ix
        models.InternetExchange.objects.filter(pk=ix.pk).update(tech_email="")
        response = self._accept(
            ["ix", str(ix.id)], username="admin", sales_email="sales@localhost"
        )
        self.assertEqual(response.status_code, 302)
        ix.refresh_from_db()
        self.assertEqual(ix.sales_email, "sales@localhost")
        self.assertEqual(ix.tech_email, "")

        # a check of the object as a whole refuses, social media is one
        social_media = [{"service": "", "identifier": "x"}]
        models.Network.objects.filter(pk=self.net.pk).update(social_media=social_media)
        response = self._accept(["net", str(self.net.id)], info_prefixes4="31")
        self.assertContains(response, "could not be applied")
        self.net.refresh_from_db()
        self.assertNotEqual(self.net.info_prefixes4, 31)

    @override_settings(FACILITY_ADDRESS_SELECTION_ENABLED=True)
    def test_verified_update_facility_location_with_other_field(self):
        fac = models.Facility.objects.filter(status="ok", org=self.org).first()
        response = self._accept(
            ["fac", str(fac.id)], username="admin", city="Elsewhere", clli="ABCDEFGH"
        )
        self.assertEqual(response.status_code, 302)
        fac.refresh_from_db()
        self.assertEqual(fac.city, "Elsewhere")
        self.assertEqual(fac.clli, "ABCDEFGH")

    def test_verified_update_preview_allow_ixp_update_without_contact(self):
        net = self._net_without_contacts()
        response = self._preview(
            "net", net.id, {"allow_ixp_update": True, "info_prefixes4": 7}
        )
        self.assertContains(response, 'name="data[0][info_prefixes4]"')
        self.assertNotContains(response, "allow_ixp_update]")

    def test_verified_update_preview_rate_limit_per_user(self):
        for _ in range(3):
            self._preview("net", self.net.id, {"info_prefixes4": 13})
        response = self._preview("net", self.net.id, {"info_prefixes4": 13})
        self.assertEqual(response.status_code, 400)
        response = self._preview(
            "net", self.net.id, {"info_prefixes4": 13}, username="admin"
        )
        self.assertEqual(response.status_code, 200)

    def test_verified_update_request_size(self):
        self.client.login(username="admin", password="admin")
        for updates, message in (
            (
                [
                    {
                        "ref_tag": "net",
                        "obj_id": self.net.id,
                        "data": {"info_prefixes4": 1},
                    }
                ]
                * 2,
                "only be proposed once",
            ),
            (
                [
                    {"ref_tag": "net", "obj_id": obj_id, "data": {"info_prefixes4": 1}}
                    for obj_id in range(1, 22)
                ],
                "Too many proposed updates",
            ),
        ):
            with self.subTest(count=len(updates)):
                caches["default"].clear()
                encoded_payload = self._get_encoded_payload(
                    {"source": "pdb", "reason": "testing", "updates": updates}
                )
                response = self.client.get(f"/verified-update/?p={encoded_payload}")
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()["error"])

    def test_verified_update_accept_fields_per_object(self):
        """
        Each object gets the fields proposed for it
        """
        other = self._net_without_contacts()
        self.client.login(username="admin", password="admin")
        response = self.client.post(
            "/verified-update/accept/",
            {
                "data[]": ["net", str(self.net.id), "net", str(other.id)],
                "data[0][info_prefixes4]": "10",
                "data[1][info_prefixes4]": "20",
                "data[1][info_prefixes6]": "30",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.net.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.net.info_prefixes4, 10)
        self.assertNotEqual(self.net.info_prefixes6, 30)
        self.assertEqual(other.info_prefixes4, 20)
        self.assertEqual(other.info_prefixes6, 30)
