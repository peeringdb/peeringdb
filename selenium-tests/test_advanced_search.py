import selenium.webdriver.support.expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait


def test_advanced_search_exchange(config, driver):
    driver.get(config["url"])
    ix_name = config["test_search_exchange"]["name"]
    advanced_search_for_name(driver, "Exchanges", ix_name)
    assert check_advanced_search_results(driver, "Exchanges", ix_name)


def test_advanced_search_url_exchange(config, driver):
    driver.get(config["url"])
    ix_name = config["test_search_exchange"]["name"]
    advanced_search_for_name(driver, "Exchanges", ix_name)
    # reload with current url
    driver.get(driver.current_url)
    assert check_advanced_search_results(driver, "Exchanges", ix_name)


def test_advanced_search_network(config, driver):
    driver.get(config["url"])
    network_name = config["test_search_network"]["name"]
    advanced_search_for_name(driver, "Networks", network_name)
    wait_for_results(driver, "Networks")
    try:
        assert driver.find_element(
            By.XPATH,
            f'//div[@id="{get_id("Networks")}"]//div[@class="results"]'
            + f'//a[@data-edit-name="name"][starts-with(., "{network_name}")]',
        )
    except NoSuchElementException as exc:
        assert False, f"Element not found {exc}"


def test_advanced_search_url_network(config, driver):
    driver.get(config["url"])
    network_name = config["test_search_network"]["name"]
    advanced_search_for_name(driver, "Networks", network_name)
    # reload with current url
    driver.get(driver.current_url)
    wait_for_results(driver, "Networks")
    try:
        assert driver.find_element(
            By.XPATH,
            f'//div[@id="{get_id("Networks")}"]//div[@class="results"]'
            + f'//a[@data-edit-name="name"][starts-with(., "{network_name}")]',
        )
    except NoSuchElementException as exc:
        assert False, f"Element not found {exc}"


def test_advanced_search_facility(config, driver):
    driver.get(config["url"])
    facility_name = config["test_search_facility"]["name"]
    advanced_search_for_name(driver, "Facilities", facility_name)
    assert check_advanced_search_results(driver, "Facilities", facility_name)


def test_advanced_search_url_facility(config, driver):
    driver.get(config["url"])
    facility_name = config["test_search_facility"]["name"]
    advanced_search_for_name(driver, "Facilities", facility_name)
    # reload with current url
    driver.get(driver.current_url)
    assert check_advanced_search_results(driver, "Facilities", facility_name)


def test_advanced_search_organization(config, driver):
    driver.get(config["url"])
    org_name = config["test_search_organization"]["name"]
    advanced_search_for_name(driver, "Organizations", org_name)
    assert check_advanced_search_results(driver, "Organizations", org_name)


def test_advanced_search_url_organization(config, driver):
    driver.get(config["url"])
    org_name = config["test_search_organization"]["name"]
    advanced_search_for_name(driver, "Organizations", org_name)
    # reload with current url
    driver.get(driver.current_url)
    assert check_advanced_search_results(driver, "Organizations", org_name)


def advanced_search_for_name(driver, category, name):
    category_id = get_id(category)
    driver.find_element(By.XPATH, '//a[@href="/advanced_search"]').click()
    driver.find_element(
        By.CSS_SELECTOR, f'.advanced-search-view a[href="#{category_id}"]'
    ).click()
    driver.find_element(
        By.XPATH,
        f'//div[@id="{category_id}"]//div[@data-edit-name="name_search"]//input',
    ).send_keys(name)
    driver.find_element(
        By.XPATH, f'//div[@id="{category_id}"]//a[@data-edit-action="submit"]'
    ).click()


def check_advanced_search_results(driver, category, name):
    wait_for_results(driver, category)

    try:
        driver.find_element(
            By.XPATH,
            f'//div[@id="{get_id(category)}"]//div[@class="results"]'
            + f'//a[@data-edit-name="name"][normalize-space()="{name}"]',
        )
        return True
    except NoSuchElementException as exc:
        return False, f"Element not found {exc}"


def wait_for_results(driver, category):
    category_id = get_id(category)
    # wait till results load
    WebDriverWait(driver, 10).until(
        EC.any_of(
            EC.visibility_of(
                driver.find_element(By.CSS_SELECTOR, f"#{category_id} .results-empty")
            ),
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, f"#{category_id} .results div")
            ),
            EC.visibility_of(
                driver.find_element(By.CSS_SELECTOR, f"#{category_id} .results-empty")
            ),
        )
    )


def get_id(category):
    return {
        "Exchanges": "ix",
        "Networks": "net",
        "Facilities": "fac",
        "Organizations": "org",
    }[category]
