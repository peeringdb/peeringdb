#!/bin/sh


if [[ "$PDB_NO_MIGRATE" == "" ]]; then
  echo applying migrations - django_peeringdb
  # always fake, since peeeringdb_server does not use concrete models
  manage migrate django_peeringdb --fake
  echo applying all migrations
  manage migrate
fi


cd /srv/www.peeringdb.com

case "$1" in
  "uwsgi" )
    echo starting uwsgi
    exec venv/bin/uwsgi --ini etc/django-uwsgi.ini
    ;;
  "inetd" )
    inetd -f -e -q 1024
    ;;
  "in.whois" )
    exec ./in.whoisd
    ;;
  "whois" )
    line=$(head -1 | tr -cd '[:alnum:]._-')
    exec manage pdb_whois "$line"
    ;;
  "/bin/sh" )
    echo dropping to shell
    exec /bin/sh
    ;;
  * )
    exec manage $@
    ;;
esac
