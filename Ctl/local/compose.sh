#!/bin/bash


COMPOSE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PROJECT_NAME=$(basename $(git rev-parse --show-toplevel))$(basename $COMPOSE_DIR)
DOCKER_COMPOSE="docker-compose"
docker compose version >/dev/null 2>&1 && DOCKER_COMPOSE="docker compose"

$DOCKER_COMPOSE -p $PROJECT_NAME -f $COMPOSE_DIR/docker-compose.yml $@
if [[ "$@" == *"up -d peeringdb"* ]]; then
    ./Ctl/local/auto_pdb_load_data.sh start
fi
