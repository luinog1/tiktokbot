#!/bin/sh
set -eu

echo "Starting Firefox/Selenium environment..."

SELENIUM_MANAGER="$(find /usr/local/lib/python3.11/site-packages/selenium \
  -type f -name selenium-manager -perm -111 2>/dev/null | head -n 1 || true)"

if [ -z "$SELENIUM_MANAGER" ]; then
    echo "ERROR: Selenium Manager not found"
    exit 1
fi

DRIVER_PATH="$(
    "$SELENIUM_MANAGER" \
        --browser firefox \
        --output json 2>/dev/null |
    python -c '
import json
import sys
data=json.load(sys.stdin)
print(data["result"]["driver_path"])
'
)"

if [ -z "$DRIVER_PATH" ]; then
    echo "ERROR: Could not obtain geckodriver"
    exit 1
fi

ln -sf "$DRIVER_PATH" /usr/local/bin/geckodriver

echo "Firefox:"
firefox --version

echo "Geckodriver:"
geckodriver --version

echo "Starting bot..."

exec xvfb-run -a \
    --server-args="-screen 0 1280x900x24" \
    python bot.py
