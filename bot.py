import os
import re
import sys
import json
import hashlib
import base64
from io import BytesIO
from random import choices
from string import ascii_letters, digits
from time import sleep, time
from datetime import datetime, timezone
from urllib.parse import unquote

import requests
from colorama import Fore, init; init()

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    AES_OK = True
except ImportError:
    AES_OK = False

try:
    from PIL import Image, ImageFilter, ImageOps
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import pytesseract
    OCR_LOCAL = True
except ImportError:
    OCR_LOCAL = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TIKTOK_URL = os.environ.get("TIKTOK_VIDEO_URL", "").strip()
SERVICE = os.environ.get("TIKTOK_SERVICE", "views").strip().lower()
FALLBACK = os.environ.get("TIKTOK_FALLBACK", "1").strip() not in ("0", "false", "no")
SERVICE_DOWN_WAIT = int(os.environ.get("SERVICE_DOWN_WAIT", "120"))
PLOWSIDE_URL = os.environ.get(
    "CAPTCHA_API_URL",
    "https://plowsidecaptcha.pythonanywhere.com/captcha",
).strip()
OCRSPACE_KEY = os.environ.get("OCRSPACE_API_KEY", "helloworld").strip()
HEADLESS = not sys.stdin.isatty() or bool(os.environ.get("RENDER"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
AES_PASSPHRASE = "43fdda1192dde7f8ffff7161e13580d7"
BASE = "https://zefoy.com"

SERVICE_ALIASES = {
    "views": "views",
    "view": "views",
    "followers": "followers",
    "follower": "followers",
    "likes": "hearts",
    "like": "hearts",
    "hearts": "hearts",
    "heart": "hearts",
    "shares": "shares",
    "share": "shares",
    "favorites": "favorites",
    "favourite": "favorites",
    "favourites": "favorites",
    "favorite": "favorites",
}

# fallback se o HTML do painel nao parsear
SERVICE_MAP = {
    "views": "c2VuZF92aWV3c190aWt0b2s",
    "followers": "c2VuZF9mb2xsb3dlcnNfdGlrdG9r",
    "hearts": "c2VuZF9oZWFydHNfdGlrdG9r",
    "shares": "c2VuZF9zaGFyZXNfdGlrdG9r",
    "favorites": "c2VuZF9mYXZvcml0ZXNfdGlrdG9r",
}

if not TIKTOK_URL:
    print("[!] ERRO: defina TIKTOK_VIDEO_URL nas env vars")
    sys.exit(1)

SERVICE = SERVICE_ALIASES.get(SERVICE, SERVICE)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{Fore.CYAN}{ts} {Fore.BLUE}INFO {Fore.MAGENTA}bot -> {Fore.RESET}{msg}", flush=True)


def decode(text: str) -> str:
    try:
        return base64.b64decode(unquote(text[::-1])).decode()
    except Exception:
        return text


def letters_only(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16):
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len:key_len + iv_len]


def encrypt_cryptojs_json(plaintext: dict) -> str:
    if not AES_OK:
        raise RuntimeError("pycryptodome nao instalado")
    raw = json.dumps(plaintext, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    salt = os.urandom(8)
    key, iv = evp_bytes_to_key(AES_PASSPHRASE.encode("utf-8"), salt)
    ct = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(raw, AES.block_size))
    return json.dumps(
        {
            "ct": base64.b64encode(ct).decode("ascii"),
            "iv": iv.hex(),
            "s": salt.hex(),
        },
        separators=(",", ":"),
    )


def build_fingerprint(user_agent: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "deviceInfo": {
            "cpuCores": 8,
            "cpuLoad": "Skipped",
            "deviceMemoryGB": 8,
            "platform": "Win32",
            "maxTouchPoints": 0,
            "msMaxTouchPoints": 0,
            "gpu": {
                "vendor": "Google Inc. (Intel)",
                "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            },
            "battery": "Not Supported",
            "stylusDetection": "No",
            "touchSupport": "No",
        },
        "browserInfo": {
            "userAgent": user_agent,
            "timezone": "America/New_York",
            "timezoneOffset": 240,
            "localeDateTime": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "localUnixTime": int(time()),
            "calendar": "gregory",
            "day": "numeric",
            "locale": "en-US",
            "month": "long",
            "numberingSystem": "latn",
            "year": "numeric",
            "appName": "Netscape",
            "appVersion": "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "vendor": "Google Inc.",
            "language": "en-US",
            "languages": ["en-US", "en"],
            "cookieEnabled": True,
            "onlineStatus": "Online",
            "javaEnabled": False,
            "doNotTrack": "unspecified",
            "referrerHeader": "https://www.google.com/",
            "httpsConnection": "Yes",
            "historyLength": 3,
            "mimeTypes": 4,
            "plugins": 5,
            "webdriver": False,
            "pageVisibility": "visible",
            "isBot": "No",
            "featuresSupported": {
                "geolocation": "Yes",
                "serviceWorker": "Yes",
                "localStorage": "Yes",
                "sessionStorage": "Yes",
                "indexedDB": "Yes",
                "notifications": "Yes",
                "notificationsFirebase": "default",
                "clipboard": "Yes",
                "pushAPI": "Yes",
                "webRTC": "Yes",
                "gamepadAPI": "No",
                "speechSynthesis": "Yes",
                "webGL": "Yes",
                "vibrationAPI": "No",
                "deviceMotion": "No",
                "deviceOrientation": "No",
                "wakeLock": "No",
                "serial": "No",
                "usb": "No",
                "networkInformation": "Yes",
                "screenCapture": "Yes",
                "fullscreenAPI": "Yes",
                "pictureInPicture": "Yes",
            },
        },
        "screenInfo": {
            "width": 1920,
            "height": 1080,
            "colorDepth": 24,
            "pixelDepth": 24,
            "devicePixelRatio": 1,
            "orientation": "landscape-primary",
            "screenOrientationAngle": 0,
            "availableWidth": 1920,
            "availableHeight": 1040,
            "screenLeft": 0,
            "screenTop": 0,
            "outerWidth": 1920,
            "outerHeight": 1080,
            "innerWidth": 1920,
            "innerHeight": 1040,
        },
        "otherData": {
            "mouseAvailable": "Yes",
            "keyboardAvailable": "Yes",
            "bluetoothSupport": "No",
            "usbSupport": "No",
            "gamepadSupport": "No",
            "incognitoMode": "No",
        },
        "storageInfo": {
            "localStorage": 5,
            "sessionStorage": 2,
            "indexedDB": "Available",
            "cacheStorage": "Available",
            "storageEstimate": "Not Supported",
        },
    }


def get_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": BASE,
        "Referer": BASE + "/",
        "cp-extension-installed": "Yes",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    })
    return s


