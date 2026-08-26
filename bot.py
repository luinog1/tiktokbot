"""
TikTok Bot — Zefoy CAPTCHA solver via Tesseract OCR (memory-optimized for 512MB).
Removes OpenCV (heavy) → uses only PIL for preprocessing.
"""

import re
import os
import sys
import subprocess
import io
import gc
import time
from datetime import datetime
from PIL import Image, ImageFilter, ImageOps, ImageEnhance"""
TikTok Bot — Zefoy CAPTCHA solver with aggressive OCR retry strategy.
Uses OpenCV headless (lighter) + PIL fallback + multi-parameter retry.
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

# Try OpenCV headless first, fallback to PIL-only
try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False
    print("[!] OpenCV not available, using PIL-only fallback")

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
        print("|   TikTok Bot — Aggressive CAPTCHA Retry                |")
        print(f"|   OCR: {'OpenCV+Tesseract' if HAS_OPENCV else 'PIL+Tesseract'} |")
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
        options.set_preference("security.sandbox.content.tempdir.level", 0)
        options.set_preference("browser.tabs.crashReporting.sendReport", False)
        options.set_preference("toolkit.startup.max_resumed_crashes", -1)
        options.set_preference("datareporting.healthreport.uploadEnabled", False)
        options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
        options.set_preference("services.settings.server", "")
        options.set_preference("browser.cache.disk.enable", False)
        options.set_preference("browser.cache.memory.enable", False)
        options.set_preference("browser.sessionstore.resume_from_crash", False)
        options.set_preference("dom.ipc.processCount", 1)
        options.set_preference("javascript.options.mem.max", 128 * 1024)
        options.set_preference("general.useragent.override",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0")
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)
        options.set_preference("dom.webnotifications.enabled", False)
        options.set_preference("dom.push.enabled", False)
        options.set_preference("permissions.default.desktop-notification", 2)
        options.set_preference("geo.enabled", False)

        service = webdriver.FirefoxService(
            executable_path="/usr/local/bin/geckodriver",
            log_output=sys.stdout,
        )
        driver = webdriver.Firefox(options=options, service=service)
        log("[+] Driver loaded")
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
    # MAIN FLOW
    # ===================================================================
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

    # ===================================================================
    # CAPTCHA SOLVER — Aggressive retry on same page
    # ===================================================================
    def _solve_captcha(self):
        log("[~] Scanning for CAPTCHA...")

        # Wait for input
        try:
            self._wait_for_element(By.TAG_NAME, "input", timeout=30)
        except TimeoutException:
            log("[!] No input found in 30s")
            raise

        self._dismiss_alert()

        # Try solving captcha up to 5 times on the SAME page
        for solve_attempt in range(1, 6):
            log(f"[~] Captcha solve attempt {solve_attempt}/5")
            self._dismiss_alert()

            # Check if captcha is already cleared
            if self._is_captcha_cleared():
                log("[+] Captcha already cleared")
                print()
                return

            # Get captcha image
            png = self._get_captcha_image()
            if not png:
                log("[!] Could not capture captcha image")
                time.sleep(2)
                continue

            # Try multiple OCR configs
            text = self._ocr_multi_attempt(png)
            if not text:
                log("[!] OCR returned empty, trying different params...")
                text = self._ocr_with_fallback_params(png)

            if text:
                log(f"[+] OCR result: '{text}'")
                self._fill_and_submit(text)

                # Wait briefly to see if captcha clears
                time.sleep(3)
                if self._is_captcha_cleared():
                    log("[+] Captcha cleared after submit")
                    print()
                    return
                else:
                    log("[!] Captcha still present — likely wrong answer")
                    # Clear input for next attempt
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
        """Check if the captcha is gone (Youtube link visible or input gone)."""
        try:
            # If Youtube link is visible, captcha is cleared
            links = self.driver.find_elements(By.LINK_TEXT, "Youtube")
            for link in links:
                if link.is_displayed():
                    return True
        except Exception:
            pass

        # If input is gone, captcha is cleared
        try:
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            visible_inputs = [i for i in inputs if i.is_displayed()]
            if not visible_inputs:
                return True
        except Exception:
            pass

        return False

    def _get_captcha_image(self):
        """Capture the captcha image element."""
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

        # Fallback: screenshot top portion
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

    # ===================================================================
    # OCR — Multiple attempts with different preprocessing
    # ===================================================================
    def _ocr_multi_attempt(self, png_bytes):
        """Try OCR with OpenCV preprocessing (best quality)."""
        if not HAS_OPENCV:
            return self._ocr_pil_only(png_bytes)

        try:
            nparr = np.frombuffer(png_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return self._ocr_pil_only(png_bytes)

            # Save raw for debug
            self._save_cv(img, "captcha_raw")

            results = []

            # Attempt 1: Standard pipeline
            text = self._ocr_cv_pipeline(img, scale=3, blur=(5,5), morph_k=2)
            if text: results.append(text)

            # Attempt 2: Higher contrast
            text = self._ocr_cv_pipeline(img, scale=4, blur=(3,3), morph_k=1, contrast=2.0)
            if text: results.append(text)

            # Attempt 3: No blur, just threshold
            text = self._ocr_cv_pipeline(img, scale=3, blur=None, morph_k=1)
            if text: results.append(text)

            # Attempt 4: Inverted
            text = self._ocr_cv_pipeline(img, scale=3, blur=(5,5), morph_k=2, invert=True)
            if text: results.append(text)

            # Attempt 5: Dilate then erode
            text = self._ocr_cv_pipeline(img, scale=3, blur=(3,3), morph_k=3, dilate_first=True)
            if text: results.append(text)

            if results:
                from collections import Counter
                best = Counter(results).most_common(1)[0][0]
                log(f"[~] OCR candidates: {results} → best: {best}")
                return best
            return ""
        except Exception as e:
            log(f"[!] OpenCV OCR error: {e}")
            return self._ocr_pil_only(png_bytes)

    def _ocr_cv_pipeline(self, img, scale=3, blur=(5,5), morph_k=2, contrast=1.0, invert=False, dilate_first=False):
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape
            gray = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

            if contrast != 1.0:
                gray = cv2.convertScaleAbs(gray, alpha=contrast, beta=0)

            if blur:
                gray = cv2.GaussianBlur(gray, blur, 0)

            # Adaptive threshold
            thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, 11, 2)

            if dilate_first:
                kernel = np.ones((2,2), np.uint8)
                thresh = cv2.dilate(thresh, kernel, iterations=1)
                thresh = cv2.erode(thresh, kernel, iterations=1)
            else:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_k, morph_k))
                thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

            if invert:
                thresh = cv2.bitwise_not(thresh)
            else:
                # Auto-invert if mostly white
                white = cv2.countNonZero(thresh)
                if white > thresh.size * 0.7:
                    thresh = cv2.bitwise_not(thresh)

            self._save_cv(thresh, f"captcha_proc_s{scale}")

            configs = [
                r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
                r'--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
            ]
            for cfg in configs:
                txt = pytesseract.image_to_string(thresh, config=cfg)
                clean = re.sub(r'[^A-Za-z0-9]', '', txt).strip()
                if 3 <= len(clean) <= 10:
                    return clean
            return ""
        except Exception:
            return ""

    def _ocr_with_fallback_params(self, png_bytes):
        """Last resort: try with PIL-only aggressive preprocessing."""
        return self._ocr_pil_only(png_bytes, aggressive=True)

    def _ocr_pil_only(self, png_bytes, aggressive=False):
        try:
            img = Image.open(io.BytesIO(png_bytes))
            img = ImageOps.grayscale(img)
            w, h = img.size
            img = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)

            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(3.0 if aggressive else 2.0)

            img = img.filter(ImageFilter.SHARPEN)
            if aggressive:
                img = img.filter(ImageFilter.SHARPEN)
                img = img.filter(ImageFilter.MedianFilter(size=3))

            img = img.point(lambda x: 0 if x < 100 else 255, '1')
            img = img.convert('L')

            self._save_pil(img, "captcha_pil")

            configs = [
                r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
                r'--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
            ]
            results = []
            for cfg in configs:
                txt = pytesseract.image_to_string(img, config=cfg)
                clean = re.sub(r'[^A-Za-z0-9]', '', txt).strip()
                if clean:
                    results.append(clean)

            if results:
                from collections import Counter
                best = Counter(results).most_common(1)[0][0]
                if 3 <= len(best) <= 10:
                    return best
            return ""
        except Exception:
            return ""

    # ===================================================================
    # DEBUG SAVES
    # ===================================================================
    def _save_cv(self, img, name):
        try:
            path = os.path.join(DEBUG_DIR, f"{name}_{int(time.time())}.png")
            cv2.imwrite(path, img)
        except Exception:
            pass

    def _save_pil(self, img, name):
        try:
            path = os.path.join(DEBUG_DIR, f"{name}_{int(time.time())}.png")
            img.save(path)
        except Exception:
            pass

    # ===================================================================
    # ORIGINAL BOT LOGIC
    # ===================================================================
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

# Modo headless/Render
_HEADLESS_MODE = not sys.stdin.isatty() or os.environ.get("RENDER")

# Tesseract path
pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD", "/usr/bin/tesseract")

# Debug
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
        print("|   TikTok Bot — Memory Optimized (512MB)                |")
        print("|   CAPTCHA : Tesseract + PIL (no OpenCV)                |")
        print("+--------------------------------------------------------+")
        print()

    def _init_driver(self):
        log("[~] Loading Firefox driver (memory-optimized)...")

        options = webdriver.FirefoxOptions()

        for binary in ["/usr/bin/firefox-esr", "/usr/bin/firefox"]:
            if os.path.exists(binary):
                options.binary_location = binary
                break

        options.add_argument("-headless")

        # Sandbox
        options.set_preference("security.sandbox.content.level", 0)
        options.set_preference("security.sandbox.gpu.level", 0)
        options.set_preference("security.sandbox.media.level", 0)
        options.set_preference("security.sandbox.content.tempdir.level", 0)

        # Crash reporter off
        options.set_preference("browser.tabs.crashReporting.sendReport", False)
        options.set_preference("toolkit.startup.max_resumed_crashes", -1)

        # Telemetry / remote settings OFF
        options.set_preference("datareporting.healthreport.uploadEnabled", False)
        options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
        options.set_preference("services.settings.server", "")

        # MEMORY OPTIMIZATIONS for 512MB container
        options.set_preference("browser.cache.disk.enable", False)
        options.set_preference("browser.cache.memory.enable", False)
        options.set_preference("browser.sessionstore.resume_from_crash", False)
        options.set_preference("browser.tabs.firefox-view", False)
        options.set_preference("browser.download.start_downloads_in_tmp_dir", True)
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.useDownloadDir", False)
        options.set_preference("dom.ipc.processCount", 1)  # Single content process
        options.set_preference("browser.preferences.defaultPerformanceSettings.enabled", False)
        options.set_preference("dom.max_chrome_script_run_time", 0)
        options.set_preference("dom.max_script_run_time", 30)
        options.set_preference("javascript.options.mem.max", 128 * 1024)  # 128MB JS heap
        options.set_preference("javascript.options.mem.high_water_mark", 96)

        # Anti-detection
        options.set_preference("general.useragent.override",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0")
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)

        # Block notifications
        options.set_preference("dom.webnotifications.enabled", False)
        options.set_preference("dom.push.enabled", False)
        options.set_preference("permissions.default.desktop-notification", 2)

        # Block geo
        options.set_preference("geo.enabled", False)

        service = webdriver.FirefoxService(
            executable_path="/usr/local/bin/geckodriver",
            log_output=sys.stdout,
        )

        driver = webdriver.Firefox(options=options, service=service)
        log("[+] Driver loaded")
        return driver

    def _init_services(self):
        return {
            "followers":    {"title": "Followers",    "selector": "t-followers-button", "status": None},
            "hearts":       {"title": "Hearts",       "selector": "t-hearts-button",    "status": None},
            "comments_hearts": {"title": "Comments Hearts", "selector": "t-chearts-button", "status": None},
            "views":        {"title": "Views",        "selector": "t-views-button",     "status": None},
            "shares":       {"title": "Shares",       "selector": "t-shares-button",    "status": None},
            "favorites":    {"title": "Favorites",    "selector": "t-favorites-button", "status": None},
            "live_stream":  {"title": "Live Stream [VS+LIKES]", "selector": "t-livesteam-button", "status": None},
        }

    # ------------------------------------------------------------------
    def _dismiss_alert(self):
        try:
            alert = self.driver.switch_to.alert
            log(f"[!] Alert: {alert.text[:60]}")
            alert.dismiss()
            time.sleep(0.3)
        except NoAlertPresentException:
            pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    def start(self):
        for attempt in range(1, 6):
            log(f"=== Attempt {attempt}/5 ===")
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
                log(f"[!] Attempt {attempt} failed: {str(e)[:120]}")
                if attempt < 5:
                    log("[~] Retrying in 5s...")
                    time.sleep(5)
                else:
                    log("[x] Max attempts reached")
                    raise
            finally:
                gc.collect()

    # ------------------------------------------------------------------
    def _solve_captcha(self):
        log("[~] Scanning for CAPTCHA...")

        try:
            self._wait_for_element(By.TAG_NAME, "input", timeout=30)
        except TimeoutException:
            log("[!] No input found in 30s")
            self._save_debug("no_input")
            raise

        self._dismiss_alert()

        text = self._ocr_solve()
        if text:
            log(f"[+] OCR result: {text}")
            self._fill_captcha(text)
        else:
            log("[!] OCR empty, waiting fallback...")

        # Wait for page to clear
        try:
            self._wait_for_element(By.LINK_TEXT, "Youtube", timeout=60)
            log("[+] Captcha cleared")
        except TimeoutException:
            log("[!] Captcha not cleared in 60s")
            self._save_debug("captcha_timeout")
            raise
        print()

    def _fill_captcha(self, text):
        try:
            self._dismiss_alert()
            inp = self.driver.find_element(By.TAG_NAME, "input")
            inp.clear()
            inp.send_keys(text)
            time.sleep(1)

            # Try submit
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR,
                    "button[type='submit'], button.btn-primary, form button")
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    log("[+] Submitted")
                    time.sleep(3)
            except NoSuchElementException:
                inp.submit()
                log("[+] Submitted via enter")
                time.sleep(3)

            # Check for error
            if self._has_error():
                log("[!] Captcha rejected by site")
                raise Exception("Captcha rejected")
        except UnexpectedAlertPresentException:
            self._dismiss_alert()

    def _has_error(self):
        for sel in ["[class*='error' i]", "[class*='wrong' i]", "[class*='invalid' i]"]:
            try:
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed() and el.text.strip():
                        return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # OCR — PIL only (no OpenCV, memory-light)
    # ------------------------------------------------------------------
    def _ocr_solve(self):
        try:
            self._dismiss_alert()
            img_elem = None
            for sel in ["img[src*='captcha']", "img.captcha", "#captcha",
                        "img[alt*='captcha' i]", "form img", "div.form-group img"]:
                try:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if el.is_displayed():
                            sz = el.size
                            if sz.get("width", 0) > 50 and sz.get("height", 0) > 20:
                                img_elem = el
                                break
                    if img_elem:
                        break
                except Exception:
                    continue

            if not img_elem:
                return self._ocr_from_screenshot()

            png = img_elem.screenshot_as_png
            self._save_img(png, "captcha_raw")
            return self._ocr_image(png)
        except Exception as e:
            log(f"[!] OCR error: {e}")
            return ""

    def _ocr_from_screenshot(self):
        try:
            self._dismiss_alert()
            png = self.driver.get_screenshot_as_png()
            img = Image.open(io.BytesIO(png))
            w, h = img.size
            cropped = img.crop((0, 0, w, int(h * 0.4)))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return self._ocr_image(buf.getvalue())
        except Exception as e:
            log(f"[!] Screenshot OCR error: {e}")
            return ""

    def _ocr_image(self, png_bytes):
        try:
            img = Image.open(io.BytesIO(png_bytes))

            # Convert to grayscale
            img = ImageOps.grayscale(img)

            # Resize 3x
            w, h = img.size
            img = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)

            # Enhance contrast
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)

            # Sharpen
            img = img.filter(ImageFilter.SHARPEN)

            # Simple threshold (no OpenCV)
            img = img.point(lambda x: 0 if x < 128 else 255, '1')
            img = img.convert('L')

            # Save debug
            self._save_img_pil(img, "captcha_proc")

            # Try multiple configs
            configs = [
                r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
                r'--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
            ]
            results = []
            for cfg in configs:
                txt = pytesseract.image_to_string(img, config=cfg)
                clean = re.sub(r'[^A-Za-z0-9]', '', txt).strip()
                if clean:
                    results.append(clean)

            if results:
                from collections import Counter
                best = Counter(results).most_common(1)[0][0]
                log(f"[~] OCR candidates: {results} → best: {best}")
                if 3 <= len(best) <= 10:
                    return best
            return ""
        except Exception as e:
            log(f"[!] OCR processing error: {e}")
            return ""

    # ------------------------------------------------------------------
    def _save_img(self, data, name):
        try:
            path = os.path.join(DEBUG_DIR, f"{name}_{int(time.time())}.png")
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            pass

    def _save_img_pil(self, img, name):
        try:
            path = os.path.join(DEBUG_DIR, f"{name}_{int(time.time())}.png")
            img.save(path)
        except Exception:
            pass

    def _save_debug(self, suffix):
        try:
            path = os.path.join(DEBUG_DIR, f"page_{suffix}_{int(time.time())}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
        except Exception:
            pass

    # ------------------------------------------------------------------
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
