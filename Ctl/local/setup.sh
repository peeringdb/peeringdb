#!/bin/bash

if [ "$1" = "" ]; then
    cron="on"
elif [ "$1" = "disable" ]; then
    cron="off"
elif [ "$1" = "-h" ] || [ "$1" = "help" ]; then
    echo "Usage: ./Ctl/local/setup.sh"
    echo ""
    echo "Available options:"
    echo "  disable             Disable automated generate data from pdb_load_data command"
    echo "  help                Show available commands"
    exit 1
else
    echo "$1 is not an option, use '-h' or 'help' for usage"
    exit 1
fi

# Check if .env file exists, if not copy from example.env
if [ ! -f ./Ctl/local/.env ]; then
    cp ./Ctl/local/env.example ./Ctl/local/.env
fi

./Ctl/local/compose.sh build peeringdb
./Ctl/local/compose.sh up -d database
./Ctl/local/run.sh migrate
until ./Ctl/local/run.sh migrate; do
    echo "Migrations failed. Retrying in 5 seconds..."
    sleep 5
done
./Ctl/local/run.sh loaddata fixtures/initial_data.json

#echo "--- Creating superuser ---"
#echo ""

#./Ctl/local/run.sh createsuperuser
./Ctl/local/run.sh createcachetable

echo "--- Starting PeeringDB ---"
echo ""
./Ctl/local/compose.sh up -d peeringdb

echo "--- Loading PeeringDB data (this can take a while) ---"
echo ""
./Ctl/local/run.sh pdb_load_data --commit

echo "--- Updating search index ---"
echo ""
./Ctl/local/run.sh search_index -f --rebuild

echo "--- Fetching api-cache ---"
echo ""
./Ctl/local/exec.sh pdb_fetch_api_cache

if [ "$cron" = "on" ]; then
    echo "Starting automatic sync daemon"
    ./Ctl/local/auto_pdb_load_data.sh start
fi
