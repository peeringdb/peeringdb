#!/bin/bash

if [ "$1" = "" ]; then
    cron="on"
elif [ "$1" = "disable" ]; then
    cron="off"
elif [ "$1" = "-h" ] || [ "$1" = "help" ]; then
    echo "Usage: ./Ctl/dev/setup.sh"
    echo ""
    echo "Available options:"
    echo "  disable             Disable automated generate data from pdb_load_data command"
    echo "  help                Show available commands"
    exit 1
else
    echo "$1 is not an option, use '-h' or 'help' for usage"
    exit 1
fi

./Ctl/dev/compose.sh build peeringdb
./Ctl/dev/compose.sh up -d database
./Ctl/dev/run.sh migrate
until ./Ctl/dev/run.sh migrate; do
    echo "Migrations failed. Retrying in 5 seconds..."
    sleep 5
done
./Ctl/dev/run.sh loaddata fixtures/initial_data.json
./Ctl/dev/run.sh createsuperuser
./Ctl/dev/run.sh createcachetable
./Ctl/dev/compose.sh up -d peeringdb
if [ "$cron" = "on" ]; then
    ./Ctl/dev/auto_pdb_load_data.sh start
fi
