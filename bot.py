import os
import sys
import re
import threading
import base64
from io           import BytesIO
from base64       import b64decode
from time         import sleep, time
from datetime     import datetime
from urllib.parse import unquote, urlparse

import requests
from requests.auth import HTTPProxyAuth
from colorama import Fore, init; init()

# ---------------------------------------------------------------------------
# Config via env vars
# ---------------------------------------------------------------------------
TIKTOK_URL = os.environ.get("TIKTOK_VIDEO_URL", "").strip()
SERVICE    = os.environ.get("TIKTOK_SERVICE", "Views").strip()
HEADLESS   = not sys.stdin.isatty() or bool(os.environ.get("RENDER"))
PROXY_RAW  = os.environ.get("PROXY_URL", "").strip()

if not TIKTOK_URL:
    print("[!] ERRO: defina TIKTOK_VIDEO_URL nas env vars")
    sys.exit(1)

BASE_URL = "https://zefoy.com/"
HEADERS  = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/112.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Proxy
# ---------------------------------------------------------------------------
_proxy_list  = [p.strip() for p in PROXY_RAW.split(",") if p.strip()] if PROXY_RAW else []
_proxy_index = 0

def next_proxy() -> str | None:
    global _proxy_index
    if not _proxy_list:
        return None
    p = _proxy_list[_proxy_index % len(_proxy_list)]
    _proxy_index += 1
    return p

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{Fore.CYAN}{ts} {Fore.BLUE}INFO {Fore.MAGENTA}bot -> {Fore.RESET}{msg}", flush=True)

def decode(text) -> str:
    try:
        if isinstance(text, str):
            text = text.encode()
        return b64decode(unquote(text[::-1])).decode()
    except Exception:
        return text if isinstance(text, str) else text.decode(errors="replace")

def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)

    proxy_url = next_proxy()
    if proxy_url:
        parsed = urlparse(proxy_url)
        host_port = f"{parsed.hostname}:{parsed.port}"
        log(f"Usando proxy: {host_port}")

        # Passa proxy nas duas formas: via proxies dict E via HTTPProxyAuth
        # O requests tem um bug conhecido onde credenciais no URL não são
        # enviadas no header CONNECT para túneis HTTPS — HTTPProxyAuth resolve isso
        s.proxies.update({"http": proxy_url, "https": proxy_url})
        if parsed.username and parsed.password:
            s.auth = HTTPProxyAuth(parsed.username, parsed.password)
    else:
        log("AVISO: sem proxy — IP do Render provavelmente bloqueado pelo zefoy")

    return s

# ---------------------------------------------------------------------------
# Captcha API
# ---------------------------------------------------------------------------
CAPTCHA_API = "https://plowsidecaptcha.pythonanywhere.com/captcha"

def solve_captcha_api(image_bytes: bytes) -> str:
    try:
        resp = requests.post(
            CAPTCHA_API,
            files={"file": ("captcha.png", image_bytes, "image/png")},
            timeout=30,
        )
        text = resp.json().get("captcha_text", "").strip().lower()
        log(f"Captcha API: '{text}'")
        return text
    except Exception as e:
        log(f"Captcha API falhou: {e}")
        return ""

