## Modules

### RDAP

- Add output to parsing test

```sh
curl -L https://rdap.db.ripe.net/autnum/$ASN > tests/data/rdap/autnum/$ASN.input
```

or
```sh
scripts/rdap_getasn.sh
scripts/rdap_getent.sh
```

- Pretty print RDAP data

```sh
munge json:https://rdap.arin.net/registry/autnum/2914 yaml:
```

## Dependencies

All dependencies are now handled by poetry.

To update them, do `poetry lock`, rebuild docker and test.
