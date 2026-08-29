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

VIDEO_URL   = os.environ.get("TIKTOK_VIDEO_URL", "")
SERVICE     = os.environ.get("TIKTOK_SERVICE", "Views").lower()
PROXY_URL   = os.environ.get("PROXY_URL", "")
GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "")
OPENAI_KEY  = os.environ.get("OPENAI_API_KEY", "")
PORT        = int(os.environ.get("PORT", 8080))


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


def keep_alive_ping():
    """Faz self-ping a cada 20s para evitar 'slept due to inactivity'."""
    import requests as req
    time.sleep(10)
    while True:
        try:
            req.get(f"http://localhost:{PORT}/ping", timeout=5)
        except Exception:
            pass
        time.sleep(20)


threading.Thread(target=keep_alive_ping, daemon=True).start()

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
            "contents": [{"parts": [
                {"inline_data": {"mime_type": "image/png", "data": b64}},
                {"text": CAPTCHA_PROMPT},
            ]}],
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
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": CAPTCHA_PROMPT},
                ]}],
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
    "views":     "Views",
    "likes":     "Hearts",
    "hearts":    "Hearts",
    "followers": "Followers",
    "shares":    "Shares",
    "favorites": "Favorites",
}

SERVICE_CSS = {
    "views":     ".t-views-button",
    "likes":     ".t-hearts-button",
    "hearts":    ".t-hearts-button",
    "followers": ".t-followers-button",
    "shares":    ".t-shares-button",
    "favorites": ".t-favorites-button",
}

# XPaths absolutos do zefoy (fallback robusto)
# div[7] = favorites, div[5] = views, div[3] = hearts, etc.
SERVICE_DIV = {
    "followers": "6",
    "hearts":    "7",
    "likes":     "7",
    "views":     "9",
    "shares":    "10",
    "favorites": "11",
}


def get_active_container(page):
    """
    Retorna o locator do container do serviço activo (o que não tem classe 'nonec').
    Este é o painel que o zefoy abre após clicar no botão do serviço.
    """
    return page.locator("div.col-sm-5.col-xs-12.p-1.container:not(.nonec)").first


def click_service_button(page, service_label: str, css_btn: str) -> bool:
    """Tenta abrir o painel do serviço. Cascata de seletores + JS fallback."""
    selectors = []
    if css_btn:
        selectors.append(css_btn)
    selectors += [
        f"button:has-text('{service_label}')",
        f".btn:has-text('{service_label}')",
        f"div.card:has-text('{service_label}') button",
        f"h5:has-text('{service_label}') >> xpath=../..//button",
        f"text={service_label}",
    ]

    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=4000)
            log.info(f"Clicou serviço: {sel}")
            return True
        except Exception:
            continue

    # JS fallback
    try:
        page.evaluate(f"""
            const els = Array.from(document.querySelectorAll('button, .btn, a'));
            const target = els.find(e => e.textContent.trim().includes('{service_label}'));
            if (target) target.click();
        """)
        log.info(f"Clicou serviço via JS: {service_label}")
        return True
    except Exception as e:
        log.info(f"JS click falhou: {e}")

    return False


def parse_timer(text: str) -> int:
    """
    Extrai segundos totais do timer do zefoy.
    Formatos possíveis:
      "Please wait 0 minute(s) 24 second(s) for your next submit"
      "Please wait 24 seconds"
      "Aguardando 24s"
    Retorna 0 se não encontrar.
    """
    if not re.search(r"please wait|seconds?", text, re.I):
        return 0

    # Formato com minutos e segundos: "X minute(s) Y second(s)"
    m = re.search(r"(\d+)\s*minute[s(]*\)?.*?(\d+)\s*second", text, re.I)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    # Só segundos: "Y second(s)"
    m = re.search(r"(\d+)\s*second", text, re.I)
    if m:
        return int(m.group(1))

    return 0


def get_timer_from_page(page) -> int:
    """Lê o timer do span.br ou do body."""
    try:
        # Tentar span.br primeiro (mais preciso)
        spans = page.locator("span.br").all()
        for span in spans:
            try:
                t = span.inner_text(timeout=500)
                secs = parse_timer(t)
                if secs > 0:
                    return secs
            except Exception:
                continue
    except Exception:
        pass

    # Fallback: body completo
    try:
        body = page.inner_text("body")
        return parse_timer(body)
    except Exception:
        return 0


