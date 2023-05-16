Generated from util.py on 2023-04-12 10:09:44.563425

# peeringdb_server.util

Assorted utility functions for peeringdb site templates.

# Functions
---

## coerce_ipaddr
`def coerce_ipaddr(value)`

ipaddresses can have multiple formats that are equivalent.
This function will standardize a ipaddress string.

Note: this function is not a validator. If it errors
It will return the original string.

---
## generate_social_media_render_data
`def generate_social_media_render_data(data, social_media, insert_index, dismiss)`

Generate the data for rendering the social media in view.html.
This function will insert the generated social media data to `data`.

---
## v2_social_media_services
`def v2_social_media_services()`

Until v3 website is still set through the main `website` property
of the object, we need to skip it here so it is not rendered to
the UX as a pickable choice in the social media dropdown

---
