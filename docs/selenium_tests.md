# Selenium Tests

Selenium tests are in `selenium-tests/` and can be run using pytest.

```
poetry install
pytest selenium-tests/
```

## Config

On your environment you will need to configure an account with an unverified email and an account with a verified email. You will also need to make(and approve if necessary) an Organization, Exchange, Facility and a Network. These are necessary to run all the tests.

#### Permissions for testing write operations

In order for write operations (`--tests=test-writes`) the verified account needs to be an organization admin of the organization specified in the `org_id` config parameters.

### Config file

The config should be placed at `selenium-tests/config.json`, the file contains information used by the tests. There is an example config file at `selenium-tests/config.example.json`, you can copy it or use it as reference. The keys are named after the tests that use the values. Additionally, a different config file can be specified by using the `--config=` command line option.

#### Keys and values

- `"url"`: URL of the PeeringDB instance to test against.
- `"accounts"`: account credentials to be used to sign-in for the tests. These accounts need to already exist on the instance.
- `"test_submit_exchange"`: the test attempts to add an exchange with the `name` and `prefix` specified.
- `"test_edit_exchange"`: the test attempts to find an exchange with `old_name` as name (needs to be already created and approved) and attempts to edit it to the `name`, `website` and `email` specified.
- `"test_delete_exchange"`: the test tries to find an Exchange with `name`, if no such exchange exists, the test submits an exchange with specified `name`, `prefix` and then attempts to delete it.
- `"test_search_exchange"`: the test tries to search for an exchange with the specified `name`, match needs to be exact and whole, fails if exchange not found (exchange must be already created).
- `"test_search_network"`: the test tries to search for a network with the specified `name`, match needs to be exact and whole, fails if network not found (network must be already created).
- `"test_search_facility"`: the test tries to search for a facility with the specified `name`, match needs to be exact and whole, fails if facility not found (facility must be already created).
- `"test_search_organization"`: the test tries to search for an organization with the specified `name`, match needs to be exact and whole, fails if organization not found (organization must be already created).
- `"test_add_api_key"`: the test attempts to add an API key with the specified `description`.
- `"test_delete_api_key"`: the test attempts to remove an API key with the specified `description`.
- `"test_change_password"`: the test attempts to change the password to the specified `password` and changes it back to the original password (the one specified in `"accounts"`).

## Command line options

There are 2 additional command line options that these tests take, `--test` and `--account`

### --account

There are 3 options `--account=` `unauthenticated`(default), `unverified` or `verified`. Some features are not available for `unauthenticated`(not logged in) and others not available for `unverified`(email not verified) users while all features are available for `verified` users. Depending on the value of `--account` different users are logged in, and different tests are run.

### --test

Some tests are categorized to not run by default. Currently, the only category that exists is `test-writes` these test make changes to the database by writing in new data and that might not be desirable in certain environments. Those test will only be run if you specify it in the command line options like `--tests=test-writes`.

### --config

Use this to specify a config file you want to use (by default it uses `config.json`). Example: `--config=config2.json`
