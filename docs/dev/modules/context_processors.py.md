Generated from context_processors.py on 2026-07-14 21:31:39.993597

# peeringdb_server.context_processors

# Functions
---

## admin_config
`def admin_config(request)`

Context processor to provide suggest entity org configuration values

---
## notification_banner
`def notification_banner(request)`

Context processor that exposes the site-wide notification banner
content to every template.

Resolution order: EnvironmentSetting DB override, falling back to the
NOTIFICATION_BANNER_CONTENT Django setting (which is itself populated
from an environment variable of the same name). When the resulting
value is empty the banner template renders nothing.

---
## theme_mode
`def theme_mode(request)`

Add theme preferences to all template contexts

---
## ui_version
`def ui_version(request)`

Context processor to determine the UI version to render
based on user's opt-in/opt-out flags.

---