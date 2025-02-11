Generated on 2025-02-11 10:26:48.481231

## [admin.py](/docs/dev/modules/admin.py.md)

django-admin interface definitions

This is the interface used by peeringdb admin-com that is currently
exposed at the path `/cp`.

New admin views wrapping HandleRef models need to extend the
`SoftDeleteAdmin` class.

Admin views wrapping verification-queue enabled models need to also
add the `ModelAdminWithVQCtrl` Mixin.

Version history is implemented through django-handleref.

## [admin_commandline_tools.py](/docs/dev/modules/admin_commandline_tools.py.md)

Defines CLI wrappers for django commands that should
be executable through the django-admin interface.

Extend the CommandLineToolWrapper class and call the
register_tool decorator to add support for a new django
command to exposed in this manner.

## [api_cache.py](/docs/dev/modules/api_cache.py.md)

Handle loading of api-cache data.

## [api_key_views.py](/docs/dev/modules/api_key_views.py.md)

Views for organization api key management.

## [api_schema.py](/docs/dev/modules/api_schema.py.md)

Augment REST API schema to use for open-api schema generation.

open-api schema generation leans heavily on automatic generation
implemented through the django-rest-framework.

Specify custom fields to be added to the generated open-api schema.

## [apps.py](/docs/dev/modules/apps.py.md)

Django apps configuration.

## [auth.py](/docs/dev/modules/auth.py.md)

Authentication utilities for securing API access.

Provides decorators to enforce Basic Authentication or API Key Authentication on IX-F import preview.

## [autocomplete_views.py](/docs/dev/modules/autocomplete_views.py.md)

Autocomplete views.

Handle most autocomplete functionality found in peeringdb.

Note: Quick search behavior is specified in search.py

## [context.py](/docs/dev/modules/context.py.md)

Define custom context managers.

## [context_processors.py](/docs/dev/modules/context_processors.py.md)

# Functions

## [data_views.py](/docs/dev/modules/data_views.py.md)

This holds JSON views for various data sets.

These are needed for filling form-selects for editable
mode in UX.

## [db_router.py](/docs/dev/modules/db_router.py.md)

Custom django database routers.

Split read and write database connections if needed.

## [deskpro.py](/docs/dev/modules/deskpro.py.md)

DeskPro API Client used to post and retrieve support ticket information
from the deskpro API.

## [documents.py](/docs/dev/modules/documents.py.md)

# Functions

## [exceptions.py](/docs/dev/modules/exceptions.py.md)

# Functions

## [export_kmz.py](/docs/dev/modules/export_kmz.py.md)

# Functions

## [export_views.py](/docs/dev/modules/export_views.py.md)

Define export views used for IX-F export and advanced search file download.

## [forms.py](/docs/dev/modules/forms.py.md)

Custom django forms.

Note: This does not includes forms pointed directly
at the REST api to handle updates (such as /net, /ix, /fac or /org endpoints).

Look in rest.py and serializers.py for those.

## [geo.py](/docs/dev/modules/geo.py.md)

Utilities for geocoding and geo normalization.

## [import_views.py](/docs/dev/modules/import_views.py.md)

Define IX-F import preview, review and post-mortem views.

## [inet.py](/docs/dev/modules/inet.py.md)

RDAP lookup and validation.

Network validation.

Prefix renumbering.

## [ixf.py](/docs/dev/modules/ixf.py.md)

IX-F importer implementation.

Handles import of IX-F feeds, creation of suggestions for networks and exchanges
to follow.

Handles notifications of networks and exchanges as part of that process.

A substantial part of the import logic is handled through models.py::IXFMemberData

## [log.py](/docs/dev/modules/log.py.md)

# Classes

## [mail.py](/docs/dev/modules/mail.py.md)

Utility functions for emailing users and admin staff.

## [maintenance.py](/docs/dev/modules/maintenance.py.md)

Django middleware to handle maintenance mode.

## [middleware.py](/docs/dev/modules/middleware.py.md)

Custom django middleware.

## [mock.py](/docs/dev/modules/mock.py.md)

Handle generation of mock data for testing purposes.

## [models.py](/docs/dev/modules/models.py.md)

