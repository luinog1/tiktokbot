FROM python:3.11-slim

# Instala o Firefox, Xvfb (para headless) e ferramentas úteis
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    xvfb \
    wget \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instala o Geckodriver manualmente (evita totalmente o Selenium Manager)
RUN GECKODRIVER_VERSION=$(curl -s https://api.github.com/repos/mozilla/geckodriver/releases/latest | grep -oP '"tag_name": "\K[^"]*') \
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

# Define o entrypoint e o comando padrão (ajuste "bot.py" se o nome do arquivo for diferente, ex: "main.py")
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "bot.py"]
