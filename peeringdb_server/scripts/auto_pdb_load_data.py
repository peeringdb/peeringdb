"""
Runs the pdb_load_data command on a randomized interval

Minimum interval is set through PEERINGDB_SYNC_INTERVAL environment variable (seconds)
and will default to 15 minutes if not set.

A random offset of up to 15 minutes will be appalied.
"""

import os
import random
import subprocess
import time

import structlog

# Configure logging
logger = structlog.getLogger(__name__)


def run_pdb_load_data():
    command = "python manage.py pdb_load_data --commit"
    directory = "/srv/www.peeringdb.com/"

    subprocess.call(command, shell=True, cwd=directory)


if __name__ == "__main__":
    try:
        PEERINGDB_SYNC_INTERVAL = int(
            os.environ.get("PEERINGDB_SYNC_INTERVAL", 15 * 60)
        )
    except ValueError:
        PEERINGDB_SYNC_INTERVAL = 1

    default_sleep = PEERINGDB_SYNC_INTERVAL

    # apply a maximum offset of 15 minutes
    max_sleep = default_sleep + (15 * 60)

    logger.info("Starting pdb_load_data daemon...")

    first_run = True

    while bool(PEERINGDB_SYNC_INTERVAL):
        # sleep for a random amount of time between the default interval
        # and the maximum interval
        if first_run:
            sleep_time = 0
        else:
            sleep_time = random.randint(default_sleep, max_sleep)
            logger.info(f"Sleeping for {sleep_time} seconds...")

        time.sleep(sleep_time)

        run_pdb_load_data()
        logger.info("Data loaded successfully.")

        first_run = False
