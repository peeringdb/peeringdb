import json

import pytest
from helper import login
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager


def pytest_configure(config):
    # register the "key" marker
    config.addinivalue_line(
        "markers",
        "key(str): mark what type tests that shouldn't run by default are, start with 'test-'.",
    )

    # register the "lvl" marker
    config.addinivalue_line(
        "markers", "lvl(str): unathenticated, unverified or verified level tests."
    )


def pytest_addoption(parser):
    parser.addoption(
        "--account",
        action="store",
        default="unauthenticated",
        help="What type of user to run the tests as: unauthenticated, unverified or verified",
        choices=("unauthenticated", "unverified", "verified"),
    )

    parser.addoption(
        "--tests",
        action="store",
        help="Also run tests with specified keys, eg: tests-write",
    )

    parser.addoption(
        "--config",
        action="store",
        default="config.json",
        help="Specify a config file to run the tests off of.",
    )


def pytest_collection_modifyitems(session, config, items):
    add_tests = tuple()
    if config.getoption("--tests"):
        add_tests = tuple(config.getoption("--tests").split(","))

    for item in items:
        key = item.get_closest_marker("key")
        if (key and key.args and key.args[0][:5] == "test-") and (
            key.args[0] not in add_tests
        ):
            # remove items with tests- as start
            items.remove(item)

    # remove items that don't meet lvl
    levels = {"unauthenticated": 1, "unverified": 2, "verified": 3}
    account_lvl = levels[config.getoption("--account")]
    for item in items:
        test_lvl = item.get_closest_marker("lvl")
        if test_lvl and test_lvl.args and levels[test_lvl.args[0]] > account_lvl:
            items.remove(item)


@pytest.fixture(scope="session")
def config(request):
    config_path = request.config.getoption("--config")

    result = {}
    with open(config_path) as config_file:
        result = json.load(config_file)
    return result


@pytest.fixture(scope="session")
def driver(request, config):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()), options=options
    )

    driver.get(config["url"])
    test_account = request.config.getoption("--account")
    account_credentials = config["accounts"]
    if test_account == "verified":
        login(
            driver,
            account_credentials["verified"]["username"],
            account_credentials["verified"]["password"],
        )
    if test_account == "unverified":
        login(
            driver,
            account_credentials["unverified"]["username"],
            account_credentials["unverified"]["password"],
        )

    driver.get(config["url"])
    yield driver

    driver.quit()


@pytest.fixture
def account_credentials(request, config):
    test_account = request.config.getoption("--account")
    return config["accounts"][test_account]
