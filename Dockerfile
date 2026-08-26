FROM python:3.11-slim

# Instala o Firefox, Xvfb, ferramentas e xvfb-run
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    xvfb \
    wget \
    ca-certificates \
    curl \
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

EXPOSE 10000

# Entrypoint verifica geckodriver e Firefox
ENTRYPOINT ["/docker-entrypoint.sh"]

# Executa o bot com xvfb-run (cria display virtual automaticamente)
# ⚠️ Altere "main.py" para o nome real do seu script
CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1280x1024x24", "python", "main.py"]
