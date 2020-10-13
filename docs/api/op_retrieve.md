## Retrieve a single object

### Depth

Nested sets will not be expanded (any field ending with the _set suffix, with the exception of 'irr_as_set') unless the 'depth'
parameter is passed in the request URL.

Depth can be one of three values:

  - 1 : expand sets into ids (slow)
  - 2 : expand sets into objects (slower)
  - 0 : don't expand sets at all (default behaviour)

**example**

    ?depth=1


