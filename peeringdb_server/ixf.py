import json

import requests
import ipaddress

from django.db import transaction
from django.utils.translation import ugettext_lazy as _

import reversion

from peeringdb_server.models import (
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    Network,
    NetworkIXLan,
)


class Importer(object):

    allowed_member_types = ["peering",
                            "ixp",
                            "routeserver",
                            "probono",
                            ]
    allowed_states = ["",
                      None,
                      "active",
                      "inactive",
                      "connected",
                      "operational",
                      ]

    def __init__(self):
        self.reset()

    def reset(self, ixlan=None, save=False):
        self.reset_log()
        self.netixlans = []
        self.netixlans_deleted = []
        self.ipaddresses = []
        self.asns = []
        self.ixlan = ixlan
        self.save = save

    def fetch(self, url, timeout=5):
        """
        Retrieves ixf member export data from the url

        Will do a quick sanity check on the data

        Returns dict containing the parsed data.

        Arguments:
            - url <str>

        Keyword arguments:
            - timeout <float>: max time to spend on request
        """

        if not url:
            return {"pdb_error": _("IXF import url not specified")}

        try:
            result = requests.get(url, timeout=timeout)
        except Exception as exc:
            return {"pdb_error": exc}

        if result.status_code != 200:
            return {"pdb_error": "Got HTTP status {}".format(result.status_code)}

        try:
            data = result.json()
        except Exception as inst:
            data = {"pdb_error": _("No JSON could be parsed")}
            return data

        return self.sanitize(data)

    def sanitize(self, data):
        """
        Takes ixf data dict and runs some sanitization on it
        """

        invalid = None
        vlan_list_found = False

        # This fixes instances where ixps provide two separate entries for
        # vlans in vlan_list for ipv4 and ipv6 (AMS-IX for example)
        for member in data.get("member_list", []):
            asn = member.get("asnum")
            for conn in member.get("connection_list", []):
                vlans = conn.get("vlan_list", [])
                if not vlans:
                    continue
                vlan_list_found = True
                if len(vlans) == 2:
                    # if vlans[0].get("vlan_id") == vlans[1].get("vlan_id"):
                    keys = vlans[0].keys() + vlans[1].keys()
                    if keys.count("ipv4") == 1 and keys.count("ipv6") == 1:
                        vlans[0].update(**vlans[1])
                        conn["vlan_list"] = [vlans[0]]

        if not vlan_list_found:
            invalid = _("No entries in any of the vlan_list lists, aborting.")

        data["pdb_error"] = invalid

        return data

    def update(self, ixlan, save=True, data=None, timeout=5):
        """
        Sync netixlans under this ixlan from ixf member export json data (specs
        can be found at https://github.com/euro-ix/json-schemas)

        Arguments:
            - ixlan (IXLan): ixlan object to update from ixf

        Keyword Arguments:
            - save (bool): commit changes to db

        Returns:
            - Tuple(success<bool>, netixlans<list>, log<list>)
        """

        self.reset(ixlan=ixlan, save=save)

        if data is None:
            data = self.fetch(ixlan.ixf_ixp_member_list_url, timeout=timeout)

        # bail if there has been any errors during sanitize() or fetch()
        if data.get("pdb_error"):
            self.log_error(data.get("pdb_error"), save=save)
            return (False, [], [], self.log)

        # bail if there are no active prefixes on the ixlan
        if ixlan.ixpfx_set_active.count() == 0:
            self.log_error(_("No prefixes defined on ixlan"), save=save)
            return (False, [], [], self.log)

        try:
            # parse the ixf data
            self.parse(data)
        except KeyError as exc:
            # any key erros mean that the data is invalid, log the error and
            # bail (transactions are atomic and will be rolled back)
            self.log_error("Internal Error 'KeyError': {}".format(exc),
                           save=save)
            return (False, self.netixlans, [], self.log)

        # process any netixlans that need to be deleted
        self.process_deletions()

        # archive the import so we can roll it back later if needed
        self.archive()

        if save:
            self.save_log()

        return (True, self.netixlans, self.netixlans_deleted, self.log)

    @reversion.create_revision()
    def process_deletions(self):
        """
        Cycles all netixlans on the ixlan targeted by the importer and
        will remove any that are no longer found in the ixf data by
        their ip addresses

        In order for a netixlan to be removed both it's ipv4 and ipv6 address
        or it's asn need to be gone from the ixf data after validation
        """
        for netixlan in self.ixlan.netixlan_set_active:
            ipv4 = "{}-{}".format(netixlan.asn, netixlan.ipaddr4)
            ipv6 = "{}-{}".format(netixlan.asn, netixlan.ipaddr6)

            if netixlan.asn not in self.asns:
                self.log_peer(netixlan.asn, "delete",
                              _("ASN no longer in data"), netixlan)
                self.netixlans_deleted.append(netixlan)
                if self.save:
                    netixlan.delete()
            elif ipv4 not in self.ipaddresses and ipv6 not in self.ipaddresses:
                self.log_peer(netixlan.asn, "delete",
                              _("Ip addresses no longer exist in validated data or are "\
                                "no longer with this asn"), netixlan)
                self.netixlans_deleted.append(netixlan)
                if self.save:
                    netixlan.delete()
            elif ipv4 not in self.ipaddresses or ipv6 not in self.ipaddresses:
                if not netixlan.network.allow_ixp_update:
                    self.log_peer(netixlan.asn, "delete",
                                  _("At least one ipaddress mismatched and "\
                                    "network has disabled upates"), netixlan)
                    self.netixlans_deleted.append(netixlan)
                    if self.save:
                        netixlan.delete()


    @transaction.atomic()
    def archive(self):
        """
        Create the IXLanIXFMemberImportLog for this import
        """

        if self.save and (self.netixlans or self.netixlans_deleted):
            persist_log = IXLanIXFMemberImportLog.objects.create(
                ixlan=self.ixlan)
            for netixlan in self.netixlans + self.netixlans_deleted:
                versions = reversion.models.Version.objects.get_for_object(
                    netixlan)
                if len(versions) == 1:
                    version_before = None
                else:
                    version_before = versions[1]
                version_after = versions[0]
                persist_log.entries.create(netixlan=netixlan,
                                           version_before=version_before,
                                           version_after=version_after)

    def parse(self, data):
        """
        Parse ixf data

        Arguments:
            - data <dict>: result from fetch()
        """
        with transaction.atomic():
            self.parse_members(data.get("member_list", []))

    def parse_members(self, member_list):
        """
        Parse the `member_list` section of the ixf schema

        Arguments:
            - member_list <list>
        """
        for member in member_list:
            # we only process members of certain types
            member_type = member.get("member_type", "peering").lower()
            if member_type in self.allowed_member_types:
                # check that the as exists in pdb
                asn = member["asnum"]

                # keep track of asns we find in the ix-f data
                if asn not in self.asns:
                    self.asns.append(asn)

                if Network.objects.filter(asn=asn).exists():
                    network = Network.objects.get(asn=asn)
                    if network.status != "ok":
                        self.log_peer(
                            asn, "ignore",
                            _("Network status is '{}'").format(network.status))
                        continue

                    self.parse_connections(
                        member.get("connection_list", []), network, member)
                else:
                    self.log_peer(asn, "ignore",
                                  _("Network does not exist in peeringdb"))
            else:
                self.log_peer(asn, "ignore",
                              _("Invalid member type: {}").format(member_type))

    def parse_connections(self, connection_list, network, member):
        """
        Parse the 'connection_list' section of the ixf schema

        Arguments:
            - connection_list <list>
            - network <Network>: pdb network instance
            - member <dict>: row from ixf member_list
        """

        asn = member["asnum"]
        for connection in connection_list:
            state = connection.get("state", "active").lower()
            if state in self.allowed_states:

                speed = self.parse_speed(connection.get("if_list", []))

                self.parse_vlans(
                    connection.get("vlan_list", []), network, member,
                    connection, speed)
            else:
                self.log_peer(asn, "ignore",
                              _("Invalid connection state: {}").format(state))

    def parse_vlans(self, vlan_list, network, member, connection, speed):
        """
        Parse the 'vlan_list' section of the ixf_schema

        Arguments:
            - vlan_list <list>
            - network <Network>: pdb network instance
            - member <dict>: row from ixf member_list
            - connection <dict>: row from ixf connection_list
            - speed <int>: interface speed
        """

        asn = member["asnum"]
        for lan in vlan_list:
            ipv4_valid = False
            ipv6_valid = False

            ipv4 = lan.get("ipv4", {})
            ipv6 = lan.get("ipv6", {})

            # vlan entry has no ipaddresses set, log and ignore
            if not ipv4 and not ipv6:
                self.log_error(_("Could not find ipv4 or 6 address in " \
                              "vlan_list entry for vlan_id {} (AS{})").format(
                              lan.get("vlan_id"), asn))
                continue

            ipv4_addr = ipv4.get("address")
            ipv6_addr = ipv6.get("address")

            # parse and validate the ipaddresses attached to the vlan
            # append the ipaddresses to self.ipaddresses so we can
            # later check them to see which netixlans need to be
            # dropped during `process_deletions`
            try:
                if ipv4_addr:
                    self.ipaddresses.append("{}-{}".format(
                        asn, ipaddress.ip_address(unicode(ipv4_addr))))
                if ipv6_addr:
                    self.ipaddresses.append("{}-{}".format(
                        asn, ipaddress.ip_address(unicode(ipv6_addr))))
            except (ipaddress.AddressValueError, ValueError) as exc:
                self.log_error(
                    _("Ip address error '{}' in vlan_list entry for vlan_id {}"
                      ).format(exc, lan.get("vlan_id")))
                continue

            netixlan_info = NetworkIXLan(
                    ixlan=self.ixlan,
                    network=network,
                    ipaddr4=ipv4_addr,
                    ipaddr6=ipv6_addr,
                    speed=speed,
                    asn=asn,
                    is_rs_peer=(ipv4.get("routeserver", False) or \
                        ipv6.get("routeserver", False))
            )

            if not self.save and (not self.ixlan.test_ipv4_address(ipv4_addr) or not \
                self.ixlan.test_ipv6_address(ipv6_addr)):
                #for the preview we don't care at all about new ip addresses
                #not at the ixlan if they dont match the prefix
                continue


            # if connection state is inactive we won't create or update
            if connection.get("state", "active") == "inactive":
                self.log_peer(asn, "noop",
                              _("Connection is currently marked as inactive"),
                              netixlan_info)
                continue


            # after this point we either add or modify the netixlan, so
            # now is a good time to check if the related network allows
            # such updates, bail if not
            if not network.allow_ixp_update:
                self.log_peer(asn, "noop",
                              _("Network has disabled ixp updates"),
                              netixlan_info)
                continue


            # add / modify the netixlan
            result = self.ixlan.add_netixlan(netixlan_info, save=self.save,
                                             save_others=self.save)

            if result["netixlan"] and result["changed"]:
                self.netixlans.append(result["netixlan"])
                if result["created"]:
                    action = "add"
                else:
                    action = "modify"

                self.log_peer(asn, action, "", result["netixlan"])
            elif result["netixlan"]:
                self.log_peer(asn, "noop", "", result["netixlan"])
            elif result["log"]:
                self.log_peer(asn, "ignore", "\n".join(result["log"]),
                              netixlan_info)

    def parse_speed(self, if_list):
        """
        Parse speed from the 'if_list' section in the ixf data

        Arguments:
            - if_list <list>

        Returns:
            - speed <int>
        """
        speed = 0
        for iface in if_list:
            try:
                speed += int(iface.get("if_speed", 0))
            except ValueError:
                self.log_error(
                    _("Invalid speed value: {}").format(iface.get("if_speed")))
        return speed

    def save_log(self):
        """
        Save the attempt log
        """
        IXLanIXFMemberImportAttempt.objects.update_or_create(
            ixlan=self.ixlan,
            defaults={"info": "\n".join(json.dumps(self.log))})

    def reset_log(self):
        """
        Reset the attempt log
        """
        self.log = {"data": [], "errors": []}

    def log_peer(self, asn, action, reason, netixlan=None):
        """
        log peer action in attempt log

        Arguments:
            - asn <int>
            - action <str>: add | modify | delete | noop | ignore
            - reason <str>

        Keyrword Arguments:
            - netixlan <Netixlan>: if set, extra data will be added
                to the log.
        """
        peer = {
            "ixlan_id": self.ixlan.id,
            "asn": asn,
        }

        if netixlan:
            peer.update({
                "net_id": netixlan.network_id,
                "ipaddr4": u"{}".format(netixlan.ipaddr4 or ""),
                "ipaddr6": u"{}".format(netixlan.ipaddr6 or ""),
                "speed": netixlan.speed,
                "is_rs_peer": netixlan.is_rs_peer,
            })

        self.log["data"].append({
            "peer": peer,
            "action": action,
            "reason": u"{}".format(reason),
        })

    def log_error(self, error, save=False):
        """
        Append error to the attempt log
        """
        self.log["errors"].append(u"{}".format(error))
        if save:
            self.save_log()
