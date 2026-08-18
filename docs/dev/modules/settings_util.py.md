Generated from settings_util.py on 2026-08-15 04:17:12.049436

# peeringdb_server.settings_util

Helpers for reading and coercing Django settings.

Deliberately free of peeringdb_server imports: `validators` is imported by
`models`, so anything `validators` depends on must not reach back into the model
layer.

# Functions
---

## get_setting_time
`def get_setting_time(setting_name)`

A date/datetime setting as an aware datetime, or None when unset.

The dated rollout settings (MFA_FORCE_SOFT_START / _HARD_START,
IRR_AS_SET_CAP_SOFT_START / _HARD_START) load as naive datetimes, so every
consumer has to localize them before comparing to timezone.now(). `make_aware`
raises for a midnight that does not exist in the active timezone (DST) — treat
that as "no date configured" rather than breaking the caller.

---
