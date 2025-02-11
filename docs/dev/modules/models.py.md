Generated from models.py on 2025-02-11 10:26:48.481231

# peeringdb_server.models

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

# Functions
---

## default_time_e
`def default_time_e()`

Returns datetime set to today with a time of 23:59:59.

---
## default_time_s
`def default_time_s()`

Returns datetime set to today with a time of 00:00:00.

---
## is_suggested
`def is_suggested(entity)`

Check if the network, facility or exchange is a suggested
entity (is it a memeber of the organization designated to
hold suggested entities).

---
## validate_PUT_ownership
`def validate_PUT_ownership(permission_holder, instance, data, fields)`

Helper function that checks if a user or API key has write perms to
the instance provided as well as write perms to any
child instances specified by fields as they exist on
the model and in data.

Example:

validate_PUT_ownership(
  request.user,
  network_contact,
  {
    "network": 123,
    ...
  },
  ["network"]
)

will check that the user has write perms to

  1. <NetworkContact> network_contact
  2. <Network> network_contact.network
  3. <Network> network(id=123)

if any fail the permission check False is returned.

---
# Classes
---

## Campus

```
Campus(peeringdb_server.models.ProtectedMixin, django_peeringdb.models.abstract.CampusBase, peeringdb_server.models.SocialMediaMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a peeringdb campus


### Instanced Attributes

These attributes / properties will be available on instances of the class

- city (`@property`): Return city of related facility object
- country (`@property`): Return country of related facility object
- grainy_namespace (`@property`): None
- latitude (`@property`): Return latitude of related facility object
- longitude (`@property`): Return longitude of related facility object
- search_result_name (`@property`): This will be the name displayed for quick search matches
of this entity.
- state (`@property`): Return state of related facility object
- view_url (`@property`): Return the URL to this campus's web view.
- zipcode (`@property`): Return zipcode of related facility object

### Class Methods

#### related_to_facility
`def related_to_facility(cls, value=None, filt=None, field=fac_set__id, qset=None)`

Filter queryset of campus objects related to facilities with name match
in fac_set__id according to filter.

Relationship through facility.

---

### Methods

#### save
`def save(self, *args, **kwargs)`

Save the current instance

---

## Carrier

```
Carrier(peeringdb_server.models.ProtectedMixin, django_peeringdb.models.abstract.CarrierBase, peeringdb_server.models.SocialMediaMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a carrier object.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- carrierfac_set_active (`@property`): Returns queryset of active CarrierFacility objects connected to this
carrier.
- grainy_namespace (`@property`): None
- search_result_name (`@property`): This will be the name displayed for quick search matches
of this entity.
- sponsorship (`@property`): Returns sponsorship oject for this carrier (through the owning org).
- view_url (`@property`): Return the URL to this carrier's web view.

## CarrierFacility

```
CarrierFacility(django_peeringdb.models.abstract.CarrierFacilityBase, peeringdb_server.models.StripFieldMixin)
```

Describes a carrier <-> facility relationship.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- descriptive_name (`@property`): Returns a descriptive label of the netfac for logging purposes.
- grainy_namespace (`@property`): None

### Class Methods

#### related_to_city
`def related_to_city(cls, value=None, filt=None, field=facility__city, qset=None)`

Filter queryset of carrierfac objects related to city via match
in facility__city according to filter.

Relationship through facility.

---
#### related_to_country
`def related_to_country(cls, value=None, filt=None, field=facility__country, qset=None)`

Filter queryset of carrierfac objects related to country via match
in facility__country according to filter.

Relationship through facility.

---
#### related_to_name
`def related_to_name(cls, value=None, filt=None, field=facility__name, qset=None)`

Filter queryset of carrierfac objects related to facilities with name match
in facility__name according to filter.

Relationship through facility.

---

## CommandLineTool

```
CommandLineTool(peeringdb_server.models.StripFieldMixin)
```

Describes command line tool execution by a staff user inside the
control panel (admin).


### Methods

#### \__str__
`def __str__(self)`

Return str(self).

---

## DataChangeEmail

```
DataChangeEmail(peeringdb_server.models.StripFieldMixin)
```

DataChangeEmail(id, user, watched_object, email, content, subject, created, sent)


## DataChangeNotificationQueue

```
DataChangeNotificationQueue(peeringdb_server.models.StripFieldMixin)
```

DataChangeNotificationQueue(id, watched_ref_tag, watched_object_id, ref_tag, object_id, reason, version_before, version_after, action, source, created)


### Instanced Attributes

These attributes / properties will be available on instances of the class

- data (`@property`): Retrieve relevant data from the version snap shot of the notification
object
- details (`@property`): Generates a string describing change details according to
notification object type, action type and notification
source

Will return self.reason if nothing else can be gathered.
- target_id (`@property`): None
- target_object (`@property`): Returns instance of the target object
- title (`@property`): Used to label a change to an object in the notification message
- title_netixlan (`@property`): Used to label a change to a netixlan in the notification message
- watched_object (`@property`): Returns instance of the watched object

### Class Methods

#### consolidate
`def consolidate(cls, watched_ref_tag, watched_object_id, date_limit)`

Returns a dict of all DataChangeQueueNotification entries for the specified
ref tag and object id.

`date_limit` is the cut off point for considering eligible notifications (notifications
older than this date will be ignored)

---

## DataChangeWatchedObject

```
DataChangeWatchedObject(peeringdb_server.models.StripFieldMixin)
```

Describes a user's intention to be notified about
changes to a specific objects.

Currently only `net` objects are watchable


### Instanced Attributes

These attributes / properties will be available on instances of the class

- changes_since (`@property`): None
- watched_object (`@property`): Returns instance of the watched object

### Class Methods

#### cleanup
`def cleanup(cls)`

1) checks for deleted objects and removes all watched object instances for them

2) only users that write permissions to the watched object are eligible for notifications

---
#### collect
`def collect(cls)`

Collects all instances that require notifications to be sent.

This will take into account created/last_notified data of the DataChangeWatchedObject
instance to determine new notifications.

Returns

- dict, dict where the first dictionary is a mapping of user id to `User` and the
  second dictionary is a mapping of user id to a dicitionary structure holding collected
  notifications for the user as decribed below.

  ```
  {
        (watched_ref_tag, watched_object_id): {
            "watched": DataChangeWatchedObject,
            "entries": {
                (ref_tag, id): list<DataChangeNotificationQueue>
            }
        }
  }
  ```

---

### Methods

#### \__str__
`def __str__(self)`

Return str(self).

---

## DeskProTicket

```
DeskProTicket(peeringdb_server.models.StripFieldMixin)
```

DeskProTicket(id, subject, body, user, email, created, published, deskpro_ref, deskpro_id)


## DeskProTicketCC

```
DeskProTicketCC(peeringdb_server.models.StripFieldMixin)
```

Describes a contact to be cc'd on the deskpro ticket.


## EmailAddressData

```
EmailAddressData(peeringdb_server.models.StripFieldMixin)
```

EmailAddressData(id, email, confirmed_date)


## EnvironmentSetting

```
EnvironmentSetting(peeringdb_server.models.StripFieldMixin)
```

Environment settings overrides controlled through
django admin (/cp).


### Instanced Attributes

These attributes / properties will be available on instances of the class

- value (`@property`): Get the value for this setting.

### Class Methods

#### get_setting_value
`def get_setting_value(cls, setting)`

Get the current value of the setting specified by
its setting name.