def apply_guard_cookies(client: requests.Session) -> None:
    zf = hashlib.md5(str(int(time() * 1000)).encode()).hexdigest()
    client.cookies.set("zf", zf, domain="zefoy.com", path="/")
    client.cookies.set("za", "200", domain="zefoy.com", path="/")


def fetch_captcha_image(client: requests.Session) -> bytes:
    home = client.get(BASE + "/", timeout=30)
    log(f"HTTP {home.status_code} | {len(home.content)} bytes")
    html = home.text
    if home.status_code in (403, 429, 503) or "Just a moment" in html or "cf-wrapper" in html:
        raise RuntimeError(f"Cloudflare/WAF bloqueou (HTTP {home.status_code})")
    if not client.cookies.get("PHPSESSID"):
        raise RuntimeError("PHPSESSID ausente")

    apply_guard_cookies(client)
    ts = int(time())
    payload = client.get(
        f"{BASE}/?getcapthca={ts}",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + "/",
        },
        timeout=30,
    )
    data = payload.json()
    ua_md5 = hashlib.md5(USER_AGENT.encode("utf-8")).hexdigest()
    encoded = data.get(ua_md5)
    if not encoded:
        if len(data) == 1:
            encoded = next(iter(data.values()))
        else:
            raise RuntimeError(f"chave captcha {ua_md5} ausente; keys={list(data.keys())[:4]}")
    path = base64.b64decode(base64.b64decode(encoded)).decode("utf-8").strip()
    if not path.startswith("/"):
        path = "/" + path
    log(f"captcha path={path}")
    img = client.get(
        BASE + path,
        headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8", "Referer": BASE + "/"},
        timeout=15,
    )
    if img.status_code != 200 or not img.content:
        raise RuntimeError(f"falha ao baixar imagem HTTP {img.status_code}")
    return img.content


