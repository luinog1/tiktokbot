#!/bin/bash
set -e

echo "Starting Firefox/Selenium environment..."

export MOZ_HEADLESS=1          # Força modo headless no Firefox
export DISPLAY=:99             # Garante um display (caso o xvfb-run não defina)

if ! command -v geckodriver &> /dev/null; then
    echo "ERROR: geckodriver not found in PATH."
    exit 1
fi

echo "geckodriver found at: $(which geckodriver)"
firefox --version

exec "$@"
