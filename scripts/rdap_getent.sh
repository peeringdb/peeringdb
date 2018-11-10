#!/bin/bash

function die_usage
  {
  echo usage $0 RIR HANDLE
  exit 1
  }

case "$1" in

'afrnic')
  url=https://rdap.afrinic.net/rdap/entity/
  ;;

'apnic')
  url=https://rdap.apnic.net/entity/
  ;;

'arin')
  url=https://rdap.arin.net/
  ;;

'lacnic')
  echo Lacnic needs to be done by hand since it redirects again
  exit 1
  ;;

'ripe')
  url=https://rdap.db.ripe.net/entity/
  ;;

*)
  die_usage
  ;;
esac

shift

if test -z "$1"; then
  die_usage
fi

for handle in $@; do
  curl $url/$handle > tests/data/rdap/entity/${handle}.input
done
