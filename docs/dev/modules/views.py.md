Generated from views.py on 2025-02-11 10:26:48.481231

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
## build_template_environment
`def build_template_environment(result, geo, version, request, q)`

Constructs the environment dictionary for rendering the template.

Args:
    result: The search results.
    geo: The geographical search parameters.
    version: The version of the search functionality.
    q: Search query string

Returns:
    dict: The environment variables for the template.

---
## cancel_affiliation_request
`def cancel_affiliation_request(request, uoar_id)`

Cancel a user's affiliation request.

---
## combine_search_results
`def combine_search_results(result)`

Combines all search results into a single list.

Args:
    result: Dictionary containing search results by category

Returns:
    list: Combined search results

---
## export_permissions
`def export_permissions(user, entity)`

Return dict of permission bools for the specified user and entity
to be used in template context.

---
## export_permissions_campus
`def export_permissions_campus(user, entity)`

Return dict of permission bools for the specified user and entity
to be used in template context.

---
## extract_query
`def extract_query(request, version)`

Extracts the query and geographical parameters from the request.

Args:
    request: The HTTP request object.
    version: The version of the search functionality.

Returns:
    tuple: (query list, geo dictionary, original query string)

---
## field_help
`def field_help(model, field)`

Helper function return help_text of a model
field.

---
## get_page_range
`def get_page_range(paginator, current_page, show_pages=5)`

Calculate which page numbers to show in pagination.
Args:
paginator: The paginator instance
current_page: Current page number
show_pages: Number of pages to show on each side of current page
Returns:
list: Page numbers to display

---
## handle_asn_query
`def handle_asn_query(q, version)`

Checks if the query is for a direct ASN or AS and handles redirection.

Args:
    q: The list of query terms.

Returns:
    HttpResponseRedirect or None

---
## handle_city_country_search
`def handle_city_country_search(list_of_words, idx, q, query_idx, geo)`

Handles city and country search and updates the geo dictionary.

This will send of a request to google maps to geocode the city and set the
lat and long to `geo`. The distance is set to 50km.

Args:
    list_of_words: The list of words from the search query.
    idx: The index of the "near" or "in" keyword.
    q: The original list of queries.
    query_idx: The index of the current query in the list.
    geo: A dictionary to hold geographical search parameters.

Returns:
    dict[str, Union[str, float]]: Updated geo dictionary.

---
## handle_coordinate_search
`def handle_coordinate_search(list_of_words, idx, q, query_idx, geo)`

Handles coordinate search and updates the geo dictionary.

Args:
    list_of_words: The list of words from the search query.
    idx: The index of the "near" keyword.
    q: The original list of queries.
    query_idx: The index of the current query in the list.
    geo: A dictionary to hold geographical search parameters.

Returns:
    dict[str, Union[str, float]]: Updated geo dictionary.

---
## handle_proximity_entity_search
`def handle_proximity_entity_search(list_of_words, idx, q, query_idx, geo)`

Handles proximity entity search and updates the geo dictionary.

Will search for an entity (fac, org etc.) by name and return its lat/lng
to `geo` if found. The distance is set to 20km.

Args:
    list_of_words: The list of words from the search query.
    idx: The index of the "near" keyword.
    q: The original list of queries.
    query_idx: The index of the current query in the list.
    geo: A dictionary to hold geographical search parameters.

Returns:
    dict[str, Union[str, float]]: Updated geo dictionary.

---
## perform_search
`def perform_search(q, geo, version, original_query)`

Executes the search based on the query and version.

Args:
    q: The list of query terms.
    geo: The geographical search parameters.
    version: The version of the search functionality.
    original_query: The original search query string.

Returns:
    dict: Search results.

---
## process_in_search
`def process_in_search(q, geo)`

Handles "IN" search patterns.
Extracts and processes the "IN" search patterns from the query string
and updates the geo dictionary which includes the geographical search parameters.

Args:
    q: The list of query terms.
    geo: A dictionary to hold geographical search parameters.

Returns:
    dict[str, Union[str, float]]: Updated geo dictionary.

