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

# ── HTTP keep-alive (SnapDeploy / Render healthcheck) ─────────────────────────
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

# ── Playwright ────────────────────────────────────────────────────────────────
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
    word = (text or "").strip().lower()
    return re.sub(r"[^a-z]", "", word)


def solve_captcha_gemini(img_bytes: bytes) -> str:
    """Gemini Vision via REST (free tier). Sem SDK extra."""
    import requests as req

    if not GEMINI_KEY:
        return ""
    b64 = base64.b64encode(img_bytes).decode()
    models = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]
    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_KEY}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": "image/png", "data": b64}},
                        {"text": CAPTCHA_PROMPT},
                    ]
                }
            ],
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
            log.info(f"Gemini {model} resposta vazia: {data}")
        except Exception as e:
            log.info(f"Gemini {model} erro: {e}")
    return ""


def solve_captcha_openai(img_bytes: bytes) -> str:
    """OpenAI Vision (opcional)."""
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
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64}",
                                },
                            },
                            {"type": "text", "text": CAPTCHA_PROMPT},
                        ],
                    }
                ],
            },
            timeout=30,
        )
        data = resp.json()
        if resp.status_code != 200:
            log.info(f"OpenAI HTTP {resp.status_code}: {data}")
            return ""
        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        word = _clean_word(text)
        if word:
            log.info(f"OpenAI captcha → '{word}'")
        return word
    except Exception as e:
        log.info(f"OpenAI erro: {e}")
        return ""


def solve_captcha(img_bytes: bytes) -> str:
    """Tenta Gemini → OpenAI."""
    word = solve_captcha_gemini(img_bytes)
    if word:
        return word
    word = solve_captcha_openai(img_bytes)
    if word:
        return word
    log.info("Nenhum solver de captcha conseguiu resolver (keys em falta ou API erro)")
    return ""


SERVICE_MAP = {
    "views": "Views",
    "likes": "Hearts",
    "hearts": "Hearts",
    "followers": "Followers",
    "shares": "Shares",
    "favorites": "Favorites",
}


def run_bot():
    proxy = get_proxy_config()
    if proxy:
        log.info(f"Proxy configurado: {proxy.get('server')}")
    else:
        log.info("Sem PROXY_URL — a correr sem proxy")

    if not GEMINI_KEY and not OPENAI_KEY:
        log.info("AVISO: GEMINI_API_KEY e OPENAI_API_KEY vazias — captcha não será resolvido")

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

        # ── Login loop ───────────────────────────────────────────────────────
        logged_in = False
        for attempt in range(1, 6):
            log.info(f"Tentativa de login {attempt}/5")
            try:
                page.goto(
                    "https://zefoy.com",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                log.info(f"Página carregada: {len(page.content())} chars")

                page.wait_for_function(
                    "document.getElementById('captcha-img') && "
                    "document.getElementById('captcha-img').naturalWidth > 0",
                    timeout=15000,
                )
                img_el = page.query_selector("#captcha-img")
                if not img_el:
                    log.info("Elemento #captcha-img não encontrado")
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

                body = page.content().lower()
                if "zefoy.com" in page.url and "captcha" not in body:
                    log.info("Login OK!")
                    logged_in = True
                    break
                else:
                    log.info("Login falhou — captcha errado ou página recarregou")
                    time.sleep(15)

            except Exception as e:
                log.info(f"Erro na tentativa {attempt}: {e}")
                time.sleep(15)

        if not logged_in:
            log.info("Login falhou 5x. Reiniciando em 60s...")
            time.sleep(60)
            browser.close()
            return

        # ── Loop principal do serviço ────────────────────────────────────────
        service_label = SERVICE_MAP.get(SERVICE, "Views")
        log.info(f"Serviço: {service_label} | URL: {VIDEO_URL}")

        if not VIDEO_URL:
            log.info("TIKTOK_VIDEO_URL vazia — a aguardar env var")
            time.sleep(60)
            browser.close()
            return

        service_selectors = [
            f"text={service_label}",
            f"button:has-text('{service_label}')",
            f".t-{SERVICE}-button",
            f".t-views-button" if SERVICE in ("views", "view") else None,
            f"h5:has-text('{service_label}')",
            f".card-title:has-text('{service_label}')",
            f"div:has-text('{service_label}') >> button",
        ]
        service_selectors = [s for s in service_selectors if s]

        while True:
            try:
                clicked = False
                for sel in service_selectors:
                    try:
                        page.locator(sel).first.click(timeout=5000)
                        clicked = True
                        log.info(f"Clicou serviço com seletor: {sel}")
                        break
                    except Exception:
                        continue

                if not clicked:
                    body_snip = page.inner_text("body")[:500]
                    log.info(f"Botão '{service_label}' não encontrado. Página: {body_snip}")
                    time.sleep(20)
                    continue

                time.sleep(1.5)

                url_filled = False
                for sel in [
                    "input[placeholder*='URL' i]",
                    "input[placeholder*='Enter' i]",
                    "input[type='search']",
                    "input[type='text']",
                    "form input",
                ]:
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=2000):
                            loc.fill(VIDEO_URL)
                            url_filled = True
                            break
                    except Exception:
                        continue

                if not url_filled:
                    log.info("Campo de URL não encontrado")
                    time.sleep(15)
                    continue

                time.sleep(0.5)

                for sel in [
                    "button[type='submit']",
                    "form button",
                    ".btn-primary",
                    ".btn-dark",
                    "button:has-text('Search')",
                    "button:has-text('Submit')",
                ]:
                    try:
                        page.locator(sel).first.click(timeout=3000)
                        break
                    except Exception:
                        continue

                time.sleep(3)
                result = page.inner_text("body")

                if re.search(r"please wait|seconds?", result, re.I):
                    wait_match = re.search(r"(\d+)\s*second", result, re.I)
                    wait_sec = int(wait_match.group(1)) if wait_match else 60
                    log.info(f"Aguardando {wait_sec}s para próxima tentativa...")
                    time.sleep(wait_sec + 5)
                elif re.search(r"successfully|sent", result, re.I):
                    log.info("Sucesso! Próxima rodada em 30s")
                    time.sleep(30)
                else:
                    log.info(f"Resposta: {result[:300]}")
                    time.sleep(30)

            except Exception as e:
                log.info(f"Erro no loop principal: {e}")
                time.sleep(30)

        browser.close()


# ── Main ─────────────────────────────────────────────────────────────────────
while True:
    try:
        run_bot()
    except Exception as e:
        log.info(f"Crash: {e} — reiniciando em 60s")
        time.sleep(60)
