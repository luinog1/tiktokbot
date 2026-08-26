#!/bin/bash
set -e

echo "Starting Firefox/Selenium environment..."

# Verifica se o geckodriver foi instalado corretamente
if ! command -v geckodriver &> /dev/null; then
    echo "ERROR: geckodriver not found in PATH."
    exit 1
fi

echo "geckodriver found at: $(which geckodriver)"
firefox --version

# Executa o comando passado (vindo do CMD do Dockerfile ou do Render)
exec "$@"
