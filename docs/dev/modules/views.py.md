Generated from views.py on 2022-06-14 09:38:55.484251

# peeringdb_server.views

View definitions:

- Login
- Logout
- Advanced search
- User Profile
- OAuth Profile
- Landing page
- Search results
- Entity views (network, facility, internet exchange and organization)
- Sponsorships
- User Registration

# Functions
---

## beta_sync_dt
`def beta_sync_dt()`

Return the next date for a beta sync.

This is currently hard coded to return 00:00Z for the
next Sunday.

---
## cancel_affiliation_request
`def cancel_affiliation_request(*args, **kwds)`

Cancel a user's affiliation request.

---
## export_permissions
`def export_permissions(user, entity)`

Return dict of permission bools for the specified user and entity
to be used in template context.

---
## field_help
`def field_help(model, field)`

Helper function return help_text of a model
field.

---
## request_api_search
`def request_api_search(request)`

Triggered by typing something in the main peeringdb search bar
without hitting enter (quasi autocomplete).

---
## request_search
`def request_search(request)`

Triggered by hitting enter on the main search bar.
Renders a search result page.

---
## validator_result_cache
`def validator_result_cache(request, cache_id)`

Return CSV data from cache.

---
## view_about
`def view_about(request)`

Render page containing about.

---
## view_advanced_search
`def view_advanced_search(request)`

View for advanced search.

---
## view_affiliate_to_org
`def view_affiliate_to_org(request, *args, **kwargs)`

Allow the user to request affiliation with an organization through
an ASN they provide.

---
## view_aup
`def view_aup(request)`

Render page containing acceptable use policy.

---
## view_close_account
`def view_close_account(request, *args, **kwargs)`

Set user's account inactive, delete email addresses and API keys and logout the session.

---
## view_component
`def view_component(request, component, data, title, perms=None, instance=None, **kwargs)`

Generic component view.

---
## view_exchange
`def view_exchange(request, id)`

View exchange data for exchange specified by id.

---
## view_facility
`def view_facility(request, id)`

View facility data for facility specified by id.

---
## view_index
`def view_index(request, errors=None)`

Landing page view.

---
## view_network
`def view_network(request, id)`

View network data for network specified by id.

---
## view_organization
`def view_organization(request, id)`

View organization data for org specified by id.

---
## view_partnerships
`def view_partnerships(request)`

View current partners.

---
## view_password_reset
`def view_password_reset(request, *args, **kwargs)`

Password reset initiation view.

---
## view_registration
`def view_registration(request, *args, **kwargs)`

User registration page view.

---
## view_request_ownership
`def view_request_ownership(*args, **kwds)`

Render the form that allows users to request ownership
to an unclaimed organization.

---
## view_simple_content
`def view_simple_content(request, content_name)`

Render the content in templates/{{ content_name }} inside
the peeringdb layout.

---
## view_sponsorships
`def view_sponsorships(request)`

View current sponsorships.

---
## view_username_retrieve
`def view_username_retrieve(request, *args, **kwargs)`

Username retrieval view.

---
## view_username_retrieve_complete
`def view_username_retrieve_complete(request, *args, **kwargs)`

Username retrieval completion view.

Show the list of usernames associated to an email if
the correct secret is provided.

---
## view_username_retrieve_initiate
`def view_username_retrieve_initiate(request, *args, **kwargs)`

Username retrieval initiate view.

---
## watch_network
`def watch_network(request, id)`

Adds data-change notifications for the specified network (id)
for the rquesting user.

User needs write permissions to the network to be eligible for data change
notifications.

---
# Classes
---

## ApplicationDelete

```
ApplicationDelete(peeringdb_server.views.ApplicationOwnerMixin, oauth2_provider.views.application.ApplicationDelete)
```

OAuth mixin it that filters application queryset for ownership
considering either the owning user or the owning organization.

For organizations any user in the administrator group for the organization
may manage the oauth application


## ApplicationDetail

```
ApplicationDetail(peeringdb_server.views.ApplicationOwnerMixin, oauth2_provider.views.application.ApplicationDetail)
```

