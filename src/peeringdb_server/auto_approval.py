import structlog
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from peeringdb_server.inet import RdapLookup
from peeringdb_server.ixf import Importer
from peeringdb_server.models import Network
from peeringdb_server.models import EnvironmentSetting

log = structlog.get_logger("django")


def _validate_ixf_feed(ixf_ixp_member_list_url, submitting_org):
    """
    Validate the IX-F feed at the given URL for auto-approval eligibility.

    Checks:
      1. URL is provided.
      2. Feed is fetchable and parseable (no pdb_error).
      3. Feed contains at least settings.IXF_PREFIXAUTO_MIN_ASN_COUNT unique ASNs.
      4. None of those ASNs belong to the same org as the submitting entity.

    Note on check 4: conflict detection is limited to Networks already registered
    in PeeringDB with status ok or pending. RIR-level ownership of an ASN that has
    not yet been added to PDB (or was deleted) will not be detected.

    Returns:
        (bool, str): (valid, reason) — reason is non-empty string when invalid.
    """
    min_asn_count = settings.IXF_PREFIXAUTO_MIN_ASN_COUNT

    if not ixf_ixp_member_list_url:
        return False, "no IX-F member list URL provided"

    importer = Importer()
    data = importer.fetch(ixf_ixp_member_list_url, timeout=settings.IXF_FETCH_TIMEOUT)

    if data.get("pdb_error"):
        log.warning(
            "ixf_prefixauto_fetch_error",
            url=ixf_ixp_member_list_url,
            error=data["pdb_error"],
        )
        return False, f"IX-F feed error: {data['pdb_error']}"

    member_list = data.get("member_list", [])
    unique_asns = {m.get("asnum") for m in member_list if m.get("asnum") is not None}

    if len(unique_asns) < min_asn_count:
        return False, (
            f"IX-F feed contains {len(unique_asns)} unique ASN(s); "
            f"at least {min_asn_count} are required"
        )

    if submitting_org:
        conflicting = Network.objects.filter(
            asn__in=unique_asns, org=submitting_org, status__in=["ok", "pending"]
        ).exists()
        if conflicting:
            return False, (
                "IX-F feed contains an ASN belonging to the submitting organization"
            )

    return True, ""


def auto_approve_ix(request, prefix, ixf_ixp_member_list_url=None, submitting_org=None):
    if not EnvironmentSetting.get_setting_value("AUTO_IX_APPROVAL_ENABLED"):
        return False, "pending", ""

    user = request.user

    if isinstance(user, AnonymousUser):
        # anon user shouldnt ever be passed here, but some test cases
        # do so we need to handle it
        return False, "pending", ""

    # Get administration emails of the prefix using RdapLookup
    try:
        rdap = RdapLookup().get_ip(prefix)
    except Exception as exc:
        # unhandled rdap issue, log and return pending
        log.error("rdap_error", prefix=prefix, exc=exc)
        return False, "pending", ""

    # Calculate status and auto_approve values
    auto_approve = False
    ixf_reason = ""

    email_address = user.emailaddress_set.filter(email__in=rdap.emails, verified=True)
    if email_address.exists():
        # RDAP check passed — now validate the IX-F feed
        ixf_valid, ixf_reason = _validate_ixf_feed(
            ixf_ixp_member_list_url, submitting_org
        )
        if ixf_valid:
            auto_approve = True
        else:
            log.info(
                "ixf_prefixauto_validation_failed",
                prefix=str(prefix),
                reason=ixf_reason,
            )

    status = "ok" if auto_approve else "pending"

    return auto_approve, status, ixf_reason
