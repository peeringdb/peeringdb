
# PeeringDB Container


## Building

```sh
export CONTAINER_TAG=peeringdb:server-`cat Ctl/VERSION`
docker build -t $CONTAINER_TAG -f Dockerfile .
```

## Running

### Environment Variables

`PDB_NO_MIGRATE`: If set to anything, will skip migrations, otherwise, migrations will always be applied first thing while running.

`DATABASE_ENGINE` default "mysql"
`DATABASE_HOST` default "127.0.0.1"
`DATABASE_PORT` default ""
`DATABASE_NAME` default "peeringdb"
`DATABASE_USER` default "peeringdb"
`DATABASE_PASSWORD` default ""



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
