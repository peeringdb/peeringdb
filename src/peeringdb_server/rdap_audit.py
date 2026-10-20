"""Read-only affiliation evidence; approval method and historical verification are not recorded."""

import json
from collections.abc import Iterator

from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.utils import timezone
from reversion.models import Version

from peeringdb_server.models import Organization, User


def iter_affiliation_audit(database: str = "default") -> Iterator[dict[str, object]]:
    """Yield evidence and explicit limitations without exposing names or email addresses."""
    yield dict(
        type="metadata",
        schema=1,
        generated_at=timezone.now().isoformat(),
        database_alias=database,
        approval_method="not_recorded",
        email_verification_at_approval="not_recorded",
        limitations=[
            "Candidates are not proof of unauthorized or RDAP-based approval.",
            "Current email verification does not establish historical ownership.",
            "Deleted or unretained history may omit approvals.",
            "Use a consistent read-only snapshot for reproducible results.",
        ],
    )
    users = set(User.objects.using(database).values_list("pk", flat=True))
    verified_users = set(
        EmailAddress.objects.using(database)
        .filter(verified=True)
        .values_list("user_id", flat=True)
    )
    org_groups = {
        f"org.{pk}.admin": pk
        for pk in Organization.objects.using(database).values_list("pk", flat=True)
    }
    groups = {
        pk: org_groups[name]
        for pk, name in Group.objects.using(database)
        .filter(name__in=org_groups)
        .values_list("pk", "name")
    }
    memberships = set(
        (groups[group_id], user_id)
        for group_id, user_id in User.groups.through.objects.using(database)
        .filter(group_id__in=groups)
        .values_list("group_id", "user_id")
    )
    history_pairs = set()
    versions_scanned = approvals = 0
    versions = (
        Version.objects.using(database)
        .filter(
            content_type__app_label="peeringdb_server",
            content_type__model="userorgaffiliationrequest",
        )
        .select_related("revision")
        .order_by("pk")
    )
    for version in versions.iterator(chunk_size=500):
        versions_scanned += 1
        if version.format != "json":
            raise ValueError(f"Unsupported format for version {version.pk}")
        try:
            fields = json.loads(version.serialized_data)[0]["fields"]
            status = fields["status"]
            org_id, user_id = fields["org"], fields["user"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Cannot read version {version.pk}") from exc
        if status != "processing-approval":
            continue
        approvals += 1
        history_pairs.add((org_id, user_id))
        yield dict(
            type="approval_snapshot",
            version_id=version.pk,
            request_id=version.object_id,
            approved_at=version.revision.date_created.isoformat(),
            org_id=org_id,
            user_id=user_id,
            actor_id=version.revision.user_id,
            user_exists_now=user_id in users,
            user_has_verified_email_now=user_id in verified_users,
            user_is_org_admin_now=(org_id, user_id) in memberships,
        )
    for org_id, user_id in sorted(memberships):
        yield dict(
            type="current_admin",
            org_id=org_id,
            user_id=user_id,
            has_retained_approval_snapshot=(org_id, user_id) in history_pairs,
            user_has_verified_email_now=user_id in verified_users,
        )
    yield dict(
        type="summary",
        affiliation_versions_scanned=versions_scanned,
        approval_snapshots=approvals,
        current_admin_memberships=len(memberships),
        current_admins_without_approval_snapshot=len(memberships - history_pairs),
        current_admins_without_verified_email=sum(
            user_id not in verified_users for _, user_id in memberships
        ),
    )
