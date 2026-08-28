import os
import time
import base64
import threading
import logging
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s INFO bot -> %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

VIDEO_URL = os.environ.get("TIKTOK_VIDEO_URL", "")
SERVICE = os.environ.get("TIKTOK_SERVICE", "Views").lower()
PROXY_URL = os.environ.get("PROXY_URL", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
PORT = int(os.environ.get("PORT", 8080))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def start_http():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


threading.Thread(target=start_http, daemon=True).start()

from playwright.sync_api import sync_playwright


def get_proxy_config():
    if not PROXY_URL:
        return None
    m = re.match(r"http://([^:]+):([^@]+)@([^:]+):(\d+)", PROXY_URL)
    if m:
        return {
            "server": f"http://{m.group(3)}:{m.group(4)}",
            "username": m.group(1),
            "password": m.group(2),
        }
    return {"server": PROXY_URL}


CAPTCHA_PROMPT = (
    "What single word is shown in this captcha image? "
    "Reply with only the word in lowercase letters, no punctuation, no explanation."
)


def _clean_word(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").strip().lower())


def solve_captcha_gemini(img_bytes: bytes) -> str:
    import requests as req

    if not GEMINI_KEY:
        return ""
    b64 = base64.b64encode(img_bytes).decode()
    for model in ["gemini-3.5-flash-lite", "gemini-3.6-flash"]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_KEY}"
        )
        payload = {
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": b64}},
                    {"text": CAPTCHA_PROMPT},
                ]
            }],
            "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
        }
        try:
            resp = req.post(url, json=payload, timeout=30)
            data = resp.json()
            if resp.status_code != 200:
                log.info(f"Gemini {model} HTTP {resp.status_code}: {data}")
                continue
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            word = _clean_word(text)
            if word:
                log.info(f"Gemini ({model}) captcha → '{word}'")
                return word
        except Exception as e:
            log.info(f"Gemini {model} erro: {e}")
    return ""


def solve_captcha_openai(img_bytes: bytes) -> str:
    import requests as req

    if not OPENAI_KEY:
        return ""
    b64 = base64.b64encode(img_bytes).decode()
    try:
        resp = req.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 16,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {"type": "text", "text": CAPTCHA_PROMPT},
                    ],
                }],
            },
            timeout=30,
        )
        data = resp.json()
        if resp.status_code != 200:
            log.info(f"OpenAI HTTP {resp.status_code}: {data}")
            return ""
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        word = _clean_word(text)
        if word:
            log.info(f"OpenAI captcha → '{word}'")
        return word
    except Exception as e:
        log.info(f"OpenAI erro: {e}")
        return ""


def solve_captcha(img_bytes: bytes) -> str:
    word = solve_captcha_gemini(img_bytes)
    if word:
        return word
    word = solve_captcha_openai(img_bytes)
    if word:
        return word
    log.info("Captcha não resolvido (keys ou API)")
    return ""


SERVICE_MAP = {
    "views": "Views",
    "likes": "Hearts",
    "hearts": "Hearts",
    "followers": "Followers",
    "shares": "Shares",
    "favorites": "Favorites",
}

# botões CSS típicos do zefoy
SERVICE_CSS = {
    "views": ".t-views-button",
    "likes": ".t-hearts-button",
    "hearts": ".t-hearts-button",
    "followers": ".t-followers-button",
    "shares": ".t-shares-button",
    "favorites": ".t-favorites-button",
}


