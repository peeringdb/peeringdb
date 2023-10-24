import pytest
from playwright.sync_api import Page


@pytest.mark.links
def test_links(config, page: Page, account_credentials):
    """
    This function tests all the links in the page.
    """
    page.goto(config["url"], wait_until="load")  # wait for the 'load' event
    anchors = page.query_selector_all("a")
    links = []
    logout_link = None
    for anchor in anchors:
        link = page.evaluate("(el) => el.href", anchor)
        if link and config["url"] in link:
            if "logout" in link:
                logout_link = link
            else:
                links.append(link)
    # keep logout as the last
    if logout_link:
        links.append(logout_link)

    # remove duplicates
    links = list(dict.fromkeys(links))

    # remove /docs
    if config["url"] + "/docs" in links:
        links.remove(config["url"] + "/docs")

    for link in links:
        page.goto(link, wait_until="load")  # wait for the 'load' event
        try:
            assert page.is_visible("#header .logo")
        except Exception:
            assert page.title() == "PeeringDB API Documentation"
