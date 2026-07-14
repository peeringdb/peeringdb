Generated on 2026-07-14 15:39:36.347825

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
