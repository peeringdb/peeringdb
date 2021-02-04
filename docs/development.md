
# PeeringDB Server Development

## Models

Note: to add fk's to base models, you must add in both peeringdb.models. and in django_peeringdb.models concrete class

models.py
  - make model
  - add ref_tag_

serializers.py
  - add serializer

peeringdb/rest.py
  - make ViewSet
  - register

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

All dependencies are now handled by the Pipfile.

To update them, do a pipenv lock, and test.

To update the requirements.txt file, from the base dir, run:

```sh
scripts/update_requirements_file.sh
```


## Troubleshooting

### 404 on static files with runserver:

Make sure it's in debug mode

### api tests fail

You need to specify the test directory:

```sh
pytest tests/
```

### Can't see error because of warnings

Run pytest with `-p no:warnings`

### Run one specific test

Run pytest with `-k $test_name`
