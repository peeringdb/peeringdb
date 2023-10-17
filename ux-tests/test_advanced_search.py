import pytest
from playwright.sync_api import Page

TIMEOUT = 60000


def get_id(category):
    return {
        "Exchanges": "ix",
        "Networks": "net",
        "Facilities": "fac",
        "Organizations": "org",
    }[category]


def wait_for_results(page: Page, category):
    """
    This function waits for the search results to load on the page.
    """
    category_id = get_id(category)

    # Wait for either the results to appear or for a "no results" message to appear
    try:
        page.wait_for_selector(f"#{category_id} .results div", timeout=TIMEOUT)
    except Exception:
        page.wait_for_selector(f"#{category_id} .results-empty", timeout=TIMEOUT)


def advanced_search_for_name(page: Page, category, name):
    """
    This function performs an advanced search for the given name in the specified category.
    """
    category_id = get_id(category)
    page.click('a[href="/advanced_search"]')
    page.click(f'.advanced-search-view a[href="#{category_id}"]')
    page.fill(
        f'//div[@id="{category_id}"]//div[@data-edit-name="name_search"]//input',
        name,
        timeout=TIMEOUT,
    )
    page.click(f'//div[@id="{category_id}"]//a[@data-edit-action="submit"]')


def check_advanced_search_results(page: Page, category, name):
    """
    This function checks if the advanced search results contain the expected name.
    """
    wait_for_results(page, category)

    try:
        page.wait_for_selector(
            f'//div[@id="{get_id(category)}"]//div[@class="results"]'
            + f'//a[@data-edit-name="name"][normalize-space()="{name}"]',
            timeout=TIMEOUT,
        )
        return True
    except Exception as exc:
        return False, f"Element not found {exc}"


@pytest.mark.search
def test_advanced_search_exchange(config, page: Page):
    """
    This function tests the advanced search functionality for exchanges.
    """
    page.goto(config["url"])
    ix_name = config["test_search_exchange"]["name"]
    advanced_search_for_name(page, "Exchanges", ix_name)
    assert check_advanced_search_results(page, "Exchanges", ix_name)


@pytest.mark.search
def test_advanced_search_network(config, page: Page):
    """
    This function tests the advanced search functionality for networks.
    """
    page.goto(config["url"])
    network_name = config["test_search_network"]["name"]
    advanced_search_for_name(page, "Networks", network_name)
    assert check_advanced_search_results(page, "Networks", network_name)


@pytest.mark.search
def test_advanced_search_facility(config, page: Page):
    """
    This function tests the advanced search functionality for facilities.
    """
    page.goto(config["url"])
    facility_name = config["test_search_facility"]["name"]
    advanced_search_for_name(page, "Facilities", facility_name)
    assert check_advanced_search_results(page, "Facilities", facility_name)


@pytest.mark.search
def test_advanced_search_organization(config, page: Page):
    """
    This function tests the advanced search functionality for organizations.
    """
    page.goto(config["url"])
    org_name = config["test_search_organization"]["name"]
    advanced_search_for_name(page, "Organizations", org_name)
    assert check_advanced_search_results(page, "Organizations", org_name)


@pytest.mark.search
def test_advanced_search_url_exchange(config, page: Page):
    """
    This function tests the advanced search functionality for exchanges with URL checks.
    """
    page.goto(config["url"])
    ix_name = config["test_search_exchange"]["name"]
    advanced_search_for_name(page, "Exchanges", ix_name)
    # reload with current url
    page.goto(page.url)
    assert check_advanced_search_results(page, "Exchanges", ix_name)


@pytest.mark.search
def test_advanced_search_url_network(config, page: Page):
    """
    This function tests the advanced search functionality for networks with URL checks.
    """
    page.goto(config["url"])
    network_name = config["test_search_network"]["name"]
    advanced_search_for_name(page, "Networks", network_name)
    # reload with current url
    page.goto(page.url)
    assert check_advanced_search_results(page, "Networks", network_name)


@pytest.mark.search
def test_advanced_search_url_facility(config, page: Page):
    """
    This function tests the advanced search functionality for facilities with URL checks.
    """
    page.goto(config["url"])
    facility_name = config["test_search_facility"]["name"]
    advanced_search_for_name(page, "Facilities", facility_name)
    # reload with current url
    page.goto(page.url)
    assert check_advanced_search_results(page, "Facilities", facility_name)


@pytest.mark.search
def test_advanced_search_url_organization(config, page: Page):
    """
    This function tests the advanced search functionality for organizations with URL checks.
    """
    page.goto(config["url"])
    org_name = config["test_search_organization"]["name"]
    advanced_search_for_name(page, "Organizations", org_name)
    # reload with current url
    page.goto(page.url)
    assert check_advanced_search_results(page, "Organizations", org_name)
