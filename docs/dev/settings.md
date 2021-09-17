## Location

Settings are defined in `/mainsite/settings/__init__.py`

Environments may also override settings by specifying their own file (e.g., `/mainsite/settings/dev.py`)

Environments may also override settings by exporting them as environment variables.

```sh
export GOOGLE_GEOLOC_API_KEY=abcde
```

## Adding new settings

When adding a setting use the `set_from_env` and the `set_option` wrappers to do so.

These ensure that the overrides mentioned above are functionial. Use `set_from_env` for variables you anticipate are definitely going to get override on a per environment basis. 

Use `set_option` for everything else.
