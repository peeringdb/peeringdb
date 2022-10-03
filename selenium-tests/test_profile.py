import time

import pytest
import selenium.webdriver.support.expected_conditions as EC
from helper import login
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait


@pytest.mark.key("test-writes")
@pytest.mark.lvl("unverified")
def test_add_api_key(config, driver):
    driver.get(config["url"] + "/profile")
    try:
        num_of_keys = len(
            driver.find_elements(
                By.CSS_SELECTOR, '.api-keys div[data-edit-component="list"] div.row'
            )
        )
    except NoSuchElementException:
        num_of_keys = 0

    time.sleep(5)
    # add api key
    driver.find_element(
        By.CSS_SELECTOR, '.api-keys div[data-edit-name="name"] input'
    ).send_keys(config["test_add_api_key"]["description"])
    driver.find_element(By.CSS_SELECTOR, '.api-keys a[data-edit-action="add"]').click()

    # check if api key added to list
    assert WebDriverWait(driver, 5).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".api-keys #api-key-popin-frame div.alert-success")
        )
    )
    assert num_of_keys + 1 == len(
        driver.find_elements(
            By.CSS_SELECTOR, '.api-keys div[data-edit-component="list"] div.row'
        )
    )


@pytest.mark.key("test-writes")
@pytest.mark.lvl("unverified")
def test_delete_api_key(config, driver):
    # deletes an existing api key
    driver.get(config["url"] + "/profile")
    try:
        num_of_keys = len(
            driver.find_elements(
                By.CSS_SELECTOR, '.api-keys div[data-edit-component="list"] div.row'
            )
        )
    except NoSuchElementException:
        num_of_keys = 0

    # remove key
    description = config["test_delete_api_key"]["description"]
    key_revoke_btn = driver.find_element(By.CSS_SELECTOR, ".api-keys").find_element(
        By.XPATH,
        '//div[@data-edit-component="list"]'
        + f'//span[@data-edit-name="name"][normalize-space()="{description}"]'
        + '/../following-sibling::div/a[@data-edit-action="revoke"]',
    )
    key_revoke_btn.click()
    WebDriverWait(driver, 10).until(EC.alert_is_present()).accept()

    # check if key removed from list
    assert WebDriverWait(driver, 5).until(EC.invisibility_of_element(key_revoke_btn))
    assert num_of_keys - 1 == len(
        driver.find_elements(
            By.CSS_SELECTOR, '.api-keys div[data-edit-component="list"] div.row'
        )
    )


@pytest.mark.key("test-writes")
@pytest.mark.lvl("unverified")
def test_change_password(config, driver, account_credentials):
    driver.get(config["url"] + "/profile")

    old_password = account_credentials["password"]
    new_password = config["test_change_password"]["password"]
    change_password(driver, old_password, new_password)

    # check for success message
    assert WebDriverWait(driver, 5).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "#form-change-password #password-change-success")
        )
    )

    # change password back
    driver.get(config["url"])
    login(driver, account_credentials["username"], new_password)
    driver.get(config["url"] + "/profile")
    change_password(driver, new_password, old_password)

    # check for success message
    WebDriverWait(driver, 5).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "#form-change-password #password-change-success")
        )
    )


def change_password(driver, old_password, new_password):
    driver.find_element(
        By.CSS_SELECTOR, '#form-change-password input[data-edit-name="password_c"]'
    ).send_keys(old_password)
    driver.find_element(
        By.CSS_SELECTOR, '#form-change-password input[data-edit-name="password"]'
    ).send_keys(new_password)
    driver.find_element(
        By.CSS_SELECTOR, '#form-change-password input[data-edit-name="password_v"]'
    ).send_keys(new_password)
    driver.find_element(
        By.CSS_SELECTOR, '#form-change-password a.btn[data-edit-action="submit"]'
    ).click()
