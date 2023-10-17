from playwright.sync_api import Page


def login(page: Page, username: str, password: str, retry=True):
    """
    This function logs into the website using the provided username and password.
    """
    page.click("text=Login")
    page.fill("#id_auth-username", username)
    page.fill("#id_auth-password", password)
    page.click("form .btn-primary")

    if retry:
        try:
            page.wait_for_selector(
                'text="Please wait a bit before trying to login again."', timeout=5000
            )
            page.wait_for_timeout(30000)
            login(page, username, password, retry=False)
        except Exception:
            pass
