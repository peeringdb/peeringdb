from helper import login
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By


def test_links(config, driver, account_credentials):
    driver.get(config["url"])
    anchors = driver.find_elements(By.TAG_NAME, "a")
    links = []
    logout_link = None
    for anchor in anchors:
        link = anchor.get_attribute("href")
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
        driver.get(link)
        try:
            assert driver.find_element(By.CSS_SELECTOR, "#header .logo")
        # API Documentation page doesn't have logo
        except NoSuchElementException:
            assert driver.title == "PeeringDB API Documentation"
    if logout_link:
        driver.get(config["url"])
        login(driver, account_credentials["username"], account_credentials["password"])
