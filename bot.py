import os, time, base64, threading, logging, re
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s INFO bot -> %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("bot")

VIDEO_URL    = os.environ.get("TIKTOK_VIDEO_URL", "")
SERVICE      = os.environ.get("TIKTOK_SERVICE", "Views").lower()
PROXY_URL    = os.environ.get("PROXY_URL", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PORT         = int(os.environ.get("PORT", 8080))

# ── HTTP keep-alive ──────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a): pass

def start_http():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

threading.Thread(target=start_http, daemon=True).start()

# ── Playwright setup ─────────────────────────────────────────────────────────
from playwright.sync_api import sync_playwright

def get_proxy_config():
    if not PROXY_URL:
        return None
    # http://user:pass@host:port
    m = re.match(r"http://([^:]+):([^@]+)@([^:]+):(\d+)", PROXY_URL)
    if m:
        return {
            "server": f"http://{m.group(3)}:{m.group(4)}",
            "username": m.group(1),
            "password": m.group(2),
        }
    return {"server": PROXY_URL}

def solve_captcha_claude(img_bytes: bytes) -> str:
    """Envia imagem para Claude Vision e extrai a palavra do captcha."""
    import requests as req
    b64 = base64.b64encode(img_bytes).decode()
    resp = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 20,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": "What single word is shown in this captcha image? Reply with only the word in lowercase, no punctuation."}
                ]
            }]
        },
        timeout=15
    )
    data = resp.json()
    word = data["content"][0]["text"].strip().lower()
    word = re.sub(r"[^a-z]", "", word)
    log.info(f"Claude captcha solver → '{word}'")
    return word

SERVICE_MAP = {
    "views":     "Video Views",
    "likes":     "Video Likes",
    "followers": "Followers",
    "shares":    "Video Shares",
    "favorites": "Video Favorites",
}

def run_bot():
    proxy = get_proxy_config()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=proxy,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
        )
        page = context.new_page()

        # ── Login loop ───────────────────────────────────────────────────────
        logged_in = False
        for attempt in range(1, 6):
            log.info(f"Tentativa de login {attempt}/5")
            try:
                page.goto("https://zefoy.com", wait_until="networkidle", timeout=30000)
                log.info(f"Página carregada: {len(page.content())} chars")

                # Esperar a imagem do captcha ser carregada pelo JS
                page.wait_for_function(
                    "document.getElementById('captcha-img') && document.getElementById('captcha-img').naturalWidth > 0",
                    timeout=10000
                )
                img_el = page.query_selector("#captcha-img")
                img_bytes = img_el.screenshot()
                log.info(f"Captcha screenshot: {len(img_bytes)} bytes")

                if not ANTHROPIC_KEY:
                    log.info("ANTHROPIC_API_KEY não configurada — captcha não pode ser resolvido")
                    time.sleep(15)
                    continue

                word = solve_captcha_claude(img_bytes)
                if not word:
                    log.info("Captcha não resolvido (resposta vazia)")
                    time.sleep(15)
                    continue

                # Preencher e submeter
                page.fill("input[name='captchalogin']", word)
                page.click("button[type='submit'], .btn-primary")
                time.sleep(3)

                # Verificar login
                if "zefoy.com" in page.url and "captcha" not in page.content().lower():
                    log.info("Login OK!")
                    logged_in = True
                    break
                else:
                    log.info("Login falhou — captcha errado ou recarregou")
                    time.sleep(15)

            except Exception as e:
                log.info(f"Erro na tentativa {attempt}: {e}")
                time.sleep(15)

        if not logged_in:
            log.info("Login falhou 5x. Reiniciando em 60s...")
            time.sleep(60)
            browser.close()
            return

        # ── Serviço principal ────────────────────────────────────────────────
        service_label = SERVICE_MAP.get(SERVICE, "Video Views")
        log.info(f"Serviço: {service_label} | URL: {VIDEO_URL}")

        while True:
            try:
                # Clicar no botão do serviço
                page.click(f"text={service_label}", timeout=5000)
                time.sleep(1)
                page.fill("input[type='text'], input[type='search']", VIDEO_URL)
                page.click("button[type='submit'], .btn-dark, .btn-primary")
                time.sleep(3)

                result = page.inner_text("body")
                if "Please wait" in result or "seconds" in result:
                    wait_match = re.search(r"(\d+)\s*second", result)
                    wait_sec = int(wait_match.group(1)) if wait_match else 60
                    log.info(f"Aguardando {wait_sec}s para próxima tentativa...")
                    time.sleep(wait_sec + 5)
                elif "successfully" in result.lower():
                    log.info("Sucesso! Próxima rodada em 30s")
                    time.sleep(30)
                else:
                    log.info(f"Resposta: {result[:200]}")
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
