# tiktokbot no Render

Bot HTTP para zefoy.com, empacotado em Docker para o free tier do Render.

## Env vars (dashboard do Render)

| Key | Exemplo | Obrigatorio |
|---|---|---|
| `TIKTOK_VIDEO_URL` | `https://www.tiktok.com/@user/video/123` | sim |
| `TIKTOK_SERVICE` | `views` (`followers`, `likes`, `shares`, `favorites`) | nao (default views) |
| `CAPTCHA_API_URL` | `https://plowsidecaptcha.pythonanywhere.com/captcha` | nao |
| `OCRSPACE_API_KEY` | `helloworld` (gratis) ou a sua chave | nao |

Use URL de **video** (`/video/ID`). Links `/photo/` costumam ser recusados pelo zefoy.

## Captcha (2026)

O zefoy nao coloca mais a imagem no HTML inicial. O bot:

1. Abre `https://zefoy.com` (cookie `PHPSESSID`)
2. Busca a imagem em `GET /?getcapthca=<unix>`
3. Resolve a palavra (lowercase, so a-z)
4. Envia `captchalogin` + `captcha_encoded` (fingerprint AES) via XHR
5. Entra no loop do servico escolhido

Cadeia de OCR: plowside → ocr.space → tesseract no container.

## Deploy

Push neste repo. O Render (Docker web service, `render.yaml`) rebuilda sozinho.

Logs bons depois do deploy:

```
captcha path=/....php?_CAPTCHA=...
OCR ocr.space: 'eager'
POST captcha HTTP 200 body='success'
Captcha resolvido! key_1=... endpoint=...
```
