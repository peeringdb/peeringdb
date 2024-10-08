import structlog
from django.contrib.auth.models import AnonymousUser

from peeringdb_server.inet import RdapException, RdapLookup

log = structlog.get_logger("django")


def auto_approve_ix(request, prefix):
    user = request.user

    if isinstance(user, AnonymousUser):
        # anon user shouldnt ever be passed here, but some test cases
        # do so we need to handle it
        return False, "pending"

    # Get administration emails of the prefix using RdapLookup
    try:
        rdap = RdapLookup().get_ip(prefix)
    except Exception as exc:
        # unhandled rdap issue, log and return pending
        log.error("rdap_error", prefix=prefix, exc=exc)
        return False, "pending"

    # Calculate status and auto_approve values
    auto_approve = False

    email_address = user.emailaddress_set.filter(email__in=rdap.emails, verified=True)
    if email_address.exists():
        auto_approve = True

    status = "ok" if auto_approve else "pending"

    return auto_approve, status
