import os
import sys
import re
from io           import BytesIO
from base64       import b64decode
from random       import choices
from string       import ascii_letters, digits
from time         import sleep, time
from datetime     import datetime
from urllib.parse import unquote, quote

import requests
from PIL      import Image, ImageFilter, ImageOps
from colorama import Fore, init; init()

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config via env vars
# ---------------------------------------------------------------------------
TIKTOK_URL   = os.environ.get("TIKTOK_VIDEO_URL", "").strip()
SERVICE      = os.environ.get("TIKTOK_SERVICE", "views").strip().lower()
HEADLESS     = not sys.stdin.isatty() or bool(os.environ.get("RENDER"))

if not TIKTOK_URL:
    print("[!] ERRO: defina TIKTOK_VIDEO_URL nas env vars")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{Fore.CYAN}{ts} {Fore.BLUE}INFO {Fore.MAGENTA}bot -> {Fore.RESET}{msg}", flush=True)

def decode(text: str) -> str:
    try:
        return b64decode(unquote(text[::-1])).decode()
    except Exception:
        return text

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
def get_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "authority"             : "zefoy.com",
        "origin"                : "https://zefoy.com",
        "cp-extension-installed": "Yes",
        "user-agent"            : (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    })
    return s

# ---------------------------------------------------------------------------
# OCR captcha solver
# ---------------------------------------------------------------------------
def preprocess_image(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    img = ImageOps.autocontrast(img, cutoff=5)
    img = img.filter(ImageFilter.SHARPEN)
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    return img

def ocr_solve(image_bytes: bytes) -> str:
    img = Image.open(BytesIO(image_bytes))
    img = preprocess_image(img)
    config = "--psm 7 -c tessedit_char_whitelist=0123456789+-x*= "
    raw = pytesseract.image_to_string(img, config=config).strip()
    log(f"OCR raw: '{raw}'")
    expr = re.sub(r"[^0-9+\-*/]", "", raw.split("=")[0])
    try:
        result = str(int(eval(expr)))
        log(f"OCR resultado: {result}")
        return result
    except Exception:
        log(f"OCR falhou em avaliar '{expr}' — usando fallback '0'")
        return "0"

def manual_solve(image_bytes: bytes) -> str:
    img = Image.open(BytesIO(image_bytes))
    img.show()
    return input("[~] Resolva o captcha: ").strip()

# ---------------------------------------------------------------------------
# Captcha
# ---------------------------------------------------------------------------
def solve_captcha(client: requests.Session):
    log("Carregando zefoy.com...")
    try:
        resp = client.get("https://zefoy.com", timeout=30)
        log(f"HTTP {resp.status_code} | {len(resp.content)} bytes")
    except Exception as e:
        log(f"Erro ao carregar zefoy: {e}")
        return None

    html = resp.text.replace("&amp;", "&")

    # Debug: loga snippet do HTML para diagnóstico de mudanças no zefoy
    log(f"HTML[0:600]: {repr(html[:600])}")

    # Bloqueio Cloudflare / rate limit
    if resp.status_code in (403, 429, 503) or "Just a moment" in html or "cf-wrapper" in html:
        log(f"Cloudflare/WAF bloqueou (HTTP {resp.status_code}) — aguardando 60s")
        sleep(60)
        return None

    # Regex flexíveis para cobrir variações do HTML do zefoy
    hidden_matches = re.findall(
        r'<input[^>]+type=["\']hidden["\'][^>]+name=["\']([^"\']+)["\']', html
    )
    # fallback para ordem inversa de atributos
    if not hidden_matches:
        hidden_matches = re.findall(r'<input type="hidden" name="([^"]+)"', html)

    img_matches = re.findall(
        r'<img[^>]+src=["\']([^"\']*captcha[^"\']*)["\']', html, re.IGNORECASE
    )
    if not img_matches:
        img_matches = re.findall(r'img src="(/[^"]+\.(png|jpg|gif))"', html)
        img_matches = [m[0] for m in img_matches]

    text_input_matches = re.findall(
        r'<input[^>]+type=["\']text["\'][^>]+name=["\']([^"\']+)["\']', html
    )
    if not text_input_matches:
        text_input_matches = re.findall(
            r'type="text"[^>]+name="([^"]+)"', html
        )

    log(f"hidden_inputs encontrados: {hidden_matches}")
    log(f"img_srcs encontrados: {img_matches}")
    log(f"text_inputs encontrados: {text_input_matches}")

    if not hidden_matches or not img_matches or not text_input_matches:
        log("Estrutura do captcha não reconhecida — zefoy mudou o HTML ou está bloqueando")
        return None

    captcha_token    = hidden_matches[0]
    captcha_url      = img_matches[0] if img_matches[0].startswith("/") else "/" + img_matches[0]
    captcha_token_v2 = text_input_matches[0]

    log(f"captcha_token={captcha_token} | url={captcha_url} | token_v2={captcha_token_v2}")

    try:
        captcha_image_bytes = client.get("https://zefoy.com" + captcha_url, timeout=15).content
    except Exception as e:
        log(f"Erro ao baixar imagem do captcha: {e}")
        return None

    if HEADLESS and OCR_AVAILABLE:
        captcha_answer = ocr_solve(captcha_image_bytes)
    elif not HEADLESS:
        captcha_answer = manual_solve(captcha_image_bytes)
    else:
        log("HEADLESS=True mas OCR não disponível — saindo")
        sys.exit(1)

    log(f"Enviando resposta do captcha: '{captcha_answer}'")

    try:
        resp2 = requests.post(
            "https://zefoy.com",
            headers={
                "authority"                : "zefoy.com",
                "accept"                   : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language"          : "en-US,en;q=0.5",
                "cache-control"            : "no-cache",
                "content-type"             : "application/x-www-form-urlencoded",
                "cp-extension-installed"   : "Yes",
                "origin"                   : "null",
                "pragma"                   : "no-cache",
                "sec-fetch-dest"           : "document",
                "sec-fetch-mode"           : "navigate",
                "sec-fetch-site"           : "same-origin",
                "sec-fetch-user"           : "?1",
                "upgrade-insecure-requests": "1",
                "cookie"                   : f"PHPSESSID={client.cookies.get('PHPSESSID')}",
                "user-agent"               : client.headers["user-agent"],
            },
            data={
                captcha_token_v2: captcha_answer,
                captcha_token   : "",
            },
            timeout=30,
        )
    except Exception as e:
        log(f"Erro ao submeter captcha: {e}")
        return None

    log(f"POST captcha HTTP {resp2.status_code}")
    log(f"POST HTML[0:400]: {repr(resp2.text[:400])}")

    key_1_matches = re.findall(r'remove-spaces"[^>]+name="([^"]+)"', resp2.text)
    if not key_1_matches:
        key_1_matches = re.findall(r'name="([^"]+)" placeholder', resp2.text)

    if not key_1_matches:
        log("Captcha incorreto ou sessão rejeitada — chave key_1 não encontrada")
        return None

    key_1 = key_1_matches[0]
    log(f"Captcha resolvido! key_1: {key_1}")
    return key_1

# ---------------------------------------------------------------------------
# Mapa de serviços
# ---------------------------------------------------------------------------
SERVICE_MAP = {
    "views"    : "c2VuZF92aWV3c190aWt0b2s",
    "followers": "c2VuZF9mb2xsb3dlcnNfdGlrdG9L",
    "likes"    : "c2VuZF9oZWFydHNfdGlrdG9r",
    "shares"   : "c2VuZF9zaGFyZXNfdGlrdG9r",
    "favorites": "c2VuZF9mYXZvcml0ZXNfdGlrdG9r",
}

def get_endpoint() -> str:
    ep = SERVICE_MAP.get(SERVICE)
    if not ep:
        log(f"Serviço '{SERVICE}' inválido. Use: {list(SERVICE_MAP.keys())}")
        sys.exit(1)
    return ep

# ---------------------------------------------------------------------------
# Send & search
# ---------------------------------------------------------------------------
def send(client: requests.Session, key: str, aweme_id: str, endpoint: str) -> None:
    token = "".join(choices(ascii_letters + digits, k=16))
    data  = (
        f"------WebKitFormBoundary{token}\r\n"
        f"Content-Disposition: form-data; name=\"{key}\"\r\n\r\n"
        f"{aweme_id}\r\n"
        f"------WebKitFormBoundary{token}--\r\n"
    )
    cookies = dict(client.cookies) | {
        "user_agent" : quote(client.headers["user-agent"]),
        "window_size": "788x841",
    }
    resp = requests.post(
        f"https://zefoy.com/{endpoint}",
        data=data,
        cookies=cookies,
        headers={
            "authority"       : "zefoy.com",
            "accept"          : "*/*",
            "cache-control"   : "no-cache",
            "content-type"    : f"multipart/form-data; boundary=----WebKitFormBoundary{token}",
            "origin"          : "https://zefoy.com",
            "pragma"          : "no-cache",
            "sec-fetch-dest"  : "empty",
            "sec-fetch-mode"  : "cors",
            "sec-fetch-site"  : "same-origin",
            "user-agent"      : client.headers["user-agent"],
            "x-requested-with": "XMLHttpRequest",
        },
        timeout=30,
    )
    result = decode(resp.text)
    if "sent" in result:
        log(f"OK {SERVICE} enviado para {aweme_id}")
    elif "Session expired" in result:
        raise Exception("session expired")
    else:
        log(f"Resposta send: {result[:200]}")

def search_link(client: requests.Session, key_1: str, endpoint: str) -> None:
    data = (
        f"------WebKitFormBoundary\r\n"
        f"Content-Disposition: form-data; name=\"{key_1}\"\r\n\r\n"
        f"{TIKTOK_URL}\r\n"
        f"------WebKitFormBoundary--\r\n"
    )
    try:
        resp = requests.post(
            f"https://zefoy.com/{endpoint}",
            data=data,
            headers={
                "authority"       : "zefoy.com",
                "accept"          : "*/*",
                "cache-control"   : "no-cache",
                "content-type"    : "multipart/form-data; boundary=----WebKitFormBoundary",
                "cookie"          : f"PHPSESSID={client.cookies.get('PHPSESSID')}",
                "origin"          : "https://zefoy.com",
                "pragma"          : "no-cache",
                "sec-fetch-dest"  : "empty",
                "sec-fetch-mode"  : "cors",
                "sec-fetch-site"  : "same-origin",
                "user-agent"      : client.headers["user-agent"],
                "x-requested-with": "XMLHttpRequest",
            },
            timeout=30,
        )
        response = decode(resp.text)
    except Exception as e:
        log(f"Erro na requisição: {e}")
        return

    if 'onsubmit="showHideElements' in response:
        try:
            token, aweme_id = re.findall(r'name="(.*)" value="(.*)" hidden', response)[0]
            log(f"Enviando aweme_id={aweme_id} key_2={token}")
            sleep(3)
            send(client, token, aweme_id, endpoint)
        except Exception as e:
            log(f"Erro ao extrair token/aweme_id: {e}")
    else:
        timer_match = re.findall(r"ltm=(\d*);", response)
        if timer_match:
            wait = int(timer_match[0])
            if wait == 0:
                return
            log(f"Cooldown: {wait}s")
            start = time()
            while time() < start + wait:
                remaining = round((start + wait) - time())
                print(f"\r{Fore.YELLOW}[~] aguardando {remaining}s...{Fore.RESET}   ", end="", flush=True)
                sleep(1)
            print()
        else:
            log(f"Resposta inesperada: {response[:300]}")

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    log(f"TikTok ViewBot | URL: {TIKTOK_URL} | Servico: {SERVICE}")
    endpoint = get_endpoint()

    while True:
        client = get_client()
        key_1  = None

        for attempt in range(1, 6):
            log(f"Tentativa de captcha {attempt}/5")
            key_1 = solve_captcha(client)
            if key_1:
                break
            sleep(15)

        if not key_1:
            log("Nao foi possivel resolver o captcha. Reiniciando em 60s...")
            sleep(60)
            continue

        log("Sessao ativa. Iniciando loop de envio...")
        session_errors = 0

        while session_errors < 5:
            try:
                search_link(client, key_1, endpoint)
                sleep(5)
            except Exception as e:
                log(f"Erro: {e}")
                session_errors += 1
                if "session expired" in str(e).lower():
                    log("Sessao expirada — renovando captcha...")
                    break
                sleep(10)

        log("Sessao encerrada. Reiniciando...")
        sleep(5)

if __name__ == "__main__":
    main()