def run_bot():
    proxy = get_proxy_config()
    log.info(f"Proxy: {proxy.get('server') if proxy else 'nenhum'}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            proxy=proxy,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        page = context.new_page()

        # ── Login ────────────────────────────────────────────────────────────
        logged_in = False
        for attempt in range(1, 6):
            log.info(f"Tentativa de login {attempt}/5")
            try:
                page.goto("https://zefoy.com", wait_until="domcontentloaded", timeout=60000)
                log.info(f"Página carregada: {len(page.content())} chars")

                page.wait_for_function(
                    "document.getElementById('captcha-img') && "
                    "document.getElementById('captcha-img').naturalWidth > 0",
                    timeout=15000,
                )
                img_el = page.query_selector("#captcha-img")
                if not img_el:
                    log.info("#captcha-img não encontrado")
                    time.sleep(15)
                    continue

                img_bytes = img_el.screenshot()
                log.info(f"Captcha screenshot: {len(img_bytes)} bytes")

                word = solve_captcha(img_bytes)
                if not word:
                    log.info("Captcha não resolvido")
                    time.sleep(15)
                    continue

                page.fill("input[name='captchalogin']", word)
                page.click("button[type='submit'], .btn-primary")
                time.sleep(3)

                if "zefoy.com" in page.url and "captcha" not in page.content().lower():
                    log.info("Login OK!")
                    logged_in = True
                    break
                log.info("Login falhou — captcha errado?")
                time.sleep(15)
            except Exception as e:
                log.info(f"Erro login {attempt}: {e}")
                time.sleep(15)

        if not logged_in:
            log.info("Login falhou 5x. Reinicio em 60s...")
            time.sleep(60)
            browser.close()
            return

        service_label = SERVICE_MAP.get(SERVICE, "Views")
        log.info(f"Serviço: {service_label} | URL: {VIDEO_URL}")
        if not VIDEO_URL:
            log.info("TIKTOK_VIDEO_URL vazia")
            time.sleep(60)
            browser.close()
            return

        css_btn = SERVICE_CSS.get(SERVICE)
        service_selectors = [
            css_btn,
            f"button:has-text('{service_label}')",
            f".btn:has-text('{service_label}')",
            f"div.card:has-text('{service_label}') button",
            f"h5:has-text('{service_label}') >> xpath=../..//button",
            f"text={service_label}",
        ]
        service_selectors = [s for s in service_selectors if s]

        while True:
            try:
                # 1) Abrir painel do serviço
                clicked = False
                for sel in service_selectors:
                    try:
                        page.locator(sel).first.click(timeout=4000)
                        clicked = True
                        log.info(f"Clicou serviço: {sel}")
                        break
                    except Exception:
                        continue

                if not clicked:
                    log.info(f"Botão '{service_label}' não encontrado")
                    time.sleep(20)
                    continue

                # 2) Esperar input do formulário (visível ou forçar)
                time.sleep(1.5)
                input_sel = (
                    "input[placeholder*='Enter Video'], "
                    "input[placeholder*='Enter Video/Username'], "
                    "input.form-control[type='search']"
                )

                url_filled = False
                try:
                    page.wait_for_selector(
                        "input[placeholder*='Enter Video']:visible",
                        timeout=6000,
                    )
                    loc = page.locator("input[placeholder*='Enter Video']:visible").first
                    loc.click()
                    loc.fill(VIDEO_URL)
                    url_filled = True
                    log.info("URL preenchida (input visível)")
                except Exception:
                    pass

                if not url_filled:
                    # force em todos os inputs com esse placeholder (painel hidden)
                    try:
                        locs = page.locator(input_sel)
                        n = locs.count()
                        log.info(f"Inputs candidatos: {n} — a forçar fill")
                        for i in range(n):
                            try:
                                locs.nth(i).fill(VIDEO_URL, force=True)
                                url_filled = True
                            except Exception:
                                continue
                        if url_filled:
                            log.info("URL preenchida com force=True")
                    except Exception as e:
                        log.info(f"Force fill falhou: {e}")

                if not url_filled:
                    log.info("Não foi possível preencher a URL")
                    time.sleep(15)
                    continue

                time.sleep(0.5)

                # 3) Submit — preferir botão no form ativo
                submitted = False
                for sel in [
                    "form:visible button[type='submit']",
                    "form:visible button",
                    "button[type='submit']:visible",
                    ".btn-primary:visible",
                    "button:has-text('Search'):visible",
                    "button:has-text('Submit'):visible",
                    "button[type='submit']",
                    ".btn-primary",
                ]:
                    try:
                        page.locator(sel).first.click(timeout=3000, force=True)
                        submitted = True
                        log.info(f"Submit: {sel}")
                        break
                    except Exception:
                        continue

                if not submitted:
                    # Enter no input
                    try:
                        page.locator(input_sel).first.press("Enter", force=True)
                        submitted = True
                        log.info("Submit via Enter")
                    except Exception:
                        log.info("Submit não encontrado")
                        time.sleep(15)
                        continue

                time.sleep(3)
                result = page.inner_text("body")

                if re.search(r"please wait|seconds?", result, re.I):
                    m = re.search(r"(\d+)\s*second", result, re.I)
                    wait_sec = int(m.group(1)) if m else 60
                    log.info(f"Aguardando {wait_sec}s...")
                    time.sleep(wait_sec + 5)
                elif re.search(r"successfully|sent", result, re.I):
                    log.info("Sucesso! Próxima em 30s")
                    time.sleep(30)
                else:
                    log.info(f"Resposta: {result[:300]}")
                    time.sleep(30)

            except Exception as e:
                log.info(f"Erro no loop: {e}")
                time.sleep(30)

        browser.close()


while True:
    try:
        run_bot()
    except Exception as e:
        log.info(f"Crash: {e} — reinício em 60s")
        time.sleep(60)
