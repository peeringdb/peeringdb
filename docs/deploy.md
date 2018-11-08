
# PeeringDB Deploy

## Getting Started

This document uses the following variables

```sh
export PDB_REPO=git@github.com:peeringdb/peeringdb.git
```

### Install obfuscation tools (Only needed if you want to obfuscate js)

```sh
git clone src.20c.com:20c/sys-deploy
mkdir -p ~/.local/google
wget https://dl.google.com/closure-compiler/compiler-latest.zip
unzip compiler-latest.zip
mv compiler.jar ~/.local/google
```

### Install facsimile

```sh
pip install facsimile
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

```
facs $component $environment ($version|--src-dir=. for dev)
```

Use the `facs` command to deploy a virtualenv and server files for your dev instance

```sh
facs peeringdb dev --src-dir=.
facs venv dev --src-dir=.
```

Files will be deployed to `~/srv/dev.peeringdb.com`

## Setup passwords

Once you have run `facs` for the first time it will have created a .facsimile directory

You will want to open `.facimsile/state/{env}/state.yaml` and set the correct passwords for everything and then do
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
./manage.py migrate
./manage.py createcachetable
./manage.py loaddata fixtures/initial_data.json
```

## Running the dev instance

```sh
./manage.py runserver
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

```sh
pytest -v -rxs --cov-report term-missing --cov=peeringdb_server/ --capture=sys tests/
```

