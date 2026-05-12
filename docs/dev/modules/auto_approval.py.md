Generated from auto_approval.py on 2026-05-12 15:10:38.212377

# peeringdb_server.auto_approval

# Functions
---

## _validate_ixf_feed
`def _validate_ixf_feed(ixf_ixp_member_list_url, submitting_org)`

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

---