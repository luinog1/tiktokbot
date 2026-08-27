"""
TikTok Bot - Hybrid approach based on xtekky/TikTok-ViewBot v2.py
CAPTCHA solved via requests (lightweight) + Selenium only for page interaction.
"""

import re
import os
import sys
import subprocess
import io
import gc
import time
from datetime import datetime
from base64 import b64encode
from io import BytesIO
from requests import get, post, Session
from PIL import Image, ImageFilter, ImageOps, ImageEnhance

import pytesseract

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    UnexpectedAlertPresentException,
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
        self.driver = None
        self.services = self._init_services()

    def _print_banner(self):
        print("+--------------------------------------------------------+")
        print("|   TikTok Bot - Hybrid (xtekky approach)                  |")
        print("|   CAPTCHA: requests + Tesseract | Bot: Firefox            |")
        print("+--------------------------------------------------------+")
        print()

    def _init_driver(self):
        log("[~] Loading Firefox driver...")
        options = webdriver.FirefoxOptions()

        for binary in ["/usr/bin/firefox-esr", "/usr/bin/firefox"]:
            if os.path.exists(binary):
                options.binary_location = binary
                break

        options.add_argument("-headless")
        options.set_preference("security.sandbox.content.level", 0)
        options.set_preference("security.sandbox.gpu.level", 0)
        options.set_preference("security.sandbox.media.level", 0)
        options.set_preference("browser.tabs.crashReporting.sendReport", False)
        options.set_preference("toolkit.startup.max_resumed_crashes", -1)
        options.set_preference("datareporting.healthreport.uploadEnabled", False)
        options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
        options.set_preference("services.settings.server", "")
        options.set_preference("browser.cache.disk.enable", False)
        options.set_preference("browser.cache.memory.enable", False)
        options.set_preference("browser.sessionstore.resume_from_crash", False)
        options.set_preference("dom.ipc.processCount", 1)
        options.set_preference("javascript.options.mem.max", 64 * 1024)
        options.set_preference("general.useragent.override",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0")
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)
        options.set_preference("dom.webnotifications.enabled", False)
        options.set_preference("dom.push.enabled", False)
        options.set_preference("permissions.default.desktop-notification", 2)
        options.set_preference("geo.enabled", False)
        options.set_preference("media.hardware-video-decoding.enabled", False)
        options.set_preference("layers.acceleration.disabled", True)

        service = webdriver.FirefoxService(
            executable_path="/usr/local/bin/geckodriver",
            log_output=sys.stdout,
        )
        driver = webdriver.Firefox(options=options, service=service)
        log("[+] Firefox driver loaded")
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

    # ===================================================================
    # CAPTCHA SOLVER via requests (xtekky approach)
    # ===================================================================
    def _solve_captcha_via_requests(self):
        """
        Resolve captcha using requests only - no browser needed.
        Based on xtekky/TikTok-ViewBot v2.py solve() method.
        Returns PHPSESSID cookie dict for injection into browser.
        """
        log("[~] Solving CAPTCHA via requests (lightweight)...")

        session = Session()
        session.headers = {
            'authority': 'zefoy.com',
            'origin': 'https://zefoy.com',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
        }

        for attempt in range(1, 8):
            log(f"[~] Captcha request attempt {attempt}/7")

            # Get page source
            response = session.get('https://zefoy.com')
            source_code = response.text.replace('&amp;', '&')

            # Extract captcha token inputs
            captcha_tokens = re.findall(r'<input type="hidden" name="(.*)">', source_code)
            if 'token' in captcha_tokens:
                captcha_tokens.remove('token')

            # Extract captcha image URL
            captcha_urls = re.findall(r'img src="([^"]*)"', source_code)
            if not captcha_urls:
                log("[!] No captcha image found in HTML")
                time.sleep(2)
                continue

            captcha_url = captcha_urls[0]
            if not captcha_url.startswith('http'):
                captcha_url = 'https://zefoy.com' + captcha_url

            # Extract answer input name
            answer_matches = re.findall(r'type="text" name="(.*)" oninput="this.value', source_code)
            if not answer_matches:
                # Try alternative patterns
                answer_matches = re.findall(r'<input[^>]*name="([^"]*)"[^>]*placeholder="[^"]*[Cc]aptcha[^"]*"', source_code)
            if not answer_matches:
                answer_matches = re.findall(r'<input[^>]*type="text"[^>]*name="([^"]*)"', source_code)

            if not answer_matches:
                log("[!] Could not find captcha answer input name")
                time.sleep(2)
                continue

            token_answer = answer_matches[0]
            log(f"[~] Captcha URL: {captcha_url[:60]}...")
            log(f"[~] Answer field: {token_answer}")

            # Download captcha image
            img_response = session.get(captcha_url)
            if img_response.status_code != 200:
                log(f"[!] Failed to download captcha image: {img_response.status_code}")
                time.sleep(2)
                continue

            # Save for debug
            ts = int(time.time())
            raw_path = os.path.join(DEBUG_DIR, f"captcha_req_{ts}.png")
            with open(raw_path, "wb") as f:
                f.write(img_response.content)

            # OCR with Tesseract
            captcha_text = self._ocr_image(img_response.content)
            if not captcha_text:
                log("[!] OCR failed, retrying with fresh page...")
                time.sleep(2)
                continue

            log(f"[+] OCR result: '{captcha_text}'")

            # Build form data
            data = {token_answer: captcha_text}
            for token_value in captcha_tokens:
                if '" value="' in token_value:
                    token, value = token_value.split('" value="', 1)
                    data[token] = value
            data['token'] = ''

            log(f"[~] Submitting captcha...")
            submit_response = session.post('https://zefoy.com', data=data)

            # Check if captcha was accepted
            if 'name="' in submit_response.text and 'placeholder' in submit_response.text:
                # Try to find the video URL input box - means captcha passed
                try:
                    re.findall(r'remove-spaces" name="(.*)" placeholder', submit_response.text)[0]
                    log("[+] Captcha solved successfully via requests!")
                    phpsessid = session.cookies.get('PHPSESSID')
                    if phpsessid:
                        return {'name': 'PHPSESSID', 'value': phpsessid}
                    else:
                        log("[!] No PHPSESSID cookie found")
                        return None
                except IndexError:
                    pass

            # Check for error indicators
            if "wrong" in submit_response.text.lower() or "invalid" in submit_response.text.lower():
                log("[!] Captcha rejected, retrying...")
                time.sleep(2)
                continue

            # Check if we got redirected or have the main page
            if "zefoy" in submit_response.text.lower():
                phpsessid = session.cookies.get('PHPSESSID')
                if phpsessid:
                    log("[+] Captcha likely solved, proceeding with cookie")
                    return {'name': 'PHPSESSID', 'value': phpsessid}

            time.sleep(2)

        log("[x] Could not solve captcha via requests after all attempts")
        return None

    def _ocr_image(self, img_bytes):
        """OCR with PIL + Tesseract."""
        try:
            img = Image.open(BytesIO(img_bytes))

            # Preprocess
            img = ImageOps.grayscale(img)
            w, h = img.size
            img = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.5)
            img = img.filter(ImageFilter.SHARPEN)
            img = img.point(lambda x: 0 if x < 120 else 255, "1")
            img = img.convert("L")

            # Save processed
            ts = int(time.time())
            proc_path = os.path.join(DEBUG_DIR, f"captcha_req_proc_{ts}.png")
            img.save(proc_path)

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

    # ===================================================================
    # MAIN FLOW
    # ===================================================================
    def start(self):
        for page_attempt in range(1, 4):
            log(f"=== Page attempt {page_attempt}/3 ===")
            try:
                # Step 1: Solve captcha via requests (lightweight, no browser memory yet)
                cookie = self._solve_captcha_via_requests()

                if not cookie:
                    log("[!] Failed to solve captcha via requests, falling back to browser method...")
                    # Fallback: open browser and solve captcha there
                    self.driver = self._init_driver()
                    self._solve_captcha_browser()
                else:
                    # Step 2: Open browser with cookie already solved
                    log("[~] Opening browser with solved captcha cookie...")
                    self.driver = self._init_driver()
                    self.driver.get("https://zefoy.com")
                    self.driver.add_cookie(cookie)
                    self.driver.refresh()
                    log("[+] Cookie injected, page refreshed")

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

    def _solve_captcha_browser(self):
        """Fallback: solve captcha using browser + OCR."""
        log("[~] Solving CAPTCHA via browser (fallback)...")

        self.driver.get("https://zefoy.com")
        self._dismiss_alert()

        try:
            self._wait_for_element(By.TAG_NAME, "input", timeout=30)
        except TimeoutException:
            log("[!] No input found in 30s")
            raise

        self._dismiss_alert()

        for solve_attempt in range(1, 6):
            log(f"[~] Browser captcha attempt {solve_attempt}/5")
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

            text = self._ocr_image(png)

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

        log("[!] All browser captcha attempts failed")
        raise Exception("Could not solve captcha")

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
            img = Image.open(BytesIO(png))
            w, h = img.size
            cropped = img.crop((0, 0, w, int(h * 0.4)))
            buf = BytesIO()
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
