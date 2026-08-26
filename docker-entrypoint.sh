#!/bin/bash
set -e

echo "Starting Firefox/Selenium environment..."

# Inicia o Xvfb (display virtual) em background
Xvfb :99 -screen 0 1024x768x24 > /dev/null 2>&1 &
export DISPLAY=:99

# Verifica se o geckodriver foi instalado
if ! command -v geckodriver &> /dev/null; then
    echo "ERROR: geckodriver not found in PATH."
    exit 1
fi

echo "geckodriver found at: $(which geckodriver)"
firefox --version

# Define variável de ambiente para ativar modo headless (caso o bot a utilize)
export HEADLESS=true

# Executa o comando passado (vindo do CMD do Dockerfile)
exec "$@"