OAuth mixin it that filters application queryset for ownership
considering either the owning user or the owning organization.

For organizations any user in the administrator group for the organization
may manage the oauth application


## ApplicationFormMixin

```
ApplicationFormMixin(builtins.object)
```

Used for oauth application update and registration process

Will add an `org` field to the form and make sure it is filtered to only contain
organizations the requesting user has management permissions to


### Methods

#### get_form_class
`def get_form_class(self)`

Returns the form class for the application model

---

## ApplicationList

```
ApplicationList(peeringdb_server.views.ApplicationOwnerMixin, oauth2_provider.views.application.ApplicationList)
```

OAuth mixin it that filters application queryset for ownership
considering either the owning user or the owning organization.

For organizations any user in the administrator group for the organization
may manage the oauth application


## ApplicationOwnerMixin

```
ApplicationOwnerMixin(builtins.object)
```

OAuth mixin it that filters application queryset for ownership
considering either the owning user or the owning organization.

For organizations any user in the administrator group for the organization
may manage the oauth application


## ApplicationRegistration

```
ApplicationRegistration(peeringdb_server.views.ApplicationFormMixin, oauth2_provider.views.application.ApplicationRegistration)
```

Used for oauth application update and registration process

Will add an `org` field to the form and make sure it is filtered to only contain
organizations the requesting user has management permissions to


### Methods

#### form_valid
`def form_valid(self, form)`

If the form is valid, save the associated model.

---
#### get_form
`def get_form(self)`

Return an instance of the form to be used in this view.

---

## ApplicationUpdate

```
ApplicationUpdate(peeringdb_server.views.ApplicationOwnerMixin, peeringdb_server.views.ApplicationFormMixin, oauth2_provider.views.application.ApplicationUpdate)
```

OAuth mixin it that filters application queryset for ownership
considering either the owning user or the owning organization.

For organizations any user in the administrator group for the organization
may manage the oauth application


### Methods

#### form_valid
`def form_valid(self, form)`

If the form is valid, save the associated model.

---

## DoNotRender

```
DoNotRender(builtins.object)
```

Instance of this class is sent when a component attribute does not exist,
this can then be type checked in the templates to remove non existant attribute
rows while still allowing attributes with nonetype values to be rendered.


### Class Methods

#### permissioned
`def permissioned(cls, value, user, namespace, explicit=False)`

Check if the user has permissions to the supplied namespace
returns a DoNotRender instance if not, otherwise returns
the supplied value.

---

## LoginView

```
LoginView(django_security_keys.ext.two_factor.views.LoginView)
```

Extend the `LoginView` class provided
by `two_factor` because some
PDB specific functionality and checks need to be added.


### Methods

#### done
`def done(self, form_list, **kwargs)`

User authenticated successfully, set language options.

---
#### get
`def get(self, *args, **kwargs)`

If a user is already authenticated, don't show the
login process, instead redirect to /

---
#### get_context_data
`def get_context_data(self, form, **kwargs)`

If post request was rate limited the rate limit message
needs to be communicated via the template context.

---
#### get_device
`def get_device(self, step=None)`

Override this to can enable EmailDevice as a
challenge device for one time passwords.

---
#### get_email_device
`def get_email_device(self)`

Return an EmailDevice instance for the requesting user
which can be used for one time passwords.

---
#### get_form_kwargs
`def get_form_kwargs(self, step=None)`

AuthenticationTokenForm requires the user kwarg.

---
#### get_redirect_url
`def get_redirect_url(self)`

Specify which redirect urls are valid.

---
#### post
`def post(self, *args, **kwargs)`

Posts to the `auth` step of the authentication
process need to be rate limited.

---

## OrganizationLogoUpload

```
OrganizationLogoUpload(django.views.generic.base.View)
```

Handles public upload and setting of organization logo (#346)


### Methods

#### delete
`def delete(self, request, id)`

delete the logo

---
#### post
`def post(self, request, id)`

upload and set a new logo

---
