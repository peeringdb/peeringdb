import pytest
from playwright.sync_api import Page

TIMEOUT = 60000


def search_for_term(page: Page, term: str):
    """
    This function fills the search form with the given term and submits the form.
    """
    page.fill('form[action="/search"] input[id="search"]', term)
    page.press('form[action="/search"] input[id="search"]', "Enter")


def check_search_results(page: Page, category: str, term: str):
    """
    This function checks if the search results contain the given term in the specified category.
    """
    return page.wait_for_selector(
        f'xpath=//div[@class="search-result"]//div[starts-with(., "{category}")]'
        + f'//following-sibling::div//a[normalize-space()="{term}"]',
        timeout=TIMEOUT,
    )


def test_search_exchange(config, page: Page):
    """
    This function tests the functionality of searching for an exchange.
    """
    page.goto(config["url"])
    ix_name = config["test_search_exchange"]["name"]
    search_for_term(page, ix_name)
    assert check_search_results(page, "Exchanges", ix_name)


@pytest.mark.search
def test_search_network(config, page: Page):
    """
    This function tests the functionality of searching for a network.
    """
    page.goto(config["url"])
    network_name = config["test_search_network"]["name"]
    search_for_term(page, network_name)
    assert check_search_results(
        page,
        "Networks",
        config["test_search_network"].get("quick_search_result", network_name),
    )


@pytest.mark.search
def test_search_facility(config, page: Page):
    """
    This function tests the functionality of searching for a facility.
    """
    page.goto(config["url"])
    facility_name = config["test_search_facility"]["name"]
    search_for_term(page, facility_name)
    assert check_search_results(page, "Facilities", facility_name)


@pytest.mark.search
def test_search_organization(config, page: Page):
    """
    This function tests the functionality of searching for an organization.
    """
    page.goto(config["url"])
    org_name = config["test_search_organization"]["name"]
    search_for_term(page, org_name)
    assert check_search_results(page, "Organizations", org_name)
