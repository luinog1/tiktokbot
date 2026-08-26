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
import time
from datetime import datetime
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
    ElementNotInteractableException,
    StaleElementReferenceException,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Modo headless/Render
_HEADLESS_MODE = not sys.stdin.isatty() or os.environ.get("RENDER")

# Tesseract path (Render/Docker)
pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD", "/usr/bin/tesseract")

# Diretório para screenshots de debug
DEBUG_DIR = os.environ.get("DEBUG_DIR", "/tmp/tiktokbot-debug")
os.makedirs(DEBUG_DIR, exist_ok=True)


def log_debug(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


class Bot:

    def __init__(self):
        if not _HEADLESS_MODE:
            subprocess.run("clear", shell=True)

        self._print_banner()
        self.driver = self._init_driver()
        self.services = self._init_services()

    def start(self):
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            log_debug(f"=== Attempt {attempt}/{max_attempts} ===")
            try:
                self.driver.get("https://zefoy.com")
                self._dismiss_any_alert()
                self._solve_captcha()

                # Page refresh 1
                time.sleep(2)
                self.driver.refresh()
                self._dismiss_any_alert()

                # Page refresh 2
                time.sleep(2)
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
                return  # Success
            except Exception as e:
                log_debug(f"[!] Attempt {attempt} failed: {e}")
                if attempt < max_attempts:
                    log_debug("[~] Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    log_debug("[x] Max attempts reached. Exiting.")
                    raise

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

            for binary in ["/usr/bin/firefox-esr", "/usr/bin/firefox"]:
                if os.path.exists(binary):
                    options.binary_location = binary
                    break

            options.add_argument("-headless")

            # Sandbox desabilitada
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

            # Bloquear notificações
            options.set_preference("dom.webnotifications.enabled", False)
            options.set_preference("dom.push.enabled", False)
            options.set_preference("permissions.default.desktop-notification", 2)
            options.set_preference("permissions.default.desktop-notification2", 2)

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
        try:
            alert = self.driver.switch_to.alert
            log_debug(f"[!] Alert detectado: {alert.text}")
            alert.dismiss()
            log_debug("[+] Alert dismissed")
            time.sleep(0.5)
        except NoAlertPresentException:
            pass
        except Exception as e:
            log_debug(f"[!] Erro ao dismiss alert: {e}")

    # ===================================================================
    # CAPTCHA SOLVER
    # ===================================================================
    def _solve_captcha(self):
        log_debug("[~] Scanning for CAPTCHA...")

        # Wait for input with timeout
        try:
            self._wait_for_element(By.TAG_NAME, "input", timeout=30)
        except TimeoutException:
            log_debug("[!] Input not found within 30s, saving page source for debug")
            self._save_debug_html("no_input")
            raise

        self._dismiss_any_alert()

        # Try OCR-based solving
        captcha_text = self._solve_captcha_ocr()

        if captcha_text:
            log_debug(f"[+] CAPTCHA solved via OCR: {captcha_text}")
            try:
                self._dismiss_any_alert()
                captcha_input = self.driver.find_element(By.TAG_NAME, "input")
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
                time.sleep(1)

                # Try to submit
                submitted = False
                try:
                    submit_btn = self.driver.find_element(
                        By.CSS_SELECTOR, "button[type='submit'], button.btn-primary, form button"
                    )
                    if submit_btn.is_displayed() and submit_btn.is_enabled():
                        submit_btn.click()
                        submitted = True
                        log_debug("[+] Submit button clicked")
                        time.sleep(3)
                except NoSuchElementException:
                    log_debug("[~] No submit button found, pressing Enter")
                    captcha_input.submit()
                    submitted = True
                    time.sleep(3)
                except ElementNotInteractableException:
                    log_debug("[!] Submit button not interactable")

                # Check if captcha was accepted
                time.sleep(2)
                if self._is_captcha_error_visible():
                    log_debug("[!] Captcha rejected (error message visible)")
                    self._save_debug_html("captcha_rejected")
                    raise Exception("Captcha rejected")

            except UnexpectedAlertPresentException:
                self._dismiss_any_alert()
            except Exception as e:
                log_debug(f"[!] Error filling CAPTCHA: {e}")
        else:
            log_debug("[!] OCR failed, waiting for page to clear...")

        # Fallback: wait for page to clear (Youtube link appears)
        try:
            self._wait_for_element(By.LINK_TEXT, "Youtube", timeout=60)
            log_debug("[+] Captcha completed successfully")
        except TimeoutException:
            log_debug("[!] Timeout waiting for Youtube link — captcha likely failed")
            self._save_debug_html("captcha_timeout")
            raise

        print()

    def _is_captcha_error_visible(self):
        """Check if there's an error message indicating wrong captcha."""
        error_selectors = [
            "[class*='error' i]",
            "[class*='wrong' i]",
            "[class*='invalid' i]",
            "[id*='error' i]",
        ]
        for sel in error_selectors:
            try:
                elems = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in elems:
                    if el.is_displayed() and el.text.strip():
                        log_debug(f"[!] Error element found: {el.text.strip()}")
                        return True
            except Exception:
                pass
        return False

    def _solve_captcha_ocr(self) -> str:
        try:
            self._dismiss_any_alert()
            captcha_img = None
            selectors = [
                "img[src*='captcha']",
                "img.captcha",
                "#captcha",
                "img[alt*='captcha' i]",
                "form img",
                "div.form-group img",
                "div img",
            ]

            for sel in selectors:
                try:
                    elems = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for elem in elems:
                        if elem.is_displayed():
                            # Check if it looks like a captcha image
                            size = elem.size
                            if size.get("width", 0) > 50 and size.get("height", 0) > 20:
                                captcha_img = elem
                                log_debug(f"[~] Captcha image found via: {sel}")
                                break
                    if captcha_img:
                        break
                except Exception:
                    continue

            if captcha_img is None:
                log_debug("[~] Captcha image not found by selector, trying full page OCR...")
                return self._solve_captcha_from_screenshot()

            png = captcha_img.screenshot_as_png
            # Save for debug
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_path = os.path.join(DEBUG_DIR, f"captcha_{ts}.png")
            with open(debug_path, "wb") as f:
                f.write(png)
            log_debug(f"[~] Captcha screenshot saved: {debug_path}")

            return self._ocr_image(png)

        except Exception as e:
            log_debug(f"[!] CAPTCHA OCR error: {e}")
            return ""

    def _solve_captcha_from_screenshot(self) -> str:
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
            log_debug(f"[!] Screenshot OCR error: {e}")
            return ""

    def _ocr_image(self, png_bytes: bytes) -> str:
        try:
            nparr = np.frombuffer(png_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                return ""

            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Resize 3x for better OCR
            h, w = gray.shape[:2]
            gray = cv2.resize(gray, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)

            # Denoise
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

            # Gaussian blur
            blurred = cv2.GaussianBlur(denoised, (5, 5), 0)

            # Adaptive threshold
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )

            # Morphological operations to clean noise
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            morph = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            morph = cv2.morphologyEx(morph, cv2.MORPH_OPEN, kernel)

            # Invert if needed
            white_pixels = cv2.countNonZero(morph)
            total_pixels = morph.shape[0] * morph.shape[1]
            if white_pixels > total_pixels * 0.7:
                morph = cv2.bitwise_not(morph)

            # Save preprocessed image for debug
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_path = os.path.join(DEBUG_DIR, f"captcha_ocr_{ts}.png")
            cv2.imwrite(debug_path, morph)
            log_debug(f"[~] Preprocessed captcha saved: {debug_path}")

            # Run Tesseract with multiple PSM modes
            configs = [
                r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
                r'--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
                r'--oem 3 --psm 13 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
            ]

            results = []
            for config in configs:
                text = pytesseract.image_to_string(morph, config=config)
                cleaned = re.sub(r'[^A-Za-z0-9]', '', text).strip()
                if cleaned:
                    results.append(cleaned)

            # Pick the most common result
            if results:
                from collections import Counter
                most_common = Counter(results).most_common(1)[0][0]
                log_debug(f"[~] OCR results: {results} | best: {most_common}")
                if 3 <= len(most_common) <= 10:
                    return most_common

            return ""

        except Exception as e:
            log_debug(f"[!] OCR processing error: {e}")
            return ""

    def _save_debug_html(self, suffix=""):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(DEBUG_DIR, f"page_{suffix}_{ts}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            log_debug(f"[~] Page source saved: {path}")
        except Exception as e:
            log_debug(f"[!] Could not save debug HTML: {e}")

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
        self._wait_for_element(
            By.CLASS_NAME, self.services[service]["selector"], timeout=30
        ).click()

        container = self._wait_for_element(
            By.CSS_SELECTOR, "div.col-sm-5.col-xs-12.p-1.container:not(.nonec)", timeout=30
        )

        input_element = container.find_element(By.TAG_NAME, "input")
        input_element.clear()
        input_element.send_keys(video_url)

        while True:
            container.find_element(By.CSS_SELECTOR, "button.btn.btn-primary").click()
            time.sleep(3)

            try:
                container.find_element(By.CSS_SELECTOR, "button.btn.btn-dark").click()
                print("[~] {} sent successfully".format(self.services[service]["title"]))
            except NoSuchElementException:
                pass
            except UnexpectedAlertPresentException:
                self._dismiss_any_alert()

            time.sleep(3)

            remaining_time = self._compute_remaining_time(container)

            if remaining_time is not None:
                minutes = remaining_time // 60
                seconds = remaining_time - minutes * 60
                print("[~] Sleeping for {} minutes {} seconds".format(minutes, seconds))
                time.sleep(remaining_time)

            print()

    def _compute_remaining_time(self, container):
        try:
            element = container.find_element(By.CSS_SELECTOR, "span.br")
            text = element.text

            if "Please wait" in text:
                [minutes, seconds] = re.findall(r"\d+", text)
                remaining_time = int(minutes) * 60 + int(seconds) + 5
                return remaining_time
            else:
                print("NO TIME")
                return None
        except NoSuchElementException:
            print("NO ELEMENT")
            return None

    def _wait_for_element(self, by, value, timeout=60):
        """Wait for element with timeout (seconds)."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                self._dismiss_any_alert()
                element = self.driver.find_element(by, value)
                if element.is_displayed():
                    return element
            except UnexpectedAlertPresentException:
                self._dismiss_any_alert()
                time.sleep(0.5)
            except (NoSuchElementException, StaleElementReferenceException):
                time.sleep(0.5)
        raise TimeoutException(f"Element ({by}={value}) not found within {timeout}s")


if __name__ == "__main__":
    bot = Bot()
    try:
        bot.start()
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
    except Exception as e:
        log_debug(f"[x] Bot crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
