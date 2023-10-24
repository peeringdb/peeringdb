# Installation
- Install playwright: To execute UX tests, the first step is to install `playwright`. You can install it by using the command below:

```sh
pip install playwright
```

- Then, you have to run playwright's install command. This command will download all necessary browser binaries.

```sh
playwright install
```

# Running UX Tests

The ux-tests are designed to be run using pytest, and the tests can be targeted to different browsers and user accounts by using command-line options.

## Command-line Options

- `--browser`: The type of browser to run tests on. Can be either `chromium`, `firefox`, `webkit` or `all`. If not specified, `all` is used by default.

- `--account`: The type of user to run the tests as. If not specified, `unauthenticated` is used by default.

- `--config`: Specify the path to a JSON configuration file to provide variables for tests. If not specified, `config.json` is the default.

## Running the Tests

```sh
pytest --browser chromium --account user --config path/to/config.json
```
In the above command, replace `chromium` with the desired browser type, replace `user` with the type of user to be tested, and replace `path/to/config.json` with the actual path to your test configuration file.


## Test Markers

In the provided Python script (`conftest.py`), pytest markers are used to categorize test cases. Below is a brief description of the markers available:

- `profile`: This marker is used to run profile tests. Tests with this marker require the `--account` option to be set.

- `search`: This marker indicates a test is related to search functionality.

- `links`: This marker implies tests are performed on links, following them and testing the resulting pages.

### Run only search tests

```sh
pytest -m 'search' --browser firefox --config path/to/config.json
```

### Run profile tests

```sh
pytest -m 'profile' --browser firefox --account user --config path/to/config.json
```

Note: profile tests are only run if both `--account` and `-m 'profile'` are specified.

### Run search and links tests

```bash
pytest -m 'search or links' --browser firefox --account user --config path/to/config.json
```

# Setup Configuration

Before running the tests, we will need to set up the configuration for the tests. An example configuration file (`config.dev.example.json`) has been provided, and this needs to be filled in with actual values and saved as `config.json` or some other filename.

```json
{
    "url": "https://localhost:8000",
    "accounts":{
        "user": {
            "username": "<username>",
            "password": "<password>"
        }
    },
    "test_search_exchange": {
        "name": "ChIX"
    },
    "test_search_network": {
        "name": "20C",
        "quick_search_result": "20C (63311)"
    },
    "test_search_facility": {
        "name": "CoreSite - Chicago (CH1)"
    },
    "test_search_organization": {
        "name": "20C, LLC"
    },
    "test_add_api_key": {
        "description": "test"
    },
    "test_delete_api_key": {
        "description": "test"
    },
    "test_change_password": {
        "password": "Verified@test"
    }
}
```

- Replace `<username>` and `<password>` under `accounts.user` with the credentials of the user on the website under testing.
- You should also replace the values for the other fields to fit the data on your website.
