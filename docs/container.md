
# PeeringDB Container

## Start a developer instance


### 1. Install Docker

PeeringDB runs inside a docker container, make sure docker is installed on your system

### 2. Clone the peeringdb repository

```sh
git clone git@github.com:/peeringdb/peeringdb
cd peeringdb
```

### 2. Create environment variable override file

Environment variables for the server config can be added in `Ctl/dev/.env`.
This file can be empty which will make the django `SECRET_KEY` ephemeral, but
the file does need to exist.

Empty file:

```sh
touch Ctl/dev/.env
```

Create a `SECRET_KEY` using `uuidgen` or replace with something similar on your system:

```sh
echo SECRET_KEY=\"$(uuidgen)\" > Ctl/dev/.env
```

### 3. Build the container and set up your dev instance

```sh
./Ctl/dev/compose.sh build peeringdb
./Ctl/dev/compose.sh up -d database
./Ctl/dev/run.sh migrate
./Ctl/dev/run.sh createsuperuser
./Ctl/dev/run.sh createcachetable
./Ctl/dev/compose.sh up -d peeringdb
```

On some docker versions `build` can fail with a `ERROR: Service 'peeringdb' failed to build: failed to export image: failed to create image: failed to get layer` error. Simply
running it again should fix the issue.


If you want a copy of the current production data, run this command

```sh
./Ctl/dev/run.sh pdb_load_data --commit
```

After it is done you should have a peeringdb instance exposed on port `:8000` - should you want to change
this port you can do so by setting the environment variable `DJANGO_PORT`.

### Environment Variables

- `PDB_NO_MIGRATE`: If set to anything, will skip migrations when running the `uwsgi` command, otherwise, migrations will always be applied first thing while running `uwsgi`.
- `DATABASE_ENGINE` default "mysql"
- `DATABASE_HOST` default "127.0.0.1"
- `DATABASE_PORT` default ""
- `DATABASE_NAME` default "peeringdb"
- `DATABASE_USER` default "peeringdb"
- `DATABASE_PASSWORD` default ""

### Mount points

- `/srv/www.peeringdb.com/api-cache`: api cache
- `/srv/www.peeringdb.com/locale`: translations
- `/srv/www.peeringdb.com/mainsite`: site settings
- `/srv/www.peeringdb.com/media`: media files
- `/srv/www.peeringdb.com/peeringdb_server`: server code
- `/srv/www.peeringdb.com/static`: static files
- `/srv/www.peeringdb.com/var/log`: log files

### Entry point

With the exception of some specific commands (see below) the entry point will pass directly to django's manage script.

```sh
./Ctl/dev/run.sh help
```

Other options:

- `migrate` apply database migrations
- `run_tests` run unit tests
- `uwsgi` start the uwsgi process
- `/bin/sh` to drop to shell
- `inetd` run the inetd whois server



