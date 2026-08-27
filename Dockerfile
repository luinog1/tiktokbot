FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    tesseract-ocr \
    tesseract-ocr-eng \
    wget \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN GECKODRIVER_VERSION=$(curl -s https://api.github.com/repos/mozilla/geckodriver/releases/latest | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'])") \
    && wget -q "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER_VERSION}/geckodriver-${GECKODRIVER_VERSION}-linux64.tar.gz" \
    && tar -xzf geckodriver-*.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/geckodriver \
    && rm geckodriver-*.tar.gz

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN if [ -f docker-entrypoint.sh ]; then chmod +x docker-entrypoint.sh; fi

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-u", "bot.py"]
