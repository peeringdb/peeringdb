Generated on 2025-02-11 10:26:48.481231

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

## pdb_notify_2fa.py

Load initial data from another peeringdb instance using the REST API.

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

# Classes

## pdb_search_index.py

# Classes

## pdb_stats.py

Post stat breakdown for any given date.

## pdb_status.py

Checks entity status integrity (looks for orphaned entities).

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
