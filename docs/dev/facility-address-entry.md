# Facility address entry

Facility creation, suggestions, and address changes use Google address selection,
with a map pin as the fallback and email support for unresolved cases. The website user reviews the exact fields before saving. API clients may submit
ordinary address fields; the server requires an exact lookup match before saving. Address 2 and suite remain independently editable. Existing floor values are
preserved; the existing floor deprecation still permits clearing, not new values.

The selector sits immediately before Address 1 in both interfaces. On existing
facilities, Change location expands the selector while keeping the saved address
visible below it. Search suggestions support arrow-key navigation and Enter to
select. Use this location previews the confirmed fields in the address table,
marked Pending Save. Cancelling or changing the selection restores the saved
values; only saving the form writes the location.
Changing country clears the previous selection and pin. An open map moves to the
new country's overview; opening the map after changing country does the same.
The overview has no selected facility pin until the user chooses a point.

## Country policy

This is the country policy for this entry flow. Update this section when changing
policy, and keep `location.location_from_result` and its tests aligned.

- Resolve the selected coordinates to an explicit Google `locality` result;
  use `postal_town` only when no locality result exists. Resolve that city's
  Places details with English requested, requiring its city component to carry
  an English `languageCode` and its country to match the selected address.
  Multiple distinct city candidates, missing language metadata, or a non-English
  component require another selection or support. Never substitute an
  administrative area for city or take the city name from street-address details.
  Google may return local-language street components despite an English request:
  a Vienna street address can contain `Wien`, while the city result supplies
  `Vienna`. See [Google's language behavior](https://developers.google.com/maps/documentation/places/web-service/place-details#languagecode).
- Missing city names, names without letters, and names containing non-Latin
  letters require another selection or support. Latin accents are allowed.
  Latin script alone does not establish English. The language metadata supplies
  Google's identification of the city name's language; the user still reviews
  the selected municipality.
- Use the returned state/province short code wherever available, in every
  country. Use the full state/province name only when no code is returned.
- Require a state/province for US and CA. Elsewhere an absent subdivision remains
  empty. Never invent missing components.
- Require country, city, and a valid latitude/longitude pair. Country must match
  the selected country from PeeringDB's predefined country list.
- A place selection requires a street address and a postcode unless the country
  is in `NON_ZIPCODE_COUNTRIES`. Map selection permits missing street and postcode.
  Build Address 1 from Google's street number and route; supplementary building
  details belong in Address 2 or suite.
- On the map path, retain the user's pin, rounded to six decimal places. Reverse
  lookup supplies street, state and postcode from its first result, never
  replacement coordinates. City is resolved separately as above for both map and
  place selections. Reject unsuitable results instead of silently choosing another.

## Configuration and rollout

`FACILITY_ADDRESS_SELECTION_ENABLED` defaults to **True**. This controls both the
chooser and API enforcement. Set it to `False` explicitly for rollback or a
migration window; legacy raw-address writes and the previous forms then work.
The facility schema migration must be applied before deploying the application.

Configure `GOOGLE_GEOLOC_API_KEY` with **Places API (New)** and **Geocoding API**
enabled in its Google Cloud project, including billing and server-side API/key
restrictions. Configure a separate `GOOGLE_MAPS_API_KEY` for the **Maps JavaScript
API**, restricted to the site's HTTP referrers, and `GOOGLE_MAPS_MAP_ID` for the
map. Country viewport lookups use the server key. A missing map ID uses Google's
demo ID, suitable for development. Never put
the server key in the browser. The chooser shows Google Maps attribution and
any returned third-party attributions. Existing site terms/privacy pages must
cover Google Maps usage as described in the
[Places policies](https://developers.google.com/maps/documentation/places/web-service/policies).

Existing facilities require no backfill or reselection for unrelated edits.
Clients sending unchanged legacy address values may continue to do so, including
incomplete old locations. Once a location is selected, subsequent normalization
must preserve its confirmed values. Trusted corrections clear outdated provenance.

The trusted exceptions are Django admin/model writes and imports which write
models directly or use serializers without an HTTP request. There is no public
`trusted`, `skip_validation`, or administrator API bypass: all ordinary API users,
including staff, require a lookup match for creates and location changes.
Confirmed website locations use the separate save flow below. Bulk
`QuerySet.update()` imports that change a confirmed location must explicitly clear
`location_method` and
`location_place_id`, since they bypass model save hooks.

## Shared location service

`peeringdb_server.location` contains provider lookup, address extraction, location
versioning and signed confirmations without depending on the Facility model.
The website helpers accept `ref_tag` and optional `ref_id`; confirmation binds the entity type
as well as the actor, organization, entity ID and location version.
`location_views.LocationView.targets` holds entity adapters responsible for rollout and
create/update permission checks and confirmed saves. Only `fac` is registered. Supporting Organization
later requires its own adapter and save-path integration; unsupported entity types
are rejected before Google is called. Ordinary Organization editing is unchanged.

The provenance method uses the shared `LocationMethod` choices (`google`, `map`);
blank remains valid for unselected legacy locations and trusted corrections.

## API address writes

Existing clients continue to use `POST /api/fac` and `PUT /api/fac/<id>` with
ordinary address fields. No selection-specific fields are added to the public
facility serializer: `location_version` and `location_confirmation` belong only
to the website flow. With enforcement enabled, creates and changes to
`address1`, `city`, `state`, `zipcode`, `country`, `latitude` or `longitude` trigger
server-side Google lookup.
The server compares all five structured address fields against resolved results,
ignoring case. It does not ignore punctuation, accents, street abbreviations or
postcode formatting: `MAIN STREET` matches `Main Street`, but `Main St` does not.
City uses the English-city policy above. A match stores Google's canonical field
casing. Address 2 and suite remain independent of this comparison.

Client-supplied latitude and longitude are preserved if their geodesic distance
from a matching result is at most `LOCATION_MATCH_MAX_DISTANCE_KM`. This setting
is an environment-configurable number of kilometres, default **1.0**. For example,
`LOCATION_MATCH_MAX_DISTANCE_KM=0.25` permits 250 metres. More distant coordinates
return HTTP 400; they are never silently replaced. Supply both coordinates or
omit both (two null values also mean omitted); omitted coordinates come from the
matched result. Existing facility movement limits still apply separately.

On updates, omitted address fields are taken from the existing facility before
serializer defaults are applied. Explicit blanks and changed postcodes still
require an exact match. Unchanged legacy locations and unrelated edits need no lookup. Ordinary
API clients need no additional lookup request, confirmation token, or location
version field. Location changes during lookup are checked again under a row lock.

No match returns HTTP 400, for example:

```json
{"location": ["No exact address match was found. Check the address fields or select a location on the website."]}
```

Out-of-range coordinates also return 400; provider outages return 503 and lookup
throttling returns 429. No partial location is saved on failure. The website's
selection/map/support flow remains available when raw fields cannot be matched.

## Website selection helpers

These are normal Django JSON views for the website, outside the REST API. They
accept POST requests authenticated by the logged-in browser session and require
a CSRF token plus create or update permission on the target facility. API-key
authentication is not supported here; API clients use ordinary facility writes. Lookup permission is checked before
calling Google. `API_THROTTLE_LOCATION` sets the combined country/search/resolve/raw-address lookup limit
per actor (default `"60/minute"`); configure it through Django settings or the
environment using the usual `set_option` convention.
Results are plain JSON objects, without the REST response envelope.
`POST /data/location/country` accepts the same target and country fields and
returns a `viewport` with `north`, `south`, `east` and `west` bounds for the
country overview. It uses the same permissions, version checks and throttle;
it does not issue a location confirmation or select a facility pin.

1. Select a country and search with `POST /data/location/search`:

   ```json
   {"ref_tag": "fac", "org_id": 42, "country": "US", "input": "350 East Cermak Chicago", "session_token": "6286c673-4eac-4786-8067-dbc4e0ff3d63"}
   ```

   The result contains `suggestions`, each with `place_id` and `label`. Generate a
   UUID per autocomplete session and use it for that session's place resolution.
   After resolution, start a new UUID for the next search session.

2. Resolve a chosen result with `POST /data/location/resolve`:

   ```json
   {"ref_tag": "fac", "org_id": 42, "country": "US", "place_id": "GOOGLE_PLACE_ID", "session_token": "6286c673-4eac-4786-8067-dbc4e0ff3d63"}
   ```

   For map fallback, supply `latitude` and `longitude` instead of `place_id` and
   `session_token`. Zero is valid; both coordinates are required. Both selection
   methods together are rejected.

   To edit an existing facility, include `ref_id` and the `location_version`
   rendered into the page’s chooser in search, resolve and save requests. A stale version
   returns HTTP 409. For suggestions, use the configured `SUGGEST_ENTITY_ORG` as
   `org_id`, then include `suggest: true` in the create payload.

3. Display the returned `location` fields, map position, and `attributions` for
   review. The result also contains `method`, `place_id`, and a signed
   `location_confirmation`. Never replace displayed fields after confirmation.

4. Save confirmed website locations through `/data/location/save`, using POST
   for creation/suggestions or PUT for an existing facility. Send the same target
   fields plus `location_confirmation`, and put the ordinary facility fields in
   a `data` object. This Django view uses the shared facility serializer internally
   and passes the verified-flow token through server-owned context. The REST API
   does not consume confirmation tokens from request fields. Protected values may
   be omitted from `data` or supplied identically to the confirmation; other
   required facility fields remain required.

   Saves require the browser session and CSRF token, recheck permissions and the
   location version under a row lock, retain revision history and verification
   queue attribution, and run atomically. They share the existing write throttle.
   The response uses `data: [saved_facility]` for the existing website editor and
   contains neither selection-specific serializer field. Unrelated website edits
   continue through the ordinary facility REST endpoint without a lookup.

Confirmations expire after 15 minutes and are bound to the browser user,
organization, facility, and original location version. An API key cannot redeem
a browser user's confirmation. Permission is checked again at save; the
version is rechecked under a row lock. Refresh and resolve again after conflicts
or expiry. Confirmation is about location, not deduplicating create requests.

A valid confirmation avoids a second address lookup at save. Conflicting fields
return 400; concurrent location changes return 409; provider outages return 503;
throttling returns 429. These failures never enable unchecked free-text fallback.
For expiry, movement-limit, and conflict errors, the chooser displays the server's
explanation and recovery instruction, clears the rejected confirmation, and
restores the saved table values. Other editable-field errors preserve a valid
location selection while the user corrects those fields.
When the feature is disabled, website lookup/save routes return 400;
ordinary legacy writes work without the new match validation.

## Support and provenance

The last resort links to `DEFAULT_FROM_EMAIL`. The email draft suggests facility
name/ID, entered address, chosen point, and the reason for the correction. It does
not send mail or open a ticket automatically. Support reviews the exception and
uses an authorized admin workflow. Existing facility movement limits still apply.

Additional persistent provider provenance consists only of `location_method`
(`google` or `map`) and `location_place_id`. Actor/time are recorded through the
existing API revision history. Search results, attributions and full provider
responses are not stored. The validated normal facility fields remain PeeringDB
location data and appear in its public API/exports. The limited provenance fields
are internal, not new public API fields.

## Verification

`tests/test_facility_location.py` enables enforcement explicitly and exercises
mapping, exact persistence, exact raw-address matches, coordinate thresholds, rejected nonmatching/tampered writes, permissions, expiry,
concurrency, provider failures, legacy edits and rollback. The general suite uses
the disabled setting for its legacy API fixtures. Browser checks must cover both
`site` and `site_next` creation, suggestion and edit forms, invalidation after
search/country/pin changes, stale responses, errors, cancellation and support.
