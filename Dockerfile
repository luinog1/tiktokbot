FROM python:3.11-slim

# Instala o Firefox, Xvfb (para headless) e ferramentas úteis
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    xvfb \
    wget \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instala o Geckodriver usando Python para parsear a versão mais recente da API do GitHub
RUN GECKODRIVER_VERSION=$(curl -s https://api.github.com/repos/mozilla/geckodriver/releases/latest | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'])") \
    && wget -q "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER_VERSION}/geckodriver-${GECKODRIVER_VERSION}-linux64.tar.gz" \
    && tar -xzf geckodriver-*.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/geckodriver \
    && rm geckodriver-*.tar.gz

# Define o diretório de trabalho
WORKDIR /app

# Copia e instala as dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código do projeto
COPY . .

# Copia e dá permissão ao script de entrada
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Porta padrão do Render
EXPOSE 10000

# Entrypoint e comando (ajuste "bot.py" se o nome do seu arquivo for diferente)
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "bot.py"]
