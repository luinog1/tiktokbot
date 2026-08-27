"""
TikTok Bot - Ultra-lightweight edition for 512MB containers.
Chromium (lighter than Firefox) + PIL + Tesseract OCR.
"""

import re
import os
import sys
import subprocess
import io
import gc
import time
from datetime import datetime
from PIL import Image, ImageFilter, ImageOps, ImageEnhance

import pytesseract

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    UnexpectedAlertPresentException,
    NoAlertPresentException,
    ElementNotInteractableException,
    StaleElementReferenceException,
)

_HEADLESS_MODE = not sys.stdin.isatty() or os.environ.get("RENDER")
pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD", "/usr/bin/tesseract")
DEBUG_DIR = os.environ.get("DEBUG_DIR", "/tmp/tiktokbot-debug")
os.makedirs(DEBUG_DIR, exist_ok=True)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


class Bot:

    def __init__(self):
        if not _HEADLESS_MODE:
            subprocess.run("clear", shell=True)
        self._print_banner()
        self.driver = self._init_driver()
        self.services = self._init_services()

    def _print_banner(self):
        print("+--------------------------------------------------------+")
        print("|   TikTok Bot - Ultra-Lightweight (Chromium)            |")
        print("|   512MB RAM optimized | PIL + Tesseract OCR            |")
        print("+--------------------------------------------------------+")
        print()

    def _init_driver(self):
        log("[~] Loading Chromium driver (memory-optimized)...")
        options = ChromeOptions()

        # Find chromium binary
        for binary in ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome-stable"]:
            if os.path.exists(binary):
                options.binary_location = binary
                break

        # Essential headless + memory flags
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")  # CRITICAL for containers
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-component-update")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-features=TranslateUI")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-ipc-flooding-protection")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--force-color-profile=srgb")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-first-run")
        options.add_argument("--safebrowsing-disable-auto-update")
        options.add_argument("--password-store=basic")
        options.add_argument("--use-mock-keychain")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument("--disable-site-isolation-trials")
        options.add_argument("--memory-model=low")
        options.add_argument("--max_old_space_size=128")
        options.add_argument("--js-flags=--max-old-space-size=128")
        options.add_argument("--single-process")  # Experimental: saves RAM, may be unstable

        # Window size
        options.add_argument("--window-size=1280,720")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

        # Disable images to save memory
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
            "disk-cache-size": 0,
        }
        options.add_experimental_option("prefs", prefs)

        service = ChromeService(executable_path="/usr/bin/chromedriver")
        driver = webdriver.Chrome(options=options, service=service)
        log("[+] Chromium driver loaded")
        return driver

    def _init_services(self):
        return {
            "followers":       {"title": "Followers",         "selector": "t-followers-button", "status": None},
            "hearts":          {"title": "Hearts",            "selector": "t-hearts-button",    "status": None},
            "comments_hearts": {"title": "Comments Hearts",   "selector": "t-chearts-button", "status": None},
            "views":           {"title": "Views",             "selector": "t-views-button",     "status": None},
            "shares":          {"title": "Shares",            "selector": "t-shares-button",    "status": None},
            "favorites":       {"title": "Favorites",         "selector": "t-favorites-button", "status": None},
            "live_stream":     {"title": "Live Stream [VS+LIKES]", "selector": "t-livesteam-button", "status": None},
        }

    def _dismiss_alert(self):
        try:
            alert = self.driver.switch_to.alert
            alert.dismiss()
            time.sleep(0.3)
        except Exception:
            pass

    def start(self):
        for page_attempt in range(1, 4):
            log(f"=== Page attempt {page_attempt}/3 ===")
            try:
                self.driver.get("https://zefoy.com")
                self._dismiss_alert()
                self._solve_captcha()

                time.sleep(2)
                self.driver.refresh()
                self._dismiss_alert()

                time.sleep(2)
                self.driver.refresh()
                self._dismiss_alert()

                self._check_services_status()
                self._print_services_list()
                service = self._choose_service()
                video_url = self._choose_video_url()
                self._start_service(service, video_url)
                return
            except Exception as e:
                log(f"[!] Page attempt {page_attempt} failed: {str(e)[:120]}")
                if page_attempt < 3:
                    log("[~] Retrying in 5s...")
                    time.sleep(5)
                else:
                    log("[x] All page attempts exhausted")
                    raise
            finally:
                gc.collect()

    def _solve_captcha(self):
        log("[~] Scanning for CAPTCHA...")

        try:
            self._wait_for_element(By.TAG_NAME, "input", timeout=30)
        except TimeoutException:
            log("[!] No input found in 30s")
            raise

        self._dismiss_alert()

        for solve_attempt in range(1, 6):
            log(f"[~] Captcha solve attempt {solve_attempt}/5")
            self._dismiss_alert()

            if self._is_captcha_cleared():
                log("[+] Captcha already cleared")
                print()
                return

            png = self._get_captcha_image()
            if not png:
                log("[!] Could not capture captcha image")
                time.sleep(2)
                continue

            text = self._ocr_attempt(png)

            if text:
                log(f'[+] OCR result: "{text}"')
                self._fill_and_submit(text)

                time.sleep(3)
                if self._is_captcha_cleared():
                    log("[+] Captcha cleared after submit")
                    print()
                    return
                else:
                    log("[!] Captcha still present - likely wrong answer")
                    try:
                        inp = self.driver.find_element(By.TAG_NAME, "input")
                        inp.clear()
                    except Exception:
                        pass
            else:
                log("[!] No OCR result, waiting before retry...")
                time.sleep(2)

        log("[!] All captcha solve attempts failed on this page")
        raise Exception("Could not solve captcha after 5 attempts")

    def _is_captcha_cleared(self):
        try:
            links = self.driver.find_elements(By.LINK_TEXT, "Youtube")
            for link in links:
                if link.is_displayed():
                    return True
        except Exception:
            pass
        try:
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            visible_inputs = [i for i in inputs if i.is_displayed()]
            if not visible_inputs:
                return True
        except Exception:
            pass
        return False

    def _get_captcha_image(self):
        self._dismiss_alert()
        for sel in ["img[src*='captcha']", "img.captcha", "#captcha",
                    "img[alt*='captcha' i]", "form img", "div.form-group img"]:
            try:
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed():
                        sz = el.size
                        if sz.get("width", 0) > 50 and sz.get("height", 0) > 20:
                            return el.screenshot_as_png
            except Exception:
                continue
        try:
            png = self.driver.get_screenshot_as_png()
            img = Image.open(io.BytesIO(png))
            w, h = img.size
            cropped = img.crop((0, 0, w, int(h * 0.4)))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None

    def _fill_and_submit(self, text):
        try:
            self._dismiss_alert()
            inp = self.driver.find_element(By.TAG_NAME, "input")
            inp.clear()
            inp.send_keys(text)
            time.sleep(0.5)
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR,
                    "button[type='submit'], button.btn-primary, form button")
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
            except NoSuchElementException:
                inp.submit()
        except UnexpectedAlertPresentException:
            self._dismiss_alert()

    def _ocr_attempt(self, png_bytes):
        """Single lightweight OCR attempt with PIL preprocessing."""
        try:
            img = Image.open(io.BytesIO(png_bytes))
            # Save raw for debug
            self._save_pil(img, "captcha_raw")

            # Preprocess
            img = ImageOps.grayscale(img)
            w, h = img.size
            img = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.5)
            img = img.filter(ImageFilter.SHARPEN)
            # Binary threshold
            img = img.point(lambda x: 0 if x < 120 else 255, "1")
            img = img.convert("L")

            self._save_pil(img, "captcha_proc")

            config = r"--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
            txt = pytesseract.image_to_string(img, config=config)
            clean = re.sub(r"[^A-Za-z0-9]", "", txt).strip()
            log(f"[~] OCR raw: '{txt.strip()}' | cleaned: '{clean}'")

            if 3 <= len(clean) <= 10:
                return clean
            return ""
        except Exception as e:
            log(f"[!] OCR error: {e}")
            return ""

    def _save_pil(self, img, name):
        try:
            path = os.path.join(DEBUG_DIR, f"{name}_{int(time.time())}.png")
            img.save(path)
        except Exception:
            pass

    def _check_services_status(self):
        for svc in self.services:
            sel = self.services[svc]["selector"]
            try:
                self._dismiss_alert()
                el = self.driver.find_element(By.CLASS_NAME, sel)
                self.services[svc]["status"] = "[WORKING]" if el.is_enabled() else "[OFFLINE]"
            except (NoSuchElementException, UnexpectedAlertPresentException):
                self.services[svc]["status"] = "[OFFLINE]"
                self._dismiss_alert()

    def _print_services_list(self):
        for i, svc in enumerate(self.services):
            t = self.services[svc]["title"]
            s = self.services[svc]["status"]
            print(f"[{i+1}] {t}".ljust(30), s)
        print()

    def _choose_service(self):
        if _HEADLESS_MODE:
            env = os.environ.get("TIKTOK_SERVICE", "4")
            try:
                c = int(env)
            except ValueError:
                c = 4
            key = list(self.services.keys())[c - 1]
            log(f"[+] Service: {self.services[key]['title']}")
            return key
        while True:
            try:
                c = int(input("[~] Choose an option : "))
            except ValueError:
                print("[!] Invalid input")
                continue
            if c in range(1, 8):
                key = list(self.services.keys())[c - 1]
                if self.services[key]["status"] == "[OFFLINE]":
                    print("[!] Service offline")
                    continue
                print(f"[+] You chose {self.services[key]['title']}")
                return key
            print("[!] No service found")

    def _choose_video_url(self):
        if _HEADLESS_MODE:
            url = os.environ.get("TIKTOK_VIDEO_URL", "")
            if not url:
                log("[!] ERRO: defina TIKTOK_VIDEO_URL")
                sys.exit(1)
            log(f"[+] Video URL: {url}")
            return url
        return input("[~] Video URL : ")

    def _start_service(self, service, video_url):
        self._wait_for_element(By.CLASS_NAME, self.services[service]["selector"], timeout=30).click()
        container = self._wait_for_element(
            By.CSS_SELECTOR, "div.col-sm-5.col-xs-12.p-1.container:not(.nonec)", timeout=30)
        inp = container.find_element(By.TAG_NAME, "input")
        inp.clear()
        inp.send_keys(video_url)
        while True:
            container.find_element(By.CSS_SELECTOR, "button.btn.btn-primary").click()
            time.sleep(3)
            try:
                container.find_element(By.CSS_SELECTOR, "button.btn.btn-dark").click()
                log(f"[~] {self.services[service]['title']} sent")
            except NoSuchElementException:
                pass
            except UnexpectedAlertPresentException:
                self._dismiss_alert()
            time.sleep(3)
            rt = self._compute_remaining_time(container)
            if rt is not None:
                m, s = rt // 60, rt % 60
                log(f"[~] Sleeping {m}m {s}s")
                time.sleep(rt)
            print()

    def _compute_remaining_time(self, container):
        try:
            el = container.find_element(By.CSS_SELECTOR, "span.br")
            txt = el.text
            if "Please wait" in txt:
                nums = re.findall(r"\d+", txt)
                if len(nums) >= 2:
                    return int(nums[0]) * 60 + int(nums[1]) + 5
            return None
        except NoSuchElementException:
            return None

    def _wait_for_element(self, by, value, timeout=60):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                self._dismiss_alert()
                el = self.driver.find_element(by, value)
                if el.is_displayed():
                    return el
            except (NoSuchElementException, StaleElementReferenceException):
                time.sleep(0.5)
            except UnexpectedAlertPresentException:
                self._dismiss_alert()
                time.sleep(0.5)
        raise TimeoutException(f"Element ({by}={value}) not found in {timeout}s")


if __name__ == "__main__":
    bot = Bot()
    try:
        bot.start()
    except KeyboardInterrupt:
        print("\n[!] Interrupted")
    except Exception as e:
        log(f"[x] Bot crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
