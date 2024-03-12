#!/bin/sh


function migrate() {
  echo applying migrations - django_peeringdb
  # always fake, since peeeringdb_server does not use concrete models
  manage migrate django_peeringdb --fake
  echo applying all migrations
  manage migrate
}


cd /srv/www.peeringdb.com


case "$1" in
  "uwsgi" )
    echo starting uwsgi
    if [[ "$PDB_NO_MIGRATE" == "" ]]; then
      migrate
    fi
    exec venv/bin/uwsgi --ini etc/django-uwsgi.ini
    ;;
  "migrate" )
    migrate
    ;;
  "inetd" )
    inetd -f -e -q 1024
    ;;
  "in.whois" )
    exec ./in.whoisd
    ;;
  "run_tests" )
    source venv/bin/activate
    export DJANGO_SETTINGS_MODULE=mainsite.settings
    export DATABASE_USER=root
    export DATABASE_PASSWORD=""
    export RELEASE_ENV=run_tests
    export PEERINGDB_SYNC_CACHE_URL=""
    export OIDC_RSA_PRIVATE_KEY_ACTIVE_PATH=/srv/www.peeringdb.com/tests/data/oidc/oidc.key
    unset BASE_URL
    unset OAUTH2_PROVIDER_APPLICATION_MODEL
    unset SESSION_COOKIE_DOMAIN
    unset PEERINGDB_SYNC_API_KEY
    pytest -v -rA --cov-report term-missing --cov=peeringdb_server --durations=0 tests/
    ;;
  "gen_docs" )
    source venv/bin/activate
    export DJANGO_SETTINGS_MODULE=mainsite.settings
    ln -s /srv/www.peeringdb.com/peeringdb_server /srv/www.peeringdb.com/venv/lib/python3.11/site-packages/peeringdb_server
    ln -s /srv/www.peeringdb.com/mainsite /srv/www.peeringdb.com/venv/lib/python3.11/site-packages/mainsite
    mkdir /srv/www.peeringdb.com/venv/lib/python3.11/site-packages/etc/
    mkdir /srv/www.peeringdb.com/venv/lib/python3.11/site-packages/var/log -p
    cp etc/VERSION /srv/www.peeringdb.com/venv/lib/python3.11/site-packages/etc/
    echo generating module documentation files
    python peeringdb_server/gendocs.py
    echo generating schema visualization
    python manage.py graph_models -E -X .*Base --pydot -o docs/img/schema.png peeringdb_server
    echo generating api docs
    python manage.py generateschema --file peeringdb_server/static/api-schema.yaml
    ;;
  "whois" )
    line=$(head -1 | tr -cd '[:alnum:]._-')
    exec manage pdb_whois "$line"
    ;;
  "/bin/sh" )
    echo dropping to shell
    exec $@
    ;;
  "makemessages" | "compilemessages" )
    cd /mnt
    exec django-admin $@
    ;;
  * )
    exec manage $@
    ;;
esac
