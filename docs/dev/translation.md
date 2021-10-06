# Maintaining Translations

## Setup

Clone the [translations](https://github.com/peeringdb/translations) repository in the location that
contains your `peeringdb` directory

Clone the [django-peeringdb](https://github.com/peeringdb/django-peeringdb) repository in the location that
contains your `peeringdb` directory

```sh
git clone git@github.com:peeringdb/translations
git clone git@github.com:peeringdb/django-peeringdb
```

Running `ls` should show somethin like this

```sh
django-peeringdb
peeringdb
translations
```

Edit your peeringdb docker compose config to make the translation files and django-peeringdb source available

```sh
cd peeringdb
vim Ctl/dev/docker-compose.sh
```

Uncomment the mount point for `locale` under `volumes`

```
    volumes:
      ...
      - ../../../translations/locale:/srv/www.peeringdb.com/locale:Z
      - ../../../django-peeringdb/src/django_peeringdb:/srv/www.peeringdb.com/venv/lib/python3.9/site-packages/django_peeringdb:Z

```

## Generate a new locale

Call makemessages and pass the locale to the `-l` option. In this example we are passing `de` for german.

```
Ctl/dev/run.sh /bin/sh
. venv/bin/activate
django-admin makemessages -l de -s --no-wrap
django-admin makemessages -d djangojs -l de -s --no-wrap
```

## Updating messages in existing locale

This will add any new messages to all locale files. In other words if there has been new features added, you want to call this to make sure that their messages exist in gettext so they can be translated.

```
Ctl/dev/run.sh /bin/sh
. venv/bin/activate
django-admin makemessages -a -s --no-wrap
django-admin makemessages -d djangojs -a -s --no-wrap
```

## Compile messages

Once translation files are ready, you need to compile them so django can use them.

```
Ctl/dev/run.sh /bin/sh
. venv/bin/activate
django-admin compilemessages
```
