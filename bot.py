"""
TikTok Bot — Zefoy CAPTCHA solver via Tesseract OCR (100% free, open source).
Integrates OCR-based CAPTCHA resolution using Tesseract + OpenCV.
"""

import re
import os
import sys
import subprocess
import base64
import io
from time import sleep
from PIL import Image
import cv2
import numpy as np
import pytesseract

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    UnexpectedAlertPresentException,
    NoAlertPresentException,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Modo headless/Render
_HEADLESS_MODE = not sys.stdin.isatty() or os.environ.get("RENDER")

# Tesseract path (Render/Docker)
pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD", "/usr/bin/tesseract")


class Bot:

    def __init__(self):
        if not _HEADLESS_MODE:
            subprocess.run("clear", shell=True)

        self._print_banner()
        self.driver = self._init_driver()
        self.services = self._init_services()

    def start(self):
        self.driver.get("https://zefoy.com")
        self._dismiss_any_alert()
        self._solve_captcha()

        # Page refresh 1
        sleep(2)
        self.driver.refresh()
        self._dismiss_any_alert()

        # Page refresh 2
        sleep(2)
        self.driver.refresh()
        self._dismiss_any_alert()

        self._check_services_status()
        try:
            self.driver.minimize_window()
        except Exception:
            pass
        self._print_services_list()
        service = self._choose_service()
        video_url = self._choose_video_url()
        self._start_service(service, video_url)

    def _print_banner(self):
        print("+--------------------------------------------------------+")
        print("|                                                        |")
        print("|   Made by : Simon Farah                                |")
        print("|   Github  : https://github.com/simonfarah/tiktok-bot   |")
        print("|   CAPTCHA : Tesseract OCR (100% free)                  |")
        print("|                                                        |")
        print("+--------------------------------------------------------+")
        print()

    def _init_driver(self):
        try:
            print("[~] Loading driver, please wait...")

            options = webdriver.FirefoxOptions()

            # Detecta o binário disponível
            for binary in ["/usr/bin/firefox-esr", "/usr/bin/firefox"]:
                if os.path.exists(binary):
                    options.binary_location = binary
                    break

            # Headless nativo do Firefox
            options.add_argument("-headless")

            # Sandbox desabilitada (containers sem CAP_SYS_ADMIN)
            options.set_preference("security.sandbox.content.level", 0)
            options.set_preference("security.sandbox.gpu.level", 0)
            options.set_preference("security.sandbox.media.level", 0)
            options.set_preference("security.sandbox.content.tempdir.level", 0)
            options.set_preference("browser.tabs.crashReporting.sendReport", False)
            options.set_preference("toolkit.startup.max_resumed_crashes", -1)
            options.set_preference("datareporting.healthreport.uploadEnabled", False)
            options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
            options.set_preference("services.settings.server", "")

            # Anti-detection
            options.set_preference("general.useragent.override",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0")
            options.set_preference("dom.webdriver.enabled", False)
            options.set_preference("useAutomationExtension", False)

            # BLOQUEAR NOTIFICAÇÕES (evita o alert que crasha o bot)
            options.set_preference("dom.webnotifications.enabled", False)
            options.set_preference("dom.push.enabled", False)
            options.set_preference("permissions.default.desktop-notification", 2)
            options.set_preference("permissions.default.desktop-notification2", 2)
            options.set_preference("browser.search.region", "US")
            options.set_preference("browser.search.geoip.url", "")

            # Desabilitar prompts de permissão
            options.set_preference("geo.enabled", False)
            options.set_preference("geo.provider.use_corelocation", False)
            options.set_preference("geo.prompt.testing", False)
            options.set_preference("geo.prompt.testing.allow", False)

            service = webdriver.FirefoxService(
                executable_path="/usr/local/bin/geckodriver",
                log_output=sys.stdout,
            )

            driver = webdriver.Firefox(options=options, service=service)
            print("[+] Driver loaded successfully")
        except Exception as e:
            print("[x] Error loading driver: {}".format(e))
            exit(1)

        print()
        return driver

    def _init_services(self):
        return {
            "followers": {
                "title": "Followers",
                "selector": "t-followers-button",
                "status": None,
            },
            "hearts": {
                "title": "Hearts",
                "selector": "t-hearts-button",
                "status": None,
            },
            "comments_hearts": {
                "title": "Comments Hearts",
                "selector": "t-chearts-button",
                "status": None,
            },
            "views": {
                "title": "Views",
                "selector": "t-views-button",
                "status": None,
            },
            "shares": {
                "title": "Shares",
                "selector": "t-shares-button",
                "status": None,
            },
            "favorites": {
                "title": "Favorites",
                "selector": "t-favorites-button",
                "status": None,
            },
            "live_stream": {
                "title": "Live Stream [VS+LIKES]",
                "selector": "t-livesteam-button",
                "status": None,
            },
        }

    # ===================================================================
    # ALERT HANDLER
    # ===================================================================
    def _dismiss_any_alert(self):
        """Tenta dismiss qualquer alert/popup aberto."""
        try:
            alert = self.driver.switch_to.alert
            print("[!] Alert detectado: {}".format(alert.text))
            alert.dismiss()
            print("[+] Alert dismissed")
            sleep(0.5)
        except NoAlertPresentException:
            pass
        except Exception as e:
            print("[!] Erro ao dismiss alert: {}".format(e))

    # ===================================================================
    # CAPTCHA SOLVER — Tesseract OCR (100% free)
    # ===================================================================
    def _solve_captcha(self):
        print("[~] Scanning for CAPTCHA...")

        # Wait for the captcha input to appear (com tratamento de alert)
        self._wait_for_element(By.TAG_NAME, "input")
        self._dismiss_any_alert()

        # Try OCR-based solving first
        captcha_text = self._solve_captcha_ocr()

        if captcha_text:
            print("[+] CAPTCHA solved via OCR: {}".format(captcha_text))
            try:
                self._dismiss_any_alert()
                captcha_input = self.driver.find_element(By.TAG_NAME, "input")
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
                sleep(0.5)

                # Try to submit
                try:
                    submit_btn = self.driver.find_element(
                        By.CSS_SELECTOR, "button[type='submit'], button.btn-primary"
                    )
                    submit_btn.click()
                    sleep(2)
                except NoSuchElementException:
                    sleep(2)
            except UnexpectedAlertPresentException:
                self._dismiss_any_alert()
            except Exception as e:
                print("[!] Error filling CAPTCHA: {}".format(e))
        else:
            print("[!] OCR failed, waiting for page to clear...")

        # Fallback: wait for the page to indicate captcha is cleared
        self._wait_for_element(By.LINK_TEXT, "Youtube")
        print("[+] Captcha completed successfully")
        print()

    def _solve_captcha_ocr(self) -> str:
        """
        Capture the CAPTCHA image from zefoy.com and solve it using
        Tesseract OCR with OpenCV preprocessing.
        """
        try:
            self._dismiss_any_alert()
            captcha_img = None
            selectors = [
                "img[src*='captcha']",
                "img.captcha",
                "#captcha",
                "img[alt*='captcha' i]",
                "form img",
                "div img",
            ]

            for sel in selectors:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if elem.is_displayed():
                        captcha_img = elem
                        break
                except NoSuchElementException:
                    continue

            if captcha_img is None:
                print("[~] Captcha image not found by selector, trying full page OCR...")
                return self._solve_captcha_from_screenshot()

            png = captcha_img.screenshot_as_png
            return self._ocr_image(png)

        except Exception as e:
            print("[!] CAPTCHA OCR error: {}".format(e))
            return ""

    def _solve_captcha_from_screenshot(self) -> str:
        """Fallback: take full page screenshot and OCR the top portion."""
        try:
            self._dismiss_any_alert()
            png = self.driver.get_screenshot_as_png()
            image = Image.open(io.BytesIO(png))
            w, h = image.size
            cropped = image.crop((0, 0, w, int(h * 0.4)))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return self._ocr_image(buf.getvalue())
        except Exception as e:
            print("[!] Screenshot OCR error: {}".format(e))
            return ""

    def _ocr_image(self, png_bytes: bytes) -> str:
        """
        Run Tesseract OCR on PNG bytes with OpenCV preprocessing.
        """
        try:
            nparr = np.frombuffer(png_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                return ""

            # Preprocessing pipeline
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            gray = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            blurred = cv2.GaussianBlur(gray, (5, 5), sigmaX=1, sigmaY=1)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            morph = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)
            _, thresh = cv2.threshold(morph, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            white_pixels = cv2.countNonZero(thresh)
            total_pixels = thresh.shape[0] * thresh.shape[1]
            if white_pixels > total_pixels * 0.7:
                thresh = cv2.bitwise_not(thresh)

            custom_config = (
                r'--oem 3 --psm 7 '
                r'-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
            )
            text = pytesseract.image_to_string(thresh, config=custom_config)

            cleaned = re.sub(r'[^A-Za-z0-9]', '', text).strip()
            print("[~] OCR raw: '{}' | cleaned: '{}'".format(text.strip(), cleaned))

            if 3 <= len(cleaned) <= 10:
                return cleaned
            return ""

        except Exception as e:
            print("[!] OCR processing error: {}".format(e))
            return ""

    # ===================================================================
    # ORIGINAL BOT LOGIC
    # ===================================================================
    def _check_services_status(self):
        for service in self.services:
            selector = self.services[service]["selector"]

            try:
                self._dismiss_any_alert()
                element = self.driver.find_element(By.CLASS_NAME, selector)

                if element.is_enabled():
                    self.services[service]["status"] = "[WORKING]"
                else:
                    self.services[service]["status"] = "[OFFLINE]"
            except NoSuchElementException:
                self.services[service]["status"] = "[OFFLINE]"
            except UnexpectedAlertPresentException:
                self._dismiss_any_alert()
                self.services[service]["status"] = "[OFFLINE]"

    def _print_services_list(self):
        for index, service in enumerate(self.services):
            title = self.services[service]["title"]
            status = self.services[service]["status"]

            print("[{}] {}".format(str(index + 1), title).ljust(30), status)

        print()

    def _choose_service(self):
        if _HEADLESS_MODE:
            env_choice = os.environ.get("TIKTOK_SERVICE", "4")
            try:
                choice = int(env_choice)
            except ValueError:
                print("[!] TIKTOK_SERVICE inválido, usando Views (4)")
                choice = 4
            key = list(self.services.keys())[choice - 1]
            print("[+] Serviço selecionado via env: {}".format(self.services[key]["title"]))
            print()
            return key

        while True:
            try:
                choice = int(input("[~] Choose an option : "))
            except ValueError:
                print("[!] Invalid input format. Please try again...")
                print()
                continue

            if choice in range(1, 8):
                key = list(self.services.keys())[choice - 1]

                if self.services[key]["status"] == "[OFFLINE]":
                    print("[!] Service is offline. Please choose another...")
                    print()
                    continue

                print("[+] You have chosen {}".format(self.services[key]["title"]))
                print()
                break
            else:
                print("[!] No service found with this number")
                print()

        return key

    def _choose_video_url(self):
        if _HEADLESS_MODE:
            video_url = os.environ.get("TIKTOK_VIDEO_URL", "")
            if not video_url:
                print("[!] ERRO: defina a env var TIKTOK_VIDEO_URL com a URL do vídeo")
                sys.exit(1)
            print("[+] URL do vídeo via env: {}".format(video_url))
            print()
            return video_url

        video_url = input("[~] Video URL : ")
        print()
        return video_url

    def _start_service(self, service, video_url):
        # Click on the corresponding service button
        self._wait_for_element(
            By.CLASS_NAME, self.services[service]["selector"]
        ).click()

        # Get the container of the selected service
        container = self._wait_for_element(
            By.CSS_SELECTOR, "div.col-sm-5.col-xs-12.p-1.container:not(.nonec)"
        )

        # Insert the video url in the input field
        input_element = container.find_element(By.TAG_NAME, "input")
        input_element.clear()
        input_element.send_keys(video_url)

        while True:
            # Click the search button
            container.find_element(By.CSS_SELECTOR, "button.btn.btn-primary").click()

            sleep(3)

            # Click the submit button if it's present
            try:
                container.find_element(By.CSS_SELECTOR, "button.btn.btn-dark").click()
                print(
                    "[~] {} sent successfully".format(self.services[service]["title"])
                )
            except NoSuchElementException:
                pass
            except UnexpectedAlertPresentException:
                self._dismiss_any_alert()

            sleep(3)

            remaining_time = self._compute_remaining_time(container)

            if remaining_time is not None:
                minutes = remaining_time // 60
                seconds = remaining_time - minutes * 60
                print("[~] Sleeping for {} minutes {} seconds".format(minutes, seconds))
                sleep(remaining_time)

            print()

    def _compute_remaining_time(self, container):
        try:
            element = container.find_element(By.CSS_SELECTOR, "span.br")
            text = element.text

            if "Please wait" in text:
                [minutes, seconds] = re.findall(r"\d+", text)
                remaining_time = (
                    int(minutes) * 60 + int(seconds) + 5
                )

                return remaining_time
            else:
                print("NO TIME")
                return None
        except NoSuchElementException:
            print("NO ELEMENT")
            return None

    def _wait_for_element(self, by, value):
        while True:
            try:
                self._dismiss_any_alert()
                element = self.driver.find_element(by, value)
                return element
            except UnexpectedAlertPresentException:
                self._dismiss_any_alert()
                sleep(1)
            except NoSuchElementException:
                sleep(1)


if __name__ == "__main__":
    bot = Bot()
    bot.start()
