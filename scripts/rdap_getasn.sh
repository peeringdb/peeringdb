#!/bin/bash

handle=$1
if test -z "$handle"; then
  echo usage $0 HANDLE
  exit 1
fi

curl -L4 https://rdap.db.ripe.net/autnum/$handle > tests/data/rdap/autnum/${handle}.input
