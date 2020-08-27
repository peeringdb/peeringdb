import json
import re
import datetime

import requests
import ipaddress

from django.db import transaction
from django.core.cache import cache
from django.core.mail.message import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError
from django.template import loader
from django.conf import settings

import reversion

from peeringdb_server.models import (
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    Network,
    NetworkIXLan,
    IXFMemberData,
    NetworkProtocolsDisabled,
    User,
    DeskProTicket,
    EnvironmentSetting,
    debug_mail,
    IXFImportEmail,
    ValidationErrorEncoder,
)
import peeringdb_server.deskpro as deskpro

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

    @property
    def ticket_user(self):
        """
        Returns the User instance for the user to use
        to create DeskPRO tickets
        """
        if not hasattr(self, "_ticket_user"):
            self._ticket_user = User.objects.get(username="ixf_importer")
        return self._ticket_user

    @property
    def deskpro_client(self):
        if not hasattr(self, "_deskpro_client"):
            if settings.IXF_SEND_TICKETS:
                cls = deskpro.APIClient
            else:
                cls = deskpro.MockAPIClient

            self._deskpro_client = cls(settings.DESKPRO_URL, settings.DESKPRO_KEY)
        return self._deskpro_client

    @property
    def tickets_enabled(self):
        """
        Returns whether or not deskpr ticket creation for ix-f
        conflicts are enabled or not

        This can be controlled by the IXF_TICKET_ON_CONFLICT
        setting
        """

        return getattr(settings, "IXF_TICKET_ON_CONFLICT", True)

    @property
    def notify_ix_enabled(self):
        """
        Returns whether or not notifications to the exchange
        are enabled.

        This can be controlled by the IXF_NOTIFY_IX_ON_CONFLICT
        setting
        """

        return getattr(settings, "IXF_NOTIFY_IX_ON_CONFLICT", False)

    @property
    def notify_net_enabled(self):
        """
        Returns whether or not notifications to the network
        are enabled.

        This can be controlled by the IXF_NOTIFY_NET_ON_CONFLICT
        setting
        """

        return getattr(settings, "IXF_NOTIFY_NET_ON_CONFLICT", False)

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
        self.deletions = {}
        self.asns = []
        self.ixlan = ixlan
        self.save = save
        self.asn = asn
        self.now = datetime.datetime.now(datetime.timezone.utc)
        self.invalid_ip_errors = []
        self.notifications = []
        self.protocol_conflict = 0
        self.emails = 0

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

    def sanitize_vlans(self, vlans):
        """
        Sanitize vlan lists where ip 4 and 6 addresses
        for the same vlan (determined by vlan id) exist
        in separate entries by combining those
        list entries to one
        """

        _vlans = {}
        sanitized = []

        for vlan in vlans:

            # if the vlan_id is not specified we want
            # to default to 0 so we can still group based
            # on that

            id = vlan.get("vlan_id", 0)

            # neither ipv4 nor ipv6 is specified, there is
            # nothing to sanitize here, so skip

            if "ipv4" not in vlan and "ipv6" not in vlan:
                continue

            if id not in _vlans:

                # first occurance of vlan id gets appended
                # as is

                _vlans[id] = [vlan]
            else:

                # additional occurances of vlan id get checked
                # on whether or not they will fill in a missing
                # ipv4 or ipv6 address, and if so will update
                # the existing vlan entry.
                #
                # otherwise append as a new entry for that vlan id

                current = _vlans[id][-1]

                update = None

                if "ipv4" in vlan and "ipv4" not in current:
                    update = "ipv4"
                elif "ipv6" in vlan and "ipv6" not in current:
                    update = "ipv6"

                if update:
                    current[update] = vlan[update]
                else:
                    _vlans[id].append(vlan)

        for vlan_id, entries in _vlans.items():
            sanitized.extend(entries)

        return sanitized

    def sanitize(self, data):
        """
        Takes ixf data dict and runs some sanitization on it
        """

        invalid = None
        vlan_list_found = False
        ipv4_addresses = {}
        ipv6_addresses = {}

        # dedupe identical entries in member list
        member_list = [json.dumps(m) for m in data.get("member_list", [])]
        member_list = [json.loads(m) for m in set(member_list)]

        # This fixes instances where ixps provide two separate entries for
        # vlans in vlan_list for ipv4 and ipv6 (AMS-IX for example)
        for member in member_list:
            asn = member.get("asnum")
            for conn in member.get("connection_list", []):

                conn["vlan_list"] = self.sanitize_vlans(conn.get("vlan_list", []))
                vlans = conn["vlan_list"]

                if not vlans:
                    continue
                vlan_list_found = True

                # de-dupe reoccurring ipv4 / ipv6 addresses

                ipv4 = vlans[0].get("ipv4", {}).get("address")
                ipv6 = vlans[0].get("ipv6", {}).get("address")

                ixf_id = (asn, ipv4, ipv6)

                if ipv4 and ipv4 in ipv4_addresses:
                    invalid = _(
                        "Address {} assigned to more than one distinct connection"
                    ).format(ipv4)
                    break

                ipv4_addresses[ipv4] = ixf_id

                if ipv6 and ipv6 in ipv6_addresses:
                    invalid = _(
                        "Address {} assigned to more than one distinct connection"
                    ).format(ipv6)
                    break

                ipv6_addresses[ipv6] = ixf_id

        if not vlan_list_found:
            invalid = _("No entries in any of the vlan_list lists, aborting.")

        data["pdb_error"] = invalid

        # set member_list to the sanitized copy
        data["member_list"] = member_list

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
            self.ixlan.ixf_ixp_import_error_notified = None
            self.ixlan.save()

        # bail if there are no active prefixes on the ixlan
        if ixlan.ixpfx_set_active.count() == 0:
            self.log_error(_("No prefixes defined on ixlan"), save=save)
            return False

        if self.skip_import:
            return True

        try:
            # parse the ixf data
            self.parse(data)
        except KeyError as exc:
            # any key erros mean that the data is invalid, log the error and
            # bail (transactions are atomic and will be rolled back)
            self.log_error(f"Internal Error 'KeyError': {exc}", save=save)
            return False

        with transaction.atomic():
            # process any netixlans that need to be deleted
            self.process_deletions()

            # process creation of new netixlans and updates
            # of existing netixlans. This needs to happen
            # after process_deletions in order to avoid potential
            # ip conflicts
            self.process_saves()

        self.cleanup_ixf_member_data()

        # create tickets for unresolved proposals

        self.ticket_aged_proposals()

        # archive the import so we can roll it back later if needed
        self.archive()

        if self.invalid_ip_errors:
            self.notify_error("\n".join(self.invalid_ip_errors))

        if save:

            # update exchange's ixf fields
            self.update_ix()

            if (
                not self.protocol_conflict
                and self.ixlan.ixf_ixp_import_protocol_conflict
            ):
                self.ixlan.ixf_ixp_import_protocol_conflict = 0
                self.ixlan.save()

            self.save_log()

        return True

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

        ix.ixf_last_import = self.now

        ixf_net_count = len(self.pending_save)
        if ixf_net_count != ix.ixf_net_count:
            ix.ixf_net_count = ixf_net_count

        # we do not want these updates to affect the
        # exchanges `updated` timestamp as per #812
        # so we temporarily disable auto_now

        ix._meta.get_field("updated").auto_now = False
        try:
            with reversion.create_revision():
                ix.save()
        finally:

            # always turn auto_now back on afterwards

            ix._meta.get_field("updated").auto_now = True

    def fix_consolidated_modify(self, ixf_member_data):
        """
        fix consolidated modify (#770) to retain value
        for speed and is_rs_peer (#793)
        """

        for other in self.pending_save:
            if other.asn == ixf_member_data.asn:
                if (
                    other.init_ipaddr4
                    and other.init_ipaddr4 == ixf_member_data.init_ipaddr4
                ) or (
                    other.init_ipaddr6
                    and other.init_ipaddr6 == ixf_member_data.init_ipaddr6
                ):

                    if not other.modify_speed:
                        other.speed = ixf_member_data.speed

                    if not other.modify_is_rs_peer:
                        other.is_rs_peer = ixf_member_data.is_rs_peer

                    break

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
                    speed=netixlan.speed,
                    operational=netixlan.operational,
                    is_rs_peer=netixlan.is_rs_peer,
                    delete=True,
                    data={},
                )

                # fix consolidated modify (#770) to retain values
                # for speed and is_rs_peer (#793)
                self.fix_consolidated_modify(ixf_member_data)

                self.deletions[ixf_member_data.ixf_id] = ixf_member_data
                if netixlan.network.allow_ixp_update:
                    self.log_apply(
                        ixf_member_data.apply(save=self.save),
                        reason=REASON_ENTRY_GONE_FROM_REMOTE,
                    )
                else:
                    notify = ixf_member_data.set_remove(
                        save=self.save, reason=REASON_ENTRY_GONE_FROM_REMOTE
                    )
                    if notify:
                        self.queue_notification(ixf_member_data, "remove")
                    self.log_ixf_member_data(ixf_member_data)

    def cleanup_ixf_member_data(self):

        if not self.save:

            """
            In some cases you dont want to run a cleanup process
            For example when the importer runs in preview mode
            triggered by a network admin
            """

            return

        qset = IXFMemberData.objects.filter(ixlan=self.ixlan)

        if self.asn:

            # if we are only processing for a specified asn
            # we only clean up member data for that asn

            qset = qset.filter(asn=self.asn)

        # clean up old ix-f memeber data objects

        for ixf_member in qset:

            # proposed deletion got fulfilled

            if ixf_member.action == "delete":
                if ixf_member.netixlan.status == "deleted":
                    if ixf_member.set_resolved(save=self.save):
                        self.queue_notification(ixf_member, "resolved")

            # noop means the ask has been fulfilled but the
            # ixf member data entry has not been set to resolved yet

            elif ixf_member.action == "noop":
                if (
                    ixf_member.set_resolved(save=self.save)
                    and not ixf_member.requirement_of
                ):
                    self.queue_notification(ixf_member, "resolved")

            # proposed change / addition is now gone from
            # ix-f data

            elif not self.skip_import and ixf_member.ixf_id not in self.ixf_ids:
                if ixf_member.action in ["add", "modify"]:
                    if ixf_member.set_resolved(save=self.save):
                        self.queue_notification(ixf_member, "resolved")

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

            self.connection_errors = {}
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

            ipv4_support = network.ipv4_support
            ipv6_support = network.ipv6_support

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
                    ipv4_addr = ipaddress.ip_address(f"{ipv4_addr}")
                    ixf_id.append(ipv4_addr)
                else:
                    ixf_id.append(None)

                if ipv6_addr:
                    ipv6_addr = ipaddress.ip_address(f"{ipv6_addr}")
                    ixf_id.append(ipv6_addr)
                else:
                    ixf_id.append(None)

                ixf_id = tuple(ixf_id)

            except (ipaddress.AddressValueError, ValueError) as exc:
                self.invalid_ip_errors.append(f"{exc}")
                self.log_error(
                    _("Ip address error '{}' in vlan_list entry for vlan_id {}").format(
                        exc, lan.get("vlan_id")
                    )
                )
                continue

            ipv4_valid_for_ixlan = self.ixlan.test_ipv4_address(ipv4_addr)
            ipv6_valid_for_ixlan = self.ixlan.test_ipv6_address(ipv6_addr)

            if (
                ipv4_addr
                and not ipv4_valid_for_ixlan
                and ipv6_addr
                and not ipv6_valid_for_ixlan
            ):
                # neither ipaddress falls into address space
                # for this ixlan, ignore

                continue

            elif not ipv4_valid_for_ixlan and not ipv6_addr:

                # ipv4 address does not fall into address space
                # and ipv6 is not provided, ignore

                continue

            elif not ipv6_valid_for_ixlan and not ipv4_addr:

                # ipv6 address does not fall into address space
                # and ipv4 is not provided, ignore

                continue

            protocol_conflict = 0

            # keep track of conflicts between ix/net in terms of ip
            # protocols supported.

            if ipv4_addr and not ipv4_support:
                protocol_conflict = 4
            elif ipv6_addr and not ipv6_support:
                protocol_conflict = 6

            if protocol_conflict and not self.protocol_conflict:
                self.protocol_conflict = protocol_conflict

            if protocol_conflict and not self.ixlan.ixf_ixp_import_protocol_conflict:
                self.ixlan.ixf_ixp_import_protocol_conflict = protocol_conflict

                if self.save:
                    self.ixlan.save()

                self.queue_notification(
                    IXFMemberData.instantiate(
                        asn,
                        ipv4_addr,
                        ipv6_addr,
                        ixlan=self.ixlan,
                        save=False,
                        validate_network_protocols=False,
                    ),
                    "protocol-conflict",
                    ac=False,
                    net=True,
                    ix=True,
                    ipaddr4=ipv4_addr,
                    ipaddr6=ipv6_addr,
                )

            self.ixf_ids.append(ixf_id)

            if not network.ipv6_support:
                self.ixf_ids.append((asn, ixf_id[1], None))
                netixlan = NetworkIXLan.objects.filter(
                    status="ok", ipaddr4=ixf_id[1]
                ).first()
                if netixlan:
                    self.ixf_ids.append((asn, ixf_id[1], netixlan.ipaddr6))

            if not network.ipv4_support:
                self.ixf_ids.append((asn, None, ixf_id[2]))
                netixlan = NetworkIXLan.objects.filter(
                    status="ok", ipaddr6=ixf_id[2]
                ).first()
                if netixlan:
                    self.ixf_ids.append((asn, netixlan.ipaddr4, ixf_id[2]))

            if connection.get("state", "active") == "inactive":
                operational = False
            else:
                operational = True

            if "routeserver" not in ipv4 and "routeserver" not in ipv6:
                is_rs_peer = None
            else:
                is_rs_peer = ipv4.get("routeserver", ipv6.get("routeserver"))

            try:
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

                if not ixf_member_data.ipaddr4 and not ixf_member_data.ipaddr6:
                    continue

            except NetworkProtocolsDisabled as exc:
                self.log_error(f"{exc}")
                continue

            if self.connection_errors:
                ixf_member_data.error = json.dumps(
                    self.connection_errors, cls=ValidationErrorEncoder
                )
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
            except (ValueError, AttributeError):
                try:
                    log_msg = _("Invalid speed value: {}").format(iface.get("if_speed"))
                except AttributeError:
                    log_msg = _("Invalid speed value: could not be parsed")
                self.log_error(log_msg)
                if "speed" not in self.connection_errors:
                    self.connection_errors["speed"] = []
                self.connection_errors["speed"].append(log_msg)
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

    def queue_notification(
        self, ixf_member_data, typ, ac=True, ix=True, net=True, **context
    ):
        self.notifications.append(
            {
                "ixf_member_data": ixf_member_data,
                "ac": ac,
                "ix": ix,
                "net": net,
                "typ": typ,
                "action": ixf_member_data.action,
                "context": context,
            }
        )

    def resolve(self, ixf_member_data):
        if ixf_member_data.set_resolved(save=self.save):
            self.queue_notification(ixf_member_data, "resolved")

    def apply_update(self, ixf_member_data):
        changed_fields = ", ".join(ixf_member_data.changes.keys())
        reason = f"{REASON_VALUES_CHANGED}: {changed_fields}"

        if ixf_member_data.net.allow_ixp_update:
            try:
                self.log_apply(ixf_member_data.apply(save=self.save), reason=reason)
            except ValidationError as exc:
                if ixf_member_data.set_conflict(error=exc, save=self.save):
                    self.queue_notification(ixf_member_data, ixf_member_data.action)
        else:
            notify = ixf_member_data.set_update(save=self.save, reason=reason,)
            if notify:
                self.queue_notification(ixf_member_data, "modify")
            self.log_ixf_member_data(ixf_member_data)

    def apply_add(self, ixf_member_data):

        if ixf_member_data.net.allow_ixp_update:

            try:
                self.log_apply(
                    ixf_member_data.apply(save=self.save), reason=REASON_NEW_ENTRY
                )
                if not self.save:
                    self.consolidate_delete_add(ixf_member_data)
            except ValidationError as exc:
                if ixf_member_data.set_conflict(error=exc, save=self.save):
                    self.queue_notification(ixf_member_data, ixf_member_data.action)

        else:
            notify = ixf_member_data.set_add(save=self.save, reason=REASON_NEW_ENTRY)

            self.log_ixf_member_data(ixf_member_data)
            self.consolidate_delete_add(ixf_member_data)

            if notify and ixf_member_data.net_present_at_ix:
                self.queue_notification(ixf_member_data, ixf_member_data.action)
            elif notify:
                self.queue_notification(
                    ixf_member_data, ixf_member_data.action, ix=False, ac=False
                )

    def consolidate_delete_add(self, ixf_member_data):

        ip4_deletion = None
        ip6_deletion = None

        for ixf_id, deletion in self.deletions.items():
            if deletion.asn == ixf_member_data.asn:
                if deletion.ipaddr4 and deletion.ipaddr4 == ixf_member_data.init_ipaddr4:
                    ip4_deletion = deletion
                if deletion.ipaddr6 and deletion.ipaddr6 == ixf_member_data.init_ipaddr6:
                    ip6_deletion = deletion

            if ip4_deletion and ip6_deletion:
                break

        if not ip4_deletion and not ip6_deletion:
            return

        ip4_req = ixf_member_data.set_requirement(ip4_deletion, save=self.save)
        ip6_req = ixf_member_data.set_requirement(ip6_deletion, save=self.save)

        if not ip4_req and not ip6_req:
            return

        if not ixf_member_data.has_requirements:
            return

        if ip4_deletion:
            try:
                self.log["data"].remove(ip4_deletion.ixf_log_entry)
            except ValueError:
                pass
        if ip6_deletion:
            try:
                self.log["data"].remove(ip6_deletion.ixf_log_entry)
            except ValueError:
                pass

        log_entry = ixf_member_data.ixf_log_entry

        log_entry["action"] = log_entry["action"].replace("add", "modify")
        changed_fields = ", ".join(
            ixf_member_data._changes(
                getattr(ip4_deletion, "netixlan", None)
                or getattr(ip6_deletion, "netixlan", None)
            ).keys()
        )

        ipaddr_info = ""

        if ip4_deletion and ip6_deletion:
            ipaddr_info = _("IP addresses moved to same entry")
        elif ip4_deletion:
            ipaddr_info = _("IPv6 not set")
        elif ip6_deletion:
            ipaddr_info = _("IPv4 not set")

        log_entry["reason"] = f"{REASON_VALUES_CHANGED}: {changed_fields} {ipaddr_info}"

        ixf_member_data.reason = log_entry["reason"]
        ixf_member_data.error = None
        if self.save:
            if ixf_member_data.updated:
                ixf_member_data.save_without_update()
            else:
                ixf_member_data.save()

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

        result = self.log_peer(
            netixlan.asn, apply_result["action"], reason, netixlan=netixlan
        )

        apply_result["ixf_member_data"].ixf_log_entry = netixlan.ixf_log_entry

        return result

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
        entry = {
            "peer": peer,
            "action": action,
            "reason": f"{reason}",
        }
        self.log["data"].append(entry)

        if netixlan:
            netixlan.ixf_log_entry = entry

    def _email(self, subject, message, recipients, net=None, ix=None):
        """
        Send email

        Honors the MAIL_DEBUG setting

        Will create IXFImportEmail entry
        """

        if not recipients:
            return

        email_log = None

        logged_subject = f"{settings.EMAIL_SUBJECT_PREFIX}[IX-F] {subject}"

        if net:
            email_log = IXFImportEmail.objects.create(
                subject=logged_subject,
                message=message,
                recipients=",".join(recipients),
                net=net,
            )

            if not self.notify_net_enabled:
                return

        if ix:
            email_log = IXFImportEmail.objects.create(
                subject=logged_subject,
                message=message,
                recipients=",".join(recipients),
                ix=ix,
            )
            if not self.notify_ix_enabled:
                return

        if not getattr(settings, "MAIL_DEBUG", False):
            mail = EmailMultiAlternatives(
                subject, strip_tags(message), settings.DEFAULT_FROM_EMAIL, recipients,
            )
            mail.send(fail_silently=False)
            self.emails += 1
        else:
            self.emails += 1
            # debug_mail(
            #    subject, message, settings.DEFAULT_FROM_EMAIL, recipients,
            # )
        if email_log:
            email_log.sent = datetime.datetime.now(datetime.timezone.utc)
            email_log.save()

    def _ticket(self, ixf_member_data, subject, message):

        """
        Create and send a deskpro ticket

        Return the DeskPROTicket instance

        Argument(s):

        - ixf_member_data (`IXFMemberData`)
        - subject (`str`)
        - message (`str`)

        """

        subject = f"{settings.EMAIL_SUBJECT_PREFIX}[IX-F] {subject}"

        client = self.deskpro_client

        if not ixf_member_data.deskpro_id:
            old_ticket = DeskProTicket.objects.filter(
                subject=subject, deskpro_id__isnull=False
            ).first()
            if old_ticket:
                ixf_member_data.deskpro_id = old_ticket.deskpro_id
                ixf_member_data.deskpro_ref = old_ticket.deskpro_ref

        ticket = DeskProTicket.objects.create(
            subject=subject,
            body=message,
            user=self.ticket_user,
            deskpro_id=ixf_member_data.deskpro_id,
            deskpro_ref=ixf_member_data.deskpro_ref,
        )

        try:
            client.create_ticket(ticket)
            ticket.published = datetime.datetime.now(datetime.timezone.utc)
            ticket.save()
        except Exception as exc:
            ticket.subject = f"[FAILED]{ticket.subject}"
            ticket.body = f"{ticket.body}\n\n{exc.data}"
            ticket.save()
        return ticket

    def consolidate_proposals(self):

        """
        Renders and consolidates all proposals for each net and ix
        (#772)

        Returns a dict

        {
            "net": {
                Network : {
                    "proposals": {
                        InternetExchange {
                            "add" : [<str>, ...],
                            "modify" : [<str>, ...],
                            "delete" : [<str>, ...],
                        },
                    },
                    "count": <int>
                    "entity": Network,
                    "contacts": [<str>, ...]
                }
            },
            "ix": {
                InternetExchange : {
                    "proposals": {
                        Network : {
                            "add" : [<str>, ...],
                            "modify" : [<str>, ...],
                            "delete" : [<str>, ...],
                        },
                    },
                    "count": <int>
                    "entity": InternetExchange,
                    "contacts": [<str>, ...]
                }
            }
        }
        """

        net_notifications = {}
        ix_notifications = {}

        for notification in self.notifications:

            ixf_member_data = notification["ixf_member_data"]
            action = notification["action"]
            typ = notification["typ"]
            notify_ix = notification["ix"]
            notify_net = notification["net"]
            context = notification["context"]

            # we don't care about resolved proposals

            if typ == "resolved":
                if ixf_member_data.deskpro_id:
                    self.ticket_proposal(**notification)
                continue

            if typ == "protocol-conflict":
                action = "protocol_conflict"

            # in some edge cases (ip4 set on netixlan, network indicating
            # only ipv6 support) we can get empty modify notifications
            # that we need to throw out. (#771)
            if typ == "modify":
                if not ixf_member_data.actionable_changes:
                    continue

            # we don't care about proposals that are hidden
            # requirements of other proposals

            if ixf_member_data.requirement_of:
                continue

            asn = ixf_member_data.net
            ix = ixf_member_data.ix
            ix_contacts = ixf_member_data.ix_contacts
            net_contacts = ixf_member_data.net_contacts

            # no suitable contact points found for
            # one of the sides, immediately make a ticket

            if not ix_contacts or not net_contacts:
                if typ != "protocol-conflict":
                    self.ticket_proposal(**notification)

            template_file = f"email/notify-ixf-{typ}-inline.txt"

            # prepare consolidation rocketship

            if notify_net and asn not in net_notifications:
                net_notifications[asn] = {
                    "proposals": {},
                    "count": 0,
                    "entity": ixf_member_data.net,
                    "contacts": ixf_member_data.net_contacts,
                }

            if notify_net and ix not in net_notifications[asn]["proposals"]:
                net_notifications[asn]["proposals"][ix] = {
                    "add": [],
                    "modify": [],
                    "delete": [],
                    "protocol_conflict": None,
                }

            if notify_ix and ix not in ix_notifications:
                ix_notifications[ix] = {
                    "proposals": {},
                    "count": 0,
                    "entity": ixf_member_data.ix,
                    "contacts": ixf_member_data.ix_contacts,
                }

            if notify_ix and asn not in ix_notifications[ix]["proposals"]:
                ix_notifications[ix]["proposals"][asn] = {
                    "add": [],
                    "modify": [],
                    "delete": [],
                    "protocol_conflict": None,
                }

            # render and push proposal text for network

            if notify_net and (
                ixf_member_data.actionable_for_network or action == "protocol_conflict"
            ):
                proposals = net_notifications[asn]["proposals"][ix]
                message = ixf_member_data.render_notification(
                    template_file, recipient="net", context=context,
                )

                if action == "protocol_conflict" and not proposals[action]:
                    proposals[action] = message
                    net_notifications[asn]["count"] += 1
                else:
                    proposals[action].append(message)
                    net_notifications[asn]["count"] += 1

            # render and push proposal text for exchange

            if notify_ix:
                proposals = ix_notifications[ix]["proposals"][asn]
                message = ixf_member_data.render_notification(
                    template_file, recipient="ix", context=context,
                )

                if action == "protocol_conflict" and not proposals[action]:
                    proposals[action] = message
                    ix_notifications[ix]["count"] += 1
                else:
                    proposals[action].append(message)
                    ix_notifications[ix]["count"] += 1

        return {
            "net": net_notifications,
            "ix": ix_notifications,
        }

    def notify_proposals(self):

        """
        Sends all collected notification proposals
        """

        if not self.save:
            return

        # consolidate proposals into net,ix and ix,net
        # groupings

        consolidated = self.consolidate_proposals()

        ticket_days = EnvironmentSetting.get_setting_value(
            "IXF_IMPORTER_DAYS_UNTIL_TICKET"
        )

        template = loader.get_template("email/notify-ixf-consolidated.txt")

        for recipient in ["ix", "net"]:
            for other_entity, data in consolidated[recipient].items():
                contacts = data["contacts"]

                # we did not find any suitable contact points
                # skip

                if not contacts:
                    continue

                # no messages

                if not data["count"]:
                    continue

                # render the consolidated message

                message = template.render(
                    {
                        "recipient": recipient,
                        "entity": data["entity"],
                        "count": data["count"],
                        "ticket_days": ticket_days,
                        "proposals": data["proposals"],
                    }
                )

                if recipient == "net":
                    subject = _(
                        "PeeringDB: Action May Be Needed: IX-F Importer "
                        "data mismatch between AS{} and one or more IXPs"
                    ).format(data["entity"].asn)
                    self._email(subject, message, contacts, net=data["entity"])
                else:
                    subject = _(
                        "PeeringDB: Action May Be Needed: IX-F Importer "
                        "data mismatch between {} and one or more networks"
                    ).format(data["entity"].name)
                    self._email(subject, message, contacts, ix=data["entity"])

    def ticket_aged_proposals(self):

        """
        Cycle through all IXFMemberData objects that
        and create tickets for those that are older
        than the period specified in IXF_IMPORTER_DAYS_UNTIL_TICKET
        and that don't have any ticket associated with
        them yet
        """

        if not self.save:
            return

        qset = IXFMemberData.objects.filter(
            deskpro_id__isnull=True, requirement_of__isnull=True
        )

        # get ticket days period
        ticket_days = EnvironmentSetting.get_setting_value(
            "IXF_IMPORTER_DAYS_UNTIL_TICKET"
        )

        if ticket_days > 0:

            # we adjust the query to only get proposals
            # that are older than the specified period

            now = datetime.datetime.now(datetime.timezone.utc)
            max_age = now - datetime.timedelta(days=ticket_days)
            qset = qset.filter(created__lte=max_age)

        for ixf_member_data in qset:

            action = ixf_member_data.action
            if action == "delete":
                action = "remove"
            typ = action

            # create the ticket
            # and also notify the net and ix with
            # a reference to the ticket in the subject

            self.ticket_proposal(
                ixf_member_data, typ, True, True, True, {}, ixf_member_data.action
            )

    def ticket_proposal(self, ixf_member_data, typ, ac, ix, net, context, action):

        """
        Creates a deskpro ticket and contexts net and ix with
        ticket reference in the subject

        Argument(s)

        - ixf_member_data (IXFMemberData)
        - typ (str): proposal type 'add','delete','modify','resolve','conflict'
        - ac (bool): If true DeskProTicket will be created
        - ix (bool): If true email will be sent to ix
        - net (bool): If true email will be sent to net
        - context (dict): extra template context
        """

        if typ == "add" and ixf_member_data.requirements:
            typ = ixf_member_data.action
            subject = f"{ixf_member_data.primary_requirement}"
        else:
            subject = f"{ixf_member_data}"

        subject = f"{subject} IX-F Conflict Resolution"

        template_file = f"email/notify-ixf-{typ}.txt"

        # DeskPRO ticket

        if ac and self.tickets_enabled:
            message = ixf_member_data.render_notification(
                template_file, recipient="ac", context=context
            )

            ticket = self._ticket(ixf_member_data, subject, message)
            ixf_member_data.deskpro_id = ticket.deskpro_id
            ixf_member_data.deskpro_ref = ticket.deskpro_ref
            if ixf_member_data.id:
                ixf_member_data.save()

        # we have deskpro reference number, put it in the
        # subject

        if ixf_member_data.deskpro_ref:
            subject = f"{subject} [#{ixf_member_data.deskpro_ref}]"

        # Notify Exchange

        if ix:
            message = ixf_member_data.render_notification(
                template_file, recipient="ix", context=context
            )
            self._email(
                subject, message, ixf_member_data.ix_contacts, ix=ixf_member_data.ix
            )

        # Notify network

        if net and ixf_member_data.actionable_for_network:
            message = ixf_member_data.render_notification(
                template_file, recipient="net", context=context
            )
            self._email(
                subject, message, ixf_member_data.net_contacts, net=ixf_member_data.net
            )

    def notify_error(self, error):

        """
        Notifies the exchange and AC of any errors that
        were encountered when the IX-F data was
        parsed
        """

        if not self.save:
            return

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

        subject = "Could not process IX-F Data"
        template = loader.get_template("email/notify-ixf-source-error.txt")
        message = template.render(
            {"error": error, "dt": now, "instance": ixf_member_data}
        )

        # AC does not want ticket here as per #794
        # self._ticket(ixf_member_data, subject, message)

        if ixf_member_data.ix_contacts:
            self._email(
                subject, message, ixf_member_data.ix_contacts, ix=ixf_member_data.ix
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
