import pytest
import selenium.webdriver.support.expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.wait import WebDriverWait


@pytest.mark.key("test-writes")
@pytest.mark.lvl("verified")
def test_submit_exchange(config, driver):
    driver.get(config["url"])
    ix_name = config["test_submit_exchange"]["name"]
    ix_prefix = config["test_submit_exchange"]["prefix"]
    org_id = config["test_submit_exchange"]["org_id"]
    driver.get(config["url"] + f"/org/{org_id}")
    # check whether element already exists
    try:
        driver.find_element(
            By.XPATH,
            f'//div[@id="api-listing-ix"]//div[@data-filter-value="{ix_name}"]',
        )
        assert False, "Test IX already exists please specify another exchange name!"
    except NoSuchElementException:
        pass

    add_ix(driver, ix_name, ix_prefix)

    # Check if new IX appears in list
    try:
        assert WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    f'//div[@id="api-listing-ix"]//*[normalize-space()="{ix_name}"]',
                )
            )
        )
    except TimeoutException as exc:
        assert False, f"Element not found: {exc}"


def add_ix(driver, ix_name, ix_prefix):
    driver.find_element(By.XPATH, '//a[@href="#add_ix"]').click()

    driver.find_element(
        By.XPATH, '//div[@id="create-ix-form"]//div[@data-edit-name="name"]//input'
    ).send_keys(ix_name)
    driver.find_element(
        By.XPATH, '//div[@id="create-ix-form"]//div[@data-edit-name="website"]//input'
    ).send_keys("http://www.testix.com")
    driver.find_element(
        By.XPATH, '//div[@id="create-ix-form"]//div[@data-edit-name="city"]//input'
    ).send_keys("Test City")
    Select(
        driver.find_element(
            By.XPATH,
            '//div[@id="create-ix-form"]//div[@data-edit-name="proto_unicast"]//select',
        )
    ).select_by_value("0")
    Select(
        driver.find_element(
            By.XPATH,
            '//div[@id="create-ix-form"]//div[@data-edit-name="proto_multicast"]//select',
        )
    ).select_by_value("0")
    Select(
        driver.find_element(
            By.XPATH,
            '//div[@id="create-ix-form"]//div[@data-edit-name="proto_ipv6"]//select',
        )
    ).select_by_value("0")
    driver.find_element(
        By.XPATH,
        '//div[@id="create-ix-form"]//div[@data-edit-name="tech_email"]//input',
    ).send_keys("tech@testix.com")
    driver.find_element(
        By.XPATH, '//div[@id="create-ix-form"]//div[@data-edit-name="prefix"]//input'
    ).send_keys(ix_prefix)

    driver.find_element(
        By.XPATH, '//div[@id="create-ix-form"]//a[@data-edit-action="submit"]'
    ).click()


@pytest.mark.key("test-writes")
@pytest.mark.lvl("verified")
def test_edit_exchange(config, driver):
    driver.get(config["url"])
    old_ix_name = config["test_edit_exchange"]["old_name"]
    new_ix_name = config["test_edit_exchange"]["name"]
    new_ix_website = config["test_edit_exchange"]["website"]
    new_ix_email = config["test_edit_exchange"]["email"]
    org_id = config["test_edit_exchange"]["org_id"]
    driver.get(config["url"] + f"/org/{org_id}")

    # check if exchange exists and is approved
    try:
        exchange_link = driver.find_element(
            By.XPATH,
            f'//div[@id="api-listing-ix"]//a[normalize-space()="{old_ix_name}"]',
        )
    except NoSuchElementException:
        assert False, "Exchange not found, please check if it exists."
    assert exchange_link.get_attribute("href") is not None, "Exchange is not approved."
    exchange_link.click()

    # edit
    driver.find_element(
        By.CSS_SELECTOR, '.button-bar a[data-edit-action="toggle-edit"]'
    ).click()

    name_input = driver.find_element(
        By.CSS_SELECTOR, 'div[data-edit-name="name"] input'
    )
    name_input.clear()
    name_input.send_keys(new_ix_name)

    website_input = driver.find_element(
        By.CSS_SELECTOR, 'div[data-edit-name="website"] input'
    )
    website_input.clear()
    website_input.send_keys(new_ix_website)

    email_input = driver.find_element(
        By.CSS_SELECTOR, 'div[data-edit-name="tech_email"] input'
    )
    email_input.clear()
    email_input.send_keys(new_ix_email)

    driver.find_element(By.CSS_SELECTOR, 'a[data-edit-action="submit"]').click()

    # check if changed
    WebDriverWait(driver, 10).until(
        EC.invisibility_of_element(
            (By.CSS_SELECTOR, 'div[data-edit-name="name"] input')
        )
    )
    assert (
        new_ix_name
        == driver.find_element(By.CSS_SELECTOR, 'div[data-edit-name="name"]').text
    )
    assert (
        new_ix_website
        == driver.find_element(By.CSS_SELECTOR, 'div[data-edit-name="website"] a').text
    )
    assert (
        new_ix_email
        == driver.find_element(
            By.CSS_SELECTOR, 'div[data-edit-name="tech_email"] a'
        ).text
    )


    # restore name
    driver.find_element(
        By.CSS_SELECTOR, '.button-bar a[data-edit-action="toggle-edit"]'
    ).click()

    name_input = driver.find_element(
        By.CSS_SELECTOR, 'div[data-edit-name="name"] input'
    )
    name_input.clear()
    name_input.send_keys(old_ix_name)

    driver.find_element(By.CSS_SELECTOR, 'a[data-edit-action="submit"]').click()


@pytest.mark.key("test-writes")
@pytest.mark.lvl("verified")
def test_delete_exchange(config, driver):
    driver.get(config["url"])
    ix_name = config["test_delete_exchange"]["name"]
    org_id = config["test_delete_exchange"]["org_id"]

    driver.get(config["url"] + f"/org/{org_id}")
    # check whether ix already exists
    try:
        driver.find_element(
            By.XPATH,
            f'//div[@id="api-listing-ix"]//div[@data-filter-value="{ix_name}"]',
        )
    # if doesn't exist create it
    except NoSuchElementException:
        ix_prefix = config["test_delete_exchange"]["prefix"]
        add_ix(driver, ix_name, ix_prefix)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    '//div[@id="api-listing-ix"]//*[normalize-space()="'
                    + ix_name
                    + '"]',
                )
            )
        )

    # delete ix
    driver.find_element(
        By.CSS_SELECTOR, '.button-bar a[data-edit-action="toggle-edit"]'
    ).click()

    driver.find_element(
        By.XPATH,
        '//div[@id="api-listing-ix"]//div[normalize-space()="'
        + ix_name
        + '"]/preceding-sibling::a[@data-edit-action="remove"]',
    ).click()

    WebDriverWait(driver, 10).until(EC.alert_is_present()).accept()

    driver.find_element(
        By.CSS_SELECTOR, '.button-bar a[data-edit-action="submit"]'
    ).click()

    # check if ix is removed from list
    try:
        WebDriverWait(driver, 5).until(
            EC.invisibility_of_element(
                (
                    By.XPATH,
                    f'//div[@id="api-listing-ix"]//*[normalize-space()="{ix_name}"]',
                )
            )
        )
    except TimeoutException as exc:
        assert False, f"Exchange doesn't seem to be deleted {exc}"
