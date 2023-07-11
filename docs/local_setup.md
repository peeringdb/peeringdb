
# Setting up a local peeringdb instance

Note: if you're looking at setting up a developer instance please refer to the development instructions instead.

This will set up an instance you can use to run a local snapshot of peeringdb.

Usage:
```sh
./Ctl/local/setup.sh [option]
```

This is a bash script used to set up a local PeeringDB environment. The script takes an optional argument which can be either "disable" or "help". If no argument is provided, the script assumes that automated data synchronization from the production API is enabled.

The script checks if the .env file exists, if not, it copies from env.example.

It then builds the peeringdb container, sets up the database, runs migrations, loads initial data, creates a cache table, starts the PeeringDB container, loads PeeringDB data, updates the search index, fetches api-cache and if automated data generation is enabled, it starts the automatic sync daemon.


Options:
- disable: Disable automated generate data from pdb_load_data command
- help: Show available commands

# Manually interacting with the automatic data sync

This is a bash script used to manage the automated pdb_load_data service. The script takes one required argument which can be either "start", "stop", "log" or "help".

The "start" option starts the automated pdb_load_data service if it's not already running. The "stop" option stops the automated pdb_load_data service if it's running. The "log" option shows the log of the automated pdb_load_data service. The "help" option shows the available commands.

Usage:
```sh
./Ctl/local/auto_pdb_load_data.sh [option]
```

Options:
- start: Start automated service to run pdb_load_data
- stop: Stop automated pdb_load_data command
- log: Show log
- help: Show available commands

# Example: automatic api cache regeneration

Currently automatic api cache updates aren't scheduled on local instances, as they can take up a lot of resources. Here is an example of a python script that will regenerate the API cache of your instance every 1000 seconds.

```py
import subprocess
import time

def run_commands():
    """
    Run the specified shell commands every 5 minutes.
    """
    while True:
        subprocess.run(["Ctl/local/exec.sh", "pdb_api_cache", "--depth", "0"])
        time.sleep(1000)

run_commands()
```