def get_captcha(session: requests.Session) -> dict:
    log("Carregando zefoy.com...")
    try:
        resp = session.get(BASE_URL, timeout=30)
        log(f"HTTP {resp.status_code} | {len(resp.content)} bytes")
    except Exception as e:
        log(f"Erro ao carregar zefoy: {e}")
        return {}

    html = resp.text

    if "Enter Video URL" in html:
        video_key = html.split('" placeholder="Enter Video URL"')[0].split('name="')[-1]
        log(f"Sessao ja ativa! video_key={video_key}")
        return {"already_logged": True, "video_key": video_key}

    if "<title>Just a moment...</title>" in html:
        log("Cloudflare challenge — aguardando 60s")
        sleep(60)
        return {}

    log(f"HTML[0:600]: {repr(html[:600])}")

    # Debug: mostra todos os inputs, imgs e forms para diagnosticar estrutura do captcha
    all_inputs = re.findall(r'<input[^>]+>', html)
    log(f"inputs encontrados: {all_inputs[:10]}")
    all_imgs = re.findall(r'<img[^>]+>', html)
    log(f"imgs encontradas: {all_imgs[:5]}")
    all_forms = re.findall(r'<form[^>]+>', html)
    log(f"forms encontrados: {all_forms[:5]}")

    captcha_fields = {}
    for name, value in re.findall(r'<input type="hidden" name="(.*?)" value="(.*?)">', html):
        captcha_fields[name] = value
    log(f"hidden fields: {captcha_fields}")

    text_field = re.findall(r'type="text" name="(.*?)" oninput="this\.value=this\.value\.toLowerCase\(\)"', html)
    if not text_field:
        text_field = re.findall(r'type="text"[^>]+name="([^"]+)"', html)
    log(f"text field: {text_field}")

    img_match = re.findall(r'<img src="(.*?)" onerror="imgOnError\(\)"', html)
    if not img_match:
        img_match = re.findall(r'<img[^>]+src="(/[^"]+\.(?:png|jpg|gif))"', html)
    log(f"img src: {img_match}")

    if not captcha_fields or not text_field or not img_match:
        log("Estrutura HTML nao reconhecida")
        return {}

    captcha_url = img_match[0]
    if not captcha_url.startswith("http"):
        captcha_url = "https://zefoy.com" + captcha_url

    try:
        img_bytes = session.get(captcha_url, timeout=15).content
        log(f"Imagem captcha: {len(img_bytes)} bytes")
    except Exception as e:
        log(f"Erro ao baixar imagem: {e}")
        return {}

    return {
        "already_logged"    : False,
        "captcha_fields"    : captcha_fields,
        "captcha_text_field": text_field[0],
        "captcha_image"     : img_bytes,
    }

def login(session: requests.Session) -> str | None:
    data = get_captcha(session)
    if not data:
        return None
    if data.get("already_logged"):
        return data["video_key"]

    answer = solve_captcha_api(data["captcha_image"])
    if not answer:
        log("Captcha nao resolvido")
        return None

    payload = dict(data["captcha_fields"])
    payload[data["captcha_text_field"]] = answer
    log(f"Enviando captcha: {payload}")

    try:
        resp = session.post(BASE_URL, data=payload, timeout=30)
        log(f"POST captcha: HTTP {resp.status_code} | {len(resp.content)} bytes")
        log(f"POST HTML[0:400]: {repr(resp.text[:400])}")
    except Exception as e:
        log(f"Erro POST captcha: {e}")
        return None

    if "Enter Video URL" in resp.text:
        video_key = resp.text.split('" placeholder="Enter Video URL"')[0].split('name="')[-1]
        log(f"Login OK! video_key={video_key}")
        return video_key

    log("Login falhou — resposta nao contem video URL field")
    return None

# ---------------------------------------------------------------------------
# Servicos
# ---------------------------------------------------------------------------
def get_services(session: requests.Session) -> dict:
    try:
        html = session.get(BASE_URL, timeout=30).text
        services = {}
        for name, ep in re.findall(r'<h5 class="card-title mb-3">(.*?)</h5>\s*<form action="(.*?)">', html):
            services[name.strip()] = ep.strip()
        log(f"Servicos: {list(services.keys())}")
        return services
    except Exception as e:
        log(f"Erro ao obter servicos: {e}")
        return {}

# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------
def find_and_send(session: requests.Session, video_key: str, endpoint: str) -> str:
    try:
        resp = session.post(
            BASE_URL + endpoint,
            files={video_key: (None, TIKTOK_URL)},
            timeout=30,
        )
        video_info = decode(resp.text)
    except Exception as e:
        log(f"Erro no find_video: {e}")
        return "error"

    if "Session expired" in video_info:
        log("Sessao expirada")
        return "session_expired"

    if "service is currently not working" in video_info:
        log("Servico offline no zefoy")
        return "service_offline"

    if "Too many requests" in video_info:
        log("Too many requests — aguardando 30s")
        sleep(30)
        return "rate_limit"

    if "error occurred" in video_info.lower():
        log(f"Erro do zefoy (bloqueio de IP?): {video_info[:200]}")
        sleep(120)
        return "ip_blocked"

    if 'onsubmit="showHideElements"' in video_info:
        try:
            token    = video_info.split('" name="')[1].split('"')[0]
            aweme_id = video_info.split('value="')[1].split('"')[0]
            log(f"Enviando: aweme_id={aweme_id} token={token}")
        except Exception as e:
            log(f"Erro ao parsear video_info: {e} | {video_info[:300]}")
            return "parse_error"

        sleep(3)

        try:
            resp2 = session.post(
                BASE_URL + endpoint,
                files={token: (None, aweme_id)},
                timeout=30,
            )
            result = decode(resp2.text)

            if "error occurred" in result.lower():
                log(f"Bloqueio no segundo POST: {result[:200]}")
                sleep(120)
                return "ip_blocked"

            if "color:green;" in result or "sent" in result.lower():
                msg = result.split("color:green;'>")[-1].split("</")[0].strip() if "color:green;" in result else "enviado"
                log(f"OK: {msg}")
            else:
                log(f"Resposta send: {result[:200]}")
            return "ok"
        except Exception as e:
            log(f"Erro no send: {e}")
            return "error"

    timer_match = re.findall(r"ltm=(\d+);", video_info)
    if timer_match:
        wait = int(timer_match[0])
        if wait >= 1000:
            log("IP banido pelo zefoy")
            return "banned"
        if wait > 0:
            log(f"Cooldown: {wait}s")
            start = time()
            while time() < start + wait:
                remaining = round((start + wait) - time())
                print(f"\r{Fore.YELLOW}[~] aguardando {remaining}s...{Fore.RESET}   ", end="", flush=True)
                sleep(1)
            print()
        return "cooldown_done"

    log(f"Resposta inesperada: {video_info[:300]}")
    return "unknown"

# ---------------------------------------------------------------------------
# Health-check HTTP server para Render free tier
# ---------------------------------------------------------------------------
def start_http_server():
    import http.server
    port = int(os.environ.get("PORT", 10000))
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("0.0.0.0", port), H)
    log(f"HTTP health-check em :{port}")
    srv.serve_forever()

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    threading.Thread(target=start_http_server, daemon=True).start()

    if not _proxy_list:
        log("AVISO: PROXY_URL nao definida. IPs de datacenter sao bloqueados pelo zefoy.")

    log(f"TikTok ViewBot | URL: {TIKTOK_URL} | Servico: {SERVICE}")

    while True:
        session   = new_session()
        video_key = None

        for attempt in range(1, 6):
            log(f"Tentativa de login {attempt}/5")
            video_key = login(session)
            if video_key:
                break
            sleep(15)

        if not video_key:
            log("Login falhou 5x. Reiniciando em 60s...")
            sleep(60)
            continue

        services = get_services(session)
        endpoint = None
        for name, ep in services.items():
            if SERVICE.lower() in name.lower():
                endpoint = ep.lstrip("/")
                log(f"Endpoint: {name} -> {endpoint}")
                break

        if not endpoint:
            log(f"Servico '{SERVICE}' nao encontrado. Disponiveis: {list(services.keys())}")
            sleep(30)
            continue

        log("Sessao ativa. Loop de envio iniciado...")
        consecutive_errors = 0

        while consecutive_errors < 5:
            result = find_and_send(session, video_key, endpoint)

            if result == "session_expired":
                log("Sessao expirada — refazendo login")
                break
            elif result == "banned":
                log("IP banido — aguardando 5min")
                sleep(300)
                break
            elif result == "ip_blocked":
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    log("Bloqueio persistente — reiniciando sessao")
                    break
            elif result in ("ok", "cooldown_done", "rate_limit", "service_offline"):
                consecutive_errors = 0
                sleep(5)
            else:
                consecutive_errors += 1
                sleep(10)

        log("Reiniciando sessao...")
        sleep(5)

if __name__ == "__main__":
    main()