def run_service_cycle(page, service_label: str, video_url: str, service_key: str = "") -> bool:
    """
    Executa um ciclo completo do serviço:
      1. Preenche URL no input do container activo
      2. Clica btn-primary (Search/Verificar)
      3. Aguarda 3s
      4. Clica btn-dark (Send/Submit real)
    Retorna True se o ciclo completou sem erro.
    """
    time.sleep(1.5)

    # Container activo (o painel aberto pelo clique no serviço)
    container = get_active_container(page)

    # --- Passo 1: preencher URL ---
    url_filled = False
    try:
        page.wait_for_selector(
            "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) input",
            timeout=6000,
        )
        inp = container.locator("input").first
        inp.click(timeout=3000)
        inp.fill(video_url)
        url_filled = True
        log.info("URL preenchida no container activo")
    except Exception:
        pass

    # Fallback: input visível com placeholder
    if not url_filled:
        try:
            page.wait_for_selector("input[placeholder*='Enter Video']:visible", timeout=5000)
            loc = page.locator("input[placeholder*='Enter Video']:visible").first
            loc.click()
            loc.fill(video_url)
            url_filled = True
            log.info("URL preenchida (input visível)")
        except Exception:
            pass

    # Fallback force
    if not url_filled:
        try:
            locs = page.locator(
                "input[placeholder*='Enter Video'], "
                "input[placeholder*='Enter Video/Username'], "
                "input.form-control[type='search']"
            )
            n = locs.count()
            log.info(f"Force fill em {n} inputs")
            for i in range(n):
                try:
                    locs.nth(i).fill(video_url, force=True)
                    url_filled = True
                except Exception:
                    continue
            if url_filled:
                log.info("URL preenchida com force=True")
        except Exception as e:
            log.info(f"Force fill falhou: {e}")

    if not url_filled:
        log.info("Não foi possível preencher a URL")
        return False

    time.sleep(0.5)

    # --- Passo 2: btn-primary (Search) ---
    searched = False
    search_sels = [
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button.btn.btn-primary",
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button[type='submit']",
        "form:visible button.btn-primary",
        "form:visible button[type='submit']",
        "button.btn-primary:visible",
        "button[type='submit']:visible",
        "button.btn-primary",
        "button[type='submit']",
    ]
    for sel in search_sels:
        try:
            page.locator(sel).first.click(timeout=3000, force=True)
            log.info(f"Search (btn-primary): {sel}")
            searched = True
            break
        except Exception:
            continue

    if not searched:
        try:
            page.locator("input[placeholder*='Enter Video']").first.press("Enter", force=True)
            log.info("Search via Enter")
            searched = True
        except Exception:
            log.info("Search falhou")
            return False

    # Aguardar AJAX do zefoy processar o Search (o btn-dark só fica válido após isso)
    # O zefoy faz request interno após o Search — aguardar network idle
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        time.sleep(4)  # fallback se timeout

    # Verificar se há timer já aqui (rate limit antes do send)
    pre_timer = get_timer_from_page(page)
    if pre_timer > 0:
        log.info(f"Rate limit antes do send: {pre_timer}s")
        return None  # sinaliza "aguardar" sem contar como falha

    # Aguardar o btn-dark aparecer/ficar ativo no container
    try:
        page.wait_for_selector(
            "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button.btn.btn-dark",
            timeout=6000,
            state="visible",
        )
        log.info("btn-dark visível — pronto para Send")
    except Exception:
        log.info("btn-dark wait timeout — tentando na mesma")

    # --- Passo 2.5: select de quantidade (apenas Favorites) ---
    if service_key in {"favorites"}:
        try:
            container = get_active_container(page)
            sel_loc = container.locator("select")
            if sel_loc.count() > 0:
                sel_loc.first.select_option("25")
                log.info("Select limit = 25")
            else:
                all_sel = page.locator("select:visible")
                if all_sel.count() > 0:
                    all_sel.first.select_option("25")
                    log.info("Select limit = 25 (fallback)")
            time.sleep(0.5)
        except Exception as e:
            log.info(f"Select limit erro: {e}")

    # --- Passo 3: btn-dark (Send — o submit real) ---
    sent = False
    send_sels = [
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button.btn.btn-dark",
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button.btn-dark",
        "form:visible button.btn-dark",
        "button.btn-dark:visible",
        ".btn-dark:visible",
        "button.btn-dark",
        ".btn-dark",
    ]
    for sel in send_sels:
        try:
            page.locator(sel).first.click(timeout=3000, force=True)
            log.info(f"Send (btn-dark): {sel}")
            sent = True
            break
        except Exception:
            continue

    if not sent:
        # btn-dark pode não existir ainda; verificar body
        body = page.inner_text("body")
        if re.search(r"successfully|sent|success", body, re.I):
            log.info("Sucesso directo (sem btn-dark)")
            sent = True
        else:
            snippet = body[:200].replace("\n", " ")
            log.info(f"btn-dark não encontrado. Body: {snippet}")
            # Não é falha fatal — pode ser que o zefoy mostre timer logo após search
            return None

    time.sleep(3)
    return True


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

        # ── Login ─────────────────────────────────────────────────────────────
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

                content = page.content().lower()
                if "zefoy.com" in page.url and "captcha" not in content:
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
        css_btn       = SERVICE_CSS.get(SERVICE)
        log.info(f"Serviço: {service_label} | URL: {VIDEO_URL}")

        if not VIDEO_URL:
            log.info("TIKTOK_VIDEO_URL vazia — abortando")
            time.sleep(60)
            browser.close()
            return

        # ── Loop principal ────────────────────────────────────────────────────
        consecutive_failures = 0
        MAX_FAILURES = 5

        while True:
            try:
                # Recarregar após muitas falhas (sessão pode ter expirado)
                if consecutive_failures >= MAX_FAILURES:
                    log.info("Muitas falhas — recarregando zefoy.com...")
                    page.goto("https://zefoy.com", wait_until="domcontentloaded", timeout=60000)
                    time.sleep(3)
                    if "captcha" in page.content().lower():
                        log.info("Sessão expirou — reiniciando bot completo")
                        browser.close()
                        return
                    consecutive_failures = 0

                # 1) Clicar botão do serviço para abrir o painel
                if not click_service_button(page, service_label, css_btn):
                    log.info(f"Botão '{service_label}' não encontrado")
                    consecutive_failures += 1
                    time.sleep(20)
                    continue

                consecutive_failures = 0

                # 2) Preencher URL → Search → Send
                result = run_service_cycle(page, service_label, VIDEO_URL, service_key=SERVICE)

                # 3) Ler timer e aguardar
                time.sleep(1)
                wait_sec = get_timer_from_page(page)

                if wait_sec > 0:
                    log.info(f"Aguardando {wait_sec}s (cooldown zefoy)...")
                    # Monitorar countdown ativo
                    deadline = time.time() + wait_sec + 6
                    while time.time() < deadline:
                        time.sleep(5)
                        remaining = int(deadline - time.time())
                        if remaining <= 0:
                            break
                        current_timer = get_timer_from_page(page)
                        if current_timer == 0:
                            log.info("Timer expirou — próxima rodada")
                            break
                        log.info(f"Cooldown: {current_timer}s restantes")

                elif result is True:
                    # Sem timer → sucesso imediato
                    body = page.inner_text("body")
                    if re.search(r"successfully|sent|success", body, re.I):
                        log.info("Sucesso confirmado! Próxima em 30s")
                    else:
                        log.info("Enviado (sem timer). Próxima em 30s")
                    time.sleep(30)

                else:
                    # result é None ou False
                    log.info("Ciclo incompleto — retry em 20s")
                    consecutive_failures += 1
                    time.sleep(20)

            except Exception as e:
                log.info(f"Erro no loop: {e}")
                consecutive_failures += 1
                time.sleep(30)

        browser.close()


while True:
    try:
        run_bot()
    except Exception as e:
        log.info(f"Crash: {e} — reinício em 60s")
        time.sleep(60)
