FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOZ_HEADLESS=1 \
    DEBIAN_FRONTEND=noninteractive

# Firefox + virtual display for Selenium.
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    xvfb \
    ca-certificates \
    procps \
    && ln -sf /usr/bin/firefox-esr /usr/bin/firefox \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
