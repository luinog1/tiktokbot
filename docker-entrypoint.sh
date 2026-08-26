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

# Sobe servidor HTTP em processo independente (não filho do bash)
# para sobreviver ao exec "$@" abaixo
PORT="${PORT:-10000}"
python3 -c "
import http.server, os, socket, time

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')
    def log_message(self, *a): pass

port = int(os.environ.get('PORT', 10000))
srv = http.server.HTTPServer(('0.0.0.0', port), H)
# Sinaliza que está pronto escrevendo na stdout
print(f'HTTP server listening on port {port}', flush=True)
srv.serve_forever()
" &
HTTP_PID=$!

# Aguarda o socket estar em LISTEN antes de continuar
for i in $(seq 1 15); do
    if python3 -c "import socket; s=socket.socket(); s.connect(('127.0.0.1', ${PORT})); s.close()" 2>/dev/null; then
        echo "Health-check HTTP server ready on port ${PORT}"
        break
    fi
    sleep 0.5
done

# Roda o bot em background e aguarda — não usa exec para manter o HTTP server vivo
"$@" &
BOT_PID=$!

# Propaga sinais para ambos os filhos
trap "kill $HTTP_PID $BOT_PID 2>/dev/null" SIGTERM SIGINT

wait $BOT_PID
