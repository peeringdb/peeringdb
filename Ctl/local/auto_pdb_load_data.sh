#!/bin/bash

AUTO_PDB_LOAD_DATA_DIR="/srv/www.peeringdb.com/peeringdb_server/scripts/auto_pdb_load_data.py"
PID=$(docker exec peeringdb pgrep -f "python $AUTO_PDB_LOAD_DATA_DIR")

if [ "$1" = "" ]; then
    echo "use '-h' or 'help' for usage"
    exit 1
elif [ "$1" = "start" ]; then
    if [[ -n $PID ]]; then
        echo "The automated pdb_load_data already started"
        exit 1
    else
        COMMAND="python $AUTO_PDB_LOAD_DATA_DIR >> /var/log/auto_pdb_load_data.log 2>&1 &"
        echo "Starting the automated pdb_load_data"
    fi
elif [ "$1" = "stop" ]; then
    if [[ -n $PID ]]; then
        COMMAND="kill $PID"
        echo "The automated pdb_load_data has been stopped"
    else
        echo "cron process not found"
        exit 1
    fi
elif [ "$1" = "log" ]; then
    COMMAND="cat /var/log/auto_pdb_load_data.log"
elif [ "$1" = "-h" ] || [ "$1" = "help" ]; then
    echo "Usage: ./Ctl/local/auto_pdb_load_data.sh"
    echo ""
    echo "Available options:"
    echo "  start             Start automated service to run pdb_load_data"
    echo "  stop              Stop automated pdb_load_data command"
    echo "  log               Show log"
    exit 1
else
    echo "$1 is not an option, use '-h' or 'help' for usage"
    exit 1
fi

docker exec peeringdb sh -c "$COMMAND"
