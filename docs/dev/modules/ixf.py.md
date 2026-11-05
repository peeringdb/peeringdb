Generated from ixf.py on 2026-11-05 20:07:16.953937

# peeringdb_server.ixf

IX-F importer implementation.

Handles import of IX-F feeds, creation of suggestions for networks and exchanges
to follow.

Handles notifications of networks and exchanges as part of that process.

A substantial part of the import logic is handled through models.py::IXFMemberData

# Functions
---

## _safe_key_value
`def _safe_key_value(value)`

Return `value` if it is a string or an integer below 2**61 - 1, raise
TypeError otherwise.

Strings have randomized hashes, and such integers hash to themselves, so
no two of them share a hash. Their dict slots can still be steered to
collide, but nothing like the cost of identical hashes, and the callers
check the deadline per connection.

---
## count_entries
`def count_entries(data, limit)`

Count the members, connections, vlans and interfaces of IX-F data,
stopping once the count passes `limit`.

---
## encode_member_data
`def encode_member_data(member)`

Return the value IXFMemberData.data stores for a member: the member's
JSON, stored as a JSON string as set_data(json.dumps(member)) does.

---
## quote_feed_value
`def quote_feed_value(value, max_length=45)`

Quote a value taken from an IX-F feed for an error message that is
mailed out, so the feed cannot put free text into the mail: characters
that do not occur in an address, ASN or VLAN id are replaced and the
length is capped (45 is the longest textual IPv6 address).

---
## snapshot_bytes
`def snapshot_bytes(data, limit)`

Return how many bytes of member snapshots the proposal rows for IX-F
data store: every vlan entry of a member gets a row holding the whole
member. Stops once the total passes `limit`.

---
## vlan_group_key
`def vlan_group_key(vlan_id)`

Return the key a feed's vlan_id groups and pairs vlans by.

Only IX-F vlan ids (integers 0 to 4095) and null group; anything else
gets a key of its own. CPython's integer hashes are predictable, so
arbitrary ids can be chosen to collide in a dict and make every insert
scan all the previous ones.

---
# Classes
---

## MultipleVlansInPrefix

```
MultipleVlansInPrefix(builtins.ValueError)
```

This error is raised when an IX-F export contains
multiple vlan ids for the prefixes defined in the processed ixlan.

Since peeringdb treats each vlan as it's own exchange this currently
is not a compatible setup for import (see #889).


### Methods

#### \__init__
`def __init__(self, importer, conflict_info, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## PostMortem

```
PostMortem(builtins.object)
```

Generate postmortem report for IX-F import.


### Methods

#### _process_log_entry
`def _process_log_entry(self, log, entry)`

Process a single IX-F import log entry.

Argument(s):

    - log <IXLanIXFMemberImportLog>
    - entry <IXLanIXFMemberImportLogEntry>

---
#### _process_logs
`def _process_logs(self, limit=100)`

Process IX-F import logs.

KeywordArgument(s):

     - limit <int=100>: limit amount of import logs to process
      max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

---
#### generate
`def generate(self, asn, **kwargs)`

Generate and return a new postmortem report.

Argument(s):

    - asn <int>: asn of the network to run postmortem
      report for

Keyword Argument(s):

    - limit <int=100>: limit amount of import logs to process
      max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

Returns:

    - dict: postmortem report

---
#### reset
`def reset(self, asn, **kwargs)`

Reset for a fresh run.

Argument(s):

    - asn <int>: asn of the network to run postormem
      report for

Keyword Argument(s):

    - limit <int=100>: limit amount of import logs to process
      max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

---