Django model definitions (database schema).

## django-peeringdb

peeringdb_server uses the abstract models from django-peeringdb.

Often, it makes the most sense for a field to be added to the abstraction
in django-peeringdb, so it can be available for people using local snapshots of the databases.

Generally speaking, if the field is to be added to the REST API output,
it should be added through django-peeringdb.

Fields to facilitate internal operations of peeringdb on the other hand, DO NOT need to be added to django-peeringdb.

## migrations

For concrete models, django-peeringdb and peeringdb_server maintain separate model migrations.

When adding new fields to django-peeringdb make sure migration files for the schema changes exist in both places.

Please open a merge request in peeringdb/django-peeringdb for the field addition as well.

## [oauth_views.py](/docs/dev/modules/oauth_views.py.md)

# Classes

## [org_admin_views.py](/docs/dev/modules/org_admin_views.py.md)

View for organization administrative actions (/org endpoint).

## [permissions.py](/docs/dev/modules/permissions.py.md)

Utilities for permission handling.

Permission logic is handled through django-grainy.

API key auth is handled through djangorestframework-api-key.

Determine permission holder from request (api key or user).

Read only user api key handling.

Censor API output data according to permissions using grainy Applicators.

## [renderers.py](/docs/dev/modules/renderers.py.md)

REST API renderer.

Ensure valid json output of the REST API.

## [request.py](/docs/dev/modules/request.py.md)

Django HTTPRequest utilities.

## [rest.py](/docs/dev/modules/rest.py.md)

REST API view definitions.

REST API path routing.

REST API permission checking (facilitated through django-grainy).

REST API error handling.

REST API list filtering logic.

peeringdb-py client compatibility checking.

The peeringdb REST API is implemented through django-rest-framework.

## [rest_throttles.py](/docs/dev/modules/rest_throttles.py.md)

Custom rate limit handlers for the REST API.

## [search.py](/docs/dev/modules/search.py.md)

Search implementation used for the peeringdb top search bar, name
searches through the api `name_search` filter, as well as advanced
search functionality.

Search logic is handled by django-haystack and whoosh.

Refer to search_indexes.py for search index definition.

## [search_indexes.py](/docs/dev/modules/search_indexes.py.md)

Defines django-haystack search indexes.

## [search_v2.py](/docs/dev/modules/search_v2.py.md)

Search v2 implementation used for the PeeringDB top search bar.

This module constructs and executes advanced Elasticsearch queries with
support for geo-based filtering, keyword logic (AND/OR), and partial
IPv6 matching. It includes functionality to prioritize exact and "OR"
term matches and organizes results alphabetically.

## [serializers.py](/docs/dev/modules/serializers.py.md)

REST API Serializer definitions.
REST API POST / PUT data validators.

New serializers should extend ModelSerializer class, which is a custom extension
of django-rest-framework's ModelSerializer.

Custom ModelSerializer implements logic for the expansion of relationships driven by the `depth` url parameter. The depth parameter indicates how many objects to recurse into.

Special api filtering implementation should be done through the `prepare_query`
method.

## [settings.py](/docs/dev/modules/settings.py.md)

(Being DEPRECATED) django settings preparation.

This is mostly DEPRECATED at this point and any new settings should be directly
defined in mainsite/settings.

## [signals.py](/docs/dev/modules/signals.py.md)

Django signal handlers

- org usergroup creation
- entity count updates (fac_count, net_count etc.)
- geocode when address model (org, fac) is saved
- verification queue creation on new objects
- asn rdap automation to automatically grant org / network to user
- user to org affiliation handling when targeted org has no users
  - notify admin-com
- CORS enabling for GET api requests

## [stats.py](/docs/dev/modules/stats.py.md)

Load and maintain global stats (displayed in peeringdb footer).

## [urls.py](/docs/dev/modules/urls.py.md)

Django url to view routing.

## [util.py](/docs/dev/modules/util.py.md)

Assorted utility functions for peeringdb site templates.

## [validators.py](/docs/dev/modules/validators.py.md)

peeringdb model / field validators

## [views.py](/docs/dev/modules/views.py.md)

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
