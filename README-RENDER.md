# Deploying this repository on Render

This bundle adds Docker/Render deployment files to the original `simonfarah/tiktok-bot` repository.

## Files added

- `Dockerfile` — Python 3.11 + Firefox ESR + Xvfb container.
- `docker-entrypoint.sh` — prepares `geckodriver` through Selenium Manager and starts `bot.py`.
- `render.yaml` — Render Blueprint using a **Background Worker**.
- `.dockerignore` — keeps the Docker build context small.

The original project currently pins `selenium==4.11.0` and the bot expects Firefox at
`/usr/bin/firefox` and geckodriver at `/usr/local/bin/geckodriver`.

## Render deployment

1. Copy these files into the root of your fork of the repository.
2. Push them to GitHub.
3. In Render, create a new Blueprint from that repository.
4. Render will read `render.yaml` and create the `tiktok-bot` Background Worker.
5. Watch the Worker logs during startup.

## Important limitation: CAPTCHA / interactive CLI

The original program is an interactive CLI. It asks for a CAPTCHA to be completed
and then asks for a service and a video URL.

A Render Background Worker is not an interactive desktop session. The Docker image
therefore provides Firefox through Xvfb, but it does **not** provide a remote GUI for
you to click through a CAPTCHA.

If the target site requires a human CAPTCHA, the worker can remain waiting for it
and will not be usable unattended. This deployment does not bypass or solve the
CAPTCHA.

For a reliable production architecture, the code should be changed to accept jobs
through an authenticated API/queue and use an approved, non-interactive workflow.

## Local Docker test

From the repository root:

```bash
docker build -t tiktok-bot-render .
docker run --rm -it tiktok-bot-render
```

Because the original bot expects interactive input, use `-it` for local testing.

## Render service type

A Background Worker is preferable to a Web Service because the original program
does not expose an HTTP server and runs as a long-lived process.

Do not add a health-check HTTP endpoint just to satisfy Render: that would be a
different application architecture.

## Persistent storage

The current repository only creates a local `geckodriver.log`; it does not define a
database or application data directory. A persistent disk is therefore not required
for the basic container.

If you later add durable state, mount a Render persistent disk and write application
data under its mount path.

## Security / platform compliance

The upstream repository describes itself as an educational automation tool and
automates interactions intended to increase TikTok engagement through Zefoy.

Use it only where you have authorization and where the activity complies with the
applicable platform rules, the target site's rules, and applicable law. This Docker
setup does not attempt to bypass CAPTCHA, authentication, rate limits, or other
anti-abuse controls.
