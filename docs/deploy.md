
# PeeringDB Deploy

PeeringDB currently only runs on python2.7 - all instructions below are to be taken with that in mind.

## Updates and formatting


For each release, everything should be updated and formatted, using the following commands.

```sh
pipenv lock
pipenv install --dev
pipenv run find . -type f -name \*.py -exec pyupgrade --py37-plus {} \;
pipenv run find . -type f -name \*.py -exec black -t py37 {} \;
```

## Getting Started

This document uses the following variables

```sh
export PDB_REPO=git@github.com:peeringdb/peeringdb.git
```

### Install facsimile

```sh
pip install facsimile jinja2
```
### Clone peeringdb

```sh
git clone $PDB_REPO
```

# Developer instance deploymnet

Create ~/srv

```sh
mkdir ~/srv
```

Copy `config/facsimile/dev.example.yaml` to `config/facsimile/dev.yaml` and make changes where needed.

```sh
cp config/facsimile/dev.example.yaml config/facsimile/dev.yaml
vi config/facsimile/dev.yaml
```

Use the `facs` command to deploy a virtualenv and server files for your dev instance

```sh
facs peeringdb dev --src-dir=.
facs venv dev --src-dir=.
```

Files will be deployed to `~/srv/dev.peeringdb.com` (unless you changed the location in your config)

## Setup passwords

Once you have run `facs` for the first time it will have created a .facsimile directory

You will want to open `.facsimile/state/dev/state.yaml` and set the correct passwords for everything and then do
**another** deploy to make sure the correct passwords are deployed.

```
instances:
  inmap: {}
  uiidmap: {}
passwd:
  deskpro: xxx # deskpro api key
  djangokey: xxx # django secret
  google_geoloc_api: xxx # google geolocation api key
  peeringdb: xxx # database password
  recaptcha: xxx # recaptcha secret
```

## Create api-cache dir

```
mkdir ~/srv/dev.peeringdb.com/etc/api-cache
```

## Symlink for convenience

In order to be able to run the manage.py command out of the pdb repository you can symlink the peeringdb_com directory from deploy location

In the peeringdb repo root:

```sh
ln -s ~/srv/dev.peeringdb.com/peeringdb/peeringdb_com peeringdb_com
```

## Setup database

During deploy facsimile will have created a sql file at `.facsimile/tmp/RELEASE/dev/peeringdb/init.sql` - load it into mysql.

```sh
mysql -u root -p < .facsimile/tmp/RELEASE/dev/peeringdb/init.sql
```

## Migrate database - empty, from scratch

```sh
. ~/srv/dev.peeringdb.com/venv/bin/activate;
./manage.py migrate;
./manage.py createcachetable;
./manage.py loaddata fixtures/initial_data.json;
```

## Running the dev instance

```sh
./manage.py runserver
```

## Populating with data

There are currently 2 ways to get some data into your developer instance

1) Sync from production peeringdb - slow, but accurate data
2) Generate test data - fast, but marginally useful test data

### 1) Sync from Production

You can populate your data from peeringdb.com using

```sh
./manage.py pdb_load_data --commit
```

However be prepared for this to take 15-20 minutes as it will not only sync the entities, but also set up usergroups for each organization and so forth.

This should only be used to populate initial data. Once you have started adding / updating objects and your data diverges from production data, it is no longer useful to call this command.

Special Note: this will only sync data visible to everyone, any fields or rows hidden behind authentication will be missed.

### 2) Generate test data

Alternatively a faster way to get data into your instance is to generate a set of test data.

The data generated has no relation to real world data, but should be good enough for testing purposes

```sh
./manage.py pdb_generate_test_data --commit
```

## Admin

The admin area can be accessed from the `/cp` endpoint, you will need to have a superuser to access it

```sh
./manage.py createsuperuser
```

## Hangups

### Authentication not working

This is usually caused by misconfigured session settings

In `peeringdb_com/settings.d/01-local.conf`

- Check that `SESSION_COOKIE_DOMAIN` is set to the apropriate domain
- Check that `SESSION_COOKIE_SECURE` is `False` if youre not serving over https

# Versioning

Everything is versioned for deploy, using facsimile.

```sh
# to update dev versions
version_bump_dev

# to update release versions
version_merge_release
```

# Tests

Requires `pip install tox`

```sh
tox
```

