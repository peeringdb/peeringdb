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
  "whois" )
    line=$(head -1 | tr -cd '[:alnum:]._-')
    exec manage pdb_whois "$line"
    ;;
  "/bin/sh" )
    echo dropping to shell
    exec /bin/sh
    ;;
  "makemessages" | "compilemessages" )
    cd /mnt
    exec django-admin $@
    ;;
  * )
    exec manage $@
    ;;
esac
