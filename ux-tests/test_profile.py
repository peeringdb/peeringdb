import pytest
from helpers import login
from playwright.sync_api import Page

TIMEOUT = 10000


def change_password(page: Page, old_password, new_password):
    """
    This function changes the user's password.
    """
    page.fill(
        '#form-change-password input[data-edit-name="password_c"]',
        old_password,
        timeout=TIMEOUT,
    )
    page.fill(
        '#form-change-password input[data-edit-name="password"]',
        new_password,
        timeout=TIMEOUT,
    )
    page.fill(
        '#form-change-password input[data-edit-name="password_v"]',
        new_password,
        timeout=TIMEOUT,
    )
    page.click(
        '#form-change-password a.btn[data-edit-action="submit"]', timeout=TIMEOUT
    )


@pytest.mark.profile
def test_profile_add_api_key(config, page: Page, account):
    """
    This function tests the functionality of adding an API key.
    """
    page.goto(config["url"] + "/profile")
    num_of_keys = len(
        page.query_selector_all('.api-keys div[data-edit-component="list"] div.row')
    )

    # add api key
    page.fill(
        '.api-keys div[data-edit-name="name"] input',
        config["test_add_api_key"]["description"],
        timeout=TIMEOUT,
    )
    page.click('.api-keys a[data-edit-action="add"]', timeout=TIMEOUT)

    # check if api key added to list
    assert page.wait_for_selector(
        ".api-keys #api-key-popin-frame div.alert-success", timeout=TIMEOUT
    )
    assert num_of_keys + 1 == len(
        page.query_selector_all('.api-keys div[data-edit-component="list"] div.row')
    )


@pytest.mark.profile
def test_profile_delete_api_key(config, page: Page, account):
    """
    This function tests the functionality of deleting an API key.
    """
    # deletes an existing api key
    page.goto(config["url"] + "/profile")
    num_of_keys = len(
        page.query_selector_all('.api-keys div[data-edit-component="list"] div.row')
    )
    page.on("dialog", lambda dialog: dialog.accept())

    # remove key
    description = config["test_delete_api_key"]["description"]
    key_revoke_btn_selector = f'.api-keys div[data-edit-component="list"] div.row:has(span[data-edit-name="name"]:has-text("{description}")) a[data-edit-action="revoke"]'

    page.wait_for_selector(key_revoke_btn_selector, timeout=TIMEOUT)
    key_revoke_btn = page.query_selector(key_revoke_btn_selector)
    key_revoke_btn.click()

    page.goto(config["url"] + "/profile")

    # check if key removed from list
    assert num_of_keys - 1 == len(
        page.query_selector_all('.api-keys div[data-edit-component="list"] div.row')
    )


@pytest.mark.profile
def test_profile_change_password(config, page: Page, account_credentials, account):
    """
    This function tests the functionality of changing the user's password.
    """
    page.goto(config["url"] + "/profile", wait_until="load")

    old_password = account_credentials["password"]
    new_password = config["test_change_password"]["password"]
    change_password(page, old_password, new_password)

    # check for success message
    assert page.wait_for_selector(
        "#form-change-password #password-change-success", timeout=TIMEOUT
    )

    # re login
    page.goto(config["url"], wait_until="load")
    login(page, account_credentials["username"], new_password)

    # change password back
    page.goto(config["url"] + "/profile", wait_until="load")
    change_password(page, new_password, old_password)

    # check for success message
    assert page.wait_for_selector(
        "#form-change-password #password-change-success", timeout=TIMEOUT
    )

    # re login
    page.goto(config["url"], wait_until="load")
    login(page, account_credentials["username"], new_password)
