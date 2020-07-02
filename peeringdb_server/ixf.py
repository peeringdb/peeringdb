import json
import re

import requests
import ipaddress

from django.db import transaction
from django.core.cache import cache
from django.utils.translation import ugettext_lazy as _

import reversion

from peeringdb_server.models import (
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    Network,
    NetworkIXLan,
)


class Importer(object):

    allowed_member_types = [
        "peering",
        "ixp",
        "routeserver",
        "probono",
    ]
    allowed_states = [
        "",
        None,
        "active",
        "inactive",
        "connected",
        "operational",
    ]

    def __init__(self):
        self.cache_only = False
        self.skip_import = False
        self.reset()

    def reset(self, ixlan=None, save=False, asn=None):
        self.reset_log()
        self.netixlans = []
        self.netixlans_deleted = []
        self.ixf_ids = []
        self.asns = []
        self.archive_info = {}
        self.ixlan = ixlan
        self.save = save
        self.asn = asn

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

        data = self.sanitize(data)

        # locally cache result

        if data and not data.get("pdb_error"):
            cache.set(self.cache_key(url), data, timeout=None)

        return data

    def cache_key(self, url):
        """
        returns the django cache key to use for caching ix-f data

        Argument:

            url <str>
        """

        return "IXF-CACHE-{}".format(url)

    def fetch_cached(self, url):
        """
        Returns locally cached IX-F data

        Arguments:

            url <str>
        """

        if not url:
            return {"pdb_error": _("IXF import url not specified")}

        data = cache.get(self.cache_key(url))

        if data is None:
            return {
                "pdb_error": _("IX-F data not locally cached for this resource yet.")
            }

        return data

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
                    keys = list(vlans[0].keys()) + list(vlans[1].keys())
                    if keys.count("ipv4") == 1 and keys.count("ipv6") == 1:
                        vlans[0].update(**vlans[1])
                        conn["vlan_list"] = [vlans[0]]

        if not vlan_list_found:
            invalid = _("No entries in any of the vlan_list lists, aborting.")

        data["pdb_error"] = invalid

        return data

    def update(self, ixlan, save=True, data=None, timeout=5, asn=None):
        """
        Sync netixlans under this ixlan from ixf member export json data (specs
        can be found at https://github.com/euro-ix/json-schemas)

        Arguments:
            - ixlan (IXLan): ixlan object to update from ixf

        Keyword Arguments:
            - save (bool): commit changes to db
            - asn (int): only process changes for this ASN

        Returns:
            - Tuple(success<bool>, netixlans<list>, log<list>)
        """

        self.reset(ixlan=ixlan, save=save, asn=asn)

        # if data is not provided, retrieve it either from cache or
        # from the remote resource
        if data is None:
            if self.cache_only:
                data = self.fetch_cached(ixlan.ixf_ixp_member_list_url)
            else:
                data = self.fetch(ixlan.ixf_ixp_member_list_url, timeout=timeout)

        # bail if there has been any errors during sanitize() or fetch()
        if data.get("pdb_error"):
            self.log_error(data.get("pdb_error"), save=save)
            return (False, [], [], self.log)

        # bail if there are no active prefixes on the ixlan
        if ixlan.ixpfx_set_active.count() == 0:
            self.log_error(_("No prefixes defined on ixlan"), save=save)
            return (False, [], [], self.log)

        if self.skip_import:
            return (True, [], [], self.log)

        try:
            # parse the ixf data
            self.parse(data)
        except KeyError as exc:
            # any key erros mean that the data is invalid, log the error and
            # bail (transactions are atomic and will be rolled back)
            self.log_error("Internal Error 'KeyError': {}".format(exc), save=save)
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

        netixlan_qset = self.ixlan.netixlan_set_active

        # if we are only processing a specific asn ignore
        # all that dont match

        if self.asn:
            netixlan_qset = netixlan_qset.filter(asn=self.asn)

        for netixlan in netixlan_qset:
            if netixlan.ixf_id not in self.ixf_ids:
                ixf_member_data = IXFMemberData.instantiate(
                    netixlan.asn,
                    netixlan.ipaddr4,
                    netixlan.ipaddr6,
                    netixlan.ixlan
                )

                if netixlan.network.allow_ixp_updates:
                    self.log_apply(ixf_member_data.apply())

                else:
                    ixf_member_data.set_remove()


    @transaction.atomic()
    def archive(self):
        """
        Create the IXLanIXFMemberImportLog for this import
        """

        if self.save and (self.netixlans or self.netixlans_deleted):
            persist_log = IXLanIXFMemberImportLog.objects.create(ixlan=self.ixlan)
            for netixlan in self.netixlans + self.netixlans_deleted:
                versions = reversion.models.Version.objects.get_for_object(netixlan)
                if len(versions) == 1:
                    version_before = None
                else:
                    version_before = versions[1]
                version_after = versions[0]
                info = self.archive_info.get(netixlan.id, {})
                persist_log.entries.create(
                    netixlan=netixlan,
                    version_before=version_before,
                    action=info.get("action"),
                    reason=info.get("reason"),
                    version_after=version_after,
                )

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

                # if we are only processing a specific asn, ignore all
                # that dont match
                if self.asn and asn != self.asn:
                    continue

                # keep track of asns we find in the ix-f data
                if asn not in self.asns:
                    self.asns.append(asn)

                if Network.objects.filter(asn=asn).exists():
                    network = Network.objects.get(asn=asn)
                    if network.status != "ok":
                        self.log_peer(
                            asn,
                            "ignore",
                            _("Network status is '{}'").format(network.status),
                        )
                        continue

                    self.parse_connections(
                        member.get("connection_list", []), network, member
                    )
                else:
                    self.log_peer(
                        asn, "ignore", _("Network does not exist in peeringdb")
                    )
            else:
                self.log_peer(
                    asn, "ignore", _("Invalid member type: {}").format(member_type)
                )

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
                    connection.get("vlan_list", []), network, member, connection, speed
                )
            else:
                self.log_peer(
                    asn, "ignore", _("Invalid connection state: {}").format(state)
                )

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
                self.log_error(
                    _(
                        "Could not find ipv4 or 6 address in "
                        "vlan_list entry for vlan_id {} (AS{})"
                    ).format(lan.get("vlan_id"), asn)
                )
                continue

            ipv4_addr = ipv4.get("address")
            ipv6_addr = ipv6.get("address")

            # parse and validate the ipaddresses attached to the vlan
            # append a unqiue ixf identifier to self.ixf_ids
            #
            # identifier is a tuple of (asn, ip4, ip6)
            #
            # we will later check them to see which netixlans need to be
            # dropped during `process_deletions`
            try:
                ixf_id = [asn]

                if ipv4_addr:
                    ixf_id.append(ipaddress.ip_address(f"{ipv4_addr}"))
                else:
                    ixf_id.append(None)

                if ipv6_addr:
                    ixf_id.append(ipaddress.ip_address(f"{ipv6_addr}"))
                else:
                    ixf_id.append(None)

                ixf_id = tuple(ixf_id)
                self.ixf_ids.append(ixf_id)

            except (ipaddress.AddressValueError, ValueError) as exc:
                self.log_error(
                    _("Ip address error '{}' in vlan_list entry for vlan_id {}").format(
                        exc, lan.get("vlan_id")
                    )
                )
                continue

            if not self.save and (
                not self.ixlan.test_ipv4_address(ipv4_addr)
                and not self.ixlan.test_ipv6_address(ipv6_addr)
            ):
                # for the preview we don't care at all about new ip addresses
                # not at the ixlan if they dont match the prefix
                continue

            if connection.get("state", "active") == "inactive":
                is_operational = False
            else:
                is_operational = True

            is_rs_peer = (
                ipv4.get("routeserver", False) or ipv6.get("routeserver", False)
            )

            ixf_member_data = IXFMemberData.instantiate(
                asn,
                ipv4_addr,
                ipv6_addr,
                speed=speed,
                is_operational=is_operational,
                is_rs_peer=is_rs_peer,
                data=json.dumps(member),
                ixlan=self.ixlan,
            )

            self.apply_add_or_update(ixf_member_data)


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
                    _("Invalid speed value: {}").format(iface.get("if_speed"))
                )
        return speed


    def apply_add_or_update(self, ixf_member_data):

        if ixf_member_data.netixlan.id:

            # importer-protocol: netixlan exists

            if not ifx_member_data.changes:

                # importer-protocol: no changes

                self.resolve(ixf_member_data)

            else:

                # importer-protocol: data changes

                self.apply_update(ixf_member_data)

        else:

            # importer-protocol: netixlan does not exist

            self.apply_add(ixf_member_data)


    def resolve(self, ixf_member_data):
        ixf_member_data.set_resolved()


    def apply_update(self, ixf_member_data):

        if ixf_member_data.net.allow_ixp_updates:
            try:
                self.log_apply(ixf_member_data.apply())
            except ValidationError as exc:
                ixf_member_data.set_conflict(error=exc)
        else:
            ixf_member_data.set_update()


    def apply_add(self, ixf_member_data):

        if ixf_member_data.net.allow_ixp_updates:

            try:
                self.log_apply(ixf_member_data.apply())
            except ValidationError as exc:
                ixf_member_data.set_conflict(error=exc)

        else:
            ixf_member_data.set_add()



    def save_log(self):
        """
        Save the attempt log
        """
        IXLanIXFMemberImportAttempt.objects.update_or_create(
            ixlan=self.ixlan, defaults={"info": "\n".join(json.dumps(self.log))}
        )

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
            "ix_id": self.ixlan.ix.id,
            "ix_name": self.ixlan.ix.name,
            "asn": asn,
        }

        if netixlan:
            peer.update(
                {
                    "net_id": netixlan.network_id,
                    "ipaddr4": "{}".format(netixlan.ipaddr4 or ""),
                    "ipaddr6": "{}".format(netixlan.ipaddr6 or ""),
                    "speed": netixlan.speed,
                    "is_rs_peer": netixlan.is_rs_peer,
                }
            )

            if netixlan.id:
                self.archive_info[netixlan.id] = {
                    "action": action,
                    "reason": "{}".format(reason),
                }

        self.log["data"].append(
            {"peer": peer, "action": action, "reason": "{}".format(reason),}
        )


    def log_error(self, error, save=False):
        """
        Append error to the attempt log
        """
        self.log["errors"].append("{}".format(error))
        if save:
            self.save_log()


