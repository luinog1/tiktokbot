FROM python:3.11-slim

# Instala Firefox, Tesseract OCR, OpenCV dependencies, e ferramentas úteis
# Nota: libgl1-mesa-glx foi removido no Debian Trixie; substituído por libgl1 + libglx-mesa0
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    xvfb \
    xauth \
    wget \
    ca-certificates \
    curl \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglx-mesa0 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Instala o Geckodriver usando Python para parsear a API
RUN GECKODRIVER_VERSION=$(curl -s https://api.github.com/repos/mozilla/geckodriver/releases/latest | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'])") \
    && wget -q "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER_VERSION}/geckodriver-${GECKODRIVER_VERSION}-linux64.tar.gz" \
    && tar -xzf geckodriver-*.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/geckodriver \
    && rm geckodriver-*.tar.gz

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]

CMD ["python", "-u", "bot.py"]
