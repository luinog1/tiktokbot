#!/bin/bash
set -e

echo "Starting Firefox/Selenium environment..."

export MOZ_HEADLESS=1
export DISPLAY=:99

if ! command -v geckodriver &> /dev/null; then
    echo "ERROR: geckodriver not found in PATH."
    exit 1
fi

echo "geckodriver found at: $(which geckodriver)"
firefox --version

# Sobe servidor HTTP mínimo na porta 10000 para o Render detectar a porta
# e não matar o container (necessário quando rodando como web_service)
PORT="${PORT:-10000}"
python3 -c "
import http.server, threading, os
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')
    def log_message(self, *a): pass
srv = http.server.HTTPServer(('0.0.0.0', int(os.environ.get('PORT', 10000))), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
" &

echo "Health-check HTTP server started on port ${PORT}"

exec "$@"
