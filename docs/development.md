
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

perms

  ALWAYS

  - on the model create a classmethod called nsp_namespace_from_id
    that should take all the ids it needs to make its namespace
    and return that namespace

    Look at the Network or NetworkContact class for examples

  - on the model create a property method called nsp_namespace
    that calls and returns __class__.nsp_namespace_from_id with
    the aproporiate ids

  - on the serializer create a method called nsp_namespace_create
    that returns the namespace to be checked for creation perms

    this method will be passed the validated serializer data so
    you can use the ids / objects in there to help build your namespace

  SOMETIMES

  - on the model create a method called nsp_has_perms_PUT that
    chould return weither or not the user has access to update
    the instance. This is needed because in some cases in order
    to update an existing object the user may need to be checked
    on perms for more than one namespace - this lets you do that

    Look at validate_PUT_ownership for helper function

  - if the model is supposed to be rendered in a list somewhere
    eg network contacts in poc_set under network make sure list
    namespacing is setup correctly - again look at Network
    and NetworkContact for examples.


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
