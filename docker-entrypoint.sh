#!/bin/bash
set -e

PORT="${PORT:-10000}"

# Servidor HTTP mínimo para o Render detectar porta aberta (web_service free tier)
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
print(f'HTTP server listening on port {port}', flush=True)
srv.serve_forever()
" &
HTTP_PID=$!

# Aguarda socket estar em LISTEN
for i in $(seq 1 15); do
    if python3 -c "import socket; s=socket.socket(); s.connect(('127.0.0.1', ${PORT})); s.close()" 2>/dev/null; then
        echo "Health-check HTTP server ready on port ${PORT}"
        break
    fi
    sleep 0.5
done

# Roda o bot em background; bash fica vivo como pai
"$@" &
BOT_PID=$!

trap "kill $HTTP_PID $BOT_PID 2>/dev/null" SIGTERM SIGINT

wait $BOT_PID
