# Database Schema

![PeeringDB Database Schema Graph](/docs/img/schema.png)

## Django

PeeringDB runs on django 3.2 - for extensive documentation on the django framework please refer to the [official django documentation](https://docs.djangoproject.com/en/3.2/).

Django uses model classes to define the database schema.

## PeeringDB models

`peeringdb_server` defines its models (and thus db schema) in `peeringdb_server/models.py`

### django-peeringdb

The main schema for peering data is maintained in the public [django-peeringdb](https://github.com/peeringdb/django-peeringdb) module.

`peerigndb_server` uses the abstract models defined in `django-peeringdb` to represent the peering data.

This is important to keep in mind when adding new fields or new models to the schema.

Generally speaking, anything that is going to be exposed to the public on PeeringDB's REST API should be added to the abstract models in `django_peeringdb.models.abstract` so it can be available to users maintaining local snapshots of the database.

### Migrations

For concrete models, `django-peeringdb` and `peeringdb_server` maintain their own set of migrations.

Please make sure that when you add fields or models to django-peeringdb that migrations for the changes exist in both places.

Refer to [django migration documentation](https://docs.djangoproject.com/en/3.2/topics/migrations/) for further explanation.

### Peering data overview

- `Organization` (`org`): represents organization
- `Facility` (`fac`): represents a physical facility / location where a network or exchange can be present
  - has a parent `Organization` relationship
- `Network` (`net`): represents a network (asn)
  - has a parent `Organization` relationship
- `InternetExchange` (`ix`): represents an internet exchange
  - has a parent `Organization` relationship
- `IXLan` (`ixlan`): represents LAN information for an exchange
  - has a parent `InternetExchange` relationship
- `IXLanPrefix` (`ixpfx`): represents a network prefix specification for an exchange
  - has a parent `IXLan` relationship
- `NetworkIXLan` (`netixlan`): represents a networks presence at an exchange
  - has parent `Network` and `IXLan` relationships
- `InternetExchangeFacility` (`ixfac`): represents an exchange's presence at a facility / location
  - has parent `InternetExchange` and `Facility` relationships
- `NetworkFacility` (`netfac`): represents a network's presence at a facility / location
  - has parent `Network` and `Facility` relationships
- `NetworkContact` (`poc`): represens a point of contact for networks
  - has a parent `Network` relationship

### References tags (reftags)

PeeringDB uses shorthand when refering to some models, also known as reftags

This becomes more important when relating models to the REST API.

For example, the reftag for a `Network` would be `net`. This `reftag` is defined through the model's `HandleRef` meta class.

Please refer to [django-handleref](https://github.com/20c/django-handleref) for further explanation.

### Object status

Through `django-handleref` each of the above objects maintains a status field that can have one of the following values:

- `ok`: object is approved and currently live
- `pending`: object is pending approval through admin-com
- `deleted`: object is marked as deleted

### Soft delete

With the exception of stale `poc` objects, public peering data is *never* hard deleted.

Soft deleting an object means flipping its status from `ok` to `deleted`.

Note that `django-handleref` overrides the model's `delete` method to do this automatically.

```py
net = Network.objects.get(id=20)
print(net.status) # ok
net.delete()
print(net.status) # deleted
```

### Version history

Through `django-handleref` and `django-reversion`, snapshots of objects are maintained.

Every time an object is saved a snapshot is created.

This is *not* automatic behavior, and you need to manually open the `reversion.create_revision` context for any code blocks that make changes to objects.

Please refer to [django-reversion](https://django-reversion.readthedocs.io/en/stable/) for further explanation.
