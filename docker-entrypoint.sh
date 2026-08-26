#!/bin/sh
set -eu

echo "[render] Preparing Selenium/Firefox..."

# The repository pins Selenium 4.11.0 and the original bot expects
# geckodriver at /usr/local/bin/geckodriver. Selenium Manager can obtain
# a compatible driver at runtime, so the repository does not need to
# hard-code a driver download URL.
SELENIUM_MANAGER="$(find /usr/local/lib/python3.11/site-packages/selenium \
  -type f -name selenium-manager -perm -111 2>/dev/null | head -n 1 || true)"

if [ -z "${SELENIUM_MANAGER}" ]; then
  echo "[error] Selenium Manager binary was not found."
  exit 1
fi

DRIVER_PATH="$(
  "${SELENIUM_MANAGER}" --browser firefox --output json 2>/dev/null |
  python -c 'import json,sys; print(json.load(sys.stdin)["result"]["driver_path"])'
)"

if [ -z "${DRIVER_PATH}" ] || [ ! -x "${DRIVER_PATH}" ]; then
  echo "[error] Selenium Manager did not return a usable geckodriver."
  exit 1
fi

ln -sf "${DRIVER_PATH}" /usr/local/bin/geckodriver

echo "[render] Firefox: $(firefox --version)"
echo "[render] geckodriver: ${DRIVER_PATH}"
echo "[render] Starting bot..."

# Render Background Worker: no HTTP port is required.
# Xvfb provides the display expected by Firefox/Selenium.
exec xvfb-run -a --server-args="-screen 0 1280x900x24" python bot.py