def solve_plowside(image_bytes: bytes) -> str:
    r = requests.post(
        PLOWSIDE_URL,
        files={"file": ("captcha.png", image_bytes, "image/png")},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    text = data.get("captcha_text") or data.get("text") or data.get("result") or ""
    return letters_only(str(text))


def solve_ocrspace(image_bytes: bytes) -> str:
    r = requests.post(
        "https://api.ocr.space/parse/image",
        files={"file": ("captcha.png", image_bytes, "image/png")},
        data={
            "apikey": OCRSPACE_KEY,
            "language": "eng",
            "OCREngine": "2",
            "scale": "true",
            "isOverlayRequired": "false",
        },
        timeout=40,
    )
    r.raise_for_status()
    data = r.json()
    parsed = (data.get("ParsedResults") or [{}])[0].get("ParsedText") or ""
    return letters_only(parsed)


def _collapse_letter_gaps(img: Image.Image) -> Image.Image:
    gray = img.convert("L")
    arr = gray.load()
    w, h = gray.size
    cols = []
    for x in range(w):
        ink = sum(1 for y in range(h) if arr[x, y] < 140)
        if ink > 1:
            cols.append(x)
    if not cols:
        return gray
    out_w = len(cols) + 8
    out = Image.new("L", (out_w, h), 255)
    px = out.load()
    for i, x in enumerate(cols):
        for y in range(h):
            px[i + 4, y] = arr[x, y]
    return out.resize((out.width * 3, out.height * 3), Image.LANCZOS)


def solve_tesseract(image_bytes: bytes) -> str:
    if not (OCR_LOCAL and PIL_OK):
        return ""
    img = Image.open(BytesIO(image_bytes))
    collapsed = _collapse_letter_gaps(img)
    collapsed = ImageOps.autocontrast(collapsed)
    collapsed = collapsed.filter(ImageFilter.SHARPEN)
    cfg = "--psm 7 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    raw = pytesseract.image_to_string(collapsed, config=cfg)
    return letters_only(raw)


def solve_captcha_text(image_bytes: bytes) -> str:
    errors = []
    for name, fn in (
        ("plowside", solve_plowside),
        ("ocr.space", solve_ocrspace),
        ("tesseract", solve_tesseract),
    ):
        try:
            text = fn(image_bytes)
            if len(text) >= 3:
                log(f"OCR {name}: '{text}'")
                return text
            errors.append(f"{name}=empty/{text!r}")
        except Exception as e:
            errors.append(f"{name}={e}")
            log(f"OCR {name} falhou: {e}")
    raise RuntimeError("nenhum solver de captcha funcionou: " + " | ".join(errors))


def parse_services(html: str) -> dict:
    found = {}
    for m in re.finditer(
        r'<h5 class="card-title mb-3">\s*([^<]+)</h5>\s*<form action="([^"]+)">.*?'
        r'name="([^"]+)"[^>]*placeholder="Enter Video URL"',
        html,
        re.S | re.I,
    ):
        title = m.group(1).strip().lower()
        found[title] = {"endpoint": m.group(2), "key": m.group(3), "disabled": False}

    for m in re.finditer(
        r'<h5 class="card-title">\s*([^<]+)</h5>\s*<button([^>]*)class="[^"]*-button[^"]*"[^>]*>'
        r'.*?<p class="card-text">(.*?)</p>',
        html,
        re.S | re.I,
    ):
        title = m.group(1).strip().lower()
        disabled = "disabled" in m.group(2)
        badge = re.sub(r"<[^>]+>", " ", m.group(3))
        badge = re.sub(r"\s+", " ", badge).strip()
        entry = found.setdefault(title, {"endpoint": None, "key": None, "disabled": disabled})
        entry["disabled"] = disabled
        entry["status"] = badge
    return found


def pick_service(services: dict, wanted: str) -> dict | None:
    wanted = SERVICE_ALIASES.get(wanted, wanted)
    svc = services.get(wanted)
    if svc and svc.get("key") and svc.get("endpoint") and not svc.get("disabled"):
        return {"name": wanted, **svc}

    online = [
        (name, data)
        for name, data in services.items()
        if data.get("key") and data.get("endpoint") and not data.get("disabled")
    ]
    if FALLBACK and online:
        name, data = online[0]
        log(f"Servico '{wanted}' offline no zefoy — caindo para '{name}' ({data.get('status', 'on')})")
        return {"name": name, **data}

    if svc and svc.get("key") and svc.get("endpoint"):
        log(f"Servico '{wanted}' marcado offline — tentando o endpoint mesmo assim")
        return {"name": wanted, **svc}
    return None


def service_offline(text: str) -> bool:
    low = (text or "").lower()
    return (
        "currently not working" in low
        or "soon will be update" in low
        or "service is not working" in low
    )


def parse_wait_seconds(html: str):
    m = re.search(r"remainingTimelogin\s*=\s*(\d+)", html or "")
    if m:
        return int(m.group(1))
    m = re.search(r"ltm=(\d*);", html or "")
    if m:
        return int(m.group(1))
    m = re.search(r"Please wait (\d+) seconds", html or "", re.I)
    if m:
        return int(m.group(1))
    return None


def parse_send_token(html: str):
    patterns = [
        r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']+)["\']',
        r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']+)["\'][^>]*(?:type=["\']hidden["\']|\bhidden\b)',
        r'name="([^"]+)"\s+value="([^"]+)"\s+hidden',
    ]
    for pat in patterns:
        m = re.search(pat, html or "", re.I)
        if m:
            return m.group(1), m.group(2)
    return None


def wait_seconds(seconds: int, reason: str = "Cooldown") -> None:
    if seconds <= 0:
        return
    log(f"{reason}: {seconds}s")
    end = time() + seconds
    while time() < end:
        remaining = round(end - time())
        print(f"\r{Fore.YELLOW}[~] aguardando {remaining}s...{Fore.RESET}   ", end="", flush=True)
        sleep(1)
    print()


def solve_captcha(client: requests.Session):
    log("Carregando zefoy.com...")
    try:
        image_bytes = fetch_captcha_image(client)
    except Exception as e:
        log(f"Erro ao obter captcha: {e}")
        return None

    try:
        answer = solve_captcha_text(image_bytes)
    except Exception as e:
        log(f"Erro ao resolver captcha: {e}")
        return None

    if not HEADLESS and not answer:
        answer = letters_only(input("[~] Digite o captcha: ").strip())

    encoded = encrypt_cryptojs_json(build_fingerprint(USER_AGENT))
    log(f"Enviando captcha lowercase: '{answer}'")
    try:
        resp = client.post(
            BASE + "/",
            data={"captchalogin": answer, "captcha_encoded": encoded},
            headers={
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE,
                "Referer": BASE + "/",
                "cache-control": "no-cache",
                "pragma": "no-cache",
            },
            timeout=30,
        )
    except Exception as e:
        log(f"Erro ao submeter captcha: {e}")
        return None

    body = (resp.text or "").strip()
    log(f"POST captcha HTTP {resp.status_code} body={body[:80]!r}")
    if body.lower() != "success":
        log("Captcha rejeitado")
        return None

    panel = client.get(BASE + "/", timeout=30)
    html = panel.text
    if 'name="captchalogin"' in html or "captcha-login-input" in html:
        log("XHR success mas o painel ainda pede captcha")
        return None

    services = parse_services(html)
    summary = {
        k: ("off" if v.get("disabled") else "on") + (f"/{v.get('status')}" if v.get("status") else "")
        for k, v in services.items()
    }
    log(f"Servicos: {summary}")
    picked = pick_service(services, SERVICE)
    if not picked:
        log(f"Nenhum servico usavel. Pedido={SERVICE}")
        return None
    log(f"Captcha resolvido! servico={picked['name']} key_1={picked['key']} endpoint={picked['endpoint']}")
    return {"key": picked["key"], "endpoint": picked["endpoint"], "name": picked["name"]}


def send(client: requests.Session, key: str, aweme_id: str, endpoint: str) -> None:
    token = "".join(choices(ascii_letters + digits, k=16))
    data = (
        f"------WebKitFormBoundary{token}\r\n"
        f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
        f"{aweme_id}\r\n"
        f"------WebKitFormBoundary{token}--\r\n"
    )
    resp = client.post(
        f"{BASE}/{endpoint}",
        data=data,
        headers={
            "accept": "*/*",
            "cache-control": "no-cache",
            "content-type": f"multipart/form-data; boundary=----WebKitFormBoundary{token}",
            "origin": BASE,
            "pragma": "no-cache",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-requested-with": "XMLHttpRequest",
        },
        timeout=30,
    )
    result = decode(resp.text)
    low = result.lower()
    if "sent" in low or "success" in low:
        log(f"OK enviado para {aweme_id}")
    elif "Session expired" in result:
        raise Exception("session expired")
    elif service_offline(result):
        raise Exception("service offline")
    wait = parse_wait_seconds(result)
    if wait:
        wait_seconds(wait + 2, "Cooldown apos envio")
        return
    if "sent" not in low and "success" not in low:
        log(f"Resposta send: {result[:250]}")


def search_link(client: requests.Session, key_1: str, endpoint: str) -> None:
    token = "".join(choices(ascii_letters + digits, k=16))
    data = (
        f"------WebKitFormBoundary{token}\r\n"
        f'Content-Disposition: form-data; name="{key_1}"\r\n\r\n'
        f"{TIKTOK_URL}\r\n"
        f"------WebKitFormBoundary{token}--\r\n"
    )
    try:
        resp = client.post(
            f"{BASE}/{endpoint}",
            data=data,
            headers={
                "accept": "*/*",
                "cache-control": "no-cache",
                "content-type": f"multipart/form-data; boundary=----WebKitFormBoundary{token}",
                "origin": BASE,
                "pragma": "no-cache",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "x-requested-with": "XMLHttpRequest",
            },
            timeout=30,
        )
        response = decode(resp.text)
    except Exception as e:
        log(f"Erro na requisicao: {e}")
        return

    token_pair = parse_send_token(response)
    if token_pair and (
        "fcde" in response
        or "showHideElements" in response
        or 'type="hidden"' in response
        or "type='hidden'" in response
    ):
        token2, aweme_id = token_pair
        log(f"Enviando aweme_id={aweme_id} key_2={token2}")
        sleep(2)
        send(client, token2, aweme_id, endpoint)
        return

    wait = parse_wait_seconds(response)
    if wait is not None:
        wait_seconds(wait + 2, "Cooldown zefoy")
        return

    if service_offline(response):
        raise Exception("service offline")
    if "Session expired" in response:
        raise Exception("session expired")
    log(f"Resposta inesperada: {response[:300]}")


def main():
    log(f"TikTok ViewBot | URL: {TIKTOK_URL} | Servico: {SERVICE}")
    if "/photo/" in TIKTOK_URL:
        log("Aviso: URL e de photo. Zefoy costuma exigir link de video (/video/ID)")
    if not AES_OK:
        log("ERRO: instale pycryptodome (requirements.txt)")
        sys.exit(1)

    while True:
        client = get_client()
        session = None

        for attempt in range(1, 8):
            log(f"Tentativa de captcha {attempt}/7")
            session = solve_captcha(client)
            if session:
                break
            client = get_client()
            sleep(8)

        if not session:
            log("Nao foi possivel resolver o captcha. Reiniciando em 60s...")
            sleep(60)
            continue

        log("Sessao ativa. Iniciando loop de envio...")
        session_errors = 0
        while session_errors < 5:
            try:
                search_link(client, session["key"], session["endpoint"])
                sleep(5)
            except Exception as e:
                msg = str(e).lower()
                log(f"Erro: {e}")
                if "session expired" in msg:
                    log("Sessao expirada — renovando captcha...")
                    break
                if "service offline" in msg:
                    log(
                        f"Zefoy: servico '{session.get('name', SERVICE)}' fora do ar. "
                        f"Aguardando {SERVICE_DOWN_WAIT}s (nao e bug do captcha)"
                    )
                    sleep(SERVICE_DOWN_WAIT)
                    break
                session_errors += 1
                sleep(10)

        log("Sessao encerrada. Reiniciando...")
        sleep(5)


if __name__ == "__main__":
    main()
