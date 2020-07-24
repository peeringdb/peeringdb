## List objects

### Querying

You may query the resultset by passing field names as url parameters

### Numeric Queries

On numeric fields you can suffix the field names with the following filters:

- \_\_lt : less-than
- \_\_lte : less-than-equal
- \_\_gt : greater-than
- \_\_gte : greater-than-equal
- \_\_in : value inside set of values (comma separated)

**examples**

    ?<field_name>__lt=10
    ?<field_name>__in=1,10

### String Queries

On string fields you can suffix the field names with the following filters:

- \_\_contains : field value contains specified value
- \_\_startswith : field value starts with specified value
- \_\_in : value contained inside set of values (comma separated)

**examples**

    ?<field_name>__contains=something
    ?<field_name>__in=this,that

All string filtering operations are case-insensitive

### Since


You can use the since argument with a unix timestamp (seconds) to retrieve all
objects updated since then. Note that this result will contain objects that were
deleted in that timeframe as well - you can spot them by checking for status "deleted"

**example**

    ?since=1443414678

### Nested data

Any field ending in the suffix **_set** is a list of objects in a relationship with the parent
object, you can expand those lists with the 'depth' parameter as explained below.

The naming schema of the field will always tell you which type of object the set is holding
and will correspond with the object's endpoint on the API

    <object_type>_set

So a set called 'net_set' will hold Network objects (api endpoint /net)

### Depth

Nested sets will not be loaded (any field ending with the _set suffix) unless the 'depth'
parameter is passed in the request URL.

Depth can be one of three values:

  - 1 : expand sets into ids (slow)
  - 2 : expand sets into objects (slower)
  - 0 : dont expand sets at all (default behaviour)

**example**

    ?depth=1

### Cached Responses

Any request that does not require lookups will be served a cached result. Cache is updated approximately every 15 minutes.

You can spot cached responses by checking for the "generated" property inside the "meta" object.

    "meta" : {
        // the cached data was last regenerated at this time (epoch)
        "generated" : 1456121358.6301942
    }

**examples**

will serve a cached result:

    ?depth=2

will serve a live result:

    ?id__in=1,2

### Resultset limit

Any request that does lookup queries and has it's **depth** parameter specified will have a result limit of 250 entries, any entries past this limit will be truncated, at which point you either should be more specific with your query or use the skip and limit parameters to page through the result set

**examples**

will serve a live result and a maximum of 250 rows at a time:

    ?updated__gt=2011-01-01&depth=1

will serve a live result and will not be truncated:

    ?updated__gt=2011-01-01

will serve a cached result and will not be truncated:

    ?depth=1

### Pagination

Use the skip and limit parameters to page through results

    ?updated__gt=2011-01-01&depth=1&limit=250 - first page
    ?updated__gt=2011-01-01&depth=1&limit=250&skip=250 - second page
    ?updated__gt=2011-01-01&depth=1&limit=250&skip=500 - third page
