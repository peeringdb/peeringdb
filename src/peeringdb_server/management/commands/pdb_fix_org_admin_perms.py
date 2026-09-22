"""
Remove the user-level grainy permissions that shadow an org role's group grant.

Several role transitions used to leave a user's own `UserPermission` rows in
place, where they replace rather than widen the role's grant at the same
namespace (#2038).
"""

import re
from collections import defaultdict

from django_grainy.models import UserPermission

from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import Organization, User

# the org id out of an org namespace, on the same boundary
# org_namespace_filter draws: `...organization.5` and `...organization.5.network`
# yield 5, `...organization.50` does not.

ORG_NAMESPACE_RE = re.compile(
    rf"^{re.escape(Organization.Grainy.namespace())}\.(\d+)(?:\.|$)"
)


class Command(PeeringDBBaseCommand):
    help = "Remove stale user-level grainy permissions left behind by org role changes (#2038)"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--list-unaffiliated",
            action="store_true",
            help=(
                "Additionally list users holding permissions for an org they are "
                "in neither group of. Never deletes anything."
            ),
        )

    def handle(self, *args, **options):
        super().handle(*args, **options)

        admins, unaffiliated = self.collect()

        self.fix_org_admins(admins)

        if options.get("list_unaffiliated"):
            self.report_unaffiliated(unaffiliated)

    def collect(self):
        """
        Return (admins, unaffiliated), each a list of (org, user, permission
        ids) sorted by org then user, where `admins` holds the users in the
        org's admin group and `unaffiliated` the users in neither of its groups.

        Users in the member group are left out: a member is meant to hold
        granular permissions.
        """

        rows = defaultdict(list)

        # iterator() because on production this scans every org permission row
        # ever granted, and only the parsed ids are kept

        for permission in (
            UserPermission.objects.filter(
                namespace__startswith=f"{Organization.Grainy.namespace()}."
            )
            .only("id", "user_id", "namespace")
            .iterator()
        ):
            match = ORG_NAMESPACE_RE.match(permission.namespace)
            if match:
                rows[(permission.user_id, int(match.group(1)))].append(permission.id)

        users = {
            user.id: user
            for user in User.objects.filter(
                id__in={user_id for user_id, _ in rows}
            ).prefetch_related("groups")
        }
        orgs = {
            org.id: org
            for org in Organization.objects.filter(
                id__in={org_id for _, org_id in rows}
            )
        }

        admins = []
        unaffiliated = []

        for (user_id, org_id), permission_ids in rows.items():
            user = users.get(user_id)
            org = orgs.get(org_id)

            if not user or not org:
                # nothing to shadow

                continue

            groups = {group.name for group in user.groups.all()}

            if org.admin_group_name in groups:
                admins.append((org, user, permission_ids))
            elif org.group_name not in groups:
                unaffiliated.append((org, user, permission_ids))

        def by_org_then_user(entry):
            org, user, _ = entry
            return (org.id, user.id)

        return sorted(admins, key=by_org_then_user), sorted(
            unaffiliated, key=by_org_then_user
        )

    def fix_org_admins(self, admins):
        for org, user, permission_ids in admins:
            self.log(
                f"removing {len(permission_ids)} permission(s) held by {user} "
                f"for org {org.id} ({org.name}), which they administer"
            )

            if self.commit:
                UserPermission.objects.filter(id__in=permission_ids).delete()

        self.log(f"{len(admins)} org admin(s) with shadowing permissions")

    def report_unaffiliated(self, unaffiliated):
        """
        List users holding permissions for an org they are in neither group of.

        The permissions panel only lists users in one of the org's groups, so
        these are invisible today and their number is unknown until this runs.
        Reported, never deleted: nothing here establishes they are all
        leftovers.
        """

        for org, user, permission_ids in unaffiliated:
            self.stdout.write(
                f"[unaffiliated] {user} holds {len(permission_ids)} permission(s) "
                f"for org {org.id} ({org.name}) while in neither of its groups"
            )

        self.stdout.write(
            f"[unaffiliated] {len(unaffiliated)} user/org pair(s), none touched"
        )
