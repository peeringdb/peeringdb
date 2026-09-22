# #1742: netixlan status absorbs operational-ness.
#
# Existing non-operational rows are migrated from the boolean. Scoped to
# status="ok" on purpose -- pending and deleted rows keep their lifecycle
# status regardless of the boolean, otherwise the migration would resurrect
# deleted connections.
#
# `updated` is bumped explicitly (update() bypasses auto_now) so incremental
# sync clients receive the migrated rows -- without it the status change
# would only ever reach clients on a full resync.

from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    # _default_manager: on historical models the only manager kept is the
    # first-declared one (handleref), so there is no `objects` here
    NetworkIXLan = apps.get_model("peeringdb_server", "NetworkIXLan")
    NetworkIXLan._default_manager.filter(status="ok", operational=False).update(
        status="not-operational", updated=timezone.now()
    )


def backwards(apps, schema_editor):
    NetworkIXLan = apps.get_model("peeringdb_server", "NetworkIXLan")
    # not-operational rows all came from status="ok" (see forwards); their
    # operational boolean was never touched, so this restores the exact
    # pre-migration state (minus the updated bump).
    NetworkIXLan._default_manager.filter(status="not-operational").update(
        status="ok", updated=timezone.now()
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "peeringdb_server",
            "0159_ixfmemberdata_meta_network_meta_networkixlan_meta_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
