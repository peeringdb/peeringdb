"""
Fix users affected by being both in the org admin
and org user group when it should be one or the other.
"""

from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import User


class Command(PeeringDBBaseCommand):
    """
    Fixes users affected by being both in the org admin
    and org user group when it should be one or the other
    """

    def handle(self, *args, **options):
        super().handle(*args, **options)
        self.fix_users()

    def fix_users(self):
        issues = 0

        for user in User.objects.all():
            groups = {}
            for group in user.groups.all():
                groups[group.name] = group
            for group_name, group in groups.items():
                if f"{group_name}.admin" in groups:
                    # user is in both groups
                    if self.commit:
                        # remove user from the normal users group
                        user.groups.remove(group)
                    self.log(f"removed {user} from {group_name}")
                    issues += 1

        self.log(f"{issues} fixed")
