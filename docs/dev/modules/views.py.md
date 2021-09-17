Generated from views.py on 2021-09-17 13:22:42.251452

# peeringdb_server.views

View definitions

- Login
- Logout
- Advanced search
- User Profile
- oAuth Profile
- Landing page
- Search results
- Entity views (network, facility, internet exchange and organization)
- Sponsorships
- User Registration

# Functions
---

## beta_sync_dt
`def beta_sync_dt()`

Returns the next date for a beta sync

This is currently hard coded to return 00:00Z for the
next sunday

---
## cancel_affiliation_request
`def cancel_affiliation_request(request, *args, **kwargs)`

Cancels a user's affiliation request

---
## export_permissions
`def export_permissions(user, entity)`

returns dict of permission bools for the specified user and entity

to be used in template context

---
## field_help
`def field_help(model, field)`

helper function return help_text of a model
field

---
## request_api_search
`def request_api_search(request)`

Triggered off of typing something in the main peeringdb searchbar
without hitting enter (quasi autocomplete)

---
## request_search
`def request_search(request)`

Triggered off of hitting enter on the main search bar
Renders a search result page.

---
## view_about
`def view_about(request)`

Render page containing about

---
## view_advanced_search
`def view_advanced_search(request)`

View for advanced search

---
## view_affiliate_to_org
`def view_affiliate_to_org(request, *args, **kwargs)`

Allows the user to request affiliation with an organization through
an ASN they provide

---
## view_aup
`def view_aup(request)`

Render page containing acceptable use policy

---
## view_component
`def view_component(request, component, data, title, perms=None, instance=None, **kwargs)`

Generic component view

---
## view_exchange
`def view_exchange(request, id)`

View exchange data for exchange specified by id

---
## view_facility
`def view_facility(request, id)`

View facility data for facility specified by id

---
## view_index
`def view_index(request, errors=None)`

landing page view

---
## view_network
`def view_network(request, id)`

View network data for network specified by id

---
## view_organization
`def view_organization(request, id)`

View organization data for org specified by id

---
## view_partnerships
`def view_partnerships(request)`

View current partners

---
## view_password_reset
`def view_password_reset(request, *args, **kwargs)`

password reset initiation view

---
## view_registration
`def view_registration(request, *args, **kwargs)`

user registration page view

---
## view_request_ownership
`def view_request_ownership(request, *args, **kw)`

Renders the form that allows users to request ownership
to an unclaimed organization

---
## view_simple_content
`def view_simple_content(request, content_name)`

Renders the content in templates/{{ content_name }} inside
the peeringdb layout

---
## view_sponsorships
`def view_sponsorships(request)`

View current sponsorships

---
## view_username_retrieve
`def view_username_retrieve(request, *args, **kwargs)`

username retrieval view

---
## view_username_retrieve_complete
`def view_username_retrieve_complete(request, *args, **kwargs)`

username retrieval completion view

show the list of usernames associated to an email if
the correct secret is provided

---
## view_username_retrieve_initiate
`def view_username_retrieve_initiate(request, *args, **kwargs)`

username retrieval initiate view

---
# Classes
---

## DoNotRender

```
DoNotRender(builtins.object)
```

Instance of this class is sent when a component attribute does not exist,
this can then be type checked in the templates to remove non existant attribute
rows while still allowing attributes with nonetype values to be rendered


### Class Methods

#### permissioned
`def permissioned(cls, value, user, namespace, explicit=False)`

Check if the user has permissions to the supplied namespace
returns a DoNotRender instance if not, otherwise returns
the supplied value

---

## LoginView

```
LoginView(two_factor.views.core.LoginView)
```

We extend the `LoginView` class provided
by `two_factor` because we need to add some
pdb specific functionality and checks


### Methods

#### done
`def done(self, form_list, **kwargs)`

User authenticated successfully, set language options

---
#### get
`def get(self, *args, **kwargs)`

If a user is already authenticated, don't show the
login process, instead redirect to /

---
#### get_context_data
`def get_context_data(self, form, **kwargs)`

If post request was rate limited the rate limit message
needs to be communicated via the template context

---
#### get_device
`def get_device(self, step=None)`

We override this so we can enable EmailDevice as a
challenge device for one time passwords

---
#### get_email_device
`def get_email_device(self)`

Returns an EmailDevice instance for the requesting user
which can be used for one time passwords.

---
#### get_redirect_url
`def get_redirect_url(self)`

Specifies which redirect urls are valid

---
#### post
`def post(self, *args, **kwargs)`

Posts to the `auth` step of the authentication
process need to be rate limited

---
