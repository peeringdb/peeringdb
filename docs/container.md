
# PeeringDB Container

## Start a developer instance


### Install and Run Docker

PeeringDB runs inside a Docker container. Docker Compose is used to build both the PeeringDB container and a MySQL server container for testing.

Make sure the ```docker``` and ```docker-compose``` commands are installed on your system, and that the Docker Engine is running. Docker Desktop for Mac/Windows (>=2.5.0.1) includes these tools and they are also available for various POSIX systems. Ensure that ```docker-compose version``` indicates at least version 1.25.4, and that ```docker version``` indicates Engine version at least 19.03.5 and does not report any connection errors to Docker Engine. Connection errors may indicate a need to start the engine.

### Fork the PeeringDB repository, Clone it, Set upstream

Your development and experimentation with the PeeringDB code base should take place in a [fork of the project](https://docs.github.com/en/free-pro-team@latest/github/getting-started-with-github/fork-a-repo).  When you have improvements or fixes to share, you will be able to point other developers to your code, or submit a pull request.

Navigate to [https://github.com/peeringdb/peeringdb](https://github.com/peeringdb/peeringdb).

In the top-right corner of the page, click **Fork**.

On GitHub, navigate to *your* fork of the PeeringDB repository.

Above the list of files, click **Code**.  Copy the HTTPS URL.  It will be something like: ```https://github.com/YOUR-USERNAME/peeringdb.git```

Perform the following:

```sh
PDBHOME=~/src/peeringdb    # Adjust as appropriate to your environment.
mkdir -p $PDBHOME && cd $PDBHOME
git clone https://github.com/YOUR-USERNAME/peeringdb.git
cd $PDBHOME/peeringdb      # Henceforth commands on this page assume you are in this working directory.
git remote add upstream https://github.com/peeringdb/peeringdb.git
git remote -v
> origin	https://github.com/YOUR-USERNAME/peeringdb.git (fetch)
> origin	https://github.com/YOUR-USERNAME/peeringdb.git (push)
> upstream	https://github.com/peeringdb/peeringdb.git (fetch)
> upstream	https://github.com/peeringdb/peeringdb.git (push)
```

Keep your fork up-to-date with the upstream repository: [https://docs.github.com/en/free-pro-team@latest/github/collaborating-with-issues-and-pull-requests/syncing-a-fork](https://docs.github.com/en/free-pro-team@latest/github/collaborating-with-issues-and-pull-requests/syncing-a-fork)

```sh
git fetch upstream
git checkout master    # or other branch you are working on
git merge upstream/master
```

### Create environment variable override file

Environment variables for the server config can be added in `Ctl/dev/.env`.
This file can be empty which will make the django `SECRET_KEY` ephemeral, but
the file does need to exist.

Empty file:

```sh
touch Ctl/dev/.env
```

Alternatively, create a `SECRET_KEY` using `uuidgen` or replace with something similar on your system:

```sh
echo SECRET_KEY=\"$(uuidgen)\" > Ctl/dev/.env
```

If you are serving from anywhere but localhost you will also need to specify the `SESSION_COOKIE_DOMAIN`

```sh
echo "SESSION_COOKIE_DOMAIN=example.com" >> Ctl/dev/.env
```

If you want to enable OIDC's JWT RS256 token signing, you need to specify the file with the RSA secret key found inside the container with the `OIDC_RSA_PRIVATE_KEY_ACTIVE_PATH` variable. You can create the key with open ssl and place it in `Ctl/dev/jwks/filename.key` or let the build system auto generated from the path specified with the variable.

```sh
echo "OIDC_RSA_PRIVATE_KEY_ACTIVE_PATH=/srv/www.peeringdb.com/var/jwks/oidc.key" >> Ctl/dev/.env
```

### Build the container and set up your dev instance

```sh
./Ctl/dev/compose.sh build peeringdb
./Ctl/dev/compose.sh up -d database
./Ctl/dev/run.sh migrate            # Re-run if there are errors.  The database may not yet have started.
./Ctl/dev/run.sh loaddata fixtures/initial_data.json
./Ctl/dev/run.sh createsuperuser
./Ctl/dev/run.sh createcachetable
./Ctl/dev/compose.sh up -d peeringdb
```

On some docker versions `build` can fail with a `ERROR: Service 'peeringdb' failed to build: failed to export image: failed to create image: failed to get layer` error. Simply
running it again should fix the issue.


If you want a copy of the current *public* production data, run this command which often takes more than 15 minutes:

```sh
./Ctl/dev/run.sh pdb_load_data --commit
```

After it is done you should have a PeeringDB instance exposed on port `:8000`: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

(should you want to change this port you can do so by setting the environment variable `DJANGO_PORT`)

### Migration Notes

#### Organization management of oauth applications

Once migration `0085` has been applied you should override the `OAUTH2_PROVIDER_APPLICATION_MODEL` environment variable to
`"peeringdb_server.OAuthApplication"` in order to enable organization management of oauth applications.

Warning: Overriding before migration 0085 has been applied will result in the following migration error and a broken migration state.

```
Related model 'peeringdb_server.oauthapplication` cannot be resolved
```

### Stop and start the containers

```sh
./Ctl/dev/compose.sh down
./Ctl/dev/compose.sh up -d
```

### Environment Variables

Edit ```Ctl/dev/.env``` and then stop and start the containers.

- `PDB_NO_MIGRATE`: If set to anything, will skip migrations when running the `uwsgi` command, otherwise, migrations will always be applied first thing while running `uwsgi`.
- `DATABASE_ENGINE` default "mysql"
- `DATABASE_HOST` default "127.0.0.1"
- `DATABASE_PORT` default ""
- `DATABASE_NAME` default "peeringdb"
- `DATABASE_USER` default "peeringdb"
- `DATABASE_PASSWORD` default ""
- `EMAIL_HOST` default "localhost"
- `EMAIL_PORT` default "25"
- `EMAIL_HOST_USERHOST` default ""
- `EMAIL_HOST_PASSWORD` default ""

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

### Contributing your code

After testing and carefully code-reviewing your changes, commit and push them to your repository. You can then share the changes with other developers, such as those on the <pdb-tech@lists.peeringdb.com> mailing list: [https://lists.peeringdb.com/cgi-bin/mailman/listinfo/pdb-tech](https://lists.peeringdb.com/cgi-bin/mailman/listinfo/pdb-tech)

When ready to contribute the change to the project, create a pull request to the main repository along with a description of your goals for the change and/or what you are fixing.
