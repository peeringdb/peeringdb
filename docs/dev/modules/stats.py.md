Generated from stats.py on 2023-01-17 22:33:48.733266

# peeringdb_server.stats

Load and maintain global stats (displayed in peeringdb footer).

# Functions
---

## gen_stats
`def gen_stats()`

Regenerates global statics to stats.__STATS['data']

---
## stats
`def stats()`

Returns dict of global statistics

Will return cached statistics according to `GLOBAL_STATS_CACHE_DURATION` setting

---
