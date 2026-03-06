#!/bin/bash
# Test runner for PeeringDB development
# By default uses --reuse-db and parallel execution for faster execution

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Check if --no-reuse-db is passed
if [[ " $@ " =~ " --no-reuse-db " ]]; then
    # Remove --no-reuse-db from arguments and run without --reuse-db
    ARGS="${@//--no-reuse-db/}"
    $SCRIPT_DIR/run.sh run_tests -n auto --dist loadgroup $ARGS
else
    # Default: run with --reuse-db and parallel execution for speed
    $SCRIPT_DIR/run.sh run_tests --reuse-db -n auto --dist loadgroup --disable-warnings "$@"
fi
