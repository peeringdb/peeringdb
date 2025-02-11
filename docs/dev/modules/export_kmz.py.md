Generated from export_kmz.py on 2025-02-11 10:26:48.481231

# peeringdb_server.export_kmz

# Functions
---

## collect_carriers
`def collect_carriers(path=None)`

This function collects all the carriers and relates them to facilities.

---
## collect_exchanges
`def collect_exchanges(path=None)`

This function collects all the exchanges and relates them to facilities.

---
## collect_networks
`def collect_networks(path=None)`

This function collects all the networks and relates them to facilities.

---
## fac_export_kmz
`def fac_export_kmz(limit=None, path=None, output_dir=None)`

This function exports facility data to a KMZ file.
It reads the facility data from a JSON file, creates a KML object, and adds points to a folder in the KML.
Each point represents a facility with its name, notes, and coordinates.
The KML is then saved as a KMZ file.

If `output_dir` is not passed, it uses `path`

---
