Generated from stats.py on 2026-11-05 20:07:17.286006

# peeringdb_server.stats

Load and maintain global stats (displayed in peeringdb footer).

# Functions
---

## gen_stats
`def gen_stats()`

Regenerates global statics to stats.__STATS['data']

---
## reset_stats
`def reset_stats()`

Resets global stats to empty. Useful to reset for testing purposes.

---
## stats
`def stats()`

Returns dict of global statistics

Will return cached statistics according to `GLOBAL_STATS_CACHE_DURATION` setting

---
