# Maintaining Translations

NOTE!: This page is for PeeringDB developers, not translators. Per [https://docs.peeringdb.com/translation/](https://docs.peeringdb.com/translation/) translations are performed at [https://translate.peeringdb.com/](https://translate.peeringdb.com/).

## Setup

Clone the [translations](https://github.com/peeringdb/translations) repository in the location that
contains your `peeringdb` directory.

Clone the [django-peeringdb](https://github.com/peeringdb/django-peeringdb) repository in the location that
contains your `peeringdb` directory.

```sh
git clone git@github.com:peeringdb/translations
git clone git@github.com:peeringdb/django-peeringdb
```

Running `ls` should show something like this:

```sh
django-peeringdb
peeringdb
translations
```

Edit the peeringdb docker compose config to make the translation files and django-peeringdb source available.

```sh
cd peeringdb
vim Ctl/dev/docker-compose.yml
```

Uncomment the mount point for `locale` under `volumes`

```
    volumes:
      ...
      - ../../../translations/locale:/srv/www.peeringdb.com/locale:Z
      - ../../../django-peeringdb/src/django_peeringdb:/srv/www.peeringdb.com/venv/lib/python3.9/site-packages/django_peeringdb:Z

```

Create an empty .env to avoid errors when bringing containers up:

```sh
touch Ctl/dev/.env
```

## Generate a new locale

Call makemessages and pass the locale to the `-l` option. In this example we are passing `de` for German.

```
Ctl/dev/run.sh /bin/sh
. venv/bin/activate
django-admin makemessages -l de -s --no-wrap -i venv
django-admin makemessages -d djangojs -l de -s --no-wrap -i venv
```

## Updating messages in existing locale

This will add any new messages to all locale files. In other words, if there have been new features added, one wants to call this to make sure the messages exist in gettext so they can be translated.

```
Ctl/dev/run.sh /bin/sh
. venv/bin/activate
django-admin makemessages -a -s --no-wrap -i venv
django-admin makemessages -d djangojs -a -s --no-wrap -i venv
```

## Compile messages

Once translation files are ready, one needs to compile them so django can use them.

```
Ctl/dev/run.sh /bin/sh
. venv/bin/activate
django-admin compilemessages -i venv
```
