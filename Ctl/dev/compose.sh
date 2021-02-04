#!/bin/bash


COMPOSE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

docker-compose -f $COMPOSE_DIR/docker-compose.yml $@
