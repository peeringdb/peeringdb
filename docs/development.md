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


### Whois Server

- To locally test whois, setup `/etc/xinetd.d/pdb-whois` with similar:

```
service whois
{
        disable         = no
        socket_type     = stream
        wait            = no
        user            = $USER

        passenv =

        server          = /home/$USER/srv/dev.peeringdb.com/peeringdb/in.whoisd
        log_on_failure  = HOST
}

```

- Deploy and test against local

```sh
facs peeringdb dev --src-dir=. ; whois -h 127.0.0.1 as63311
pytest -v -rxs --cov-report term-missing --cov=peeringdb_server/ --capture=sys tests/
```

## Dependencies

All dependencies are now handled by poetry.

To update them, do `poetry lock`, rebuild docker and test.
