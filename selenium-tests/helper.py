import time

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By


def login(driver, username, password, retry=True):
    driver.find_element(By.LINK_TEXT, "Login").click()
    driver.find_element(By.CSS_SELECTOR, "#id_auth-username").send_keys(username)
    driver.find_element(By.CSS_SELECTOR, "#id_auth-password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "form .btn-primary").click()
    if retry == True:
        try:
            driver.find_element(
                By.XPATH,
                '//div[normalize-space()="Please wait a bit before trying to login again."]',
            )
            time.sleep(30)
            login(driver, username, password, retry=False)
        except NoSuchElementException:
            pass