class PostMortem(object):

    """
    Generate postmortem report for ix-f import
    """

    def reset(self, asn, **kwargs):

        """
        Reset for a fresh run

        Argument(s):

            - asn <int>: asn of the network to run postormem
              report for

        Keyword Argument(s):

            - limit <int=100>: limit amount of import logs to process
              max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

        """

        self.asn = asn
        self.limit = kwargs.get("limit", 100)
        self.post_mortem = []

    def generate(self, asn, **kwargs):
        """
        Generate and return a new postmortem report

        Argument(s):

            - asn <int>: asn of the network to run postmortem
              report for

        Keyword Argument(s):

            - limit <int=100>: limit amount of import logs to process
              max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

        Returns:

            - dict: postmortem report
        """

        self.reset(asn, **kwargs)
        self._process_logs(limit=self.limit)
        return self.post_mortem

    def _process_logs(self, limit=100):

        """
        Process IX-F import logs

        KeywordArgument(s):

             - limit <int=100>: limit amount of import logs to process
              max limit is defined by server config `IXF_POSTMORTEM_LIMIT`
        """

        # we only want import logs that actually touched the specified
        # asn

        qset = IXLanIXFMemberImportLogEntry.objects.filter(netixlan__asn=self.asn)
        qset = qset.exclude(action__isnull=True)
        qset = qset.order_by("-log__created")
        qset = qset.select_related("log", "netixlan", "log__ixlan", "log__ixlan__ix")

        for entry in qset[:limit]:
            self._process_log_entry(entry.log, entry)

    def _process_log_entry(self, log, entry):

        """
        Process a single IX-F import log entry

        Argument(s):

            - log <IXLanIXFMemberImportLog>
            - entry <IXLanIXFMemberImportLogEntry>

        """

        if entry.netixlan.asn != self.asn:
            return

        data = entry.version_after.field_dict
        if data.get("asn") != self.asn:
            return

        if data.get("ipaddr4"):
            ipaddr4 = "{}".format(data.get("ipaddr4"))
        else:
            ipaddr4 = None

        if data.get("ipaddr6"):
            ipaddr6 = "{}".format(data.get("ipaddr6"))
        else:
            ipaddr6 = None

        self.post_mortem.append(
            {
                "ix_id": log.ixlan.ix.id,
                "ix_name": log.ixlan.ix.name,
                "ixlan_id": log.ixlan.id,
                "changes": entry.changes,
                "reason": entry.reason,
                "action": entry.action,
                "asn": data.get("asn"),
                "ipaddr4": ipaddr4,
                "ipaddr6": ipaddr6,
                "speed": data.get("speed"),
                "is_rs_peer": data.get("is_rs_peer"),
                "created": log.created.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