If no instance has been saved for the specified setting
the default value will be returned.

---

### Methods

#### \__str__
`def __str__(self)`

Return str(self).

---
#### clean
`def clean(self)`

Hook for doing any extra model-wide validation after clean() has been
called on every field by self.clean_fields. Any ValidationError raised
by this method will not be associated with a particular field; it will
have a special-case association with the field defined by NON_FIELD_ERRORS.

---
#### set_value
`def set_value(self, value)`

Update the value for this setting.

---

## Facility

```
Facility(peeringdb_server.models.ProtectedMixin, django_peeringdb.models.abstract.FacilityBase, peeringdb_server.models.GeocodeBaseMixin, peeringdb_server.models.ParentStatusCheckMixin, peeringdb_server.models.SocialMediaMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a peeringdb facility.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- carrierfac_set_active (`@property`): Returns queryset of active CarrierFacility objects connected
to this facility.
- deletable (`@property`): Returns whether or not the facility is currently
in a state where it can be marked as deleted.

This will be False for facilites of which ANY
of the following is True:

- has a network facility under it with status=ok
- has an exchange facility under it with status=ok
- grainy_namespace (`@property`): None
- ixfac_set_active (`@property`): Returns queryset of active InternetExchangeFacility objects connected
to this facility.
- netfac_set_active (`@property`): Returns queryset of active NetworkFacility objects connected to this
facility.
- search_result_name (`@property`): This will be the name displayed for quick search matches
of this entity.
- sponsorship (`@property`): Returns sponsorship oject for this facility (through the owning org).
- view_url (`@property`): Return the URL to this facility's web view.

### Class Methods

#### not_related_to_ix
`def not_related_to_ix(cls, value=None, filt=None, field=ix_id, qset=None)`

Returns queryset of Facility objects that
are related to the ixwork specified via ix_id

Relationship through ixfac -> ix

---
#### not_related_to_net
`def not_related_to_net(cls, value=None, filt=None, field=network_id, qset=None)`

Returns queryset of Facility objects that
are related to the network specified via net_id

Relationship through netfac -> net

---
#### overlapping_asns
`def overlapping_asns(cls, asns, qset=None)`

Returns queryset of Facility objects
that have a relationship to all asns specified in `asns`

Relationship through netfac.

Arguments:
    - asns <list>: list of asns

Keyword Arguments:
    - qset <Facility QuerySet>: if specified use as base query

Returns:
    - Facility QuerySet

---
#### related_to_ix
`def related_to_ix(cls, value=None, filt=None, field=ix_id, qset=None)`

Returns queryset of Facility objects that
are related to the ixwork specified via ix_id

Relationship through ixfac -> ix

---
#### related_to_multiple_networks
`def related_to_multiple_networks(cls, value_list=None, field=network_id, qset=None)`

Returns queryset of Facility objects that
are related to ALL networks specified in the value list
(a list of integer network ids).

Used in Advanced Search (ALL search).
Relationship through netfac -> net

---
#### related_to_net
`def related_to_net(cls, value=None, filt=None, field=network_id, qset=None)`

Returns queryset of Facility objects that
are related to the network specified via net_id

Relationship through netfac -> net

---

### Methods

#### save
`def save(self, *args, **kwargs)`

Save the current instance

---

## GeoCoordinateCache

```
GeoCoordinateCache(peeringdb_server.models.StripFieldMixin)
```

Stores geocoordinates for address lookups.


## GeocodeBaseMixin

```
GeocodeBaseMixin(django.db.models.base.Model)
```

Mixin to use for geocode enabled entities.
Allows an entity to be geocoded with the pdb_geo_sync command.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- geocode_address (`@property`): Returns an address string suitable for geo API query.
- geocode_coordinates (`@property`): Return a tuple holding the latitude and longitude.

### Methods

#### clean
`def clean(self)`

As per #1482 the floor field is being deprecated
and only empty values are allowed.

---
#### process_geo_location
`def process_geo_location(self, geocode=True, save=True)`

Sets longitude and latitude.

Will return a dict containing normalized address
data.

---

## IXFImportEmail

```
IXFImportEmail(peeringdb_server.models.StripFieldMixin)
```

A copy of all emails sent by the IX-F importer.


## IXFMemberData

```
IXFMemberData(django_peeringdb.models.abstract.NetworkIXLanBase, peeringdb_server.models.StripFieldMixin)
```

Describes a potential data update that arose during an IX-F import
attempt for a specific member (asn, ip4, ip6) to netixlan
(asn, ip4, ip6) where the importer could not complete the
update automatically.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- ac_netixlan_url (`@property`): None
- ac_url (`@property`): None
- action (`@property`): Returns the implied action of applying this
entry to peeringdb.

Will return either "add", "modify", "delete" or "noop"
- actionable_changes (`@property`): None
- actionable_error (`@property`): Returns whether or not the error is actionable
by exchange or network.

If actionable will return self.error otherwise
will return None.
- actionable_for_network (`@property`): Returns whether or not the proposed action by
this IXFMemberData instance is actionable by
the network.
- changed_fields (`@property`): Returns a comma separated string of field names
for changes proposed by this IXFMemberData instance.
- changes (`@property`): Returns a dict of changes (field, value)
between this entry and the related netixlan.

If an empty dict is returned that means no changes.

```
{
    <field_name> : {
        "from" : <value>,
        "to : <value>
    }
}
```
- has_requirements (`@property`): Return whether or not this IXFMemberData has
other IXFMemberData objects as requirements.
- ipaddr4_on_requirement (`@property`): Returns true if the ipv4 address claimed by this IXFMemberData
object exists on one of its requirement IXFMemberData objects.
- ipaddr6_on_requirement (`@property`): Returns true if the ipv6 address claimed by this IXFMemberData
object exists on one of its requirement IXFMemberData objects.
- ix (`@property`): Returns the InternetExchange instance related to
this entry.
- ix_contacts (`@property`): Returns a list of email addresses that
are suitable contact points for conflict resolution
at the exchange end.
- ixf_id (`@property`): Returns a tuple that identifies the IX-F member
as a unqiue record by asn, ip4 and ip6 address.
- ixf_id_pretty_str (`@property`): None
- json (`@property`): Returns dict for self.data
- marked_for_removal (`@property`): Returns whether or not this entry implies that
the related netixlan should be removed.

We do this by checking if the IX-F data was provided
or not.
- modify_is_rs_peer (`@property`): Returns whether or not the `is_rs_peer` property
is enabled to receive modify updates or not (#793).
- modify_speed (`@property`): Returns whether or not the `speed` property
is enabled to receive modify updates or not (#793).
- net (`@property`): Returns the Network instance related to
this entry.
- net_contacts (`@property`): Returns a list of email addresses that
are suitable contact points for conflict resolution
at the network's end.
- net_present_at_ix (`@property`): Returns whether or not the network associated with
this IXFMemberData instance currently has a presence
at the exchange associated with this IXFMemberData
instance.
- netixlan (`@property`): Will either return a matching existing netixlan
instance (asn,ip4,ip6) or a new netixlan if
a matching netixlan does not currently exist.

Any new netixlan will NOT be saved at this point.

Note that the netixlan that matched may be currently
soft-deleted (status=="deleted").
- netixlan_exists (`@property`): Returns whether or not an active netixlan exists
for this IXFMemberData instance.
- previous_data (`@property`): None
- previous_error (`@property`): None
- primary_requirement (`@property`): Return the initial requirement IXFMemberData
for this IXFMemberData instance, None if there
isn't any.
- remote_changes (`@property`): Returns a dict of changed fields between previously
fetched IX-F data and current IX-F data.

If an empty dict is returned that means no changes.

```
{
    <field_name> : {
        "from" : <value>,
        "to : <value>
    }
}
```
- remote_data_missing (`@property`): Returns whether or not this IXFMemberData entry
had data at the IX-F source.

If not it indicates that it does not exist at the
IX-F source.
- requirements (`@property`): Returns list of all IXFMemberData objects
that are still active requirements for this
IXFMemberData object.
- secondary_requirements (`@property`): Return a list of secondary requirement IXFMemberData
objects for this IXFMemberData object. Currently this
only happens on add proposals that require two netixlans
to be deleted because both ipaddresses exist on separate
netixlans (#770).

### Class Methods

#### dismissed_for_network
`def dismissed_for_network(cls, net)`

Returns queryset for IXFMemberData objects that match
a network's asn and are currenlty flagged as dismissed.

Argument(s):

- net(Network)

---
#### get_for_network
`def get_for_network(cls, net)`

Returns queryset for IXFMemberData objects that match
a network's asn.

Argument(s):

- net(Network)

---
#### id_filters
`def id_filters(cls, asn, ipaddr4, ipaddr6, check_protocols=True)`

Returns a dict of filters to use with a
IXFMemberData or NetworkIXLan query set
to retrieve a unique entry.

---
#### instantiate
`def instantiate(cls, asn, ipaddr4, ipaddr6, ixlan, **kwargs)`

Returns an IXFMemberData object.

It will take into consideration whether or not an instance
for this object already exists (as identified by asn and ip
addresses).

It will also update the value of `fetched` to now.

Keyword Argument(s):

- speed(int=0) : network speed (mbit)
- operational(bool=True): peer is operational
- is_rs_peer(bool=False): peer is route server

---
#### network_has_dismissed_actionable
`def network_has_dismissed_actionable(cls, net)`

Returns whether or not the specified network has
any dismissed IXFMemberData suggestions that are
actionable.

Argument(s):

- net(Network)

---
#### proposals_for_network
`def proposals_for_network(cls, net)`

Returns a dict containing actionable proposals for
a network.

```
{
  <ix_id>: {
    "ix": InternetExchange,
    "add" : list(IXFMemberData),
    "modify" : list(IXFMemberData),
    "delete" : list(IXFMemberData),
  }
}
```

Argument(s):

- net(Network)

---

### Methods

#### \__str__
`def __str__(self)`

Return str(self).

---
#### apply
`def apply(self, user=None, comment=None, save=True)`

Applies the data.

This will either create, update or delete a netixlan
object.

Will return a dict containing action and netixlan
affected.

```
{
    "action": <action(str)>
    "netixlan": <NetworkIXLan>
}
```

Keyword Argument(s):

- user(User): if set will set the user on the
  reversion revision
- comment(str): if set will set the comment on the
  reversion revision
- save(bool=True): only persist changes to the database
  if this is True

---
#### apply_requirements
`def apply_requirements(self, save=True)`

Apply all requirements.

---
#### grab_validation_errors
`def grab_validation_errors(self)`

This will attempt to validate the netixlan associated
with this IXFMemberData instance.

Any validation errors will be stored to self.error

---
#### render_notification
`def render_notification(self, template_file, recipient, context=None)`

Renders notification text for this ixfmemberdata
instance.

Argument(s):

- template_file(str): email template file
- recipient(str): ac, ix or net
- context(dict): if set will update the template context
  from this

---
#### set_add
`def set_add(self, save=True, reason=)`

Persist this IXFMemberData instance and send out notifications
for proposed creation of netixlan instance to ac, ix and net
as warranted.

---
#### set_conflict
`def set_conflict(self, error=None, save=True)`

Persist this IXFMemberData instance and send out notifications
for conflict (validation issues) for modifications proposed
to the corresponding netixlan to ac, ix and net as warranted.

---
#### set_data
`def set_data(self, data)`

Stores a dict in self.data as a json string.

---
#### set_remove
`def set_remove(self, save=True, reason=)`

Persist this IXFMemberData instance and send out notifications
for proposed removal of netixlan instance to ac, net and ix
as warranted.

---
#### set_requirement
`def set_requirement(self, ixf_member_data, save=True)`

Sets another IXFMemberData object to be a requirement
of the resolution of this IXFMemberData object.

---
#### set_resolved
`def set_resolved(self, save=True)`

Marks this IXFMemberData instance as resolved and
sends out notifications to ac,ix and net if
warranted.

This will delete the IXFMemberData instance.

---
#### set_update
`def set_update(self, save=True, reason=)`

Persist this IXFMemberData instance and send out notifications
for proposed modification to the corresponding netixlan
instance to ac, ix and net as warranted.

---
#### validate_speed
`def validate_speed(self)`

Speed errors in IX-F data are raised during parse
and speed will be on the attribute.

In order to properly handle invalid speed values,
check if speed is 0 and if there was a parsing
error for it, and if so raise a validation error.

TODO: find a better way to do this.

---

## IXLan

```
IXLan(django_peeringdb.models.abstract.IXLanBase, peeringdb_server.models.StripFieldMixin)
```

Describes a LAN at an exchange.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- descriptive_name (`@property`): Returns a descriptive label of the ixlan for logging purposes.
- grainy_namespace (`@property`): None
- ixpfx_set_active (`@property`): Returns queryset of active prefixes at this ixlan.
- ixpfx_set_active_or_pending (`@property`): Returns queryset of active or pending prefixes at this ixlan.
- netixlan_set_active (`@property`): Returns queryset of active netixlan objects at this ixlan.
- ready_for_ixf_import (`@property`): Returns True if IX-F data is ready to be imported.
- view_url (`@property`): Return the URL to related networks web view.

### Class Methods

#### api_cache_permissions_applicator
`def api_cache_permissions_applicator(cls, row, ns, permission_holder)`

Applies permissions to a row in an api-cache result
set for ixlan.

This will strip `ixf_ixp_member_list_url` fields for
users / api keys that don't have read permissions for them according
to `ixf_ixp_member_list_url_visible`

Argument(s):

- row (dict): ixlan row from api-cache result
- ns (str): ixlan namespace as determined during api-cache
  result rendering
- permission_holder (User or API Key)

---

### Methods

#### add_netixlan
`def add_netixlan(self, netixlan_info, save=True, save_others=True)`

This function allows for sane adding of netixlan object under
this ixlan.

It will take into account whether an ipaddress can be claimed from a
soft-deleted netixlan or whether an object already exists
that should be updated instead of creating a new netixlan instance.

Arguments:
    - netixlan_info (NetworkIXLan): a netixlan instance describe the netixlan
        you want to add to this ixlan. Note that this instance will actually
        not be saved. It only serves as an information provider.

Keyword Arguments:
    - save (bool): if true commit changes to db

Returns:
    - {netixlan, created, changed, log}

---
#### clean
`def clean(self)`

Hook for doing any extra model-wide validation after clean() has been
called on every field by self.clean_fields. Any ValidationError raised
by this method will not be associated with a particular field; it will
have a special-case association with the field defined by NON_FIELD_ERRORS.

---
#### related_label
`def related_label(self)`

Used by grappelli autocomplete for representation.

---
#### test_ipv4_address
`def test_ipv4_address(self, ipv4)`

Test that the ipv4 a exists in one of the prefixes in this ixlan.

---
#### test_ipv6_address
`def test_ipv6_address(self, ipv6)`

Test that the ipv6 address exists in one of the prefixes in this ixlan.

---

## IXLanIXFMemberImportAttempt

```
IXLanIXFMemberImportAttempt(peeringdb_server.models.StripFieldMixin)
```

Holds information about the most recent ixf member import
attempt for an ixlan.


## IXLanIXFMemberImportLog

```
IXLanIXFMemberImportLog(peeringdb_server.models.StripFieldMixin)
```

Import log of a IX-F member import that changed or added at least one
netixlan under the specified ixlans.


### Methods

#### rollback
`def rollback(self)`

Attempt to rollback the changes described in this log.

---

## IXLanIXFMemberImportLogEntry

```
IXLanIXFMemberImportLogEntry(peeringdb_server.models.StripFieldMixin)
```

IX-F member import log entry that holds the affected netixlan and
the netixlan's version after the change, which can be used to rollback
the change.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- changes (`@property`): Returns a dict of changes between the netixlan version
saved by the IX-F import and the version before.

Fields `created`, `updated` and `version` will be ignored.

## IXLanPrefix

```
IXLanPrefix(peeringdb_server.models.ProtectedMixin, django_peeringdb.models.abstract.IXLanPrefixBase, peeringdb_server.models.StripFieldMixin)
```

Descries a Prefix at an Exchange LAN.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- descriptive_name (`@property`): Returns a descriptive label of the ixpfx for logging purposes.
- grainy_namespace (`@property`): None
- ix_id (`@property`): None
- ix_org_id (`@property`): None
- ix_result_name (`@property`): None
- ix_sub_result_name (`@property`): None

### Class Methods

#### related_to_ix
`def related_to_ix(cls, value=None, filt=None, field=ix_id, qset=None)`

Filter queryset of ixpfx objects related to exchange via ix_id match
according to filter.

Relationship through ixlan -> ix

---
#### whereis_ip
`def whereis_ip(cls, ipaddr, qset=None)`

Filter queryset of ixpfx objects where the prefix contains
the supplied ipaddress.

---

### Methods

#### \__str__
`def __str__(self)`

Return str(self).

---
#### clean
`def clean(self)`

Custom model validation.

---
#### test_ip_address
`def test_ip_address(self, addr)`

Checks if this prefix can contain the specified ip address.

Arguments:
    - addr (ipaddress.IPv4Address or ipaddress.IPv6Address or unicode): ip address
        to check, can be either ipv4 or 6 but should be pre-validated to be in the
        correct format as this function will simply return False incase of format
        validation errors.

Returns:
    - bool: True if prefix can contain the specified address
    - bool: False if prefix cannot contain the specified address

---

## InternetExchange

```
InternetExchange(peeringdb_server.models.ProtectedMixin, django_peeringdb.models.abstract.InternetExchangeBase, peeringdb_server.models.ParentStatusCheckMixin, peeringdb_server.models.SocialMediaMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a peeringdb exchange.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- deletable (`@property`): Returns whether or not the exchange is currently
in a state where it can be marked as deleted.

This will be False for exchanges of which ANY
of the following is True:

- has netixlans connected to it
- ixfac relationship
- derived_network_count (`@property`): Returns an ad hoc count of networks attached to an Exchange.
Used in the deletable property to ensure an accurate count
even if net_count signals are not being used.
- derived_proto_ipv6 (`@property`): Returns a value for "proto_ipv6" derived from the exchanges's
ixpfx records.

If the ix has a IPv6 ixpfx, proto_ipv6 should be True.
- derived_proto_unicast (`@property`): Returns a value for "proto_unicast" derived from the exchanges's
ixpfx records.

If the ix has a IPv4 ixpfx, proto_unicast should be True.
- grainy_namespace (`@property`): None
- ixf_import_css (`@property`): Returns the appropriate bootstrap alert class
depending on recent import request status.
- ixf_import_request_recent_status (`@property`): Returns the recent ixf import request status as a tuple
of value, display.
- ixfac_set_active (`@property`): Returns queryset of active ixfac objects at this exchange.
- ixlan (`@property`): Returns the ixlan for this exchange.

As per #21, each exchange will get one ixlan with a matching
id, but the schema is to remain unchanged until a major
version bump.
- ixlan_set_active (`@property`): Returns queryset of active ixlan objects at this exchange.
- ixlan_set_active_or_pending (`@property`): Returns queryset of active or pending ixlan objects at
this exchange.
- networks (`@property`): Returns all active networks at this exchange.
- search_result_name (`@property`): This will be the name displayed for quick search matches
of this entity.
- sponsorship (`@property`): Returns sponsorship object for this exchange (through owning org).
- view_url (`@property`): Return the URL to this facility's web view.

### Class Methods

#### filter_capacity
`def filter_capacity(cls, filt=None, value=None, qset=None)`

Returns queryset of InternetExchange objects filtered by capacity
in mbits.

Arguments:

- filt (`str`|`None`): match operation, None meaning exact match
  - 'gte': greater than equal
  - 'lte': less than equal
  - 'gt': greater than
  - 'lt': less than
- value(`int`): capacity to filter in mbits
- qset(`InternetExchange`): if specified will filter ontop of
  this existing query set

---
#### not_related_to_net
`def not_related_to_net(cls, filt=None, value=None, field=network_id, qset=None)`

Returns queryset of InternetExchange objects that
are not related to the network specified by network_id

Relationship through netixlan -> ixlan

---
#### overlapping_asns
`def overlapping_asns(cls, asns, qset=None)`

Returns queryset of InternetExchange objects
that have a relationship to all asns specified in `asns`

Relationship through ixlan -> netixlan

Arguments:
    - asns <list>: list of asns

Keyword Arguments:
    - qset <InternetExchange QuerySet>: if specified use as base query

Returns:
    - InternetExchange QuerySet

---
#### related_to_fac
`def related_to_fac(cls, filt=None, value=None, field=facility_id, qset=None)`

Returns queryset of InternetExchange objects that
are related to the facility specified by fac_id

Relationship through ixfac -> fac

---
#### related_to_ipblock
`def related_to_ipblock(cls, ipblock, qset=None)`

Returns queryset of InternetExchange objects that
have ixlan prefixes matching the ipblock specified.

Relationship  through ixlan -> ixpfx

---
#### related_to_ixfac
`def related_to_ixfac(cls, value=None, filt=None, field=ixfac_id, qset=None)`

Returns queryset of InternetExchange objects that
are related to IXfac link specified by ixfac_id

Relationship through ixfac.

---
#### related_to_ixlan
`def related_to_ixlan(cls, value=None, filt=None, field=ixlan_id, qset=None)`

Returns queryset of InternetExchange objects that
are related to IXLan specified by ixlan_id

Relationship through ixlan.

---
#### related_to_multiple_networks
`def related_to_multiple_networks(cls, value_list=None, field=network_id, qset=None)`

Returns queryset of InternetExchange objects that
are related to ALL networks specified in the value list
(a list of integer network ids).

Used in Advanced Search (ALL search).
Relationship through netixlan -> ixlan

---
#### related_to_net
`def related_to_net(cls, filt=None, value=None, field=network_id, qset=None)`

Returns queryset of InternetExchange objects that
are related to the network specified by network_id

Relationship through netixlan -> ixlan

---

### Methods

#### clean
`def clean(self)`

Hook for doing any extra model-wide validation after clean() has been
called on every field by self.clean_fields. Any ValidationError raised
by this method will not be associated with a particular field; it will
have a special-case association with the field defined by NON_FIELD_ERRORS.

---
#### peer_exists_in_ixf_data
`def peer_exists_in_ixf_data(self, asn, ipaddr4, ipaddr6)`

Checks if the combination of ip-address and asn exists
in the internet exchange's IX-F data.

Arguments:

- asn (`int`)
- ipaddr4 (`str`|`ipaddress.ip_address`)
- ipaddr6 (`str`|`ipaddress.ip_address`)

---
#### save
`def save(self, create_ixlan=True, **kwargs)`

When an internet exchange is saved, make sure the ixlan for it
exists.

Keyword Argument(s):

- create_ixlan (`bool`=True): if True and the ix is missing
  its ixlan, create it

---
#### vq_approve
`def vq_approve(self)`

Called when internet exchange is approved in verification
queue.

---

## InternetExchangeFacility

```
InternetExchangeFacility(django_peeringdb.models.abstract.InternetExchangeFacilityBase, peeringdb_server.models.ParentStatusCheckMixin, peeringdb_server.models.StripFieldMixin)
```

Describes facility to exchange relationship.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- descriptive_name (`@property`): Returns a descriptive label of the ixfac for logging purposes.
- grainy_namespace (`@property`): None

### Class Methods

#### related_to_city
`def related_to_city(cls, value=None, filt=None, field=facility__city, qset=None)`

Filter queryset of ixfac objects related to city via match
in facility__city according to filter.

Relationship through facility.

---
#### related_to_country
`def related_to_country(cls, value=None, filt=None, field=facility__country, qset=None)`

Filter queryset of ixfac objects related to country via match
in facility__country according to filter.

Relationship through facility.

---
#### related_to_name
`def related_to_name(cls, value=None, filt=None, field=facility__name, qset=None)`

Filter queryset of ixfac objects related to facilities with name match
in facility__name according to filter.

Relationship through facility.

---

### Methods

#### save
`def save(self, *args, **kwargs)`

Save the current instance

---

## Network

```
Network(django_peeringdb.models.abstract.NetworkBase, peeringdb_server.models.ParentStatusCheckMixin, peeringdb_server.models.SocialMediaMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a peeringdb network.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- grainy_namespace (`@property`): None
- info_type (`@property`): None
- ipv4_support (`@property`): None
- ipv6_support (`@property`): None
- ixlan_set_active (`@property`): Returns IXLan queryset for ixlans connected to this network
through NetworkIXLan.
- ixlan_set_ixf_enabled (`@property`): Returns IXLan queryset for IX-F import enabled ixlans connected
to this network through NetworkIXLan.
- ixlan_set_ixf_enabled_with_suggestions (`@property`): Returns IXLan queryset for IX-F import enabled ixlans connected
to this network through NetworkIXLan. Only contains ixlans that
have active suggestions for the network.
- netfac_set_active (`@property`): None
- netixlan_set_active (`@property`): None
- poc_set_active (`@property`): None
- search_result_name (`@property`): This will be the name displayed for quick search matches
of this entity.
- sponsorship (`@property`): None
- view_url (`@property`): Return the URL to this networks web view.
- view_url_asn (`@property`): Return the URL to this networks web view.

### Class Methods

#### as_set_map
`def as_set_map(cls, qset=None)`

Returns a dict mapping asns to their irr_as_set value.

---
#### automated_net_count
`def automated_net_count(cls)`

Class method that retrieves all Networks with allow_ixp_update=True.

Args:
None just returns a count of total automated_nets.

Returns:
A queryset of Network objects that match allow_ixp_update=True and status=ok .

---
#### create_from_rdap
`def create_from_rdap(cls, rdap, asn, org)`

Creates network from rdap result object.

---
#### not_related_to_fac
`def not_related_to_fac(cls, value=None, filt=None, field=facility_id, qset=None)`

Filter queryset of Network objects NOT related to the facility
specified by fac_id (as in networks NOT present at the facility)

Relationship through netfac -> fac

---
#### not_related_to_ix
`def not_related_to_ix(cls, value=None, filt=None, field=ix_id, qset=None)`

Filter queryset of Network objects not related to the ix
specified by ix_id (as in networks not present at the exchange).

Relationship through netixlan -> ixlan -> ix

---
#### related_to_fac
`def related_to_fac(cls, value=None, filt=None, field=facility_id, qset=None)`

Filter queryset of Network objects related to the facility
specified by fac_id

Relationship through netfac -> fac

---
#### related_to_ix
`def related_to_ix(cls, value=None, filt=None, field=ix_id, qset=None)`

Filter queryset of Network objects related to the ix
specified by ix_id

Relationship through netixlan -> ixlan -> ix

---
#### related_to_ixlan
`def related_to_ixlan(cls, value=None, filt=None, field=ixlan_id, qset=None)`

Filter queryset of Network objects related to the ixlan
specified by ixlan_id

Relationship through netixlan -> ixlan

---
#### related_to_netfac
`def related_to_netfac(cls, value=None, filt=None, field=id, qset=None)`

Filter queryset of Network objects related to the netfac link
specified by netfac_id

Relationship through netfac

---
#### related_to_netixlan
`def related_to_netixlan(cls, value=None, filt=None, field=id, qset=None)`

Filter queryset of Network objects related to the netixlan link
specified by netixlan_id

Relationship through netixlan.

---

### Methods

#### clean
`def clean(self)`

Custom model validation.

---
#### delete
`def delete(self, *args, **kwargs)`

Delete the Network instance.

This method ensures that all related NetworkContact instances are deleted with
the `deleting_network` flag set to True, which allows the contacts to be deleted
regardless of their current state.

---
#### save
`def save(self, *args, **kwargs)`

Save the current instance

---

## NetworkContact

```
NetworkContact(peeringdb_server.models.ProtectedMixin, django_peeringdb.models.abstract.ContactBase, peeringdb_server.models.ParentStatusCheckMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a contact point (phone, email etc.) for a network.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- deletable (`@property`): Returns whether or not the poc is currently
in a state where it can be marked as deleted.

This will be False for pocs that are the last remaining
technical contact point for a network that has
active netixlans. (#923)
- grainy_namespace (`@property`): None
- is_tech_contact (`@property`): None
- view_url (`@property`): Return the URL to related networks web view.

### Methods

#### clean
`def clean(self)`

Hook for doing any extra model-wide validation after clean() has been
called on every field by self.clean_fields. Any ValidationError raised
by this method will not be associated with a particular field; it will
have a special-case association with the field defined by NON_FIELD_ERRORS.

---
#### delete
`def delete(self, *args, **kwargs)`

Delete the NetworkContact instance.

This method sets the `_deleting_network` attribute to indicate whether
the deletion is part of a parent network deletion or not. If `deleting_network`
is passed as True in the kwargs, it indicates that the parent network is
being deleted, allowing the contact to be deleted regardless of its current state.

---
#### save
`def save(self, *args, **kwargs)`

Save the current instance

---

## NetworkFacility

```
NetworkFacility(django_peeringdb.models.abstract.NetworkFacilityBase, peeringdb_server.models.ParentStatusCheckMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a network <-> facility relationship.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- descriptive_name (`@property`): Returns a descriptive label of the netfac for logging purposes.
- grainy_namespace (`@property`): None

### Class Methods

#### related_to_city
`def related_to_city(cls, value=None, filt=None, field=facility__city, qset=None)`

Filter queryset of netfac objects related to city via match
in facility__city according to filter.

Relationship through facility.

---
#### related_to_country
`def related_to_country(cls, value=None, filt=None, field=facility__country, qset=None)`

Filter queryset of netfac objects related to country via match
in facility__country according to filter.

Relationship through facility.

---
#### related_to_name
`def related_to_name(cls, value=None, filt=None, field=facility__name, qset=None)`

Filter queryset of netfac objects related to facilities with name match
in facility__name according to filter.

Relationship through facility.

---

### Methods

#### clean
`def clean(self)`

Hook for doing any extra model-wide validation after clean() has been
called on every field by self.clean_fields. Any ValidationError raised
by this method will not be associated with a particular field; it will
have a special-case association with the field defined by NON_FIELD_ERRORS.

---
#### save
`def save(self, *args, **kwargs)`

Save the current instance

---

## NetworkIXLan

```
NetworkIXLan(django_peeringdb.models.abstract.NetworkIXLanBase, peeringdb_server.models.ParentStatusCheckMixin, peeringdb_server.models.StripFieldMixin)
```

Describes a network relationship to an IX through an IX Lan.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- data_change_parent (`@property`): Returns tuple of (str, int) describing the parent network

This makes it a supported object for data change notification implemented through
DataChangeNotificationQueue
- data_change_pretty_str (`@property`): None
- descriptive_name (`@property`): Returns a descriptive label of the netixlan for logging purposes.
- grainy_namespace (`@property`): None
- ix_id (`@property`): Returns the exchange id for this netixlan.
- ix_name (`@property`): Returns the exchange name for this netixlan.
- ix_org_id (`@property`): None
- ix_result_name (`@property`): None
- ix_sub_result_name (`@property`): None
- ixf_id (`@property`): Returns a tuple that identifies the netixlan
in the context of an IX-F member data entry as a unqiue record by asn, ip4 and ip6 address.
- ixf_id_pretty_str (`@property`): None
- name (`@property`): None
- net_id (`@property`): None
- net_org_id (`@property`): None
- net_result_name (`@property`): None
- net_sub_result_name (`@property`): None

### Class Methods

#### related_to_ix
`def related_to_ix(cls, value=None, filt=None, field=ix_id, qset=None)`

Filter queryset of netixlan objects related to the ix
specified by ix_id

Relationship through ixlan -> ix

---
#### related_to_name
`def related_to_name(cls, value=None, filt=None, field=ix__name, qset=None)`

Filter queryset of netixlan objects related to exchange via a name match
according to filter.

Relationship through ixlan -> ix

---

### Methods

#### clean
`def clean(self)`

Custom model validation.

---
#### descriptive_name_ipv
`def descriptive_name_ipv(self, version)`

Returns a descriptive label of the netixlan for logging purposes.
Will only contain the ipaddress matching the specified version.

---
#### ipaddr
`def ipaddr(self, version)`

Return the netixlan's ipaddr for ip version.

---
#### ipaddress_conflict
`def ipaddress_conflict(self, check_deleted=False)`

Checks whether the ip addresses specified on this netixlan
exist on another netixlan (with status="ok").

Arguments

- check_deleted (`bool`) - if True also look for conflicts in deleted

Returns:
    - tuple(bool, bool): tuple of two booleans, first boolean is
        true if there was a conflict with the ip4 address, second
        boolean is true if there was a conflict with the ip6
        address

---
#### save
`def save(self, *args, **kwargs)`

Save the current instance

---
#### validate_ip_conflicts
`def validate_ip_conflicts(self, check_deleted=False)`

Validates whether the ip addresses specified on this netixlan
are conflicting with any other netixlans.

Will raise a `ValidationError` on conflict

Arguments

- check_deleted (`bool`) - if True also look for conflicts in deleted
  netixlans

---
#### validate_real_peer_vs_ghost_peer
`def validate_real_peer_vs_ghost_peer(self)`

If there are ip-address conflicts with another NetworkIXLan object
try to resolve those conflicts if the new peer exists in the related
exchange's IX-F data (real peer) and the old peer does not (ghost peer)

---

## NetworkProtocolsDisabled

```
NetworkProtocolsDisabled(builtins.ValueError)
```

Raised when a network has both ipv6 and ipv4 support
disabled during IX-F import.


## OAuthAccessTokenInfo

```
OAuthAccessTokenInfo(peeringdb_server.models.StripFieldMixin)
```

OAuth access token info

Used to store additional information about an access token

- amr: Authentication method reference set on the session that
    created the grant that resulted in this access token


## OAuthApplication

```
OAuthApplication(oauth2_provider.models.AbstractApplication, peeringdb_server.models.StripFieldMixin)
```

OAuth application - extends the default oauth_provider2 application
and adds optional org ownership to it through an `org` relationship


### Methods

#### clean
`def clean(self)`

Hook for doing any extra model-wide validation after clean() has been
called on every field by self.clean_fields. Any ValidationError raised
by this method will not be associated with a particular field; it will
have a special-case association with the field defined by NON_FIELD_ERRORS.

---

## OAuthGrantInfo

```
OAuthGrantInfo(peeringdb_server.models.StripFieldMixin)
```

OAuth grant info

Used to store additional information about a grant

- amr: Authentication method reference set on the session that
    created the grant


## Organization

```
Organization(peeringdb_server.models.ProtectedMixin, django_peeringdb.models.abstract.OrganizationBase, peeringdb_server.models.GeocodeBaseMixin, peeringdb_server.models.SocialMediaMixin, peeringdb_server.models.StripFieldMixin, peeringdb_server.models.ParentStatusCheckMixin)
```

Describes a peeringdb organization.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- active_or_pending_sponsorship (`@property`): Returns sponsorship object for this organization. If the organization
has no sponsorship ongoing or pending return None.
- admin_group_name (`@property`): Returns admin usergroup name for this organization.
- admin_url (`@property`): Return the admin URL for this organization (in /cp).
- admin_usergroup (`@property`): Returns the admin usergroup for this organization.
- all_users (`@property`): Returns a set of all users in the org's user and admin groups.
- campus_set_active (`@property`): Returns queryset holding active campus in this organization.
- carrier_set_active (`@property`): Returns queryset holding active carrier in this organization.
- deletable (`@property`): Returns whether or not the organization is currently
in a state where it can be marked as deleted.

This will be False for organizations of which ANY
of the following is True:

- has a network under it with status=ok
- has a facility under it with status=ok
- has an exchange under it with status=ok
- email_domains_list (`@property`): None
- fac_set_active (`@property`): Returns queryset holding active facilities in this organization.
- grainy_namespace (`@property`): None
- grainy_namespace_manage (`@property`): Org administrators need CRUD to this namespace in order
to execute administrative actions (user management, user permission
management).
- group_name (`@property`): Returns usergroup name for this organization.
- is_empty (`@property`): Returns whether or not the organization is empty

An empty organization means an organization that does not
have any objects with status ok or pending under it
- ix_set_active (`@property`): Returns queryset holding active exchanges in this organization.
- net_set_active (`@property`): Returns queryset holding active networks in this organization.
- owned (`@property`): Returns whether or not the organization has been claimed
by any users.
- pending_affiliations (`@property`): Returns queryset holding pending affiliations to this
organization.
- rdap_collect (`@property`): Fetche rdap results for all networks under this org and returns
them by asn.
- search_result_name (`@property`): This will be the name displayed for quick search matches
of this entity.
- sponsorship (`@property`): Returns sponsorship object for this organization. If the organization
has no sponsorship ongoing return None.
- urls (`@property`): Returns all the websites for the org based on its
website field and the website fields on all the entities it
owns.
- usergroup (`@property`): Returns the usergroup for this organization.
- view_url (`@property`): Return the URL to this organizations web view.

### Class Methods

#### create_from_rdap
`def create_from_rdap(cls, rdap, asn, org_name=None)`

Creates organization from rdap result object.

---

### Methods

#### adjust_permissions_for_periodic_reauth
`def adjust_permissions_for_periodic_reauth(self, user, perms)`

Will strip users permission for the org if the org currently
flags the user as needing re-authentication

---
#### delete_cleanup
`def delete_cleanup(self, hard=False)`

Runs cleanup before delete.

Override this in the class that uses this mixin (if needed).

---
#### related_label
`def related_label(self)`

Used by grappelli autocomplete for representation.

Since grappelli doesn't easily allow one to filter status
during autocomplete lookup, make sure the objects
are marked accordingly in the result.

---
#### user_meets_email_requirements
`def user_meets_email_requirements(self, user)`

If organization has `restrict_user_emails` set to true
this will check the specified user's email addresses against
the values stored in `email_domains`.

If the user has no email address that falls within the specified
domain restrictions this will return `[]` and all associated user's email
addresses in `List`.

If the user has at least one email address that falls within the specified
domain restrictions this will return all restricted email addresses in `List`
and all associated user's email addresses in `List`.

---
#### user_requires_reauth
`def user_requires_reauth(self, user)`

Returns whether the specified user requires re-authentication according
to this organizations's periodic_reauth settings.

---

## OrganizationAPIKey

```
OrganizationAPIKey(rest_framework_api_key.models.AbstractAPIKey, peeringdb_server.models.StripFieldMixin)
```

An API Key managed by an organization.


## OrganizationAPIPermission

```
OrganizationAPIPermission(django_grainy.models.Permission, peeringdb_server.models.StripFieldMixin)
```

Describes permission for a OrganizationAPIKey.


## OrganizationMerge

```
OrganizationMerge(peeringdb_server.models.StripFieldMixin)
```

When an organization is merged into another via admin.merge_organizations
it is logged here, allowing the merge to be undone.


### Methods

#### log_entity
`def log_entity(self, entity, note=)`

Mark an entity as moved during this particular merge.

Entity can be any handleref instance or a User instance.

---
#### undo
`def undo(self)`

Undo this merge.

---

## OrganizationMergeEntity

```
OrganizationMergeEntity(peeringdb_server.models.StripFieldMixin)
```

This holds the entities moved during an
organization merge stored in OrganizationMerge.


## ParentStatusCheckMixin

```
ParentStatusCheckMixin(builtins.object)
```

Mixin that implements checks for creating
/ updating an instance that will raise
exception under certain criteria


### Methods

#### validate_parent_status
`def validate_parent_status(self)`

Validate parent status against object (child) status

A child cannot be `ok` or `pending` if the parent is `deleted`
A child cannot be `ok` if the parent is `pending`

Will raise ParentStatus exception on invalid status.

Can be disabled by setting `DATA_QUALITY_VALIDATE_PARENT_STATUS` to False

:return:

---
#### validate_status_change
`def validate_status_change(self)`

Validate status changes:
- Prevent changing from 'ok' to 'pending'

---

## ParentStatusException

```
ParentStatusException(builtins.OSError)
```

Throw this when an object cannot be created because its parent is
either status pending or deleted.


### Methods

#### \__init__
`def __init__(self, parent, typ)`

Initialize self.  See help(type(self)) for accurate signature.

---

## Partnership

```
Partnership(peeringdb_server.models.StripFieldMixin)
```

Allows an organization to be marked as a partner.

It will appear on the "partners" page.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- label (`@property`): None

## ProtectedAction

```
ProtectedAction(builtins.ValueError)
```

Inappropriate argument value (of correct type).


### Methods

#### \__init__
`def __init__(self, obj)`

Initialize self.  See help(type(self)) for accurate signature.

---

## ProtectedMixin

```
ProtectedMixin(builtins.object)
```

Mixin that implements checks for changing
/ deleting a model instance that will block
such actions under certain circumstances.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- deletable (`@property`): Should return whether the object is currently
in a state where it can safely be soft-deleted.

If not deletable, should specify reason in
`_not_deletable_reason` property.

If deletable, should set `_not_deletable_reason`
property to None.
- not_deletable_reason (`@property`): None

### Methods

#### delete_cleanup
`def delete_cleanup(self)`

Runs cleanup before delete.

Override this in the class that uses this mixin (if needed).

---

## SocialMediaMixin

```
SocialMediaMixin(django.db.models.base.Model)
```

Make subclasses preserve the alters_data attribute on overridden methods.


### Methods

#### save
`def save(self, *args, **kwargs)`

Save the current instance. Override this in a subclass if you want to
control the saving process.

The 'force_insert' and 'force_update' parameters can be used to insist
that the "save" must be an SQL insert or update (or equivalent for
non-SQL backends), respectively. Normally, they should not be set.

---

## Sponsorship

```
Sponsorship(peeringdb_server.models.StripFieldMixin)
```

Allows an organization to be marked for sponsorship
for a designated timespan.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- active (`@property`): None
- css (`@property`): Returns the css class for this sponsorship's level
- label (`@property`): Returns the label for this sponsorship's level.

### Class Methods

#### active_by_org
`def active_by_org(cls)`

Yields (Organization, Sponsorship) for all currently
active sponsorships.

---

### Methods

#### \__str__
`def __str__(self)`

Return str(self).

---
#### notify_expiration
`def notify_expiration(self)`

Sends an expiration notice to SPONSORSHIPS_EMAIL

Notification is only sent if notify_date < expiration_date

---

## SponsorshipOrganization

```
SponsorshipOrganization(peeringdb_server.models.StripFieldMixin)
```

Describes an organization->sponsorship relationship.


## StripFieldMixin

```
StripFieldMixin(django.db.models.base.Model)
```

Mixin to remove whitespace at the beginning and end of string fields


### Methods

#### clean
`def clean(self)`

Hook for doing any extra model-wide validation after clean() has been
called on every field by self.clean_fields. Any ValidationError raised
by this method will not be associated with a particular field; it will
have a special-case association with the field defined by NON_FIELD_ERRORS.

---
#### save
`def save(self, *args, **kwargs)`

Save the current instance. Override this in a subclass if you want to
control the saving process.

The 'force_insert' and 'force_update' parameters can be used to insist
that the "save" must be an SQL insert or update (or equivalent for
non-SQL backends), respectively. Normally, they should not be set.

---
#### strip_string_fields
`def strip_string_fields(self)`

Strip value in string fields

---

## URLField

```
URLField(django_peeringdb.models.abstract.URLField)
```

Local defaults for URLField.


## UTC

```
UTC(datetime.tzinfo)
```

UTC+0 tz for tz aware datetime fields.


### Methods

#### utcoffset
`def utcoffset(self, d)`

datetime -> timedelta showing offset from UTC, negative values indicating West of UTC

---

## User

```
User(django.contrib.auth.base_user.AbstractBaseUser, django.contrib.auth.models.PermissionsMixin, peeringdb_server.models.StripFieldMixin)
```

Proper length fields user.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- admin_organizations (`@property`): Returns all organizations this user is an admin of.
- affiliation_requests_available (`@property`): Returns whether the user currently has any affiliation request
slots available by checking that the number of pending affiliation requests
the user has is lower than MAX_USER_AFFILIATION_REQUESTS
- email_confirmed (`@property`): Returns True if the email specified by the user has
been confirmed, False if not.
- full_name (`@property`): None
- get_2fa_security_keys (`@property`): None
- get_passkey_security_keys (`@property`): None
- has_2fa (`@property`): Returns true if the user has set up any TOTP or webauth security keys.
- has_oauth (`@property`): None
- is_verified_user (`@property`): Returns whether the user is verified (e.g., has been validated
by PDB staff).

Currently this is accomplished by checking if the user
has been added to the 'user' user group.
- networks (`@property`): Returns all networks this user is a member of.
- organizations (`@property`): Returns all organizations this user is a member or admin of.
- pending_affiliation_requests (`@property`): Returns the currently pending user -> org affiliation
requests for this user.
- self_entity_org (`@property`): None

### Methods

#### close_account
`def close_account(self)`

Removes all identifying information from the User instance
and flags it as inactive.

Warning: users that are status == "pending" are hard-deleted

---
#### email_user
`def email_user(self, subject, message, from_email=stefan@20c.com, email=None)`

Sends an email to this User.

---
#### email_user_all_addresses
`def email_user_all_addresses(self, subject, message, from_email=stefan@20c.com, exclude=None)`

Sends email to all email addresses for the user

---
#### flush_affiliation_requests
`def flush_affiliation_requests(self)`

Removes all user -> org affiliation requests for this user
that have been denied or canceled.

---
#### get_full_name
`def get_full_name(self)`

Returns the first_name plus the last_name, with a space in between.

---
#### get_locale
`def get_locale(self)`

Returns user preferred language.

---
#### get_short_name
`def get_short_name(self)`

Returns the short name for the user.

---
#### notify_email_added
`def notify_email_added(self, email)`

Notifies the user that the specified email address has been added
to their account (#907)

---
#### notify_email_removed
`def notify_email_removed(self, email)`

Notifies the user that the specified email address has been removed
from their account (#907)

---
#### password_reset_initiate
`def password_reset_initiate(self)`

Initiate the password reset process for the user.

---
#### recheck_affiliation_requests
`def recheck_affiliation_requests(self)`

Will reevaluate pending affiliation requests to unclaimed
ASN orgs.

This allows a user with such a pending affiliation request to
change ther email and recheck against rdap data for automatic
ownership approval. (#375)

---
#### related_label
`def related_label(self)`

Used by grappelli autocomplete for representation.

---
#### send_email_confirmation
`def send_email_confirmation(self, request=None, signup=False, email=None)`

Use allauth email-confirmation process to make user
confirm that the email they provided is theirs.

---
#### set_locale
`def set_locale(self, locale)`

Returns user preferred language.

---
#### set_unverified
`def set_unverified(self)`

Remove user from 'user' group.
Add user to 'guest' group.

---
#### set_verified
`def set_verified(self)`

Add user to 'user' group.
Remove user from 'guest' group.

---
#### validate_rdap_relationship
`def validate_rdap_relationship(self, rdap)`

#Domain only matching
email_domain = self.email.split("@")[1]
for email in rdap.emails:
    try:
        domain = email.split("@")[1]
        if email_domain == domain:
            return True
    except IndexError, inst:
        pass

---

## UserAPIKey

```
UserAPIKey(rest_framework_api_key.models.AbstractAPIKey, peeringdb_server.models.StripFieldMixin)
```

An API Key managed by a user. Can be readonly or can take on the
permissions of the User.


## UserOrgAffiliationRequest

```
UserOrgAffiliationRequest(peeringdb_server.models.StripFieldMixin)
```

Whenever a user requests to be affiliated to an Organization
through an ASN the request is stored in this object.

When an ASN is entered that is not yet in the database it will
notify PDB staff.

When an ASN is entered that is already in the database the organization
adminstration is notified and they can then approve or deny
the affiliation request themselves.

Please look at signals.py for the logic of notification as
well as deriving the organization from the ASN during creation.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- name (`@property`): If org is set, returns the org's name otherwise returns the
value specified in self.org_name

### Methods

#### approve
`def approve(self)`

Approve request and add user to org's usergroup.

---
#### cancel
`def cancel(self)`

Deny request, marks request as canceled and keeps
it around until requesting user deletes it.

---
#### deny
`def deny(self)`

Deny request, marks request as denied and keeps
it around until requesting user deletes it.

---
#### notify_ownership_approved
`def notify_ownership_approved(self)`

Sends a notification email to the requesting user.

---

## UserOrgAffiliationRequestHistory

```
UserOrgAffiliationRequestHistory(reversion.models.Version, peeringdb_server.models.StripFieldMixin)
```

Proxy model for reversion Version to track changes in
UserOrgAffiliationRequest objects in django-admin


## UserPasswordReset

```
UserPasswordReset(peeringdb_server.models.StripFieldMixin)
```

UserPasswordReset(user, token, created)


## ValidationErrorEncoder

```
ValidationErrorEncoder(json.encoder.JSONEncoder)
```

Extensible JSON <https://json.org> encoder for Python data structures.

Supports the following objects and types by default:

+-------------------+---------------+
| Python            | JSON          |
+===================+===============+
| dict              | object        |
+-------------------+---------------+
| list, tuple       | array         |
+-------------------+---------------+
| str               | string        |
+-------------------+---------------+
| int, float        | number        |
+-------------------+---------------+
| True              | true          |
+-------------------+---------------+
| False             | false         |
+-------------------+---------------+
| None              | null          |
+-------------------+---------------+

To extend this to recognize other objects, subclass and implement a
``.default()`` method with another method that returns a serializable
object for ``o`` if possible, otherwise it should call the superclass
implementation (to raise ``TypeError``).


### Methods

#### default
`def default(self, obj)`

Implement this method in a subclass such that it returns
a serializable object for ``o``, or calls the base implementation
(to raise a ``TypeError``).

For example, to support arbitrary iterators, you could
implement default like this::

    def default(self, o):
        try:
            iterable = iter(o)
        except TypeError:
            pass
        else:
            return list(iterable)
        # Let the base class default method raise the TypeError
        return super().default(o)

---

## VerificationQueueItem

```
VerificationQueueItem(peeringdb_server.models.StripFieldMixin)
```

Keeps track of new items created that need to be reviewed and approved
by administrators.

Queue items are added through the create signals tied to the various
objects (peeringdb_server/signals.py).


### Instanced Attributes

These attributes / properties will be available on instances of the class

- approve_admin_url (`@property`): Return admin url for approval of the verification queue item.
- deny_admin_url (`@property`): Return admin url for denial of the verification queue item.
- item_admin_url (`@property`): Return admin url for the object in the verification queue.

### Class Methods

#### get_for_entity
`def get_for_entity(cls, entity)`

Returns verification queue item for the provided
entity if it exists or raises a DoesNotExist
exception.

---

### Methods

#### approve
`def approve(self)`

Approve the verification queue item.

---
#### deny
`def deny(self)`

Deny the verification queue item.

---
