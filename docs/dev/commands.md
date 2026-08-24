Generated on 2026-08-15 04:17:12.049436

## _db_command.py

DEPRECATED

## migrate.py

# Classes

## pdb_api_cache.py

Regen the api cache files.

## pdb_api_test.py

Series of integration/unit tests for the PDB API.

## pdb_base_command.py

Base class to use for command creation.

## pdb_batch_replace.py

Replace a value in a field across several entities.

## pdb_cleanup_vq.py

Verification queue cleanup.

## pdb_convert_irr_as_set_postfix.py

Convert irr_as_set @SOURCE postfix tokens to SOURCE:: prefix notation.

Finds all Network objects (status=ok) whose irr_as_set contains @SOURCE
tokens and rewrites each token to SOURCE::as-set format.

Usage:

    # Preview changes without modifying the database
    ./Ctl/dev/run.sh manage pdb_convert_irr_as_set_postfix

    # Apply changes
    ./Ctl/dev/run.sh manage pdb_convert_irr_as_set_postfix --commit

## pdb_delete_addressless_netixlan.py

Remove active netixlans that were created by the IX-F importer with neither
an IPv4 nor an IPv6 address.

The IX-F importer used to create address-less netixlans when a network
disabled the only ip protocol its feed advertised (#2005). That has been
fixed at the source, but rows created before the fix remain in the
database - this command cleans them up.

An address-less netixlan is NOT necessarily an import artifact: an admin
can intentionally blank both ip fields via the inline form (#644), and the
importer may have merely modified an entry that was later blanked by hand.
To stay safe this command only deletes a row when the importer itself
CREATED it already address-less - i.e. it has an "add" IX-F import log entry
whose resulting version had neither ip set. Every other address-less row is
only reported, never deleted - handle those by hand.

Rows are soft-deleted (status -> "deleted") so the change is reversible.

Usage:

    # Preview what would be deleted without modifying the database
    ./Ctl/dev/run.sh manage pdb_delete_addressless_netixlan

    # Apply
    ./Ctl/dev/run.sh manage pdb_delete_addressless_netixlan --commit

## pdb_delete_childless_org.py

Delete childless org objects

## pdb_delete_outdated_pending_affil_request.py

Deletes outdated pending affiliation requests from the database.

## pdb_delete_pocs.py

Hard delete old soft-deleted network contract instances.

## pdb_delete_users.py

Delete childless org objects

## pdb_deskpro_publish.py

Process deskpro ticket queue.

## pdb_deskpro_requeue.py

Reset a deskpro ticket and requeue for publishing.

## pdb_export_address_info.py

# Classes

## pdb_fac_fix_carrier_count_values.py

Management command to check and fix carrier_count field on Facility objects.

This command verifies and updates the carrier_count field for facilities
based on their active CarrierFacility relationships.

Usage:
    # Check all facilities for wrong carrier_count values (read-only)
    python manage.py pdb_fac_fix_carrier_count_values

    # Check specific facility for wrong carrier_count value
    python manage.py pdb_fac_fix_carrier_count_values --facility-id 2148

    # Fix all facilities with wrong carrier_count values (dry run)
    python manage.py pdb_fac_fix_carrier_count_values --fix-all

    # Fix all facilities with wrong carrier_count values (apply changes)
    python manage.py pdb_fac_fix_carrier_count_values --fix-all --commit

    # Fix specific facility's wrong carrier_count value (apply changes)
    python manage.py pdb_fac_fix_carrier_count_values --facility-id 2148 --commit

## pdb_fac_merge.py

Merge facilities.

## pdb_fac_merge_undo.py

Undo a facility merge.

## pdb_fetch_api_cache.py

Django management command
Will fetch api cache files from PEERINGDB_SYNC_CACHE_URL to API_CACHE_ROOT

## pdb_fix_930_users.py

Fix users affected by being both in the org admin
and org user group when it should be one or the other.

## pdb_fix_net_counts.py

Fix incorrect net_count and ixf_net_count values for InternetExchange objects.

This command recalculates net_count and ixf_net_count for all exchanges
to fix any inconsistencies caused by issue #1607.

net_count: Number of unique networks actually peering at the exchange
ixf_net_count: Number of unique networks in the IX-F export data

## pdb_fix_orphaned_objects.py

Fix orphaned objects where a child has status="ok" but its parent FK
has status="deleted". This can happen when cascade deletes were not
properly triggered historically (e.g., missing delete_cascade entries
or a ProtectedAction blocking the cascade mid-way).

Usage:
    # Preview only — shows what would be fixed, no changes made
    python manage.py pdb_fix_orphaned_objects

    # Apply fixes — soft-deletes all orphaned records
    python manage.py pdb_fix_orphaned_objects --commit

## pdb_generate_test_data.py

Create test data. This will wipe all data locally, so use with caution. This command is NOT to be run on production or beta environments.

## pdb_geo_normalize_existing.py

Normalize existing address fields based on Google Maps API response.

## pdb_geo_normalize_state.py

# Classes

## pdb_geosync.py

DEPRECATED
Sync latitude and longitude on all geocoding enabled entities.

## pdb_irr_as_set_fetch.py

Download and refresh the local IRR dump cache used by batch AS-SET jobs.

The interactive editor and save path use the live IRR lookup pool. This command
maintains the separate bulk cache used by pdb_irr_as_set_cleanup and the periodic
checker so those jobs do not issue tens of thousands of per-object mirror queries.

Dry-run by default, --commit to download, like every other command in this suite.
A dry run reports what each source would do and touches nothing: it makes no
request, and the dump directory and its staging area are left alone, so it also
answers on a cold host. That offline rule is why any *usable* cache is reported
conditionally, however old it is: once the cache is valid the real run decides on
the published serial and ignores file age, so only the reason string can say what
that source's outcome actually turns on.

Under --commit every source is attempted independently: a refresh that failed but
kept a usable cache is "stale", one with no usable dump at all is "failed", and the
remaining sources are refreshed either way. The command then exits non-zero,
because the run otherwise looks successful while a registry silently stops
refreshing and pdb_irr_as_set_cleanup --commit auto-prefixes from an ageing index.

Usage:
  manage pdb_irr_as_set_fetch [--source SOURCE] [--force] [--commit]
                              [--dump-dir PATH] [--max-age-hours HOURS]

## pdb_irr_as_set_status.py

Periodic re-verification of Network.irr_as_set (#1973).

Save-path validation and pdb_irr_as_set_cleanup only ever look at values that are
syntactically wrong -- bare, placeholder, route-set, invalid. A correctly prefixed
value is never re-checked by either, so RIPE::AS-GONE, whose object was deleted
from RIPE last month, is invisible to every other batch job. That is also the class
of row the cleanup campaign is busy creating, which is why this command exists:
without it the data starts rotting again the moment an operator's object is
deleted.

Modeled on pdb_rir_status (#1942), as the spec directs, and sharing
pdb_irr_as_set_cleanup's conventions so ops muscle memory transfers: dry-run by
default, --commit, --dump-dir, --allow-stale-index.

Every status=ok network with a value is swept on every run, rather than tracking
which rows were saved during a lookup outage. That covers the save path's
fail-open accepts with no extra field to keep in sync, and it is the only design
that also covers rows written by a non-clean() writer.

Each prefixed token is resolved against the local bulk dump index first and goes
to the live pool only when the index does not hold it in its pinned source. The
dump narrows the candidate set; the live pool is what makes a claim. Nothing is
ever flagged off a dump miss alone -- a dump up to IRR_BULK_DUMP_MAX_AGE_HOURS
old, or one registry silently failing to refresh, would otherwise mail operators
that their working as-set is gone.

Four outcomes are recorded (see IRR_AS_SET_STATUSES), and two more are run-local:
`skipped` for a value carrying a token with no verifiable pin, and `deferred` for
one the run's --max-lookups budget did not reach. Neither writes state, and both
are reported separately so they are not silently folded into `unknown`.

Without --commit the command never modifies the database and sends no mail.
--commit records each outcome and mails the moved and gone ones, bounded by
--max-notifications with irr_as_set_verify_notified as the cursor and
--renotify-after-days as the reminder cadence. `unknown` is never
mailed: the pool failing to answer is not news, and mailing it would turn an IRR
outage into a mass notification.

What this command deliberately does NOT do is remove or rewrite an operator's
value. Its model, pdb_rir_status, removes the record after KEEP_RIR_STATUS days;
wiping an operator's irr_as_set silently degrades their peers' filters and needs a
ruling (#1973, still open), not an implementation decision. irr_as_set_missing_since
is the field such an escalation would read, so that ruling costs no migration. Its
own verification columns it does clear, once the verdict they carry is no longer
about the value the network holds (see _retract).

Ordering, for whoever schedules this: pdb_irr_as_set_fetch --commit must have run
first, or --commit refuses on the dump-health guard (--allow-stale-index overrides,
at the cost of spending the live-lookup budget on tokens the index should have
answered for free). The defaults cap a run at --max-lookups 1000 / --max-notifications 100
and --commit refuses 0 for either, so a first sweep over the whole set takes
several passes -- a partial first run is the design, not a failure.

Usage:
  manage pdb_irr_as_set_status [--detail] [--dump-dir PATH] [--commit]
                               [--max-lookups N] [--max-notifications N]
                               [--renotify-after-days N] [--allow-stale-index]

## pdb_ixf_ixp_member_import.py

Run the IX-F Importer.

## pdb_ixp_merge.py

Merge exchanges.

## pdb_load_data.py

Load initial data from another peeringdb instance using the REST API.

## pdb_maintenance.py

Put peeringdb in or out of maintenance mode.

## pdb_migrate_ixlans.py

DEPRECATED
Used during ixlan migrations for #21.

## pdb_normalize_name_whitespace.py

Backfill: collapse 2+ consecutive whitespace in entity `name` fields (#1984).

Fixes rows that predate the validate_name validator. Rows whose normalized name
would collide with an existing non-deleted row (unique=True) are skipped and
reported - a collision may be two distinct entities, so it needs human review,
not an automatic merge. Run this at/before the deploy enabling validate_name.

Usage:

    ./Ctl/dev/run.sh manage pdb_normalize_name_whitespace           # preview
    ./Ctl/dev/run.sh manage pdb_normalize_name_whitespace --commit  # apply

## pdb_notify_geocoords.py

# Classes

## pdb_process_admin_tool_command.py

Process one item in the admin tool command queue.

## pdb_rdap_cache.py

Update the cache of the RDAP cache from IANA.

## pdb_renumber_lans.py

Renumber addresses by providing the first three octets of a current ip4 address and the first three octets to change to.

## pdb_reversion_inspect.py

Inspect an object's history of changes.

## pdb_rir_status.py

Check and update the RIR status of networks against RIR allocation data, and
remove networks whose ASN has been reclaimed by the RIR/NIR (GH #1942).

Each run compares every network's ASN to the RIR data and:

- flags a network whose status went good -> bad (e.g. "missing"/"reserved"),
  notifying its contacts and starting the deletion countdown,
- deletes a still-unassigned network once it has been notified and
  KEEP_RIR_STATUS days have elapsed -- but only if a live RDAP lookup no longer
  resolves the ASN #2001; if RDAP still finds it, or cannot be reached, the
  deletion is deferred to a later run,
- clears the flag if the assignment recovers (bad -> good).

The pre-deletion RDAP verification is on by default and can be toggled with the
RIR_STATUS_VERIFY_BEFORE_DELETE setting (env-overridable).

Typically run from cron. Without --commit it runs in pretend mode (logs only,
no DB changes or emails).

Usage:
    # dry run (no changes, no emails)
    ./Ctl/dev/run.sh manage pdb_rir_status

    # apply changes / send notifications
    ./Ctl/dev/run.sh manage pdb_rir_status --commit

    # only a single ASN
    ./Ctl/dev/run.sh manage pdb_rir_status --asn 63311 --commit

    # cap the per-run notification burst (e.g. draining a first-deploy backlog)
    ./Ctl/dev/run.sh manage pdb_rir_status --commit --max-notifications 100

    # reset all RIR status / deletion timers (no notifications)
    ./Ctl/dev/run.sh manage pdb_rir_status --reset --commit

    # run the full logic but send no emails (e.g. on beta)
    ./Ctl/dev/run.sh manage pdb_rir_status --commit --mute-notifications

Options:
    --commit                 Apply changes and send notifications. Without it the
                             command runs in pretend mode (logs only).
    --asn ASN                Only check this single ASN.
    --limit N                Only process the first N networks (ordered by ASN).
    --max-age HOURS          Skip networks whose rir_status was updated less than
                             HOURS ago (avoids rechecking recently-checked nets).
    --reset                  Reset every network's rir_status / rir_status_updated
                             to the current RIR data and clear the notification
                             marker, resetting all deletion timers. Sends no
                             notifications.
    -o, --output FILE        With --reset, write all networks with a bad RIR
                             status to FILE.
    -M, --max-changes N      Abort (CommandError) if more than N networks flip
                             good<->bad in one run, guarding against mass flagging
                             from bad RIR data. Default 100.
    -N, --max-notifications N  Cap how many removal notifications are sent per run.
                             Networks beyond the cap keep rir_status_notified unset
                             and are handled on later runs, bounding the burst
                             (e.g. a first-deploy backlog, which --max-changes does
                             not cover). Default 100.
    --mute-notifications     Run the full flagging/deletion logic but send no
                             removal emails. Networks are still flagged and marked
                             notified (deletion proceeds) -- only the outbound
                             emails are suppressed. For envs like beta whose DB is
                             re-synced from prod daily. Mail is also suppressed
                             globally wherever MAIL_DEBUG is set.

## pdb_search_index.py

# Classes

## pdb_stats.py

Post stat breakdown for any given date.

## pdb_status.py

Checks entity status integrity (looks for orphaned entities).

## pdb_sync_orphaned_emails.py

Django management command to sync orphaned User.email to EmailAddress table.

This command finds users where User.email is set but doesn't exist in their
emailaddress_set, and creates the corresponding EmailAddress objects.

Usage:
    python manage.py pdb_sync_orphaned_emails
    python manage.py pdb_sync_orphaned_emails --dry-run

## pdb_ui_opt_flags.py

# Classes

## pdb_undelete.py

Restore soft-deleted objects.

## pdb_validate_data.py

# Classes

## pdb_whois.py

Command line whois.

## pdb_wipe.py

Wipe all peering data.

## runserver.py

# Classes
