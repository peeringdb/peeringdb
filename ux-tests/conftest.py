import json

import pytest
from helpers import login
from playwright.sync_api import sync_playwright


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "profile: run profile tests - requires --account to be set"
    )
    config.addinivalue_line("markers", "search: run search tests")
    config.addinivalue_line("markers", "links: run follow links tests")


def pytest_addoption(parser):
    parser.addoption(
        "--account",
        action="store",
        default="unauthenticated",
        help="What type of user to run the tests as",
    )

    parser.addoption(
        "--config",
        action="store",
        default="config.json",
        help="Specify a config file to run the tests off of.",
    )

    parser.addoption(
        "--browser",
        action="store",
        default="all",
        help="Specify a browser to run the tests on.",
        choices=("chromium", "firefox", "webkit", "all"),
    )


def pytest_runtest_setup(item):
    if "profile" in item.keywords and "profile" not in item.config.option.markexpr:
        pytest.skip("Test requires -m 'profile' to be set")

    if "writes" in item.keywords and "writes" not in item.config.option.markexpr:
        pytest.skip("Test requires -m 'writes' to be set")


@pytest.fixture
def account(request):
    account_value = request.config.getoption("--account")
    if account_value is None:
        pytest.skip("Test requires --account to be set")
    return account_value


@pytest.fixture(scope="session")
def config(request):
    config_path = request.config.getoption("--config")

    result = {}
    with open(config_path) as config_file:
        result = json.load(config_file)
    return result


@pytest.fixture(scope="session", params=["chromium", "firefox", "webkit"])
def browser_type(request):
    """
    This fixture returns the type of the browser to use for the current test session.
    """
    # Use the --browser option to decide which browser to use
    browser_option = request.config.getoption("--browser")
    if browser_option == "all":
        # If no specific browser is selected, return the current parameter
        return request.param
    elif request.param == browser_option:
        # If a specific browser is selected, return it
        return browser_option
    else:
        pytest.skip("Skipping tests for this browser")


@pytest.fixture(scope="session")
def account_credentials(config, request):
    """
    This fixture returns the credentials for the type of user specified in the --account option.
    """
    test_account = request.config.getoption("--account")
    account_credentials = config["accounts"]
    # if test account is found in credentials, return it
    if test_account in account_credentials:
        return account_credentials[test_account]
    else:
        return {}


@pytest.fixture(scope="session")
def page(request, config, browser_type):
    """
    This fixture creates a new browser context for each test session.
    """
    with sync_playwright() as p:
        # Use the browser_type fixture to decide which browser to launch
        if browser_type == "chromium":
            browser = p.chromium.launch(headless=True)
        elif browser_type == "firefox":
            browser = p.firefox.launch(headless=True)
        elif browser_type == "webkit":
            browser = p.webkit.launch(headless=True)
        else:
            raise ValueError(f"Unsupported browser type: {browser_type}")

        context = browser.new_context()
        page = context.new_page()

        page.goto(config["url"])
        test_account = request.config.getoption("--account")
        account_credentials = config["accounts"]

        # if test account is found in credentials, login
        if test_account in account_credentials:
            login(
                page,
                account_credentials[test_account]["username"],
                account_credentials[test_account]["password"],
            )

        page.goto(config["url"])
        page.set_viewport_size({"width": 1920, "height": 1080})

        yield page

        context.close()
        browser.close()
