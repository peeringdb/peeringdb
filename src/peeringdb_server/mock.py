"""
Handle generation of mock data for testing purposes.
"""

import ipaddress
import uuid

from django.db import models
from django.utils import timezone

from peeringdb_server.models import REFTAG_MAP


class Mock:
    """
    Class that allows creation of mock data in the database.

    NOTE: This actually writes data to the database and should
    only be used to populate a dev instance.
    """

    def __init__(self):
        self._asn = 63311

        # Pool of IPv4 Prefixes
        # TODO - automatic generation via ipaddress module
        self.prefix_pool_v4 = [
            "206.126.236.0/22",
            "208.115.136.0/23",
            "206.223.118.0/24",
            "206.223.123.0/24",
            "206.223.116.0/23",
        ]

        # Pool of IPv6 Prefixes
        # TODO - automatic generation via ipaddrsss module
        self.prefix_pool_v6 = [
            "2001:504:0:2::/64",
            "2001:504:0:4::/64",
            "2001:504:0:5::/64",
            "2001:504:0:3::/64",
            "2001:504:0:1::/64",
        ]

        # helper function that allows us to retrieve n valid
        # hosts from an ipaddress space (prefix)
        def get_hosts(network, count=100):
            n = 0
            for host in network.hosts():
                if n > count:
                    break
                n += 1
                yield host

        # Pool of IPv4 addresses (100 per prefix)
        self.ipaddr_pool_v4 = {
            prefix: list(get_hosts(ipaddress.IPv4Network(prefix)))
            for prefix in self.prefix_pool_v4
        }

        # Pool of IPv6 addresses (100 per prefix)
        self.ipaddr_pool_v6 = {
            prefix: list(get_hosts(ipaddress.IPv6Network(prefix)))
            for prefix in self.prefix_pool_v6
        }

    def create(self, reftag, **kwargs):
        """
        Create a new instance of model specified in `reftag`

        Any arguments passed as kwargs will override mock field values.

        Note: Unless there are no relationships passed in kwargs, required parent
        objects will be automatically created as well.

        Returns: The created instance.
        """

        model = REFTAG_MAP.get(reftag)
        data = {}
        data.update(**kwargs)

        # first we create any required parent relation ships
        for field in model._meta.get_fields():
            if field.name in data:
                continue

            # dont create a campus for a facility
            if field.name == "campus":
                continue

            if field.is_relation and field.many_to_one:
                if hasattr(field.related_model, "ref_tag"):
                    data[field.name] = self.create(field.related_model.handleref.tag)

        # then we set the other fields to mock values provided by this class
        for field in model._meta.get_fields():
            # field value specified alrady, skip
            if field.name in data:
                continue

            # these we don't care about
            if field.name in ["id", "logo", "version", "created", "updated"]:
                continue
                # if reftag == "ixlan" and field.name != "id":
                #    continue
                # elif reftag != "ixlan":
                #    continue

            # this we don't care about either
            if field.name.find("geocode") == 0:
                continue

            # choice fields should automatically select a value from
            # the available choices
            #
            # PDB choices often have Not Disclosed at index 0 and 1
            # so we try index 2 first.
            if (
                not field.is_relation
                and field.choices
                and not hasattr(self, field.name)
            ):
                try:
                    data[field.name] = field.choices[2][0]
                except IndexError:
                    data[field.name] = field.choices[0][0]

            # bool fields set to True
            elif isinstance(field, models.BooleanField):
                data[field.name] = True

            # every other field
            elif not field.is_relation:
                # emails
                if field.name.find("email") > -1 and field.name != "email_domains":
                    data[field.name] = "test@peeringdb.com"

                # phone numbers
                elif field.name.find("phone") > -1:
                    data[field.name] = "+12065550199"

                # URLs
                elif field.name.find("url") > -1:
                    data[field.name] = (
                        f"{self.website(data, reftag=reftag)}/{field.name}"
                    )

                # everything else is routed to the apropriate method
                # with the same name as the field name
                else:
                    data[field.name] = getattr(self, field.name)(data, reftag=reftag)

        obj = model(**data)
        obj.clean()
        obj.save()
        return obj

    def id(self, data, reftag=None):
        if reftag == "ixlan":
            return data["ix"].id
        return None

    def status(self, data, reftag=None):
        return "ok"

    def address1(self, data, reftag=None):
        return "Address line 1"

    def address2(self, data, reftag=None):
        return "Address line 2"

    def state(self, data, reftag=None):
        return "Illinois"

    def zipcode(self, data, reftag=None):
        return "12345"

    def website(self, data, reftag=None):
        return "https://www.peeringdb.com"

    def social_media(self, data, reftag=None):
        return [{"service": "website", "identifier": "https://www.peeringdb.com"}]

    def notes(self, data, reftag=None):
        return "Some notes"

    def city(self, data, reftag=None):
        return "Chicago"

    def suite(self, data, reftag=None):
        return ""

    def floor(self, data, reftag=None):
        return ""

    def netixlan_updated(self, data, reftag=None):
        return None

    def poc_updated(self, data, reftag=None):
        return None

    def netfac_updated(self, data, reftag=None):
        return None

    def latitude(self, data, reftag=None):
        return 0.0

    def longitude(self, data, reftag=None):
        return 0.0

    def country(self, data, reftag=None):
        return "US"

    def name(self, data, reftag=None):
        return f"{reftag} {str(uuid.uuid4())[:8]}"

    def name_long(self, data, reftag=None):
        return self.name(data, reftag=reftag)

    def asn(self, data, reftag=None):
        if reftag == "netixlan":
            return data["network"].asn
        self._asn += 1
        return self._asn

    def aka(self, data, reftag=None):
        return self.name(data, reftag=reftag)

    def irr_as_set(self, data, reftag=None):
        return f"AS-{str(uuid.uuid4())[:8].upper()}@RIPE"

    def looking_glass(self, data, reftag=None):
        return f"{self.website(data, reftag=reftag)}/looking-glass"

    def route_server(self, data, reftag=None):
        return f"{self.website(data, reftag=reftag)}/route-server"

    def notes_private(self, data, reftag=None):
        return "Private notes"

    def info_types(self, data, reftag=None):
        return ["Content"]

    def info_prefixes4(self, data, reftag=None):
        return 50000

    def info_prefixes6(self, data, reftag=None):
        return 5000

    def clli(self, data, reftag=None):
        return str(uuid.uuid4())[:6].upper()

    def rencode(self, data, reftag=None):
        return ""

    def npanxx(self, data, reftag=None):
        return "123-456"

    def descr(self, data, reftag=None):
        return "Arbitrary description"

    def mtu(self, data, reftag=None):
        return 1500

    def vlan(self, data, reftag=None):
        return None

    def rs_asn(self, data, reftag=None):
        return self.asn(data, reftag=reftag)

    def local_asn(self, data, reftag=None):
        return data["network"].asn

    def arp_sponge(self, data, reftag=None):
        return None

    def prefix(self, data, reftag=None):
        if data.get("protocol") == "IPv4":
            return f"{self.prefix_pool_v4.pop()}"
        elif data.get("protocol") == "IPv6":
            return f"{self.prefix_pool_v6.pop()}"

    def ipaddr4(self, data, reftag=None):
        prefix = data["ixlan"].ixpfx_set.filter(protocol="IPv4").first().prefix
        return "{}".format(self.ipaddr_pool_v4[f"{prefix}"].pop())

    def ipaddr6(self, data, reftag=None):
        prefix = data["ixlan"].ixpfx_set.filter(protocol="IPv6").first().prefix
        return "{}".format(self.ipaddr_pool_v6[f"{prefix}"].pop())

    def speed(self, data, reftag=None):
        return 1000

    def ixf_net_count(self, data, reftag=None):
        return 0

    def ixf_last_import(self, data, reftag=None):
        return None

    def ixf_import_request(self, data, reftag=None):
        return None

    def ixf_import_request_status(self, data, reftag=None):
        return "queued"

    def ixf_import_request_user(self, data, reftag=None):
        return None

    def ix_count(self, data, reftag=None):
        return 0

    def fac_count(self, data, reftag=None):
        return 0

    def net_count(self, data, reftag=None):
        return 0

    def role(self, data, reftag=None):
        return "Abuse"

    def diverse_serving_substations(self, data, reftag=None):
        return False

    def available_voltage_services(self, data, reftag=None):
        return None

    def property(self, data, reftag=None):
        return None

    def flagged_date(self, data, reftag=None):
        return timezone.now()

    def flagged(self, data, reftag=None):
        return False

    def status_dashboard(self, data, reftag=None):
        return None

    def rir_status(self, data, reftag=None):
        return "assigned"

    def rir_status_updated(self, data, reftag=None):
        return None

    def periodic_reauth(self, data, reftag=None):
        return False

    def periodic_reauth_period(self, data, reftag=None):
        return "1y"

    def restrict_user_emails(self, data, reftag=None):
        return False

    def email_domains(self, data, reftag=None):
        return None

    def last_notified(self, data, reftag=None):
        return None
