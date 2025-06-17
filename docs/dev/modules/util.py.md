Generated from util.py on 2025-06-17 14:04:27.689296

# peeringdb_server.util

Assorted utility functions for peeringdb site templates.

# Functions
---

## add_kmz_overlay_watermark
`def add_kmz_overlay_watermark(kml)`

add overlay watermark in kmz

Args:
    kml: Kml
Returns:
   None

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
## get_template
`def get_template(request, template_name)`

Loads a template using UI version resolution based on request.

This is a wrapper around Django's template loader to resolve
and load the correct template version (default or *_next).

Parameters:
    request (HttpRequest): The HTTP request object.
    template_name (str): The original template path.

Returns:
    Template: The Django template object.

---
## render
`def render(request, template_name, context=None, *args, **kwargs)`

Renders a template using UI version resolution based on request.

This is a wrapper around Django's default render function that uses
`resolve_template` to determine the correct template path.

Parameters:
    request (HttpRequest): The HTTP request object.
    template_name (str): The original template path.
    context (dict, optional): The context data passed to the template.

Returns:
    HttpResponse: The rendered template response.

---
## resolve_template
`def resolve_template(request, template_name)`

Resolves the template path based on user preferences for the UI version.

This function checks whether the request should use the 'next' version
of the UI templates (e.g., 'site_next/' or 'two_factor_next/') based on:
  - User flags (opt_flags with UI_NEXT and UI_NEXT_REJECTED),
  - or a global setting for unauthenticated users.

Parameters:
    request (HttpRequest): The HTTP request object.
    template_name (str): The original template path.

Returns:
    str: The resolved template path (may be modified to '..._next/').

---
## v2_social_media_services
`def v2_social_media_services()`

Until v3 website is still set through the main `website` property
of the object, we need to skip it here so it is not rendered to
the UX as a pickable choice in the social media dropdown

---