---
## process_near_search
`def process_near_search(q, geo)`

Handles "NEAR" search patterns.
Extracts and processes the "NEAR" search patterns from the query string
and updates the geo dictionary which includes the geographical search parameters.

Args:
    q: The list of query terms.
    geo: A dictionary to hold geographical search parameters.

Returns:
    dict[str, Union[str, float]]: Updated geo dictionary.

---
## profile_add_email
`def profile_add_email(request)`

Allows a user to add an additional email address

---
## profile_delete_email
`def profile_delete_email(request)`

Allows a user to remove one of their emails

---
## profile_set_primary_email
`def profile_set_primary_email(request)`

Allows a user to set a different email address as their primary
contact point for peeringdb

---
## render_search_result
`def render_search_result(request, version=2)`

Triggered by hitting enter on the main search bar.
Renders a search result page based on the query provided.

Args:
    request: The HTTP request object containing the search query.
    version: The version of the search functionality to use (default is 2).

Returns:
    HttpResponse: The rendered search result page.

---
## request_api_search
`def request_api_search(request)`

Triggered by typing something in the main peeringdb search bar
without hitting enter (quasi autocomplete).

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
`def view_affiliate_to_org(request)`

Allow the user to request affiliation with an organization through
an ASN they provide.

---
## view_aup
`def view_aup(request)`

Render page containing acceptable use policy.

---
## view_campus
`def view_campus(request, id)`

View campus data for campus specified by id.

---
## view_carrier
`def view_carrier(request, id)`

View carrier data for carrier specified by id.

---
## view_close_account
`def view_close_account(request)`

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
## view_healthcheck
`def view_healthcheck(request)`

Performs a simple database version query

---
## view_index
`def view_index(request, errors=None)`

Landing page view.

---
## view_name_change
`def view_name_change(request)`

Allows a user to change their first name and last name

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
`def view_password_reset(request)`

Password reset initiation view.

---
## view_profile_name_change
`def view_profile_name_change(request)`

Renders the name change form on the profile page.

---
## view_registration
`def view_registration(request)`

User registration page view.

---
## view_remove_org_affiliation
`def view_remove_org_affiliation(request)`

Remove organization affiliation of the user

---
## view_request_ownership
`def view_request_ownership(request)`

Render the form that allows users to request ownership
to an unclaimed organization.

---
## view_self_entity
`def view_self_entity(request, data_type)`

Redirect self entity API to the corresponding url

---
## view_set_user_org
`def view_set_user_org(request)`

Sets primary organization of the user

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
`def view_username_retrieve(request)`

Username retrieval view.

---
## view_username_retrieve_complete
`def view_username_retrieve_complete(request)`

Username retrieval completion view.

Show the list of usernames associated to an email if
the correct secret is provided.

---
## view_username_retrieve_initiate
`def view_username_retrieve_initiate(request)`

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

#### attempt_passkey_auth
`def attempt_passkey_auth(self, request, **kwargs)`

Wrap attempt_passkey_auth so we can set a session
property to indicate that the passkey auth was
used

---
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
#### get_form
`def get_form(self, *args, **kwargs)`

Returns the form for the step

---
#### get_form_kwargs
`def get_form_kwargs(self, step=None)`

Returns the keyword arguments for instantiating the form
(or formset) on the given step.

---
#### get_redirect_url
`def get_redirect_url(self)`

Specify which redirect urls are valid.

---
#### post
`def post(self, args, kwargs)`

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

## TwoFactorSetupView

```
TwoFactorSetupView(two_factor.views.core.SetupView)
```

View for handling OTP setup using a wizard.

The first step of the wizard shows an introduction text, explaining how OTP
works and why it should be enabled. The user has to select the verification
method (generator / call / sms) in the second step. Depending on the method
selected, the third step configures the device. For the generator method, a
QR code is shown which can be scanned using a mobile phone app and the user
is asked to provide a generated token. For call and sms methods, the user
provides the phone number which is then validated in the final step.


### Methods

#### post
`def post(self, request, *args, **kwargs)`

Check if the current step is still available. It might not be if
conditions have changed.

---
