#!/usr/bin/env python
# Copyright 2018 - 2020 Dr. Jan-Philip Gehrcke
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

import argparse
import os
import sys
import json
import logging
import base64
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import presence_of_element_located


log = logging.getLogger()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%y%m%d-%H:%M:%S",
)


def main():

    parser = argparse.ArgumentParser(description="")
    parser.add_argument(
        "htmlpath",
        metavar="HTML_PATH",
    )

    parser.add_argument(
        "pdfpath",
        metavar="PDF_PATH",
    )

    args = parser.parse_args()

    html_doc_path = args.htmlpath
    html_apath = os.path.abspath(html_doc_path)

    log.info("html_apath: %s", html_apath)

    if not os.path.exists(html_apath):
        sys.exit(f"does not exist: {html_apath}")

    pdf_bytes = gen_pdf_bytes(html_apath)

    log.info("write %s bytes to %s", len(pdf_bytes), args.pdfpath)
    with open(args.pdfpath, "wb") as f:
        f.write(pdf_bytes)

    log.info("done")


def gen_pdf_bytes(html_apath):

    wd_options = Options()
    wd_options.add_argument("--headless")
    wd_options.add_argument("--disable-gpu")
    wd_options.add_argument("--no-sandbox")
    wd_options.add_argument("--disable-dev-shm-usage")

    log.info("set up chromedriver with capabilities %s", wd_options.to_capabilities())

    with webdriver.Chrome(
        ChromeDriverManager().install(), options=wd_options
    ) as driver:
        log.info("webdriver set up")
        waiter = WebDriverWait(driver, 10)

        driver.get(f"file:///{html_apath}")

        # Wait for Vega to add <svg> elemtn(s) to DOM.
        first_svg = waiter.until(
            presence_of_element_located((By.CSS_SELECTOR, "div>svg"))
        )
        log.info("first <svg> element detected: %s", first_svg)

        # Be sure that SVG rendering completed. It's unclear if this is
        # actually needed. A matter of caution with practically no downside
        # right now.
        time.sleep(0.5)
        b64_text = send_print_request(driver)

        log.info("decode b64 doc (length: %s chars) into bytes", len(b64_text))
        return base64.b64decode(b64_text)


def send_print_request(driver):

    # Construct chrome dev tools print request.
    # https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-printToPDF
    # Also see https://bugs.chromium.org/p/chromium/issues/detail?id=603559 for
    # context.
    print_options = {
        "landscape": False,
        "scale": 1,
        "paperWidth": 8.3,  # inches
        "paperHeight": 11.7,  # inches
        "martinTop": 0,
        "martinBottom": 0,
        "martinLeft": 0,
        "martinRight": 0,
        "displayHeaderFooter": False,
        "printBackground": False,
        "preferCSSPageSize": True,
    }

    url = (
        driver.command_executor._url
        + f"/session/{driver.session_id}/chromium/send_command_and_get_result"
    )

    log.info("send Page.printToPDF webdriver request to %s", url)

    response = driver.command_executor._request(
        "POST", url, json.dumps({"cmd": "Page.printToPDF", "params": print_options})
    )

    if "value" in response:
        if "data" in response["value"]:
            log.info("got expected Page.printToPDF() response format")
            return response["value"]["data"]

    log.error("unexpected response: %s", response)
    raise Exception("unexpected webdriver response")


if __name__ == "__main__":
    main()
