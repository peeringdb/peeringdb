import json
import re
import datetime

import requests
import ipaddress

from django.db import transaction
from django.core.cache import cache
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError
from django.conf import settings

import reversion

from peeringdb_server.models import (
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    Network,
    NetworkIXLan,
    IXFMemberData,
)

REASON_ENTRY_GONE_FROM_REMOTE = _(
    "The entry for (asn and IPv4 and IPv6) does not exist "
    "in the exchange's IX-F data as a singular member connection"
)

REASON_NEW_ENTRY = _(
    "The entry for (asn and IPv4 and IPv6) does not exist "
    "in PeeringDB as a singular network -> ix connection"
)

REASON_VALUES_CHANGED = _(
    "Data differences between PeeringDB and the exchange's IX-F data"
)


class Importer:

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
        self.ixf_ids = []
        self.actions_taken = {
            "add": [],
            "delete": [],
            "modify": [],
            "noop": [],
        }
        self.pending_save = []
        self.asns = []
        self.ixlan = ixlan
        self.save = save
        self.asn = asn
        self.now = datetime.datetime.now(datetime.timezone.utc)
        self.invalid_ip_errors = []

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
            return {"pdb_error": f"Got HTTP status {result.status_code}"}

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

        return f"IXF-CACHE-{url}"

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
            self.notify_error(data.get("pdb_error"))
            self.log_error(data.get("pdb_error"), save=save)
            return False

        # null ix-f error note on ixlan if it had error'd before
        if self.ixlan.ixf_ixp_import_error:
            self.ixlan.ixf_ixp_import_error = None
            self.ixlan.save()

        # bail if there are no active prefixes on the ixlan
        if ixlan.ixpfx_set_active.count() == 0:
            self.log_error(_("No prefixes defined on ixlan"), save=save)
            return False

        if self.skip_import:
            self.cleanup_ixf_member_data()
            return True

        try:
            # parse the ixf data
            self.parse(data)
        except KeyError as exc:
            # any key erros mean that the data is invalid, log the error and
            # bail (transactions are atomic and will be rolled back)
            self.log_error(f"Internal Error 'KeyError': {exc}", save=save)
            return False

        # process any netixlans that need to be deleted
        self.process_deletions()

        # process creation of new netixlans and updates
        # of existing netixlans. This needs to happen
        # after process_deletions in order to avoid potential
        # ip conflicts
        self.process_saves()

        self.cleanup_ixf_member_data()

        # archive the import so we can roll it back later if needed
        self.archive()

        if self.invalid_ip_errors:
            self.notify_error("\n".join(self.invalid_ip_errors))

        if save:

            # update exchange's ixf fields
            self.update_ix()

            self.save_log()

        return True

    @reversion.create_revision()
    def update_ix(self):

        """
        Will see if any data was changed during this import
        and update the exchange's ixf_last_import timestamp
        if so

        Also will set the ixf_net_count value if it has changed
        from before
        """

        ix = self.ixlan.ix
        save_ix = False

        ixf_member_data_changed = IXFMemberData.objects.filter(
            updated__gte=self.now, ixlan=self.ixlan
        ).exists()

        netixlan_data_changed = NetworkIXLan.objects.filter(
            updated__gte=self.now, ixlan=self.ixlan
        ).exists()

        if ixf_member_data_changed or netixlan_data_changed:
            ix.ixf_last_import = self.now
            save_ix = True

        ixf_net_count = len(self.pending_save)
        if ixf_net_count != ix.ixf_net_count:
            ix.ixf_net_count = ixf_net_count
            save_ix = True

        if save_ix:
            ix.save()

    @reversion.create_revision()
    def process_saves(self):
        for ixf_member in self.pending_save:
            self.apply_add_or_update(ixf_member)

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
                    netixlan.ixlan,
                    data={},
                )

                if netixlan.network.allow_ixp_update:
                    self.log_apply(
                        ixf_member_data.apply(save=self.save),
                        reason=REASON_ENTRY_GONE_FROM_REMOTE,
                    )
                else:
                    ixf_member_data.set_remove(
                        save=self.save, reason=REASON_ENTRY_GONE_FROM_REMOTE
                    )
                    self.log_ixf_member_data(ixf_member_data)

    def cleanup_ixf_member_data(self):

        # clean up old ix-f memeber data objects

        for ixf_member in IXFMemberData.objects.filter(ixlan=self.ixlan):

            # proposed deletion got fulfilled

            if ixf_member.action == "delete":
                if ixf_member.netixlan.status == "deleted":
                    ixf_member.set_resolved()

            # noop means the ask has been fulfilled but the
            # ixf member data entry has not been set to resolved yet

            elif ixf_member.action == "noop":
                ixf_member.set_resolved()

            # proposed change / addition is now gone from
            # ix-f data

            elif not self.skip_import and ixf_member.ixf_id not in self.ixf_ids:
                if ixf_member.action in ["add", "modify"]:
                    ixf_member.set_resolved()

    @transaction.atomic()
    def archive(self):
        """
        Create the IXLanIXFMemberImportLog for this import
        """

        if not self.save:
            return

        persist_log = IXLanIXFMemberImportLog.objects.create(ixlan=self.ixlan)
        for action in ["delete", "modify", "add"]:
            for info in self.actions_taken[action]:

                netixlan = info["netixlan"]
                version_before = info["version"]

                versions = reversion.models.Version.objects.get_for_object(netixlan)

                if version_before:
                    versions = versions.filter(id__gt=version_before.id)
                    version_after = versions.last()
                else:
                    version_after = versions.first()

                if not version_after:
                    continue

                persist_log.entries.create(
                    netixlan=netixlan,
                    version_before=version_before,
                    action=action,
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
            self.connection_errors = []
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
                self.invalid_ip_errors.append(f"{exc}")
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
                operational = False
            else:
                operational = True

            is_rs_peer = ipv4.get("routeserver", False) or ipv6.get(
                "routeserver", False
            )

            ixf_member_data = IXFMemberData.instantiate(
                asn,
                ipv4_addr,
                ipv6_addr,
                speed=speed,
                operational=operational,
                is_rs_peer=is_rs_peer,
                data=json.dumps(member),
                ixlan=self.ixlan,
                save=self.save,
            )

            if self.connection_errors:
                ixf_member_data.error = "\n".join(self.connection_errors)
            else:
                ixf_member_data.error = ixf_member_data.previous_error

            self.pending_save.append(ixf_member_data)

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
                log_msg = _("Invalid speed value: {}").format(iface.get("if_speed"))
                self.log_error(log_msg)
                self.connection_errors.append(log_msg)
        return speed

    def apply_add_or_update(self, ixf_member_data):

        if ixf_member_data.netixlan_exists:

            # importer-protocol: netixlan exists

            if not ixf_member_data.changes:

                # importer-protocol: no changes

                self.resolve(ixf_member_data)

            else:

                # importer-protocol: data changes

                self.apply_update(ixf_member_data)

        else:

            # importer-protocol: netixlan does not exist

            self.apply_add(ixf_member_data)

    def resolve(self, ixf_member_data):
        ixf_member_data.set_resolved(save=self.save)

    def apply_update(self, ixf_member_data):
        changed_fields = ", ".join(ixf_member_data.changes.keys())
        reason = f"{REASON_VALUES_CHANGED}: {changed_fields}"

        if ixf_member_data.net.allow_ixp_update:
            try:
                self.log_apply(ixf_member_data.apply(save=self.save), reason=reason)
            except ValidationError as exc:
                ixf_member_data.set_conflict(error=exc, save=self.save)
        else:
            ixf_member_data.set_update(
                save=self.save, reason=reason,
            )
            self.log_ixf_member_data(ixf_member_data)

    def apply_add(self, ixf_member_data):

        if ixf_member_data.net.allow_ixp_update:

            try:
                self.log_apply(
                    ixf_member_data.apply(save=self.save), reason=REASON_NEW_ENTRY
                )
            except ValidationError as exc:
                ixf_member_data.set_conflict(error=exc, save=self.save)

        else:
            ixf_member_data.set_add(save=self.save, reason=REASON_NEW_ENTRY)
            self.log_ixf_member_data(ixf_member_data)

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

    def log_apply(self, apply_result, reason=""):

        netixlan = apply_result["netixlan"]
        self.actions_taken[apply_result["action"]].append(
            {
                "netixlan": netixlan,
                "version": reversion.models.Version.objects.get_for_object(
                    netixlan
                ).first(),
                "reason": reason,
            }
        )

        return self.log_peer(
            netixlan.asn, apply_result["action"], reason, netixlan=netixlan
        )

    def log_ixf_member_data(self, ixf_member_data):
        return self.log_peer(
            ixf_member_data.net.asn,
            f"suggest-{ixf_member_data.action}",
            ixf_member_data.reason,
            netixlan=ixf_member_data,
        )

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

            if hasattr(netixlan, "network_id"):
                net_id = netixlan.network_id
            else:
                net_id = netixlan.net.id

            peer.update(
                {
                    "net_id": net_id,
                    "ipaddr4": "{}".format(netixlan.ipaddr4 or ""),
                    "ipaddr6": "{}".format(netixlan.ipaddr6 or ""),
                    "speed": netixlan.speed,
                    "is_rs_peer": netixlan.is_rs_peer,
                    "operational": netixlan.operational,
                }
            )

        self.log["data"].append(
            {"peer": peer, "action": action, "reason": f"{reason}",}
        )

    def notify_error(self, error):
        now = datetime.datetime.now(datetime.timezone.utc)
        notified = self.ixlan.ixf_ixp_import_error_notified
        prev_error = self.ixlan.ixf_ixp_import_error

        if notified:
            diff = (now - notified).total_seconds() / 3600
            if diff < settings.IXF_PARSE_ERROR_NOTIFICATION_PERIOD:
                return

        self.ixlan.ixf_ixp_import_error_notified = now
        self.ixlan.ixf_ixp_import_error = error
        self.ixlan.save()

        ixf_member_data = IXFMemberData(ixlan=self.ixlan, asn=0)
        ixf_member_data._notify(
            "email/notify-ixf-source-error.txt",
            "Could not process IX-F Data",
            context={"error": error, "dt": now},
            save=False,
            ix=True,
            ac=True,
        )

    def log_error(self, error, save=False):
        """
        Append error to the attempt log
        """
        self.log["errors"].append(f"{error}")
        if save:
            self.save_log()


class PostMortem:

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
        qset = qset.order_by("-log__created", "-id")
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
