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
    """
    Self-ping a cada 25s para evitar 'slept due to inactivity' no SnapDeploy/Back4App.
    Tenta primeiro localhost; se falhar, usa a URL pública via env RENDER_EXTERNAL_URL.
    """
    import requests as req
    public_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    time.sleep(15)
    while True:
        try:
            req.get(f"http://localhost:{PORT}/", timeout=5)
        except Exception:
            pass
        if public_url:
            try:
                req.get(public_url, timeout=8)
            except Exception:
                pass
        time.sleep(25)


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
    Flow correto do zefoy:
      1. Preencher URL
      2. Click Search (btn-primary) — dispara AJAX que valida URL e devolve o count
      3. Esperar response HTTP do AJAX (page.expect_response)
      4. Se timer → return None
      5. Select quantidade se Favorites
      6. Click Send (btn-dark) — submete de facto
    """
    time.sleep(1.5)

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
        inp.triple_click(timeout=3000)   # selecionar texto existente
        inp.fill(video_url)
        url_filled = True
        log.info("URL preenchida no container activo")
    except Exception:
        pass

    if not url_filled:
        try:
            page.wait_for_selector("input[placeholder*=\'Enter Video\']:visible", timeout=5000)
            loc = page.locator("input[placeholder*=\'Enter Video\']:visible").first
            loc.click()
            loc.fill(video_url)
            url_filled = True
            log.info("URL preenchida (input visível)")
        except Exception:
            pass

    if not url_filled:
        try:
            locs = page.locator(
                "input[placeholder*=\'Enter Video\'], "
                "input[placeholder*=\'Enter Video/Username\'], "
                "input.form-control[type=\'search\']"
            )
            n = locs.count()
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

    time.sleep(0.3)

    # --- Passo 2: Search (btn-primary) + aguardar AJAX via expect_response ---
    search_sels = [
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button.btn.btn-primary",
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button[type=\'submit\']",
        "form:visible button.btn-primary",
        "button.btn-primary:visible",
        "button.btn-primary",
        "button[type=\'submit\']",
    ]

    searched = False
    ajax_response_text = ""

    for sel in search_sels:
        try:
            # Interceptar a response do AJAX que o zefoy dispara após o Search
            with page.expect_response(
                lambda r: "zefoy.com" in r.url and r.request.method == "POST",
                timeout=10000,
            ) as resp_info:
                page.locator(sel).first.click(timeout=3000, force=True)
                log.info(f"Search clicado: {sel}")
            response = resp_info.value
            ajax_response_text = response.text()
            log.info(f"AJAX Search response ({response.status}): {ajax_response_text[:120]}")
            searched = True
            break
        except Exception:
            # Se expect_response falhar (sem AJAX), ainda contar como clicado
            try:
                page.locator(sel).first.click(timeout=2000, force=True)
                log.info(f"Search sem AJAX intercept: {sel}")
                searched = True
                time.sleep(4)  # wait manual
                break
            except Exception:
                continue

    if not searched:
        try:
            page.locator("input[placeholder*=\'Enter Video\']").first.press("Enter", force=True)
            log.info("Search via Enter")
            searched = True
            time.sleep(4)
        except Exception:
            log.info("Search falhou")
            return False

    # --- Verificar timer na response AJAX ou na página ---
    pre_timer = 0
    if ajax_response_text:
        pre_timer = parse_timer(ajax_response_text)
    if pre_timer == 0:
        pre_timer = get_timer_from_page(page)

    if pre_timer > 0:
        log.info(f"Rate limit: {pre_timer}s")
        return None

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

    # --- Passo 3: Send (btn-dark) + aguardar AJAX de confirmação ---
    send_sels = [
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button.btn.btn-dark",
        "div.col-sm-5.col-xs-12.p-1.container:not(.nonec) button.btn-dark",
        "form:visible button.btn-dark",
        "button.btn-dark:visible",
        ".btn-dark:visible",
        "button.btn-dark",
        ".btn-dark",
    ]

    sent = False
    send_response_text = ""

    for sel in send_sels:
        try:
            with page.expect_response(
                lambda r: "zefoy.com" in r.url and r.request.method == "POST",
                timeout=10000,
            ) as resp_info:
                page.locator(sel).first.click(timeout=3000, force=True)
                log.info(f"Send clicado: {sel}")
            response = resp_info.value
            send_response_text = response.text()
            log.info(f"AJAX Send response ({response.status}): {send_response_text[:120]}")
            sent = True
            break
        except Exception:
            try:
                page.locator(sel).first.click(timeout=2000, force=True)
                log.info(f"Send sem AJAX intercept: {sel}")
                sent = True
                time.sleep(3)
                break
            except Exception:
                continue

    if not sent:
        body = page.inner_text("body")
        if re.search(r"successfully|sent|success", body, re.I):
            log.info("Sucesso directo (sem btn-dark)")
            sent = True
        else:
            snippet = body[:200].replace("\n", " ")
            log.info(f"btn-dark não encontrado. Body: {snippet}")
            return None

    # Confirmar resultado pelo texto da response
    if send_response_text:
        if re.search(r"successfully|success|sent|ok", send_response_text, re.I):
            log.info("Confirmado pelo servidor — sucesso!")
        elif re.search(r"please wait|wait|timer", send_response_text, re.I):
            log.info(f"Servidor devolveu timer: {send_response_text[:80]}")
        else:
            log.info(f"Resposta do servidor: {send_response_text[:80]}")

    time.sleep(2)
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
