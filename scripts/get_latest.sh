#1/bin/env bash

HOST=pdb@www.peeringdb.com
FILE=pdb-latest-$$.sql

set -x
ssh $HOST "mysqldump --opt peeringdb -r $FILE"
#ssh $HOST "xz -f $FILE"
# no compression because the CPU cries
scp $HOST:${FILE} pdb-latest.sql
ssh $HOST "rm -f $FILE"
