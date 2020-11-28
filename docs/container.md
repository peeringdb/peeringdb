
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

This file can be used to set environment variables for your peeringdb environment. For
now it is ok for it to be empty, but it needs to exist.

# XXX make run do this
```sh
touch Ctl/dev/.env
```

### 3. Build the container and set up your dev instance

```sh
./Ctl/dev/compose.sh up -d database
./Ctl/dev/run.sh migrate
./Ctl/dev/run.sh createsuperuser
./Ctl/dev/run.sh createcachetable
./Ctl/dev/run.sh pdb_load_data --commit #only if you want to sync data from live pdb
./Ctl/dev/compose.sh up -d peeringdb
```

After it is done you should have a peeringdb instance exposed on port `:8000` - should you want to change
this port you can do so by setting the environment variable `DJANGO_PORT`.

### Environment Variables

`PDB_NO_MIGRATE`: If set to anything, will skip migrations, otherwise, migrations will always be applied first thing while running.

- `DATABASE_ENGINE` default "mysql"
- `DATABASE_HOST` default "127.0.0.1"
- `DATABASE_PORT` default ""
- `DATABASE_NAME` default "peeringdb"
- `DATABASE_USER` default "peeringdb"
- `DATABASE_PASSWORD` default ""

### Mount points

`/srv/www.peeringdb.com/api-cache`: api cache
`/srv/www.peeringdb.com/locale`: translations
`/srv/www.peeringdb.com/mainsite`: site settings
`/srv/www.peeringdb.com/media`: media files
`/srv/www.peeringdb.com/peeringdb_server`: server code
`/srv/www.peeringdb.com/static`: static files
`/srv/www.peeringdb.com/var/log`: log files

### Entry point

The entry point will run migrations and pass directly to django's manage script.

Other options:

`/bin/sh` to drop to shell
`inetd` run the inetd whois server


### Examples

Example: Using a shell for development

This is assuming you have an external synced database running locally

```sh
export CONTAINER_TAG=peeringdb:server-`cat Ctl/VERSION`
docker run --net=host -it \
  -v `pwd`/mainsite/:/srv/www.peeringdb.com/mainsite \
  -v `pwd`/peeringdb_server:/srv/www.peeringdb.com/peeringdb_server \
  -e DATABASE_PASSWORD=$DB_PASSWORD \
  $CONTAINER_TAG /bin/sh
```

Once you're in the container, you can run `manage runserver 0.0.0.0:$PORT` to start a development server.
