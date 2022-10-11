from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


def test_search_exchange(config, driver):
    driver.get(config["url"])
    ix_name = config["test_search_exchange"]["name"]
    search_for_term(driver, ix_name)
    assert check_search_results(driver, "Exchanges", ix_name)


def test_search_network(config, driver):
    driver.get(config["url"])
    network_name = config["test_search_network"]["name"]
    search_for_term(driver, network_name)
    assert driver.find_element(
        By.XPATH,
        '//div[@class="search-result"]//div[starts-with(., "Networks")]'
        + f'//following-sibling::div//a[starts-with(., "{network_name}")]',
    )


def test_search_facility(config, driver):
    driver.get(config["url"])
    facility_name = config["test_search_facility"]["name"]
    search_for_term(driver, facility_name)
    assert check_search_results(driver, "Facilities", facility_name)


def test_search_organization(config, driver):
    driver.get(config["url"])
    org_name = config["test_search_organization"]["name"]
    search_for_term(driver, org_name)
    assert check_search_results(driver, "Organizations", org_name)


def search_for_term(driver, term):
    driver.find_element(
        By.XPATH, '//form[@action="/search"]//input[@id="search"]'
    ).send_keys(term + Keys.ENTER)


def check_search_results(driver, category, term):
    return driver.find_element(
        By.XPATH,
        f'//div[@class="search-result"]//div[starts-with(., "{category}")]'
        + f'//following-sibling::div//a[normalize-space()="{term}"]',
    )
